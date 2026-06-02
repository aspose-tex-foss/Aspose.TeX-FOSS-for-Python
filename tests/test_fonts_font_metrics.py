"""Unit tests for FontMetrics and CharMetrics.

Uses synthetic TFMs built in memory — no filesystem access.
"""
from __future__ import annotations

import struct

import pytest

from aspose_tex._fonts.font_metrics import FontMetrics
from aspose_tex._fonts.tfm_parser import parse_tfm
from aspose_tex.exceptions import FontError

# ---------------------------------------------------------------------------
# Synthetic TFM helpers (duplicated from test_fonts_tfm_parser for isolation)
# ---------------------------------------------------------------------------

def _build_minimal_tfm(
 bc: int = 65,
 ec: int = 65,
 design_size_fw: int = 0xA00000,
 width_fw: int = 0xC0000,
 params_fw: tuple[int, ...] = (0, 0x280000, 0x80000, 0x40000, 0x6EB85, 0x100000, 0),
) -> bytes:
 lh = 2
 n_chars = ec - bc + 1 if ec >= bc else 0
 nw = 2
 nh = 1
 nd = 1
 ni = 1
 nl = 0
 nk = 0
 ne = 0
 np_ = len(params_fw)
 lf = 6 + lh + n_chars + nw + nh + nd + ni + nl + nk + ne + np_
 buf = bytearray()
 buf += struct.pack(">12H", lf, lh, bc, ec, nw, nh, nd, ni, nl, nk, ne, np_)
 buf += struct.pack(">Ii", 0, design_size_fw)
 for _ in range(n_chars):
 buf += struct.pack(">I", 1 << 24)
 buf += struct.pack(">ii", 0, width_fw)
 buf += struct.pack(">i", 0)
 buf += struct.pack(">i", 0)
 buf += struct.pack(">i", 0)
 for p in params_fw:
 buf += struct.pack(">i", p)
 assert len(buf) == lf * 4
 return bytes(buf)


def _build_ligkern_tfm(
 src: int = 102,
 mid: int = 105,
 lig_result: int = 12,
 kern_char: int = 86,
 kern_fw: int = -116509,
) -> bytes:
 """TFM with lig src+mid→lig_result and kern src+kern_char → kern_fw."""
 # char_info for src: tag=1, rem=0 → lig_kern starts at index 0
 src_info = (1 << 24) | (0x01 << 8) | 0

 lh = 2
 nw = 2
 nh = 1
 nd = 1
 ni = 1
 nl = 2
 nk = 1
 ne = 0
 np_ = 7
 n_chars = 128
 lf = 6 + lh + n_chars + nw + nh + nd + ni + nl + nk + ne + np_
 buf = bytearray()
 buf += struct.pack(">12H", lf, lh, 0, 127, nw, nh, nd, ni, nl, nk, ne, np_)
 buf += struct.pack(">Ii", 0, 0xA00000)
 for code in range(128):
 buf += struct.pack(">I", src_info if code == src else (1 << 24))
 buf += struct.pack(">ii", 0, 0x80000)
 buf += struct.pack(">i", 0)
 buf += struct.pack(">i", 0)
 buf += struct.pack(">i", 0)
 # lig_kern[0]: LIG src+mid → lig_result
 buf += struct.pack(">I", (0 << 24) | (mid << 16) | (0 << 8) | lig_result)
 # lig_kern[1]: KERN src+kern_char, last entry (skip=128)
 buf += struct.pack(">I", (128 << 24) | (kern_char << 16) | (128 << 8) | 0)
 buf += struct.pack(">i", kern_fw)
 params = (0, 0x280000, 0x80000, 0x40000, 0x6EB85, 0x100000, 0)
 for p in params:
 buf += struct.pack(">i", p)
 assert len(buf) == lf * 4
 return bytes(buf)


# ---------------------------------------------------------------------------
# Tests for CharMetrics (basic metrics)
# ---------------------------------------------------------------------------

def test_char_metrics_at_design_size() -> None:
 design_fw = 0xA00000 # 10pt = 655360 sp
 width_fw = 0xC0000 # 0.75 x design_size
 data = _build_minimal_tfm(bc=65, ec=65, design_size_fw=design_fw, width_fw=width_fw)
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=655360)
 cm = metrics.char_metrics(65)
 expected_width = width_fw * 655360 >> 20
 assert cm.width == expected_width


def test_char_metrics_scaled_2x() -> None:
 design_fw = 0xA00000
 width_fw = 0xC0000
 design_sp = 655360
 data = _build_minimal_tfm(bc=65, ec=65, design_size_fw=design_fw, width_fw=width_fw)
 tfm = parse_tfm(data)
 m1 = FontMetrics(tfm, at_sp=design_sp)
 m2 = FontMetrics(tfm, at_sp=design_sp * 2)
 assert m2.char_metrics(65).width == m1.char_metrics(65).width * 2


def test_has_char_true() -> None:
 data = _build_minimal_tfm(bc=65, ec=65)
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=655360)
 assert metrics.has_char(65) is True


def test_has_char_false_width0() -> None:
 # char_info with width_index=0 means nonexistent char
 data = _build_minimal_tfm(bc=65, ec=65)
 # Patch char_info[0] to have width_index=0
 lh = 2
 off_char = (6 + lh) * 4 # byte offset
 buf = bytearray(data)
 struct.pack_into(">I", buf, off_char, 0) # all zeros → width_index=0
 tfm = parse_tfm(bytes(buf))
 metrics = FontMetrics(tfm, at_sp=655360)
 assert metrics.has_char(65) is False


def test_has_char_false_out_of_range() -> None:
 data = _build_minimal_tfm(bc=65, ec=65)
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=655360)
 assert metrics.has_char(64) is False
 assert metrics.has_char(66) is False


def test_char_metrics_out_of_range() -> None:
 data = _build_minimal_tfm(bc=65, ec=65)
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=655360)
 with pytest.raises(FontError, match="not in font range"):
 metrics.char_metrics(64)


# ---------------------------------------------------------------------------
# Tests for kern/ligature
# ---------------------------------------------------------------------------

def test_kern_found() -> None:
 kern_fw = -116509
 data = _build_ligkern_tfm(src=102, kern_char=86, kern_fw=kern_fw)
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=tfm.design_size_sp)
 kern_sp = metrics.kern(102, 86)
 expected = kern_fw * tfm.design_size_sp >> 20
 assert kern_sp == expected
 assert kern_sp < 0 # kern pulls chars together


def test_kern_not_found() -> None:
 data = _build_ligkern_tfm(src=102, kern_char=86)
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=tfm.design_size_sp)
 # Different pair → no kern
 assert metrics.kern(102, 90) is None


def test_kern_char_without_tag() -> None:
 data = _build_minimal_tfm(bc=65, ec=65)
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=655360)
 assert metrics.kern(65, 65) is None


def test_ligature_found() -> None:
 data = _build_ligkern_tfm(src=102, mid=105, lig_result=12)
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=tfm.design_size_sp)
 lig = metrics.ligature(102, 105)
 assert lig == 12


def test_ligature_not_found_wrong_pair() -> None:
 data = _build_ligkern_tfm(src=102, mid=105, lig_result=12)
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=tfm.design_size_sp)
 assert metrics.ligature(102, 90) is None # 'f'+'Z' — not in table


def test_ligature_other_type_returns_none() -> None:
 """op_byte=1 (/LIG/ >) should return None (not supported in M1)."""
 lh = 2
 n_chars = 128
 nw, nh, nd, ni, nl, nk, ne, np_ = 2, 1, 1, 1, 1, 0, 0, 7
 lf = 6 + lh + n_chars + nw + nh + nd + ni + nl + nk + ne + np_
 buf = bytearray()
 buf += struct.pack(">12H", lf, lh, 0, 127, nw, nh, nd, ni, nl, nk, ne, np_)
 buf += struct.pack(">Ii", 0, 0xA00000)
 for code in range(128):
 if code == 102: # 'f': tag=1, rem=0
 buf += struct.pack(">I", (1 << 24) | (0x01 << 8) | 0)
 else:
 buf += struct.pack(">I", 1 << 24)
 buf += struct.pack(">ii", 0, 0x80000)
 buf += struct.pack(">i", 0)
 buf += struct.pack(">i", 0)
 buf += struct.pack(">i", 0)
 # lig_kern[0]: op_byte=1 (LIG/ >) — not supported in M1
 buf += struct.pack(">I", (128 << 24) | (105 << 16) | (1 << 8) | 12)
 params = (0, 0x280000, 0x80000, 0x40000, 0x6EB85, 0x100000, 0)
 for p in params:
 buf += struct.pack(">i", p)
 assert len(buf) == lf * 4
 tfm = parse_tfm(bytes(buf))
 metrics = FontMetrics(tfm, at_sp=655360)
 assert metrics.ligature(102, 105) is None


# ---------------------------------------------------------------------------
# Tests for fontdimen
# ---------------------------------------------------------------------------

def test_fontdimen_index_1_slant() -> None:
 params = (0, 0x280000, 0x80000, 0x40000, 0x6EB85, 0x100000, 0)
 data = _build_minimal_tfm(params_fw=params)
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=655360)
 # slant is params_fw[0]=0 → scaled = 0
 assert metrics.fontdimen(1) == 0


def test_fontdimen_scaling() -> None:
 # fontdimen 6 (quad) = params_fw[5] = 0x100000 = 1.0 design_size
 # at 2x design_size → quad = 2 x design_size_sp
 design_sp = 655360
 params = (0, 0x280000, 0x80000, 0x40000, 0x6EB85, 0x100000, 0)
 data = _build_minimal_tfm(design_size_fw=0xA00000, params_fw=params)
 tfm = parse_tfm(data)
 m1 = FontMetrics(tfm, at_sp=design_sp)
 m2 = FontMetrics(tfm, at_sp=design_sp * 2)
 assert m2.fontdimen(6) == m1.fontdimen(6) * 2


def test_fontdimen_out_of_range() -> None:
 data = _build_minimal_tfm(params_fw=(0, 0x280000, 0x80000, 0x40000, 0x6EB85, 0x100000, 0))
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=655360)
 assert metrics.fontdimen(0) == 0 # 0 is below range
 assert metrics.fontdimen(8) == 0 # only 7 params


def test_set_fontdimen_override() -> None:
 data = _build_minimal_tfm()
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=655360)
 metrics.set_fontdimen(2, 99999)
 assert metrics.fontdimen(2) == 99999


def test_design_size_and_at_size_sp_properties() -> None:
 data = _build_minimal_tfm(design_size_fw=0xA00000)
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=720896) # 11pt
 assert metrics.design_size_sp == 655360
 assert metrics.at_size_sp == 720896


# ---------------------------------------------------------------------------
# Tests for tfm_name and checksum properties
# ---------------------------------------------------------------------------

def test_font_metrics_tfm_name() -> None:
 """FontMetrics.tfm_name returns the value passed at construction."""
 data = _build_minimal_tfm()
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=655360, tfm_name="cmr10")
 assert metrics.tfm_name == "cmr10"


def test_font_metrics_tfm_name_default_empty() -> None:
 """FontMetrics.tfm_name defaults to empty string when not supplied."""
 data = _build_minimal_tfm()
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=655360)
 assert metrics.tfm_name == ""


def test_font_metrics_checksum() -> None:
 """FontMetrics.checksum equals tfm.checksum."""
 data = _build_minimal_tfm()
 tfm = parse_tfm(data)
 metrics = FontMetrics(tfm, at_sp=655360)
 assert metrics.checksum == tfm.checksum
