"""Integration tests for FontManager using bundled cmr10.tfm.

Reference values were extracted from cmr10.tfm binary via direct parsing
(see implementation notes — the cmr10.tfm in MiKTeX was verified
to have the standard Knuth checksum 0x9B33AE44).
"""
from __future__ import annotations

import pytest

from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._fonts.tfm_parser import parse_tfm
from aspose_tex.exceptions import FontError

# ---------------------------------------------------------------------------
# cmr10 reference constants (extracted from bundled binary, at design size 10pt)
# ---------------------------------------------------------------------------
CMR10_DESIGN_SIZE_SP = 655360 # 10 pt x 65536
CMR10_CHAR_A_WIDTH_SP = 491521 # char 65 ('A') width at design size
CMR10_KERN_AV_SP = -72819 # kern between 'A' (65) and 'V' (86), negative
CMR10_FI_LIGATURE_CODE = 12 # char 102 ('f') + char 105 ('i') → char 12
CMR10_QUAD_SP = 655361 # fontdimen 6 (quad) at design size
CMR10_XHEIGHT_SP = 282168 # fontdimen 5 (x-height) at design size


# ---------------------------------------------------------------------------
# Loading tests
# ---------------------------------------------------------------------------

def test_load_bundled_cmr10() -> None:
 """AC-4: loads from bundled data without external TeX installation."""
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 assert mgr.is_font("tenrm")


def test_design_size() -> None:
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 m = mgr.get_metrics("tenrm")
 assert m is not None
 assert m.design_size_sp == CMR10_DESIGN_SIZE_SP


def test_char_a_width() -> None:
 """AC-1: char 'A' has correct width."""
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 m = mgr.get_metrics("tenrm")
 assert m is not None
 assert m.char_metrics(65).width == CMR10_CHAR_A_WIDTH_SP


def test_kern_a_v() -> None:
 """AC-2: kern pair A+V returns correct negative kern value."""
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 m = mgr.get_metrics("tenrm")
 assert m is not None
 kern = m.kern(65, 86)
 assert kern == CMR10_KERN_AV_SP
 assert kern < 0


def test_ligature_f_i() -> None:
 """AC-3: f+i → fi ligature (char 12)."""
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 m = mgr.get_metrics("tenrm")
 assert m is not None
 lig = m.ligature(102, 105)
 assert lig == CMR10_FI_LIGATURE_CODE


def test_fontdimen_quad() -> None:
 """AC-6: fontdimen 6 (quad) matches reference."""
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 assert mgr.fontdimen("tenrm", 6) == CMR10_QUAD_SP


def test_fontdimen_xheight() -> None:
 """AC-6: fontdimen 5 (x-height) matches reference."""
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 assert mgr.fontdimen("tenrm", 5) == CMR10_XHEIGHT_SP


def test_corrupt_tfm_raises() -> None:
 """AC-7: corrupt TFM raises FontError."""
 with pytest.raises(FontError):
 parse_tfm(b"garbage data that is not a TFM file at all")


def test_cache_reuse() -> None:
 """AC-8: loading the same TFM twice reuses the cached TfmData object."""
 mgr = FontManager()
 mgr.load_font("a", "cmr10")
 mgr.load_font("b", "cmr10")
 m_a = mgr.get_metrics("a")
 m_b = mgr.get_metrics("b")
 assert m_a is not None and m_b is not None
 # Both FontMetrics instances share the same underlying TfmData object.
 assert m_a._tfm is m_b._tfm


# ---------------------------------------------------------------------------
# Scaling tests
# ---------------------------------------------------------------------------

def test_at_scaling() -> None:
 """AC-5: load cmr10 at 14pt → quad scales by 14/10."""
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 mgr.load_font("big", "cmr10", at_sp=14 * 65536)
 q10 = mgr.fontdimen("tenrm", 6)
 q14 = mgr.fontdimen("big", 6)
 # q14 / q10 ≈ 14/10; allow ±1 sp for integer rounding
 assert abs(q14 * 10 - q10 * 14) <= 14


def test_scaled_1200() -> None:
 """FR-6: scaled=1200 → at_size_sp == design_size_sp * 1200 // 1000."""
 mgr = FontManager()
 mgr.load_font("scaled", "cmr10", scaled=1200)
 m = mgr.get_metrics("scaled")
 assert m is not None
 assert m.at_size_sp == CMR10_DESIGN_SIZE_SP * 1200 // 1000


def test_load_font_at_and_scaled_exclusive() -> None:
 mgr = FontManager()
 with pytest.raises(ValueError, match="mutually exclusive"):
 mgr.load_font("x", "cmr10", at_sp=655360, scaled=1200)


# ---------------------------------------------------------------------------
# Search path tests
# ---------------------------------------------------------------------------

def test_extra_search_path(tmp_path) -> None:
 """FR-7: TFM found via extra_search_paths when not in bundled data."""
 # Copy cmr10.tfm into tmp_path under a fictitious name
 import importlib.resources

 pkg = importlib.resources.files("aspose_tex") / "data" / "fonts"
 raw = (pkg / "cmr10.tfm").read_bytes()
 (tmp_path / "myfont.tfm").write_bytes(raw)

 mgr = FontManager(extra_search_paths=[tmp_path])
 mgr.load_font("myfont", "myfont")
 assert mgr.is_font("myfont")
 m = mgr.get_metrics("myfont")
 assert m is not None
 assert m.design_size_sp == CMR10_DESIGN_SIZE_SP


def test_font_not_found_raises() -> None:
 mgr = FontManager()
 with pytest.raises(FontError, match="not found"):
 mgr.load_font("x", "does_not_exist_font_name")


# ---------------------------------------------------------------------------
# Font selection and introspection tests
# ---------------------------------------------------------------------------

def test_select_current() -> None:
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 assert mgr.current_metrics is None
 mgr.select_font("tenrm")
 assert mgr.current_metrics is not None


def test_select_unknown_raises() -> None:
 mgr = FontManager()
 with pytest.raises(FontError, match="not a defined font"):
 mgr.select_font("nosuch")


def test_is_font() -> None:
 mgr = FontManager()
 assert mgr.is_font("tenrm") is False
 mgr.load_font("tenrm", "cmr10")
 assert mgr.is_font("tenrm") is True


def test_fontdimen_unknown_font_raises() -> None:
 mgr = FontManager()
 with pytest.raises(FontError, match="not a defined font"):
 mgr.fontdimen("nosuch", 6)


# ---------------------------------------------------------------------------
# Group-scoped font selection (FR-8)
# ---------------------------------------------------------------------------

def test_font_scoping(monkeypatch) -> None:
 """FR-8: select_font inside a group; after group closes, previous font is restored."""
 from aspose_tex._engine.group import GroupKind, GroupStack

 groups = GroupStack()
 mgr = FontManager(group_stack=groups)
 mgr.load_font("tenrm", "cmr10")
 mgr.load_font("bfont", "cmr10", scaled=1200)
 mgr.select_font("tenrm")

 groups.open_group(GroupKind.BRACE)
 mgr.select_font("bfont")
 assert mgr._current == "bfont"

 groups.close_group()
 assert mgr._current == "tenrm"


# ---------------------------------------------------------------------------
# fontdimen set/get via FontManager
# ---------------------------------------------------------------------------

def test_set_fontdimen() -> None:
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 mgr.set_fontdimen("tenrm", 2, 99999)
 assert mgr.fontdimen("tenrm", 2) == 99999


def test_set_fontdimen_unknown_raises() -> None:
 mgr = FontManager()
 with pytest.raises(FontError, match="not a defined font"):
 mgr.set_fontdimen("nosuch", 2, 0)


# ---------------------------------------------------------------------------
# Tests for font_def_info
# ---------------------------------------------------------------------------

def test_font_def_info_returns_tuple() -> None:
 """font_def_info("tenrm") returns (str, int, int, int)."""
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 info = mgr.font_def_info("tenrm")
 assert info is not None
 tfm_name, checksum, design_size_sp, at_size_sp = info
 assert isinstance(tfm_name, str)
 assert isinstance(checksum, int)
 assert isinstance(design_size_sp, int)
 assert isinstance(at_size_sp, int)


def test_font_def_info_unknown_returns_none() -> None:
 """font_def_info("nofont") returns None."""
 mgr = FontManager()
 assert mgr.font_def_info("nofont") is None


def test_font_def_info_tfm_name() -> None:
 """font_def_info("tenrm")[0] == "cmr10"."""
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 info = mgr.font_def_info("tenrm")
 assert info is not None
 assert info[0] == "cmr10"
