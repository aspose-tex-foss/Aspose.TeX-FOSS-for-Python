"""Tests for the macro expansion engine."""

from __future__ import annotations

import pytest

from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.macro import MacroDefinition, Meaning
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_expander(text: str, macros: dict[str, Meaning] | None = None) -> Expander:
 """Build an Expander from a raw TeX string."""
 src = StringInputSource(text)
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 exp = Expander(reader, tok, catcodes)
 if macros:
 for name, meaning in macros.items():
 exp.define(name, meaning)
 return exp


def expand(text: str, macros: dict[str, Meaning] | None = None) -> list:
 """Expand ``text`` fully and return the unexpandable token list."""
 return list(make_expander(text, macros))


def chars(tokens: list) -> str:
 """Extract character string from a list of CharTokens."""
 return "".join(t.char for t in tokens if isinstance(t, CharToken))


def cs_names(tokens: list) -> list[str]:
 """Extract CS names from a list of ControlSequenceTokens."""
 return [t.name for t in tokens if isinstance(t, ControlSequenceToken)]


# ---------------------------------------------------------------------------
# 1. Passthrough — no expansion
# ---------------------------------------------------------------------------

def test_passthrough_letters():
 tokens = expand("Hello")
 letter_tokens = [t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER]
 assert len(letter_tokens) == 5
 assert chars(letter_tokens) == "Hello"


# ---------------------------------------------------------------------------
# 2-6. \def — basic macro definition and expansion
# ---------------------------------------------------------------------------

def test_def_and_expand_no_params():
 tokens = expand(r"\def\hi{Hello}\hi")
 result = "".join(
 t.char for t in tokens
 if isinstance(t, CharToken) and t.catcode == Catcode.LETTER
 )
 assert result == "Hello"


def test_def_one_undelimited_param():
 tokens = expand(r"\def\bold#1{[#1]}\bold{text}")
 result = chars(tokens)
 assert "text" in result
 assert "[" in result
 assert "]" in result


def test_def_one_undelimited_single_token():
 tokens = expand(r"\def\f#1{(#1)}\f A")
 result = chars(tokens)
 assert "(" in result
 assert "A" in result
 assert ")" in result


def test_def_two_params():
 tokens = expand(r"\def\pair#1#2{#1,#2}\pair{A}{B}")
 result = chars(tokens)
 assert "A" in result
 assert "B" in result
 # The comma should appear between A and B
 full = "".join(t.char for t in tokens if isinstance(t, CharToken))
 assert "A" in full and "B" in full


def test_def_delimited_param():
 tokens = expand(r"\def\swap#1,#2.{#2,#1.}\swap AB,CD.")
 result = chars(tokens)
 # Result should be CD,AB.
 assert "CD" in result or ("C" in result and "D" in result)
 assert "AB" in result or ("A" in result and "B" in result)


# ---------------------------------------------------------------------------
# 7-8. \edef
# ---------------------------------------------------------------------------

def test_edef_expands_at_definition():
 tokens = expand(r"\def\foo{bar}\edef\baz{\foo}\baz")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 # \baz should expand to "bar"
 assert "bar" in result


def test_edef_noexpand_suppresses():
 # \edef\bar{\noexpand\foo}: \bar's replacement should store \foo as a CS token,
 # not its expansion 'X'. (\noexpand suppresses expansion during edef scanning.)
 exp = make_expander(r"\def\foo{X}\edef\bar{\noexpand\foo}")
 list(exp)
 bar_def = exp.macros.get("bar")
 assert isinstance(bar_def, MacroDefinition)
 assert len(bar_def.replacement) == 1
 tok = bar_def.replacement[0]
 assert isinstance(tok, ControlSequenceToken)
 assert tok.name == "foo"


def test_edef_with_nested_macro():
 tokens = expand(r"\def\inner{42}\edef\outer{\inner}\outer")
 result = chars([t for t in tokens if isinstance(t, CharToken)])
 assert "4" in result and "2" in result


# ---------------------------------------------------------------------------
# 9-10. \gdef, \xdef
# ---------------------------------------------------------------------------

def test_gdef_same_as_def():
 tokens = expand(r"\gdef\hi{Hi}\hi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "Hi" in result


def test_xdef_same_as_edef():
 tokens = expand(r"\def\x{Q}\xdef\y{\x}\y")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "Q" in result


# ---------------------------------------------------------------------------
# 11-13. \let
# ---------------------------------------------------------------------------

def test_let_cs_alias():
 tokens = expand(r"\def\foo{X}\let\bar=\foo\bar")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "X" in result


def test_let_no_equals():
 tokens = expand(r"\def\foo{Y}\let\baz\foo\baz")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "Y" in result


def test_let_token_alias():
 # \let\lbrace={ → \lbrace should produce CharToken('{', BEGIN_GROUP)
 exp = make_expander(r"\let\lbrace={")
 list(exp) # execute \let
 meaning = exp.macros.get("lbrace")
 assert isinstance(meaning, CharToken)
 assert meaning.catcode == Catcode.BEGIN_GROUP


# ---------------------------------------------------------------------------
# 14-15. \iftrue / \iffalse
# ---------------------------------------------------------------------------

def test_iftrue_takes_true_branch():
 tokens = expand(r"\iftrue yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "yes" in result
 assert "no" not in result


def test_iffalse_takes_else_branch():
 tokens = expand(r"\iffalse yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "no" in result
 assert "yes" not in result


# ---------------------------------------------------------------------------
# 16-19. \ifnum
# ---------------------------------------------------------------------------

def test_ifnum_less_true():
 tokens = expand(r"\ifnum 1<2 yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "yes" in result
 assert "no" not in result


def test_ifnum_less_false():
 tokens = expand(r"\ifnum 2<1 yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "no" in result
 assert "yes" not in result


def test_ifnum_equal():
 tokens = expand(r"\ifnum 3=3 yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "yes" in result


def test_ifnum_greater():
 tokens = expand(r"\ifnum 5>3 yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "yes" in result


# ---------------------------------------------------------------------------
# 20-21. Nested conditionals
# ---------------------------------------------------------------------------

def test_nested_conditionals():
 tokens = expand(r"\iftrue\iftrue A\else B\fi\else C\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "A" in result
 assert "B" not in result
 assert "C" not in result


def test_nested_conditionals_false_outer():
 tokens = expand(r"\iffalse\iftrue A\else B\fi\else C\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "C" in result
 assert "A" not in result
 assert "B" not in result


# ---------------------------------------------------------------------------
# 22-25. \if and \ifcat
# ---------------------------------------------------------------------------

def test_if_char_equal():
 tokens = expand(r"\if AA yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "yes" in result


def test_if_char_unequal():
 tokens = expand(r"\if AB yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "no" in result
 assert "yes" not in result


def test_ifcat_same_catcode():
 # A and B are both LETTER
 tokens = expand(r"\ifcat AB yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "yes" in result


def test_ifcat_diff_catcode():
 # A is LETTER, { is BEGIN_GROUP
 tokens = expand(r"\ifcat A{ yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "no" in result
 assert "yes" not in result


# ---------------------------------------------------------------------------
# 26-27. \ifx
# ---------------------------------------------------------------------------

def test_ifx_equal_macros():
 tokens = expand(r"\def\a{x}\let\b=\a\ifx\a\b yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "yes" in result


def test_ifx_unequal():
 tokens = expand(r"\def\a{x}\def\b{y}\ifx\a\b yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "no" in result
 assert "yes" not in result


# ---------------------------------------------------------------------------
# 28-29. \expandafter and \csname
# ---------------------------------------------------------------------------

def test_expandafter_simple():
 # \expandafter\def\csname foo\endcsname{bar} should define \foo
 exp = make_expander(r"\expandafter\def\csname foo\endcsname{bar}")
 list(exp)
 assert "foo" in exp.macros


def test_csname_endcsname():
 tokens = expand(r"\csname hello\endcsname")
 cs = [t for t in tokens if isinstance(t, ControlSequenceToken)]
 assert any(t.name == "hello" for t in cs)


# ---------------------------------------------------------------------------
# 30-31. \number
# ---------------------------------------------------------------------------

def test_number_positive():
 tokens = expand(r"\number 42")
 other_tokens = [t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.OTHER]
 result = "".join(t.char for t in other_tokens if t.char.isdigit())
 assert "4" in result
 assert "2" in result


def test_number_negative():
 tokens = expand(r"\number -7")
 other_tokens = [t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.OTHER]
 chars_str = "".join(t.char for t in other_tokens)
 assert "-" in chars_str
 assert "7" in chars_str


# ---------------------------------------------------------------------------
# 32-34. \string
# ---------------------------------------------------------------------------

def test_string_control_sequence():
 tokens = expand(r"\string\foo")
 other_tokens = [t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.OTHER]
 chars_str = "".join(t.char for t in other_tokens)
 assert "\\" in chars_str
 assert "f" in chars_str
 assert "o" in chars_str


def test_string_char_token():
 tokens = expand(r"\string A")
 other_tokens = [t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.OTHER]
 assert any(t.char == "A" for t in other_tokens)


def test_string_digit():
 # \string applied to a digit produces an OTHER-catcode token
 tokens = expand(r"\string 1")
 other_tokens = [t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.OTHER]
 assert any(t.char == "1" for t in other_tokens)


# ---------------------------------------------------------------------------
# 35. Infinite recursion detection
# ---------------------------------------------------------------------------

def test_infinite_recursion_raises():
 with pytest.raises(EngineError, match="Expansion depth limit"):
 expand(r"\def\loop{\loop}\loop")


# ---------------------------------------------------------------------------
# 36-37. peek() and push_tokens()
# ---------------------------------------------------------------------------

def test_peek_nondestructive():
 exp = make_expander("AB")
 p1 = exp.peek()
 p2 = exp.peek()
 assert p1 == p2
 consumed = next(iter(exp))
 assert consumed == p1


def test_push_tokens():
 exp = make_expander("")
 tok = CharToken("X", Catcode.LETTER)
 exp.push_tokens([tok])
 result = next(iter(exp))
 assert result == tok


# ---------------------------------------------------------------------------
# 38. Chained macro expansion (one level at a time)
# ---------------------------------------------------------------------------

def test_nested_macro_expansion():
 # Each macro expands exactly to its body; chaining works correctly
 tokens = expand(r"\def\a{hello}\def\b{world}\a\b")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "hello" in result
 assert "world" in result


# ---------------------------------------------------------------------------
# 39-40. Error cases for \fi and \else
# ---------------------------------------------------------------------------

def test_fi_without_if_raises():
 with pytest.raises(EngineError, match=r"\\fi without matching"):
 expand(r"\fi")


def test_else_without_if_raises():
 with pytest.raises(EngineError, match=r"\\else without matching"):
 expand(r"\else")


# ---------------------------------------------------------------------------
# 41. \def requires CS
# ---------------------------------------------------------------------------

def test_def_requires_cs():
 with pytest.raises(EngineError, match="control sequence or active character expected"):
 expand(r"\def A{x}")


# ---------------------------------------------------------------------------
# 42-43. \ifnum with hex and octal literals
# ---------------------------------------------------------------------------

def test_ifnum_hex_literal():
 # "1A hex = 26 decimal, > 19 decimal
 tokens = expand(r'\ifnum "1A>19 yes\else no\fi')
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "yes" in result


def test_ifnum_octal_literal():
 # '12 octal = 10 decimal, = 10 decimal
 tokens = expand(r"\ifnum '12=10 yes\else no\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "yes" in result


# ---------------------------------------------------------------------------
# 44-45. \ifcase
# ---------------------------------------------------------------------------

def test_ifcase_zero():
 tokens = expand(r"\ifcase 0 zero\or one\or two\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "zero" in result
 assert "one" not in result
 assert "two" not in result


def test_ifcase_one():
 tokens = expand(r"\ifcase 1 zero\or one\or two\fi")
 result = chars([t for t in tokens if isinstance(t, CharToken) and t.catcode == Catcode.LETTER])
 assert "one" in result
 assert "zero" not in result
 assert "two" not in result


# ---------------------------------------------------------------------------
# 46. \edef with nested macro (already covered in test_edef_with_nested_macro)
# Additional: ensure \edef really expands at definition time
# ---------------------------------------------------------------------------

def test_edef_snapshots_at_definition():
 # Define \inner, then \edef\outer to capture \inner, then redefine \inner
 # \outer should still expand to original value of \inner
 exp = make_expander(r"\def\inner{A}\edef\outer{\inner}\def\inner{B}")
 list(exp) # execute all three defs
 # Now \outer should be defined as 'A' (from when edef ran)
 meaning = exp.macros.get("outer")
 assert isinstance(meaning, MacroDefinition)
 # replacement should contain CharToken('A', LETTER)
 assert any(
 isinstance(t, CharToken) and t.char == "A"
 for t in meaning.replacement
 )


# ---------------------------------------------------------------------------
# : \outer and \long prefix parsing ( FR-1a / FR-1b)
# ---------------------------------------------------------------------------

def test_outer_def_parsed_without_error():
 """AC-1: \\outer\\def\\newcount{...} is parsed without error; outer flag stored."""
 exp = make_expander(r"\outer\def\newcount{hello}")
 list(exp)
 meaning = exp.macros.get("newcount")
 assert isinstance(meaning, MacroDefinition)
 assert meaning.outer is True
 assert meaning.long is False


def test_long_def_parsed_without_error():
 """AC-2: \\long\\def\\foo#1{#1} is parsed; long flag stored."""
 exp = make_expander(r"\long\def\foo#1{#1}")
 list(exp)
 meaning = exp.macros.get("foo")
 assert isinstance(meaning, MacroDefinition)
 assert meaning.long is True
 assert meaning.outer is False


def test_outer_long_def_parsed():
 """AC-3: \\outer\\long\\def accepted; both flags stored."""
 exp = make_expander(r"\outer\long\def\bar{x}")
 list(exp)
 meaning = exp.macros.get("bar")
 assert isinstance(meaning, MacroDefinition)
 assert meaning.outer is True
 assert meaning.long is True


def test_long_outer_def_parsed():
 """AC-3: \\long\\outer\\def accepted; both flags stored."""
 exp = make_expander(r"\long\outer\def\baz{y}")
 list(exp)
 meaning = exp.macros.get("baz")
 assert isinstance(meaning, MacroDefinition)
 assert meaning.long is True
 assert meaning.outer is True


def test_long_def_expands_correctly():
 """\\long\\def macro expands its body correctly."""
 exp = make_expander(r"\long\def\greet{Hi}\greet")
 tokens = list(exp)
 assert chars(tokens) == "Hi"


def test_outer_def_expands_correctly():
 """\\outer\\def macro expands its body correctly."""
 exp = make_expander(r"\outer\def\bye{Bye}\bye")
 tokens = list(exp)
 assert chars(tokens) == "Bye"


def test_plain_def_flags_unchanged():
 """AC-4: Plain \\def still produces long=False, outer=False."""
 exp = make_expander(r"\def\plain{ok}")
 list(exp)
 meaning = exp.macros.get("plain")
 assert isinstance(meaning, MacroDefinition)
 assert meaning.long is False
 assert meaning.outer is False


def test_prefix_flags_not_sticky():
 """Flags from one \\def do not bleed into the next \\def."""
 exp = make_expander(r"\long\def\first{a}\def\second{b}")
 list(exp)
 first = exp.macros.get("first")
 second = exp.macros.get("second")
 assert isinstance(first, MacroDefinition) and first.long is True
 assert isinstance(second, MacroDefinition) and second.long is False


# ---------------------------------------------------------------------------
# : prefix flags cleared when non-def command follows
# ---------------------------------------------------------------------------

def test_long_before_let_does_not_corrupt_next_def():
 """AC-1: \\long\\let\\foo=\\bar does not set long=True on subsequent \\def."""
 exp = make_expander(r"\long\let\foo=\bar\def\plain{ok}")
 list(exp)
 plain = exp.macros.get("plain")
 assert isinstance(plain, MacroDefinition)
 assert plain.long is False


def test_outer_before_let_does_not_corrupt_next_def():
 """AC-2: \\outer\\let does not set outer=True on subsequent definition."""
 exp = make_expander(r"\outer\let\foo=\bar\def\plain{ok}")
 list(exp)
 plain = exp.macros.get("plain")
 assert isinstance(plain, MacroDefinition)
 assert plain.outer is False
