"""Unit tests for FontManager PFB methods."""
from __future__ import annotations

import importlib.resources
import struct
from pathlib import Path

import pytest

from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._fonts.pfb_parser import PfbData
from aspose_tex.exceptions import FontError

# Core 12 CM fonts per AC-3
CORE_FONTS = [
 "cmr5", "cmr7", "cmr10", "cmr12",
 "cmbx10", "cmti10", "cmsl10", "cmtt10", "cmss10",
 "cmmi10", "cmsy10", "cmex10",
]


class TestFindPfb:
 """AC-4: PFB lookup by TFM name."""

 def test_find_bundled(self) -> None:
 mgr = FontManager()
 raw = mgr.find_pfb("cmr10")
 assert raw is not None
 assert raw[:2] == b"\x80\x01" # PFB magic + ASCII segment type

 def test_find_not_found(self) -> None:
 mgr = FontManager()
 assert mgr.find_pfb("nonexistent_font_xyz") is None

 def test_find_from_extra_path(self, tmp_path: Path) -> None:
 # Craft a minimal valid PFB in a temp dir
 ascii_seg = bytes([0x80, 0x01]) + struct.pack("<I", 20) + b"/FontName /Test def"[:20].ljust(20)
 bin_seg = bytes([0x80, 0x02]) + struct.pack("<I", 4) + b"TEST"
 trailer = bytes([0x80, 0x01]) + struct.pack("<I", 2) + b"00"
 eof = b"\x80\x03"
 fake_pfb = ascii_seg + bin_seg + trailer + eof

 (tmp_path / "fakefont.pfb").write_bytes(fake_pfb)

 mgr = FontManager(extra_search_paths=[tmp_path])
 raw = mgr.find_pfb("fakefont")
 assert raw == fake_pfb


class TestLoadPfb:
 def test_load_returns_pfbdata(self) -> None:
 mgr = FontManager()
 pfb = mgr.load_pfb("cmr10")
 assert isinstance(pfb, PfbData)
 assert pfb.font_name == "CMR10"

 def test_load_cached_identity(self) -> None:
 mgr = FontManager()
 first = mgr.load_pfb("cmr10")
 second = mgr.load_pfb("cmr10")
 assert first is second

 def test_load_missing_returns_none(self) -> None:
 mgr = FontManager()
 assert mgr.load_pfb("nonexistent_font_xyz") is None

 def test_load_missing_cached(self) -> None:
 mgr = FontManager()
 mgr.load_pfb("nonexistent_font_xyz")
 # Second call uses cache — also None, no error
 assert mgr.load_pfb("nonexistent_font_xyz") is None

 @pytest.mark.parametrize("font_name", CORE_FONTS)
 def test_load_all_core_fonts(self, font_name: str) -> None:
 """AC-2 + AC-3: all 12 core CM fonts load successfully."""
 mgr = FontManager()
 pfb = mgr.load_pfb(font_name)
 assert pfb is not None, f"{font_name}: PFB not found"
 assert len(pfb.ascii_header) > 0
 assert len(pfb.binary_body) > 0
 assert pfb.font_name != ""


class TestBundledPfbPresence:
 """AC-3: confirm at least 12 core CM PFB files are bundled."""

 def test_core_fonts_bundled(self) -> None:
 pkg = importlib.resources.files("aspose_tex") / "data" / "fonts"
 for name in CORE_FONTS:
 resource = pkg / f"{name}.pfb"
 # importlib.resources Traversable: use is_file() if available
 raw = resource.read_bytes()
 assert raw[:1] == b"\x80", f"{name}.pfb: bad magic byte"


class TestCorruptPfbRaises:
 def test_corrupt_pfb_in_extra_path(self, tmp_path: Path) -> None:
 (tmp_path / "broken.pfb").write_bytes(b"not a pfb file")
 mgr = FontManager(extra_search_paths=[tmp_path])
 with pytest.raises(FontError):
 mgr.load_pfb("broken")
