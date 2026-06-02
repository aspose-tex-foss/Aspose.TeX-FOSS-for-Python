"""Unit tests for PFB parser."""
from __future__ import annotations

import importlib.resources
import struct

import pytest

from aspose_tex._fonts.pfb_parser import parse_pfb
from aspose_tex.exceptions import FontError


def _load_bundled(name: str) -> bytes:
 """Read a bundled PFB file by TFM name."""
 pkg = importlib.resources.files("aspose_tex") / "data" / "fonts"
 return (pkg / f"{name}.pfb").read_bytes()


# ------------------------------------------------------------------
# Real font parsing
# ------------------------------------------------------------------


class TestParseCmr10:
 """AC-1: Parse cmr10.pfb — segments, font name, encoding."""

 def setup_method(self) -> None:
 self.pfb = parse_pfb(_load_bundled("cmr10"))

 def test_segments_non_empty(self) -> None:
 assert len(self.pfb.ascii_header) > 0
 assert len(self.pfb.binary_body) > 0
 assert len(self.pfb.ascii_trailer) > 0

 def test_font_name(self) -> None:
 assert self.pfb.font_name == "CMR10"

 def test_encoding_uppercase_a(self) -> None:
 assert self.pfb.encoding[65] == "A"

 def test_encoding_lowercase_a(self) -> None:
 assert self.pfb.encoding[97] == "a"

 def test_encoding_gamma(self) -> None:
 assert self.pfb.encoding[0] == "Gamma"


class TestParseCmmi10:
 """Parse cmmi10.pfb — math italic encoding."""

 def setup_method(self) -> None:
 self.pfb = parse_pfb(_load_bundled("cmmi10"))

 def test_font_name(self) -> None:
 assert self.pfb.font_name == "CMMI10"

 def test_encoding_gamma_same(self) -> None:
 assert self.pfb.encoding[0] == "Gamma"

 def test_encoding_a_same(self) -> None:
 assert self.pfb.encoding[97] == "a"

 def test_encoding_oldstyle_digits(self) -> None:
 assert self.pfb.encoding[48] == "zerooldstyle"


class TestParseCmsy10:
 """Parse cmsy10.pfb — symbol encoding."""

 def setup_method(self) -> None:
 self.pfb = parse_pfb(_load_bundled("cmsy10"))

 def test_font_name(self) -> None:
 assert self.pfb.font_name == "CMSY10"

 def test_encoding_minus(self) -> None:
 assert self.pfb.encoding[0] == "minus"

 def test_encoding_periodcentered(self) -> None:
 assert self.pfb.encoding[1] == "periodcentered"


class TestParseCmex10:
 """Parse cmex10.pfb — extension encoding."""

 def setup_method(self) -> None:
 self.pfb = parse_pfb(_load_bundled("cmex10"))

 def test_font_name(self) -> None:
 assert self.pfb.font_name == "CMEX10"

 def test_encoding_parenleftbig(self) -> None:
 assert self.pfb.encoding[0] == "parenleftbig"


class TestAllBundledPfbFiles:
 """AC-2: All bundled PFB files parse without errors."""

 def test_all_parse_successfully(self) -> None:
 pkg = importlib.resources.files("aspose_tex") / "data" / "fonts"
 pfb_files = [
 f for f in pkg.iterdir()
 if hasattr(f, "name") and f.name.endswith(".pfb")
 ]
 assert len(pfb_files) >= 12, "Expected at least 12 bundled PFB files"
 for pfb_file in pfb_files:
 raw = pfb_file.read_bytes()
 result = parse_pfb(raw)
 assert len(result.ascii_header) > 0, f"{pfb_file.name}: empty ascii_header"
 assert len(result.binary_body) > 0, f"{pfb_file.name}: empty binary_body"
 assert result.font_name, f"{pfb_file.name}: empty font_name"


# ------------------------------------------------------------------
# Error handling
# ------------------------------------------------------------------


def _make_segment(seg_type: int, data: bytes) -> bytes:
 """Build a single PFB segment (header + data)."""
 return bytes([0x80, seg_type]) + struct.pack("<I", len(data)) + data


def _make_eof() -> bytes:
 return bytes([0x80, 0x03])


class TestInvalidPfb:
 def test_invalid_magic_byte(self) -> None:
 with pytest.raises(FontError, match="Invalid PFB magic byte"):
 parse_pfb(b"\x00\x01" + b"\x00" * 10)

 def test_truncated_segment(self) -> None:
 # Header says 1000 bytes but only 5 available
 data = bytes([0x80, 0x01]) + struct.pack("<I", 1000) + b"hello"
 with pytest.raises(FontError, match=r"only .* bytes remain"):
 parse_pfb(data)

 def test_empty_data(self) -> None:
 with pytest.raises(FontError, match="too short"):
 parse_pfb(b"")

 def test_single_byte(self) -> None:
 with pytest.raises(FontError, match="too short"):
 parse_pfb(b"\x80")

 def test_no_binary_segment(self) -> None:
 data = _make_segment(0x01, b"/FontName /Test def") + _make_eof()
 with pytest.raises(FontError, match="no binary segment"):
 parse_pfb(data)

 def test_no_ascii_segment(self) -> None:
 data = _make_segment(0x02, b"\x00" * 10) + _make_eof()
 with pytest.raises(FontError, match="no ASCII segment"):
 parse_pfb(data)

 def test_unknown_segment_type(self) -> None:
 data = bytes([0x80, 0x05]) + struct.pack("<I", 4) + b"test"
 with pytest.raises(FontError, match="Unknown PFB segment type"):
 parse_pfb(data)


class TestMultipleSegmentsSameType:
 """Synthetic PFB with two binary segments — should concatenate."""

 def test_concatenated_binary(self) -> None:
 ascii_seg = _make_segment(0x01, b"/FontName /TestFont def\n/Encoding 256 array\ndup 65 /A put\nreadonly def\n")
 bin_seg1 = _make_segment(0x02, b"AAAA")
 bin_seg2 = _make_segment(0x02, b"BBBB")
 trailer = _make_segment(0x01, b"0" * 512)
 eof = _make_eof()

 pfb = parse_pfb(ascii_seg + bin_seg1 + bin_seg2 + trailer + eof)
 assert pfb.binary_body == b"AAAABBBB"
 assert pfb.font_name == "TestFont"
 assert pfb.encoding[65] == "A"
 assert len(pfb.ascii_trailer) == 512
