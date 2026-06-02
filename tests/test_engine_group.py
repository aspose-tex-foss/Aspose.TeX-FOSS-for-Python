"""Integration tests for TeX grouping & scoping.

Tests the full pipeline: StringInputSource → InputReader → CatcodeTable →
Tokenizer → Expander(group_stack=...) + RegisterSet(group_stack=...).

Covers all acceptance criteria in .
"""
import pytest

from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.group import GroupKind, GroupStack
from aspose_tex._engine.registers import RegisterSet
from aspose_tex._input import InputReader, StringInputSource
from aspose_tex._input.catcode import Catcode, CatcodeTable
from aspose_tex._input.token import CharToken, ControlSequenceToken, Token
from aspose_tex._input.tokenizer import Tokenizer
from aspose_tex.exceptions import EngineError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_env(text: str) -> tuple[Expander, RegisterSet, GroupStack]:
 """Build a full pipeline with grouping enabled."""
 gs = GroupStack()
 src = StringInputSource(text)
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 regs = RegisterSet(group_stack=gs)
 exp = Expander(reader, tok, catcodes, register_provider=regs, group_stack=gs)
 exp._register_set = regs
 return exp, regs, gs


def run(text: str) -> tuple[list[Token], RegisterSet, GroupStack]:
 """Run the full pipeline, execute register commands, return tokens.

 Since moved group handling from Expander to the interpreter,
 this helper dispatches {/}, \\begingroup/\\endgroup/\\aftergroup here.
 """
 exp, regs, gs = make_env(text)
 tokens: list[Token] = []
 for t in exp:
 # Group open/close tokens (: now pass through expander)
 if isinstance(t, CharToken) and t.catcode == Catcode.BEGIN_GROUP:
 gs.open_group(GroupKind.BRACE)
 continue
 if isinstance(t, CharToken) and t.catcode == Catcode.END_GROUP:
 aftergroup_tokens, actual_kind = gs.close_group()
 if actual_kind != GroupKind.BRACE:
 raise EngineError("Extra }, \\begingroup was not closed")
 if aftergroup_tokens:
 exp.push_tokens(aftergroup_tokens)
 continue
 # Group CS commands (: now pass through expander)
 if isinstance(t, ControlSequenceToken):
 if t.name == "begingroup":
 gs.open_group(GroupKind.SEMI_SIMPLE)
 continue
 if t.name == "endgroup":
 aftergroup_tokens, actual_kind = gs.close_group()
 if actual_kind != GroupKind.SEMI_SIMPLE:
 raise EngineError("Extra \\endgroup, { was not closed")
 if aftergroup_tokens:
 exp.push_tokens(aftergroup_tokens)
 continue
 if t.name == "aftergroup":
 agt = next(iter(exp), None)
 if agt is not None:
 gs.push_aftergroup(agt)
 continue
 if regs.execute(t.name, exp):
 continue
 tokens.append(t)
 return tokens, regs, gs


def chars_of(tokens: list[Token]) -> str:
 """Extract chars from OTHER CharTokens (digits, signs, sp suffix)."""
 return "".join(
 t.char for t in tokens
 if isinstance(t, CharToken) and t.catcode in (Catcode.OTHER, Catcode.LETTER)
 )


def digits_of(tokens: list[Token]) -> str:
 """Extract only digit/sign chars from OTHER CharTokens."""
 return "".join(
 t.char for t in tokens
 if isinstance(t, CharToken) and t.catcode == Catcode.OTHER
 )


# ---------------------------------------------------------------------------
# AC-1: \count0=1 {\count0=2} \the\count0 produces 1
# ---------------------------------------------------------------------------

def test_count_local_restored() -> None:
 tokens, regs, _ = run(r"\count0=1 {\count0=2} \the\count0")
 assert digits_of(tokens) == "1"
 assert regs.get_count(0) == 1


def test_count_inner_value_visible_inside_group() -> None:
 """Sanity: the value inside the group is 2 before closing."""
 tokens, _regs, _ = run(r"\count0=1 {\count0=2 \the\count0} \the\count0")
 result = digits_of(tokens)
 # Inner \the\count0 → "2", outer \the\count0 → "1" → "21"
 assert result == "21"


# ---------------------------------------------------------------------------
# AC-2: {\def\foo{local}} \foo produces undefined (yielded as raw CS token)
# ---------------------------------------------------------------------------

def test_macro_local_not_visible_after_group() -> None:
 tokens, _regs, _ = run(r"{\def\foo{local}} \foo")
 # \foo should be yielded as an unexpandable CS token (macro was removed)
 cs_names = [t.name for t in tokens if isinstance(t, ControlSequenceToken)]
 assert "foo" in cs_names


# ---------------------------------------------------------------------------
# AC-3: \gdef\bar{global} inside group — \bar survives group exit
# ---------------------------------------------------------------------------

def test_gdef_global_survives() -> None:
 tokens, _regs, _ = run(r"{\gdef\bar{hi}} \bar")
 # \bar should expand to "hi" (letter tokens)
 letter_chars = "".join(
 t.char for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER
 )
 assert letter_chars == "hi"


# ---------------------------------------------------------------------------
# AC-4: \global\count0=99 inside group persists after exit
# ---------------------------------------------------------------------------

def test_global_count_survives() -> None:
 tokens, regs, _ = run(r"\count0=0 {\global\count0=99} \the\count0")
 assert digits_of(tokens) == "99"
 assert regs.get_count(0) == 99


# ---------------------------------------------------------------------------
# AC-5: \begingroup...\endgroup scoping works identically to braces
# ---------------------------------------------------------------------------

def test_begingroup_endgroup_basic() -> None:
 tokens, regs, _ = run(r"\count0=5 \begingroup \count0=10 \endgroup \the\count0")
 assert digits_of(tokens) == "5"
 assert regs.get_count(0) == 5


def test_begingroup_endgroup_macro_scope() -> None:
 tokens, _, _ = run(r"\begingroup \def\qq{Q} \endgroup \qq")
 cs_names = [t.name for t in tokens if isinstance(t, ControlSequenceToken)]
 assert "qq" in cs_names


# ---------------------------------------------------------------------------
# AC-6: \aftergroup X inserts X after group ends
# ---------------------------------------------------------------------------

def test_aftergroup_token_emitted() -> None:
 tokens, _, _ = run(r"{\aftergroup X} Y")
 letter_tokens = [
 t for t in tokens
 if isinstance(t, CharToken) and t.catcode == Catcode.LETTER
 ]
 chars = "".join(t.char for t in letter_tokens)
 # X should appear before Y
 assert "X" in chars
 assert "Y" in chars
 assert chars.index("X") < chars.index("Y")


def test_multiple_aftergroup() -> None:
 tokens, _, _ = run(r"{\aftergroup A \aftergroup B} C")
 # Filter to letter-catcode chars only (A, B, C)
 chars = "".join(
 t.char for t in tokens
 if isinstance(t, CharToken) and t.catcode == Catcode.LETTER
 )
 assert chars == "ABC"


# ---------------------------------------------------------------------------
# AC-7: Mismatched { / \endgroup detected and reported
# ---------------------------------------------------------------------------

def test_mismatch_brace_endgroup() -> None:
 # { opened BRACE group, \endgroup expects SEMI_SIMPLE → mismatch
 with pytest.raises(EngineError, match=r"Extra.*endgroup"):
 run(r"{\endgroup")


def test_mismatch_begingroup_brace() -> None:
 # \begingroup opened SEMI_SIMPLE, } expects BRACE → mismatch
 with pytest.raises(EngineError, match=r"Extra"):
 run(r"\begingroup }")


def test_extra_close_no_group() -> None:
 with pytest.raises(EngineError, match="Too many"):
 run(r"}")


# ---------------------------------------------------------------------------
# AC-8: Nested groups (3+ levels) save/restore correctly
# ---------------------------------------------------------------------------

def test_nested_groups_3_levels() -> None:
 tex = r"\count0=0 {\count0=1 {\count0=2 {\count0=3} \the\count0} \the\count0} \the\count0"
 tokens, regs, _ = run(tex)
 result = digits_of(tokens)
 # \the\count0 inside innermost group (after {count0=3}) → 2
 # \the\count0 after 2nd group closes → 1
 # \the\count0 after outermost closes → 0
 assert result == "210"
 assert regs.get_count(0) == 0


# ---------------------------------------------------------------------------
# Additional: arithmetic inside groups is restored
# ---------------------------------------------------------------------------

def test_advance_local_restored() -> None:
 tokens, regs, _ = run(r"\count0=10 {\advance\count0 by 5} \the\count0")
 assert digits_of(tokens) == "10"
 assert regs.get_count(0) == 10


def test_multiply_local_restored() -> None:
 tokens, _regs, _ = run(r"\count0=3 {\multiply\count0 by 4} \the\count0")
 assert digits_of(tokens) == "3"


def test_divide_local_restored() -> None:
 tokens, _regs, _ = run(r"\count0=12 {\divide\count0 by 3} \the\count0")
 assert digits_of(tokens) == "12"


# ---------------------------------------------------------------------------
# Additional: \global\advance works globally
# ---------------------------------------------------------------------------

def test_global_advance() -> None:
 tokens, regs, _ = run(r"\count0=10 {\global\advance\count0 by 5} \the\count0")
 assert digits_of(tokens) == "15"
 assert regs.get_count(0) == 15


# ---------------------------------------------------------------------------
# Additional: \countdef alias is local to group
# ---------------------------------------------------------------------------

def test_countdef_alias_local() -> None:
 tokens, regs, _ = run(r"{\countdef\myc=5 \myc=7} \the\count5")
 # After group, alias is gone; count5 should still be 0 (restored)
 assert digits_of(tokens) == "0"
 assert regs.get_count(5) == 0


def test_countdef_alias_value_local() -> None:
 """Value set via alias inside group is restored."""
 tokens, _regs, _ = run(r"\count5=0 {\countdef\myc=5 \myc=99} \the\count5")
 assert digits_of(tokens) == "0"


# ---------------------------------------------------------------------------
# Additional: \currentgrouplevel (FR-10)
# ---------------------------------------------------------------------------

def test_currentgrouplevel_at_0() -> None:
 # \currentgrouplevel pushes digit tokens directly (no \the needed)
 tokens, _, _ = run(r"\currentgrouplevel")
 result = digits_of(tokens)
 assert result == "0"


def test_currentgrouplevel_inside_group() -> None:
 tokens, _, _ = run(r"{ \currentgrouplevel }")
 result = digits_of(tokens)
 assert result == "1"


def test_currentgrouplevel_nested() -> None:
 tokens, _, _ = run(r"{ { \currentgrouplevel } }")
 result = digits_of(tokens)
 assert result == "2"


# ---------------------------------------------------------------------------
# Additional: \let binding is local
# ---------------------------------------------------------------------------

def test_let_local_restored() -> None:
 # \let\foo=\bar (bar undefined) inside group; after group \foo should be gone
 tokens, _, _ = run(r"{\let\foo=\bar} \foo")
 cs_names = [t.name for t in tokens if isinstance(t, ControlSequenceToken)]
 # \foo should be yielded as raw CS (not expanded to \bar)
 assert "foo" in cs_names


# ---------------------------------------------------------------------------
# Additional: toks register is locally restored
# ---------------------------------------------------------------------------

def test_toks_local_restored() -> None:
 tokens, _regs, _ = run(r"\toks0={abc} {\toks0={xyz}} \the\toks0")
 # \the\toks0 should yield the original "abc" token list (letter tokens)
 chars = "".join(
 t.char for t in tokens
 if isinstance(t, CharToken) and t.catcode == Catcode.LETTER
 )
 assert chars == "abc"


# ---------------------------------------------------------------------------
# Additional: skip register is locally restored
# ---------------------------------------------------------------------------

def test_skip_local_restored() -> None:
 tokens, regs, _ = run(r"\skip0=3pt {\skip0=1pt} \the\skip0")
 # \the\skip0 yields in sp format; 3pt = 196608sp
 result = "".join(t.char for t in tokens if isinstance(t, CharToken))
 assert "196608" in result
 assert regs.get_skip(0).width == 3 * 65536


# ---------------------------------------------------------------------------
# Additional: multiple assignments — only first write is saved
# ---------------------------------------------------------------------------

def test_save_on_first_write_only() -> None:
 """Second write in same group doesn't override first saved value."""
 tokens, regs, _ = run(
 r"\count0=1 {\count0=2 \count0=3 \count0=4} \the\count0"
 )
 assert digits_of(tokens) == "1"
 assert regs.get_count(0) == 1


# ---------------------------------------------------------------------------
# Additional: \global\def is global
# ---------------------------------------------------------------------------

def test_global_def_persists() -> None:
 tokens, _, _ = run(r"{\global\def\gfoo{yes}} \gfoo")
 chars = "".join(
 t.char for t in tokens
 if isinstance(t, CharToken) and t.catcode == Catcode.LETTER
 )
 assert chars == "yes"


# ---------------------------------------------------------------------------
# : \global\gdef must consume the global flag (regression)
# ---------------------------------------------------------------------------

def test_global_gdef_consumes_global_flag() -> None:
 # \global\gdef\foo{x} must clear _global_pending so that the following
 # \count0=1 is treated as a local (not global) assignment inside the group.
 tokens, regs, _ = run(r"\count0=0 {\global\gdef\foo{x} \count0=1} \the\count0")
 # After the group closes, count0 should be restored to 0 (local assignment)
 assert digits_of(tokens) == "0"
 assert regs.get_count(0) == 0


def test_global_def_consumes_global_flag_regression() -> None:
 # \global\def already worked; confirm it still does after fix.
 tokens, regs, _ = run(r"\count0=0 {\global\def\bar{x} \count0=1} \the\count0")
 assert digits_of(tokens) == "0"
 assert regs.get_count(0) == 0
