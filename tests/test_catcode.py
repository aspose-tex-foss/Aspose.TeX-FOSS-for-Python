"""Unit tests for CatcodeTable and Catcode enum.

Tests mirror test plan (tests/test_catcode.py section).
"""

import pytest

from aspose_tex._input.catcode import Catcode, CatcodeTable


class TestCatcodeEnum:
 def test_default_all_16_catcodes_present(self):
 """Catcode enum has exactly 16 members, values 0-15."""
 members = list(Catcode)
 assert len(members) == 16
 assert {int(c) for c in members} == set(range(16))

 def test_values_are_ints(self):
 """Catcode is IntEnum — values compare equal to plain ints."""
 assert Catcode.ESCAPE == 0
 assert Catcode.LETTER == 11
 assert Catcode.OTHER == 12
 assert Catcode.INVALID == 15


class TestCatcodeTableDefaults:
 def setup_method(self):
 self.tbl = CatcodeTable()

 def test_default_escape(self):
 assert self.tbl.get("\\") == Catcode.ESCAPE

 def test_default_begin_group(self):
 assert self.tbl.get("{") == Catcode.BEGIN_GROUP

 def test_default_end_group(self):
 assert self.tbl.get("}") == Catcode.END_GROUP

 def test_default_math_shift(self):
 assert self.tbl.get("$") == Catcode.MATH_SHIFT

 def test_default_alignment(self):
 assert self.tbl.get("&") == Catcode.ALIGNMENT

 def test_default_end_of_line(self):
 assert self.tbl.get(chr(13)) == Catcode.END_OF_LINE

 def test_default_parameter(self):
 assert self.tbl.get("#") == Catcode.PARAMETER

 def test_default_superscript(self):
 assert self.tbl.get("^") == Catcode.SUPERSCRIPT

 def test_default_subscript(self):
 assert self.tbl.get("_") == Catcode.SUBSCRIPT

 def test_default_ignored(self):
 assert self.tbl.get(chr(0)) == Catcode.IGNORED

 def test_default_space(self):
 assert self.tbl.get(" ") == Catcode.SPACE

 def test_default_letters(self):
 """All a-z and A-Z have catcode LETTER."""
 for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
 assert self.tbl.get(c) == Catcode.LETTER, f"Expected LETTER for {c!r}"

 def test_default_active(self):
 assert self.tbl.get("~") == Catcode.ACTIVE

 def test_default_comment(self):
 assert self.tbl.get("%") == Catcode.COMMENT

 def test_default_invalid(self):
 assert self.tbl.get(chr(127)) == Catcode.INVALID

 def test_default_other(self):
 """Digits and common punctuation default to OTHER."""
 for c in "0123456789!.,-+*/:;?@":
 assert self.tbl.get(c) == Catcode.OTHER, f"Expected OTHER for {c!r}"


class TestCatcodeTableMutability:
 def test_mutability(self):
 tbl = CatcodeTable()
 tbl.set("@", Catcode.LETTER)
 assert tbl.get("@") == Catcode.LETTER
 # Other entries unaffected
 assert tbl.get("a") == Catcode.LETTER
 assert tbl.get("\\") == Catcode.ESCAPE

 def test_overwrite_existing(self):
 tbl = CatcodeTable()
 tbl.set("\\", Catcode.OTHER)
 assert tbl.get("\\") == Catcode.OTHER

 def test_independent_instances(self):
 """Two CatcodeTable instances are independent."""
 t1 = CatcodeTable()
 t2 = CatcodeTable()
 t1.set("@", Catcode.LETTER)
 assert t2.get("@") == Catcode.OTHER # unchanged


class TestCatcodeTableValidation:
 def test_set_rejects_multi_char(self):
 tbl = CatcodeTable()
 with pytest.raises(ValueError):
 tbl.set("ab", Catcode.LETTER)

 def test_set_rejects_empty_string(self):
 tbl = CatcodeTable()
 with pytest.raises(ValueError):
 tbl.set("", Catcode.LETTER)

 def test_set_rejects_high_codepoint(self):
 tbl = CatcodeTable()
 with pytest.raises(ValueError):
 tbl.set(chr(256), Catcode.LETTER)

 def test_get_high_codepoint_returns_other(self):
 """Characters with code > 255 silently return OTHER."""
 tbl = CatcodeTable()
 assert tbl.get(chr(300)) == Catcode.OTHER
 assert tbl.get("\u4e2d") == Catcode.OTHER # CJK character
