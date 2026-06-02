"""Tests for Type 1 glyph outline extraction."""
from __future__ import annotations

import warnings
from typing import ClassVar

import pytest

from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._fonts.type1_outlines import (
 _parse_decrypted_body,
 decrypt_charstring,
 decrypt_eexec,
 extract_glyph_outlines,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cmr10_pfb():
 """Load cmr10 PFB data."""
 mgr = FontManager()
 pfb = mgr.load_pfb("cmr10")
 assert pfb is not None, "cmr10.pfb must be bundled"
 return pfb


@pytest.fixture(scope="module")
def cmr10_outlines(cmr10_pfb):
 """Extract all outlines from cmr10."""
 return extract_glyph_outlines(cmr10_pfb)


@pytest.fixture(scope="module")
def cmr10_decrypted(cmr10_pfb):
 """Decrypted eexec body from cmr10."""
 return decrypt_eexec(cmr10_pfb.binary_body)


# ---------------------------------------------------------------------------
# Decryption tests
# ---------------------------------------------------------------------------

class TestDecryptEexec:
 def test_decrypt_eexec_known_output(self, cmr10_pfb):
 """decrypt_eexec on cmr10 produces recognizable PostScript."""
 result = decrypt_eexec(cmr10_pfb.binary_body)
 # Decrypted eexec should contain recognizable PostScript keywords
 assert b"/Subrs" in result or b"/CharStrings" in result

 def test_decrypt_eexec_returns_bytes(self, cmr10_pfb):
 result = decrypt_eexec(cmr10_pfb.binary_body)
 assert isinstance(result, bytes)
 assert len(result) > 0


class TestDecryptCharstring:
 def test_decrypt_charstring_known_output(self, cmr10_pfb):
 """decrypt_charstring produces non-empty bytes."""
 decrypted = decrypt_eexec(cmr10_pfb.binary_body)
 _subrs, charstrings = _parse_decrypted_body(decrypted)
 # Take any charstring and decrypt it
 _name, encrypted = next(iter(charstrings.items()))
 result = decrypt_charstring(encrypted)
 assert isinstance(result, bytes)
 assert len(result) > 0

 def test_decrypt_charstring_different_from_input(self, cmr10_pfb):
 decrypted = decrypt_eexec(cmr10_pfb.binary_body)
 _subrs, charstrings = _parse_decrypted_body(decrypted)
 _name, encrypted = next(iter(charstrings.items()))
 result = decrypt_charstring(encrypted)
 assert result != encrypted


# ---------------------------------------------------------------------------
# Body parsing tests
# ---------------------------------------------------------------------------

class TestParseDecryptedBody:
 def test_parse_decrypted_body_finds_charstrings(self, cmr10_decrypted):
 """Decrypted cmr10 contains A, B, etc. in charstrings."""
 _subrs, charstrings = _parse_decrypted_body(cmr10_decrypted)
 assert "A" in charstrings
 assert "B" in charstrings
 assert "a" in charstrings

 def test_parse_decrypted_body_finds_subrs(self, cmr10_decrypted):
 """Decrypted cmr10 has non-empty subrs list."""
 subrs, _charstrings = _parse_decrypted_body(cmr10_decrypted)
 assert len(subrs) > 0
 # At least some subrs should have data
 non_empty = [s for s in subrs if s]
 assert len(non_empty) > 0


# ---------------------------------------------------------------------------
# Outline extraction tests
# ---------------------------------------------------------------------------

class TestExtractOutlines:
 def test_extract_outlines_cmr10_has_entries(self, cmr10_outlines):
 """Non-empty dict with entries for common ASCII codes."""
 assert len(cmr10_outlines) > 0
 # A=65, H=72, e=101
 assert 65 in cmr10_outlines
 assert 72 in cmr10_outlines
 assert 101 in cmr10_outlines

 def test_outline_width_positive(self, cmr10_outlines):
 """Every GlyphOutline has width > 0."""
 for code, outline in cmr10_outlines.items():
 assert outline.width > 0, f"code {code} has width={outline.width}"

 def test_outline_svg_path_nonempty(self, cmr10_outlines):
 """H (72) and e (101) have non-empty svg_path."""
 assert cmr10_outlines[72].svg_path != ""
 assert cmr10_outlines[101].svg_path != ""

 def test_svg_path_starts_with_moveto(self, cmr10_outlines):
 """Every non-empty svg_path starts with 'M' (moveto)."""
 for code, outline in cmr10_outlines.items():
 if outline.svg_path:
 assert outline.svg_path.startswith("M"), (
 f"code {code}: path starts with {outline.svg_path[:5]!r}"
 )

 def test_svg_path_valid_commands(self, cmr10_outlines):
 """Path data only contains M, L, C, Z commands with correct operands."""
 for code, outline in cmr10_outlines.items():
 if not outline.svg_path:
 continue
 # Split by command letter boundaries
 parts = outline.svg_path.split(" ")
 i = 0
 while i < len(parts):
 cmd = parts[i]
 if cmd == "M" or cmd == "L":
 assert i + 2 < len(parts), f"code {code}: incomplete {cmd}"
 i += 3
 elif cmd == "C":
 assert i + 6 < len(parts), f"code {code}: incomplete C"
 i += 7
 elif cmd == "Z":
 i += 1
 else:
 # Should be a number (part of previous command)
 # This means the format is wrong
 pytest.fail(
 f"code {code}: unexpected token '{cmd}' in path"
 )

 def test_outline_for_nonexistent_code_missing(self, cmr10_outlines):
 """Code 255 (typically unused in cmr10) is not in the dict."""
 assert 255 not in cmr10_outlines

 def test_hsbw_sets_width(self, cmr10_outlines):
 """Check that width is set correctly from hsbw (A should be ~750)."""
 a_outline = cmr10_outlines[65]
 assert 700 <= a_outline.width <= 800 # cmr10 A width ≈ 750

 def test_subr_call_and_return(self, cmr10_outlines):
 """Glyphs that use subrs still produce valid paths."""
 # Most CM glyphs use subroutines; if callsubr/return were broken,
 # the paths would be empty or malformed.
 h_outline = cmr10_outlines[72]
 assert h_outline.svg_path.count("M") >= 1
 assert h_outline.svg_path.count("C") >= 1 or h_outline.svg_path.count("L") >= 1

 def test_malformed_charstring_returns_empty(self):
 """Truncated charstring data produces empty outline with warning."""
 from aspose_tex._fonts.type1_outlines import _interpret_charstring

 with warnings.catch_warnings(record=True):
 warnings.simplefilter("always")
 outline = _interpret_charstring(
 b"\x00\x01", # truncated/garbage
 [],
 glyph_name="test_bad",
 )
 assert outline.width == 0 or outline.svg_path == ""


class TestSeacComposite:
 def test_seac_composite_char(self, cmr10_pfb, cmr10_outlines):
 """If cmr10 has seac-based composites, they produce valid outlines."""
 # seac composites in CM fonts are relatively rare; the test verifies
 # that IF any exist, they have valid paths. If none exist, the test
 # passes trivially.
 for _code, outline in cmr10_outlines.items():
 if outline.svg_path:
 # All outlines should be valid
 assert outline.svg_path.startswith("M")


# ---------------------------------------------------------------------------
# : ligature slots 11..15 (ff, fi, fl, ffi, ffl)
# ---------------------------------------------------------------------------

class TestLigatureCoverage:
 """CM fonts place the five ligatures at TeX-convention slots 11..15 and
 duplicate them at PostScript slots 174..178. Regression guard for :
 the outline dict must carry non-empty entries for both slot ranges."""

 _LIGATURE_CODES: ClassVar[tuple[int, ...]] = (11, 12, 13, 14, 15)
 _POSTSCRIPT_TWINS: ClassVar[tuple[tuple[int, int], ...]] = (
 (11, 174), (12, 175), (13, 176), (14, 177), (15, 178),
 )
 _EXPECTED_NAMES: ClassVar[dict[int, str]] = {
 11: "ff", 12: "fi", 13: "fl", 14: "ffi", 15: "ffl",
 }

 def test_cmr10_has_ligature_codes_11_to_15(self, cmr10_outlines):
 """Codes 11..15 are present with non-empty svg_path and width > 0."""
 for code in self._LIGATURE_CODES:
 assert code in cmr10_outlines, (
 f"cmr10 outline missing for ligature code {code} "
 f"({self._EXPECTED_NAMES[code]})"
 )
 outline = cmr10_outlines[code]
 assert outline.width > 0, f"code {code}: width={outline.width}"
 assert outline.svg_path, f"code {code}: empty svg_path"
 assert outline.svg_path.startswith("M"), (
 f"code {code}: path starts with {outline.svg_path[:5]!r}"
 )

 def test_cmr10_ligature_codes_match_postscript_slots(self, cmr10_outlines):
 """TeX-slot and PostScript-slot codes for each ligature share the
 same GlyphOutline (same charstring → same cached object)."""
 for tex_code, ps_code in self._POSTSCRIPT_TWINS:
 assert tex_code in cmr10_outlines, tex_code
 assert ps_code in cmr10_outlines, ps_code
 assert cmr10_outlines[tex_code] is cmr10_outlines[ps_code], (
 f"codes {tex_code} and {ps_code} expected to share outline"
 )

 def test_cmr10_encoding_codes_all_covered(self, cmr10_pfb, cmr10_outlines):
 """Every code in pfb.encoding that has a matching charstring has
 an entry in the returned dict — not just a single-code subset."""
 from aspose_tex._fonts.type1_outlines import (
 _parse_decrypted_body,
 decrypt_eexec,
 )

 _subrs, charstrings = _parse_decrypted_body(
 decrypt_eexec(cmr10_pfb.binary_body)
 )
 expected_codes = {
 code
 for code, name in cmr10_pfb.encoding.items()
 if name in charstrings
 }
 missing = expected_codes - set(cmr10_outlines.keys())
 # Allow a single glyph to be missing only if its outline came back
 # empty (width=0 AND no path) — currently none should.
 assert not missing, f"codes missing from outlines: {sorted(missing)}"


# ---------------------------------------------------------------------------
# : Type 1 Flex mechanism must not leak spurious moveto commands
# ---------------------------------------------------------------------------

class TestFlexFixTEX41:
 """Regression guard for : CM glyphs that use the Type 1 Flex
 mechanism (OtherSubr 0/1/2) were emitting one SVG `M` per rmoveto inside
 the flex sequence, producing orphan subpaths without matching `Z`.

 The 19 codes listed in `_DEFECTIVE_CODES` were observed with
 `M_count - Z_count >= 2` prior to the fix. After the fix, every outline
 in cmr10 must have balanced M/Z counts."""

 _DEFECTIVE_CODES: ClassVar[tuple[int, ...]] = (
 65, 76, 84, 86, 87,
 102, 104, 105, 107, 108, 109, 110,
 112, 113, 114, 118, 119, 120, 121,
 )
 _KNOWN_GOOD_CODES: ClassVar[tuple[int, ...]] = (79, 99, 97, 111, 101)

 def test_defective_codes_have_balanced_M_Z(self, cmr10_outlines): # noqa: N802 — 'M'/'Z' are SVG path commands under test
 """Every previously-defective code has M_count == Z_count >= 1."""
 for code in self._DEFECTIVE_CODES:
 assert code in cmr10_outlines, f"code {code} missing from outlines"
 path = cmr10_outlines[code].svg_path
 m = path.count("M")
 z = path.count("Z")
 assert m == z, f"code {code}: M={m} Z={z} (expected balanced)"
 assert m >= 1, f"code {code}: empty path"

 def test_code_65_has_exactly_two_subpaths(self, cmr10_outlines):
 """Code 65 (A) has exactly 2 M and 2 Z — outer triangle + inner
 counter bar — matching dvisvgm's reference g0-65 structure."""
 path = cmr10_outlines[65].svg_path
 assert path.count("M") == 2, f"A: M={path.count('M')} (expected 2)"
 assert path.count("Z") == 2, f"A: Z={path.count('Z')} (expected 2)"

 def test_known_good_codes_unchanged(self, cmr10_outlines):
 """Glyphs without Flex (O, c, a, o, e) keep their original structure
 — the fix must not regress non-flex paths."""
 expected = {79: 2, 99: 1, 97: 2, 111: 2, 101: 2}
 for code, want_m in expected.items():
 path = cmr10_outlines[code].svg_path
 m = path.count("M")
 assert m == want_m, f"code {code}: M={m} (expected {want_m})"
 assert path.count("Z") == m, f"code {code}: Z != M"

 def test_no_outline_has_orphan_movetos(self, cmr10_outlines):
 """FR-4a smoke heuristic: no glyph in cmr10 may have
 `M_count - Z_count >= 2`."""
 offenders = [
 code
 for code, g in cmr10_outlines.items()
 if g.svg_path.count("M") - g.svg_path.count("Z") >= 2
 ]
 assert not offenders, f"orphan M detected in codes: {sorted(offenders)}"
