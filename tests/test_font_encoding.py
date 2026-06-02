"""Unit tests for FontEncoding."""
from __future__ import annotations

import importlib.resources

import pytest

from aspose_tex._fonts.encoding import FontEncoding
from aspose_tex._fonts.pfb_parser import parse_pfb


@pytest.fixture(scope="module")
def cmr10_enc() -> FontEncoding:
 pkg = importlib.resources.files("aspose_tex") / "data" / "fonts"
 pfb = parse_pfb((pkg / "cmr10.pfb").read_bytes())
 return FontEncoding(pfb)


class TestGlyphNameLookup:
 """AC-5: ASCII letter/digit mapping in CM Roman encoding."""

 def test_uppercase_letters(self, cmr10_enc: FontEncoding) -> None:
 for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
 assert cmr10_enc.glyph_name(65 + i) == ch

 def test_lowercase_letters(self, cmr10_enc: FontEncoding) -> None:
 for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
 assert cmr10_enc.glyph_name(97 + i) == ch

 def test_digits(self, cmr10_enc: FontEncoding) -> None:
 names = ["zero", "one", "two", "three", "four",
 "five", "six", "seven", "eight", "nine"]
 for i, name in enumerate(names):
 assert cmr10_enc.glyph_name(48 + i) == name

 def test_notdef_for_unmapped(self, cmr10_enc: FontEncoding) -> None:
 # Code 255 is not in CM Roman encoding
 assert cmr10_enc.glyph_name(255) == ".notdef"


class TestReverseLookup:
 def test_char_code_existing(self, cmr10_enc: FontEncoding) -> None:
 assert cmr10_enc.char_code("A") == 65
 assert cmr10_enc.char_code("zero") == 48
 # Unique glyph (not aliased in CM): ASCII "z"
 assert cmr10_enc.char_code("z") == 122

 def test_char_code_missing(self, cmr10_enc: FontEncoding) -> None:
 assert cmr10_enc.char_code("nonexistent_glyph") is None


class TestDifferences:
 def test_differences_sorted(self, cmr10_enc: FontEncoding) -> None:
 diffs = cmr10_enc.differences()
 codes = [c for c, _ in diffs]
 assert codes == sorted(codes)

 def test_differences_no_notdef(self, cmr10_enc: FontEncoding) -> None:
 for _, name in cmr10_enc.differences():
 assert name != ".notdef"

 def test_differences_contains_ascii(self, cmr10_enc: FontEncoding) -> None:
 diffs = dict(cmr10_enc.differences())
 assert diffs[65] == "A"
 assert diffs[97] == "a"


class TestHasCode:
 def test_mapped_code(self, cmr10_enc: FontEncoding) -> None:
 assert cmr10_enc.has_code(65) is True

 def test_unmapped_code(self, cmr10_enc: FontEncoding) -> None:
 assert cmr10_enc.has_code(255) is False


class TestFontName:
 def test_font_name_preserved(self, cmr10_enc: FontEncoding) -> None:
 assert cmr10_enc.font_name == "CMR10"
