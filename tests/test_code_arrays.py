"""Tests for CodeArrays + code-array primitive dispatch.

Two layers:

1. Direct unit tests on ``CodeArrays`` — defaults, set/get, group save/restore,
 range-violation errors.
2. End-to-end tests through ``TeXInterpreter`` — dispatch of ``\\catcode``,
 ``\\mathcode``, ``\\delcode``, ``\\sfcode``, ``\\lccode``, ``\\uccode``
 plus ``\\the\\<code><n>`` reads.

Covers AC-1, AC-11, AC-12, AC-13.
"""

from __future__ import annotations

import pytest

from aspose_tex._engine.code_arrays import CodeArrays
from aspose_tex._engine.group import GroupKind, GroupStack
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_and_capture(tex: str) -> TeXInterpreter:
 """Run TeX source through a fresh interpreter, return it for state inspection.

 Appends ``\\bye`` to the source so the interpreter terminates cleanly.
 """
 interp = TeXInterpreter()
 device = DviDevice()
 interp.run_with_device(StringInputSource(tex + r"\bye"), device)
 return interp


# ---------------------------------------------------------------------------
# Direct unit tests on CodeArrays (defaults + storage semantics)
# ---------------------------------------------------------------------------

class TestCodeArraysDefaults:
 """IniTeX default tables (TeXbook Chapter 7 + plain.tex 49-51)."""

 def test_mathcode_letters_have_variable_family_bit(self) -> None:
 codes = CodeArrays()
 # 'A' (0x41) -> 0x7141; 'a' (0x61) -> 0x7161
 assert codes.get_mathcode(ord("A")) == 0x7141
 assert codes.get_mathcode(ord("a")) == 0x7161

 def test_mathcode_digits_have_class7_family7(self) -> None:
 codes = CodeArrays()
 assert codes.get_mathcode(ord("0")) == 0x7030
 assert codes.get_mathcode(ord("9")) == 0x7039

 def test_delcode_default_minus_one_except_dot(self) -> None:
 codes = CodeArrays()
 assert codes.get_delcode(ord("(")) == -1
 assert codes.get_delcode(ord(".")) == 0

 def test_sfcode_default_1000_except_uppercase_999(self) -> None:
 codes = CodeArrays()
 assert codes.get_sfcode(ord(")")) == 1000
 assert codes.get_sfcode(ord("A")) == 999
 assert codes.get_sfcode(ord("Z")) == 999
 assert codes.get_sfcode(ord("a")) == 1000

 def test_lccode_default_uppercase_to_lowercase(self) -> None:
 codes = CodeArrays()
 # AC-13: lower(A) = 97
 assert codes.get_lccode(ord("A")) == ord("a")
 assert codes.get_lccode(ord("Z")) == ord("z")
 # lowercase letters self-map
 assert codes.get_lccode(ord("a")) == ord("a")
 # other chars are 0
 assert codes.get_lccode(ord("0")) == 0

 def test_uccode_default_lowercase_to_uppercase(self) -> None:
 codes = CodeArrays()
 # AC-13: upper(a) = 65
 assert codes.get_uccode(ord("a")) == ord("A")
 assert codes.get_uccode(ord("z")) == ord("Z")
 # uppercase letters self-map
 assert codes.get_uccode(ord("A")) == ord("A")
 assert codes.get_uccode(ord("0")) == 0

 def test_each_instance_is_independent(self) -> None:
 a = CodeArrays()
 b = CodeArrays()
 a.set_sfcode(ord(")"), 0)
 assert b.get_sfcode(ord(")")) == 1000


class TestCodeArraysGroupSaveRestore:
 """Group save/restore reuses the existing GroupStack machinery."""

 def test_set_inside_group_restored_on_close(self) -> None:
 gs = GroupStack()
 codes = CodeArrays(group_stack=gs)
 codes.set_sfcode(ord(")"), 0) # global level — no save
 gs.open_group(GroupKind.BRACE)
 codes.set_sfcode(ord(")"), 999)
 assert codes.get_sfcode(ord(")")) == 999
 gs.close_group()
 assert codes.get_sfcode(ord(")")) == 0

 def test_lccode_group_restore_independent_per_char(self) -> None:
 gs = GroupStack()
 codes = CodeArrays(group_stack=gs)
 gs.open_group(GroupKind.BRACE)
 codes.set_lccode(ord("A"), 0)
 codes.set_lccode(ord("B"), 0)
 gs.close_group()
 assert codes.get_lccode(ord("A")) == ord("a")
 assert codes.get_lccode(ord("B")) == ord("b")

 def test_global_skips_save(self) -> None:
 gs = GroupStack()
 codes = CodeArrays(group_stack=gs)
 gs.open_group(GroupKind.BRACE)
 gs.set_global()
 codes.set_sfcode(ord(")"), 999)
 gs.close_group()
 assert codes.get_sfcode(ord(")")) == 999

 def test_save_on_first_write_only(self) -> None:
 """Two writes in the same group restore the value before the first."""
 gs = GroupStack()
 codes = CodeArrays(group_stack=gs)
 codes.set_sfcode(ord(")"), 100)
 gs.open_group(GroupKind.BRACE)
 codes.set_sfcode(ord(")"), 200)
 codes.set_sfcode(ord(")"), 300)
 gs.close_group()
 assert codes.get_sfcode(ord(")")) == 100


class TestCodeArraysRangeViolations:
 """Range violations raise EngineError."""

 def test_mathcode_value_too_large(self) -> None:
 codes = CodeArrays()
 with pytest.raises(EngineError, match="mathcode value"):
 codes.set_mathcode(ord("A"), 0x8001)

 def test_sfcode_value_too_large(self) -> None:
 codes = CodeArrays()
 with pytest.raises(EngineError, match="sfcode value"):
 codes.set_sfcode(ord(")"), 99999)

 def test_delcode_value_too_small(self) -> None:
 codes = CodeArrays()
 with pytest.raises(EngineError, match="delcode value"):
 codes.set_delcode(ord("("), -2)

 def test_delcode_value_too_large(self) -> None:
 codes = CodeArrays()
 with pytest.raises(EngineError, match="delcode value"):
 codes.set_delcode(ord("("), 0x1000000)

 def test_lccode_value_out_of_byte_range(self) -> None:
 codes = CodeArrays()
 with pytest.raises(EngineError, match="lccode value"):
 codes.set_lccode(ord("A"), 256)

 def test_uccode_value_negative(self) -> None:
 codes = CodeArrays()
 with pytest.raises(EngineError, match="uccode value"):
 codes.set_uccode(ord("A"), -1)

 def test_char_code_out_of_byte_range(self) -> None:
 codes = CodeArrays()
 with pytest.raises(EngineError, match="char code"):
 codes.set_sfcode(256, 0)


# ---------------------------------------------------------------------------
# End-to-end interpreter tests for code-array primitives + \the reads
# ---------------------------------------------------------------------------

class TestCatcodePrimitive:
 """ AC-1 — \\catcode write + \\the\\catcode read."""

 def test_catcode_set_and_the(self) -> None:
 # plain.tex line 11: \catcode`\{=1 — make { a BEGIN_GROUP catcode.
 interp = _run_and_capture(r"\catcode`\{=1 \catcode`\}=2 ")
 assert interp._catcodes.get("{") == Catcode.BEGIN_GROUP
 assert interp._catcodes.get("}") == Catcode.END_GROUP

 def test_catcode_group_restore(self) -> None:
 # AC-1: catcode change reverts on group close.
 # Open a brace group, set \@'s catcode to 11 (LETTER), close, observe revert.
 interp = _run_and_capture(r"\catcode`\@=11 {\catcode`\@=12 }")
 # Outer assignment persists; inner was group-scoped and reverted to 11.
 assert int(interp._catcodes.get("@")) == 11

 def test_catcode_value_range_violation(self) -> None:
 with pytest.raises(EngineError, match=r"\\catcode value"):
 _run_and_capture(r"\catcode`\@=99 ")


class TestMathcodePrimitive:
 """ — \\mathcode write + \\the\\mathcode read."""

 def test_mathcode_set_and_the(self) -> None:
 interp = _run_and_capture('\\mathcode`\\A="0741 ')
 assert interp._code_arrays.get_mathcode(ord("A")) == 0x0741


class TestDelcodePrimitive:
 """ AC-12 — \\delcode parses 24-bit hex value."""

 def test_delcode_set(self) -> None:
 # AC-12: \delcode`\(="028300 -> 164608 (decimal of 0x028300).
 interp = _run_and_capture('\\delcode`\\(="028300 ')
 assert interp._code_arrays.get_delcode(ord("(")) == 0x028300
 assert interp._code_arrays.get_delcode(ord("(")) == 164608


class TestSfcodePrimitive:
 """ AC-11 — \\sfcode set + \\the\\sfcode read."""

 def test_sfcode_set(self) -> None:
 # plain.tex line 118: \sfcode`\)=0 \sfcode`\']=0 …
 interp = _run_and_capture(r"\sfcode`\)=0 ")
 assert interp._code_arrays.get_sfcode(ord(")")) == 0

 def test_sfcode_group_restore(self) -> None:
 interp = _run_and_capture(r"\sfcode`\)=0 {\sfcode`\)=999 }")
 assert interp._code_arrays.get_sfcode(ord(")")) == 0

 def test_global_flag_on_codes(self) -> None:
 # \global inside a group survives close.
 interp = _run_and_capture(r"{\global\sfcode`\)=999 }")
 assert interp._code_arrays.get_sfcode(ord(")")) == 999


class TestLccodeUccodePrimitive:
 """ AC-13 — \\lccode/\\uccode IniTeX defaults populated."""

 def test_lccode_default_uppercase_to_lowercase(self) -> None:
 interp = _run_and_capture("")
 # AC-13: lower(A) = 97
 assert interp._code_arrays.get_lccode(ord("A")) == 97

 def test_uccode_default_lowercase_to_uppercase(self) -> None:
 interp = _run_and_capture("")
 # AC-13: upper(a) = 65
 assert interp._code_arrays.get_uccode(ord("a")) == 65

 def test_lccode_set_clears_default(self) -> None:
 interp = _run_and_capture(r"\lccode`\A=0 ")
 assert interp._code_arrays.get_lccode(ord("A")) == 0


# ---------------------------------------------------------------------------
# \the reads through the interpreter — verify the token output stream
# ---------------------------------------------------------------------------

class TestTheCodeArrayReads:
 """\\the\\<codename><n> formats the value as decimal CharTokens."""

 def test_the_sfcode_round_trip(self) -> None:
 # \the\sfcode`\) writes `0` to the count register through \count's path
 # would be ideal, but the simplest check is to feed `\the\sfcode\)`
 # into a count assignment via tokens — instead, exercise the function
 # directly to confirm decimal formatting.
 from aspose_tex._engine.code_arrays import CodeArrays
 from aspose_tex._engine.expansion import Expander
 from aspose_tex._engine.registers import RegisterSet
 from aspose_tex._input import CatcodeTable, InputReader, Tokenizer
 from aspose_tex._input.token import ControlSequenceToken

 src = StringInputSource("`\\)")
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 regs = RegisterSet()
 regs._catcodes = catcodes
 regs._code_arrays = CodeArrays()
 regs._code_arrays.set_sfcode(ord(")"), 0)
 exp = Expander(reader, tok, catcodes, register_provider=regs)
 exp._register_set = regs

 result = regs.get_tokens_for_the(
 ControlSequenceToken("sfcode"), exp,
 )
 assert "".join(t.char for t in result) == "0"

 def test_the_catcode_reads_live_value(self) -> None:
 from aspose_tex._engine.code_arrays import CodeArrays
 from aspose_tex._engine.expansion import Expander
 from aspose_tex._engine.registers import RegisterSet
 from aspose_tex._input import CatcodeTable, InputReader, Tokenizer
 from aspose_tex._input.token import ControlSequenceToken

 src = StringInputSource("`\\{")
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 regs = RegisterSet()
 regs._catcodes = catcodes
 regs._code_arrays = CodeArrays()
 # Default catcode of '{' is BEGIN_GROUP (1).
 exp = Expander(reader, tok, catcodes, register_provider=regs)
 exp._register_set = regs

 result = regs.get_tokens_for_the(
 ControlSequenceToken("catcode"), exp,
 )
 assert "".join(t.char for t in result) == "1"
