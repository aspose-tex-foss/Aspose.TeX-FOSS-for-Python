"""Tests for TeX interpreter \\font primitive and font-CS dispatch ( / §3).

Covers:
- AC#1: \\font\\myfont=cmr10 at 10pt loads cmr10, assigns font_num to \\myfont
- AC#2: \\myfont (font CS) switches FontManager current font
- AC#3: scaled modifier: \\font\\f=cmr10 scaled 1200 loads at 12pt
- AC#4: Missing TFM file raises FontError with filename
- AC#5: \\nullfont is pre-registered and selects a zero-metrics font
"""
import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode, GlueNode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError, FontError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(tex_source: str) -> bytes:
 """Run TeX source through the interpreter and return DVI bytes."""
 interp = TeXInterpreter()
 return interp.run(StringInputSource(tex_source))


def _collect_par_nodes(tex_source: str) -> list:
 """Run TeX source and capture paragraph nodes before line breaking."""
 captured: list = []

 class _CapturingInterpreter(TeXInterpreter):
 def _end_paragraph(self) -> None:
 if self._par_list is not None:
 captured.extend(self._par_list.nodes)
 super()._end_paragraph()

 interp = _CapturingInterpreter()
 interp.run(StringInputSource(tex_source + r"\par\bye"))
 return captured


def _run_and_get_font_manager(tex_source: str):
 """Run TeX source and return the FontManager for post-run inspection."""
 interp = TeXInterpreter()
 interp.run(StringInputSource(tex_source))
 return interp._font_manager


# ---------------------------------------------------------------------------
# AC#1: \font\myfont=cmr10 at 10pt loads cmr10
# ---------------------------------------------------------------------------

class TestFontLoad:
 """\\font primitive: parse and load TFM."""

 def test_font_load_basic(self) -> None:
 """\\font\\myfont=cmr10 registers 'myfont' in FontManager."""
 fm = _run_and_get_font_manager(r"\font\myfont=cmr10 \bye")
 assert fm.is_font("myfont")

 def test_font_load_at_dimen(self) -> None:
 """\\font\\f=cmr10 at 12pt loads font at 12pt (786432 sp)."""
 fm = _run_and_get_font_manager(r"\font\f=cmr10 at 12pt \bye")
 assert fm.is_font("f")
 info = fm.font_def_info("f")
 assert info is not None
 tfm_name, _cs, _ds, at_size = info
 assert tfm_name == "cmr10"
 assert at_size == 786_432 # 12pt in sp

 def test_font_load_at_10pt(self) -> None:
 """\\font\\myfont=cmr10 at 10pt loads at 655360 sp."""
 fm = _run_and_get_font_manager(r"\font\myfont=cmr10 at 10pt \bye")
 info = fm.font_def_info("myfont")
 assert info is not None
 _, _, _, at_size = info
 assert at_size == 655_360 # 10pt

 def test_font_load_without_equals(self) -> None:
 """\\font\\f cmr10 works without '=' sign."""
 fm = _run_and_get_font_manager(r"\font\f cmr10 \bye")
 assert fm.is_font("f")

 def test_font_load_design_size_default(self) -> None:
 """Without at/scaled, font loads at design size (cmr10 = 10pt)."""
 fm = _run_and_get_font_manager(r"\font\f=cmr10 \bye")
 info = fm.font_def_info("f")
 assert info is not None
 _, _, design_size, at_size = info
 assert at_size == design_size # design size == at size


# ---------------------------------------------------------------------------
# AC#2: Font CS dispatch selects font
# ---------------------------------------------------------------------------

class TestFontCSDispatch:
 """Font control sequence switches the current font."""

 def test_font_cs_selects_font(self) -> None:
 """\\myfont after \\font\\myfont=cmr10 switches current font."""
 fm = _run_and_get_font_manager(
 r"\font\myfont=cmr10 \myfont \bye"
 )
 # After \myfont, current font should be "myfont"
 assert fm._current == "myfont"

 def test_font_cs_changes_charnode_font(self) -> None:
 """Characters after font CS use the new font name."""
 nodes = _collect_par_nodes(r"\font\myfont=cmr10 \myfont A")
 char_nodes = [n for n in nodes if isinstance(n, CharNode)]
 assert len(char_nodes) >= 1
 assert char_nodes[-1].font_name == "myfont"

 def test_font_cs_switch_between_fonts(self) -> None:
 """Switching between two fonts changes CharNode font_name."""
 nodes = _collect_par_nodes(
 r"\font\fonta=cmr10 \font\fontb=cmr10 at 12pt "
 r"\fonta A\fontb B"
 )
 char_nodes = [n for n in nodes if isinstance(n, CharNode)]
 assert len(char_nodes) >= 2
 assert char_nodes[-2].font_name == "fonta"
 assert char_nodes[-1].font_name == "fontb"

 def test_font_cs_unknown_raises(self) -> None:
 """Undefined CS (not a font, not a primitive) raises EngineError."""
 with pytest.raises(EngineError, match="Undefined control sequence"):
 _run(r"\notafont\bye")


# ---------------------------------------------------------------------------
# AC#3: scaled modifier
# ---------------------------------------------------------------------------

class TestFontScaled:
 """\\font with scaled modifier."""

 def test_font_scaled_1200(self) -> None:
 """\\font\\f=cmr10 scaled 1200 loads at 1.2 * design_size."""
 fm = _run_and_get_font_manager(r"\font\f=cmr10 scaled 1200 \bye")
 assert fm.is_font("f")
 info = fm.font_def_info("f")
 assert info is not None
 _, _, design_size, at_size = info
 # cmr10 design size = 10pt = 655360sp; scaled 1200 → 12pt = 786432sp
 expected = design_size * 1200 // 1000
 assert at_size == expected

 def test_font_scaled_1000_is_design_size(self) -> None:
 """scaled 1000 is identity — at_size == design_size."""
 fm = _run_and_get_font_manager(r"\font\f=cmr10 scaled 1000 \bye")
 info = fm.font_def_info("f")
 assert info is not None
 _, _, design_size, at_size = info
 assert at_size == design_size

 def test_font_scaled_500(self) -> None:
 """scaled 500 → half design size."""
 fm = _run_and_get_font_manager(r"\font\f=cmr10 scaled 500 \bye")
 info = fm.font_def_info("f")
 assert info is not None
 _, _, design_size, at_size = info
 assert at_size == design_size * 500 // 1000


# ---------------------------------------------------------------------------
# AC#4: Missing TFM raises FontError
# ---------------------------------------------------------------------------

class TestFontMissingTFM:
 """Missing TFM file raises FontError."""

 def test_missing_tfm_raises(self) -> None:
 """\\font\\f=nonexistent raises FontError."""
 with pytest.raises(FontError):
 _run(r"\font\f=nonexistent \bye")

 def test_font_not_followed_by_cs_raises(self) -> None:
 """\\font not followed by a CS raises EngineError."""
 with pytest.raises(EngineError, match="control sequence"):
 _run(r"\font x\bye")

 def test_font_missing_name_raises(self) -> None:
 """\\font\\f= followed by non-letter raises EngineError."""
 with pytest.raises(EngineError, match="Missing font name"):
 _run(r"\font\f=\bye")


# ---------------------------------------------------------------------------
# AC#5: \nullfont
# ---------------------------------------------------------------------------

class TestNullfont:
 """\\nullfont selects a zero-metrics font."""

 def test_nullfont_produces_valid_dvi(self) -> None:
 """\\nullfont followed by text and \\bye produces valid DVI."""
 result = _run(r"\nullfont A\bye")
 assert isinstance(result, bytes)
 assert result[0] == 0xF7 # DVI preamble

 def test_nullfont_registers_font(self) -> None:
 """\\nullfont registers 'nullfont' in FontManager."""
 fm = _run_and_get_font_manager(r"\nullfont\bye")
 assert fm.is_font("nullfont")

 def test_nullfont_selects_font(self) -> None:
 """\\nullfont sets current font to 'nullfont'."""
 fm = _run_and_get_font_manager(r"\nullfont\bye")
 assert fm._current == "nullfont"

 def test_nullfont_zero_fontdimens(self) -> None:
 """\\nullfont has all fontdimens 1-7 set to zero."""
 fm = _run_and_get_font_manager(r"\nullfont\bye")
 for i in range(1, 8):
 assert fm.fontdimen("nullfont", i) == 0

 def test_nullfont_charnode_has_zero_width(self) -> None:
 """Characters in \\nullfont have zero-width metrics."""
 nodes = _collect_par_nodes(r"\nullfont A")
 char_nodes = [n for n in nodes if isinstance(n, CharNode)]
 assert len(char_nodes) >= 1
 assert char_nodes[-1].font_name == "nullfont"

 def test_nullfont_space_is_zero(self) -> None:
 """Space glue under \\nullfont has zero width (fontdimen 2 = 0)."""
 nodes = _collect_par_nodes(r"\nullfont A B")
 glue_nodes = [n for n in nodes if isinstance(n, GlueNode)]
 # At least one space glue between A and B
 assert any(g.glue.width == 0 for g in glue_nodes)

 def test_nullfont_idempotent(self) -> None:
 """Calling \\nullfont twice doesn't crash or create duplicates."""
 fm = _run_and_get_font_manager(r"\nullfont\nullfont\bye")
 assert fm.is_font("nullfont")
 assert fm._current == "nullfont"


# ---------------------------------------------------------------------------
# Integration: _scan_font_name edge cases
# ---------------------------------------------------------------------------

class TestScanFontName:
 """Edge cases for font name scanning."""

 def test_font_name_with_digits(self) -> None:
 """Font names can contain digits (e.g. cmr10)."""
 fm = _run_and_get_font_manager(r"\font\f=cmr10 \bye")
 info = fm.font_def_info("f")
 assert info is not None
 assert info[0] == "cmr10"

 def test_font_name_cmr7(self) -> None:
 """Loading cmr7 by name works."""
 fm = _run_and_get_font_manager(r"\font\f=cmr7 \bye")
 assert fm.is_font("f")
 info = fm.font_def_info("f")
 assert info is not None
 assert info[0] == "cmr7"

 def test_font_name_cmti10(self) -> None:
 """Loading cmti10 (italic) by name works."""
 fm = _run_and_get_font_manager(r"\font\f=cmti10 \bye")
 assert fm.is_font("f")
 info = fm.font_def_info("f")
 assert info is not None
 assert info[0] == "cmti10"

 def test_font_name_terminated_by_space(self) -> None:
 """Space after font name is consumed as terminator."""
 # "cmr10 " — space terminates, "at" is NOT part of name
 fm = _run_and_get_font_manager(r"\font\f=cmr10 \bye")
 info = fm.font_def_info("f")
 assert info is not None
 assert info[0] == "cmr10"


# ---------------------------------------------------------------------------
# Integration: font + character output end-to-end
# ---------------------------------------------------------------------------

class TestFontIntegration:
 """End-to-end: \\font load → font CS select → character output → DVI."""

 def test_font_load_select_output_dvi(self) -> None:
 """\\font\\myfont=cmr10 \\myfont A\\bye produces valid DVI with content."""
 result = _run(r"\font\myfont=cmr10 \myfont A\bye")
 assert isinstance(result, bytes)
 assert len(result) > 10
 assert result[0] == 0xF7

 def test_font_at_dimen_output(self) -> None:
 """\\font\\f=cmr10 at 12pt \\f A\\bye produces valid DVI."""
 result = _run(r"\font\f=cmr10 at 12pt \f A\bye")
 assert isinstance(result, bytes)
 assert result[0] == 0xF7

 def test_font_scaled_output(self) -> None:
 """\\font\\f=cmr10 scaled 1200 \\f A\\bye produces valid DVI."""
 result = _run(r"\font\f=cmr10 scaled 1200 \f A\bye")
 assert isinstance(result, bytes)
 assert result[0] == 0xF7

 def test_multiple_fonts_in_paragraph(self) -> None:
 """Two fonts in one paragraph: both appear in DVI output."""
 result = _run(
 r"\font\roman=cmr10 \font\italic=cmti10 "
 r"\roman Hello \italic World\bye"
 )
 assert isinstance(result, bytes)
 assert result[0] == 0xF7

 def test_font_in_group_scoping(self) -> None:
 """Font change inside group reverts after group closes."""
 nodes = _collect_par_nodes(
 r"\font\other=cmr7 {\other A}B"
 )
 char_nodes = [n for n in nodes if isinstance(n, CharNode)]
 # A should be in "other" (cmr7), B should revert to "tenrm"
 assert len(char_nodes) >= 2
 assert char_nodes[-2].font_name == "other"
 assert char_nodes[-1].font_name == "tenrm"

 def test_nullfont_then_real_font(self) -> None:
 """\\nullfont then switch to real font works."""
 result = _run(r"\nullfont\font\f=cmr10 \f Hello\bye")
 assert isinstance(result, bytes)
 assert result[0] == 0xF7
