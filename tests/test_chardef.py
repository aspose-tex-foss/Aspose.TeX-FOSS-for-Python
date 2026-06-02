"""Tests for \\chardef / \\mathchardef / \\muskipdef.

Two layers:

1. Direct unit tests on ``RegisterSet.define_constant`` / ``resolve_constant``.
2. End-to-end tests through the expander pipeline (``parse_integer``,
 ``\\the``) and through ``TeXInterpreter`` (H-mode chardef-constant emit).

Covers AC-2 (\\chardef\\active=13), AC-7 (\\muskipdef), AC-10
(\\mathchardef\\foo="010B -> 267).
"""

from __future__ import annotations

import pytest

from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.group import GroupKind, GroupStack
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.registers import Glue, GlueOrder, RegisterSet
from aspose_tex._input import (
 CatcodeTable,
 CharToken,
 ControlSequenceToken,
 InputReader,
 StringInputSource,
 Tokenizer,
)
from aspose_tex._input.catcode import Catcode
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_env(text: str) -> tuple[Expander, RegisterSet, GroupStack]:
 """Build a minimal pipeline: reader -> tokenizer -> expander + register set."""
 src = StringInputSource(text)
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 gs = GroupStack()
 regs = RegisterSet(group_stack=gs)
 exp = Expander(reader, tok, catcodes, register_provider=regs, group_stack=gs)
 exp._register_set = regs
 return exp, regs, gs


def _drive(text: str) -> tuple[list, RegisterSet]:
 """Drive the expander, executing register commands. Return remaining tokens + regs."""
 exp, regs, _ = _make_env(text)
 tokens: list = []
 for t in exp:
 if isinstance(t, ControlSequenceToken) and regs.execute(t.name, exp):
 continue
 tokens.append(t)
 return tokens, regs


def _chars_of(tokens: list) -> str:
 return "".join(
 t.char for t in tokens
 if isinstance(t, CharToken) and t.catcode in (Catcode.OTHER, Catcode.LETTER)
 )


def _run_and_capture(tex: str) -> TeXInterpreter:
 interp = TeXInterpreter()
 device = DviDevice()
 interp.run_with_device(StringInputSource(tex + r"\bye"), device)
 return interp


# ---------------------------------------------------------------------------
# RegisterSet.define_constant / resolve_constant — unit tests
# ---------------------------------------------------------------------------

class TestRegisterSetConstantStorage:
 """Direct unit tests on RegisterSet's _constants storage (§3c)."""

 def test_define_constant_then_resolve(self) -> None:
 regs = RegisterSet()
 regs.define_constant("foo", "chardef", 42)
 assert regs.resolve_constant("foo") == ("chardef", 42)

 def test_resolve_unknown_returns_none(self) -> None:
 regs = RegisterSet()
 assert regs.resolve_constant("missing") is None

 def test_constant_group_save_restore(self) -> None:
 gs = GroupStack()
 regs = RegisterSet(group_stack=gs)
 regs.define_constant("foo", "chardef", 1)
 gs.open_group(GroupKind.BRACE)
 regs.define_constant("foo", "chardef", 2)
 assert regs.resolve_constant("foo") == ("chardef", 2)
 gs.close_group()
 assert regs.resolve_constant("foo") == ("chardef", 1)

 def test_constant_group_pop_when_first_defined_inside(self) -> None:
 gs = GroupStack()
 regs = RegisterSet(group_stack=gs)
 gs.open_group(GroupKind.BRACE)
 regs.define_constant("foo", "chardef", 7)
 gs.close_group()
 assert regs.resolve_constant("foo") is None


# ---------------------------------------------------------------------------
# \chardef + \mathchardef + \muskipdef via RegisterSet.execute
# ---------------------------------------------------------------------------

class TestChardefDefine:
 """ AC-2 — \\chardef defines a CS as a frozen char-code constant."""

 def test_chardef_define_and_use(self) -> None:
 # plain.tex line 19: \chardef\active=13.
 _, regs = _drive(r"\chardef\active=13")
 assert regs.resolve_constant("active") == ("chardef", 13)

 def test_chardef_the(self) -> None:
 # \chardef\foo=42 => \the\foo expands to "42".
 tokens, _ = _drive(r"\chardef\foo=42 \the\foo")
 assert _chars_of(tokens) == "42"

 def test_chardef_value_as_integer_via_parse_integer(self) -> None:
 # plain.tex pattern: \chardef\active=13 \catcode`\~=\active
 # The integer scanner must coerce \active to 13.
 from aspose_tex._engine.dimparser import parse_integer
 exp, regs, _ = _make_env(r"\chardef\active=13 \active")
 # First, drive the \chardef line so the constant is defined.
 for t in exp:
 if isinstance(t, ControlSequenceToken) and regs.execute(t.name, exp):
 break
 # Now exp's stream should yield \active next; parse_integer must coerce it.
 assert parse_integer(exp) == 13

 def test_chardef_value_overflow_raises(self) -> None:
 with pytest.raises(EngineError, match=r"\\chardef value 300 out of range"):
 _drive(r"\chardef\foo=300 ")

 def test_chardef_value_negative_raises(self) -> None:
 with pytest.raises(EngineError, match="Negative integer not allowed"):
 _drive(r"\chardef\foo=-1 ")

 def test_chardef_group_scope(self) -> None:
 """\\chardef inside a group is restored on group close."""
 # We can't easily wire group open/close into _drive's loop because
 # { and } pass through to the interpreter, not the register layer.
 # Use TeXInterpreter end-to-end and then inspect _register_set._constants.
 interp = _run_and_capture(r"\chardef\foo=1 {\chardef\foo=2 }")
 assert interp._register_set.resolve_constant("foo") == ("chardef", 1)


class TestMathchardefDefine:
 """ AC-10 — \\mathchardef defines + \\the returns decimal."""

 def test_mathchardef_define_and_the(self) -> None:
 # AC-10: \mathchardef\foo="010B => \the\foo -> "267".
 tokens, regs = _drive('\\mathchardef\\foo="010B \\the\\foo')
 assert regs.resolve_constant("foo") == ("mathchardef", 0x010B)
 assert _chars_of(tokens) == "267"

 def test_mathchardef_value_overflow_raises(self) -> None:
 with pytest.raises(EngineError, match=r"\\mathchardef value"):
 _drive('\\mathchardef\\foo="9000 ')

 def test_mathchardef_in_h_mode_no_op(self) -> None:
 """\\mathchardef constant in non-math mode is a no-op
 (lookup hits the constants branch but kind != 'chardef')."""
 # Should run without error.
 interp = _run_and_capture(
 '\\mathchardef\\foo="010B \\foo'
 )
 assert interp._register_set.resolve_constant("foo") == ("mathchardef", 0x010B)


class TestMuskipdefAlias:
 """ AC-7 — \\muskipdef completes the alias family."""

 def test_muskipdef_alias_then_assign(self) -> None:
 # AC-7: \muskipdef\testmuskip=42 \testmuskip=3mu writes muskip[42].
 # We don't yet have `mu` units in parse_glue, but we can verify
 # that \muskipdef registers an alias and integer-value reads via \the work.
 _, regs = _drive(r"\muskipdef\m=42")
 assert regs.resolve_alias("m") == ("muskip", 42)

 def test_muskipdef_assignment_through_alias(self) -> None:
 # \muskipdef\m=42 then \m=2pt plus 1pt writes RegisterBank.muskip[42].
 # parse_glue accepts pt because the muglue dispatcher just delegates.
 _, regs = _drive(r"\muskipdef\m=42 \m=2pt plus 1pt")
 assert regs._bank.muskip[42] == Glue(
 width=2 * 65536, stretch=65536, stretch_order=GlueOrder.NORMAL,
 shrink=0, shrink_order=GlueOrder.NORMAL,
 )

 def test_muskipdef_the_round_trip(self) -> None:
 # \the\m formats the muskip value.
 tokens, _ = _drive(r"\muskipdef\m=42 \m=3pt \the\m")
 s = _chars_of(tokens)
 assert "196608" in s # 3pt = 3 * 65536 sp


# ---------------------------------------------------------------------------
# H-mode chardef constant emit — exercise the dispatch path in TeXInterpreter
# ---------------------------------------------------------------------------

class TestChardefEmitInHMode:
 """§5c — \\chardef constant in H mode emits a CharNode."""

 def test_chardef_in_h_mode_runs_without_error(self) -> None:
 # \chardef\bang=33 \bang in horizontal mode appends CharNode(33) (= '!').
 # We confirm the run completes with valid DVI output (so dispatch hit
 # _handle_chardef_constant -> _handle_char without crashing).
 interp = TeXInterpreter()
 device = DviDevice()
 interp.run_with_device(
 StringInputSource(r"\chardef\bang=33 \bang \bye"),
 device,
 )
 dvi = device.get_bytes()
 assert dvi is not None and dvi[0] == 0xF7 # PRE opcode
 # The character '!' (code 33) must appear as a set_char_33 opcode in DVI.
 assert bytes([33]) in dvi
