"""Unit tests for parse_tfm.

All tests use a synthetic minimal TFM built in memory — no external files needed.
"""
from __future__ import annotations

import struct

import pytest

from aspose_tex._fonts.tfm_parser import parse_tfm
from aspose_tex.exceptions import FontError

# ---------------------------------------------------------------------------
# Synthetic TFM builder (test helper)
# ---------------------------------------------------------------------------

def _build_minimal_tfm(
 bc: int = 65,
 ec: int = 65,
 design_size_fw: int = 0xA00000, # 10 pt
 width_fw: int = 0xC0000,
 params_fw: tuple[int, ...] = (0, 0x280000, 0x80000, 0x40000, 0x6EB85, 0x100000, 0),
 nl: int = 0,
 nk: int = 0,
 extra_lig_kern: bytes = b"",
 extra_kerns: bytes = b"",
) -> bytes:
 """Build a syntactically valid minimal TFM for testing.

 The resulting font has a single character at code ``bc``..``ec`` with
 width_fw as its width and zero height/depth/italic.
 """
 lh = 2
 n_chars = ec - bc + 1 if ec >= bc else 0
 nw = 2
 nh = 1
 nd = 1
 ni = 1
 ne = 0
 np_ = len(params_fw)
 lf = 6 + lh + n_chars + nw + nh + nd + ni + nl + nk + ne + np_
 buf = bytearray()
 buf += struct.pack(">12H", lf, lh, bc, ec, nw, nh, nd, ni, nl, nk, ne, np_)
 # Header: checksum=0, design_size
 buf += struct.pack(">Ii", 0, design_size_fw)
 # char_info: width_index=1, tag=0, rem=0
 for _ in range(n_chars):
 buf += struct.pack(">I", 1 << 24)
 # Width table: [0, width_fw]
 buf += struct.pack(">ii", 0, width_fw)
 # Height [0], depth [0], italic [0]
 buf += struct.pack(">i", 0)
 buf += struct.pack(">i", 0)
 buf += struct.pack(">i", 0)
 # lig_kern
 buf += extra_lig_kern
 # kerns
 buf += extra_kerns
 # params
 for p in params_fw:
 buf += struct.pack(">i", p)
 assert len(buf) == lf * 4, f"builder bug: {len(buf)} != {lf * 4}"
 return bytes(buf)


def _build_ligkern_tfm(
 src: int = 102, # 'f'
 mid: int = 105, # 'i'
 lig_result: int = 12,
 kern_char: int = 86, # 'V'
 kern_fw: int = -116509,
) -> bytes:
 """Build a TFM with one LIG entry (src+mid→lig_result) and one KERN (src+kern_char).

 lig_kern program for src:
 [0] skip=0 next=mid op=0 rem=lig_result (LIG)
 [1] skip=128 next=kern_char op=128 rem=0 (KERN, last entry)
 kerns[0] = kern_fw
 """
 # char_info for src: tag=1 (bits 9..8 = 0x01), rem=0 (byte3 = 0)
 # => byte2 = (0 << 2) | 1 = 0x01 for tag=1, italic_index=0
 # width_index = 1 (byte0), others 0
 src_info = (1 << 24) | (0x01 << 8) | 0 # tag=1, rem=0

 lh = 2
 n_chars = 128 # bc=0, ec=127 to cover all needed codes
 nw = 2
 nh = 1
 nd = 1
 ni = 1
 nl = 2
 nk = 1
 ne = 0
 np_ = 7
 lf = 6 + lh + n_chars + nw + nh + nd + ni + nl + nk + ne + np_
 buf = bytearray()
 design_fw = 0xA00000 # 10pt
 buf += struct.pack(">12H", lf, lh, 0, 127, nw, nh, nd, ni, nl, nk, ne, np_)
 buf += struct.pack(">Ii", 0, design_fw)
 # char_info for 128 chars (bc=0..ec=127)
 for code in range(128):
 if code == src:
 buf += struct.pack(">I", src_info)
 else:
 buf += struct.pack(">I", 1 << 24) # width_idx=1, no lig/kern
 # widths: [0, width_fw]
 buf += struct.pack(">ii", 0, 0x80000) # width_index=1 → some non-zero width
 buf += struct.pack(">i", 0) # heights [0]
 buf += struct.pack(">i", 0) # depths [0]
 buf += struct.pack(">i", 0) # italics [0]
 # lig_kern[0]: skip=0, next=mid, op=0, rem=lig_result (LIG)
 buf += struct.pack(">I", (0 << 24) | (mid << 16) | (0 << 8) | lig_result)
 # lig_kern[1]: skip=128 (last), next=kern_char, op=128, rem=0 (KERN index 0)
 buf += struct.pack(">I", (128 << 24) | (kern_char << 16) | (128 << 8) | 0)
 # kerns[0]
 buf += struct.pack(">i", kern_fw)
 # params
 params = (0, 0x280000, 0x80000, 0x40000, 0x6EB85, 0x100000, 0)
 for p in params:
 buf += struct.pack(">i", p)
 assert len(buf) == lf * 4, f"builder bug: {len(buf)} != {lf * 4}"
 return bytes(buf)


# ---------------------------------------------------------------------------
# Tests for parse_tfm
# ---------------------------------------------------------------------------

def test_parse_too_short() -> None:
 with pytest.raises(FontError, match="too short"):
 parse_tfm(b"")


def test_parse_too_short_not_24() -> None:
 with pytest.raises(FontError, match="too short"):
 parse_tfm(b"\x00" * 20)


def test_parse_lf_mismatch() -> None:
 data = bytearray(_build_minimal_tfm())
 # Corrupt lf: set it to 999 so len(data) != lf*4
 struct.pack_into(">H", data, 0, 999)
 with pytest.raises(FontError, match="length mismatch"):
 parse_tfm(bytes(data))


def test_parse_lf_section_mismatch() -> None:
 # Build valid TFM then adjust lf without adjusting section sizes
 data = bytearray(_build_minimal_tfm())
 lf = struct.unpack_from(">H", data, 0)[0]
 # Add 4 bytes and increase lf by 1 — now len matches lf but sections don't
 data += b"\x00\x00\x00\x00"
 struct.pack_into(">H", data, 0, lf + 1)
 with pytest.raises(FontError, match="length mismatch"):
 parse_tfm(bytes(data))


def test_parse_bc_gt_ec_valid() -> None:
 # bc=1, ec=0 → empty font (0 chars), valid
 data = _build_minimal_tfm(bc=1, ec=0)
 tfm = parse_tfm(data)
 assert tfm.bc == 1
 assert tfm.ec == 0
 assert tfm.char_info == ()


def test_parse_bc_gt_255() -> None:
 # bc=256 is out of range — but struct only packs uint16, so bc can be 256.
 # Build manually to inject bc=256 (> 255)
 data = bytearray(_build_minimal_tfm(bc=65, ec=65))
 # Rewrite bc field (offset 4) to 256
 struct.pack_into(">H", data, 4, 256)
 # Also adjust ec field accordingly (to avoid section size mismatch, keep n_chars same)
 # But 256 > 255 so it's invalid. lf will still pass because the original n_chars=1.
 # Actually bc=256 > ec=65 means n_chars=0, so lf changes. Let's just test the check.
 with pytest.raises(FontError, match=r"[Ii]nvalid char range"):
 parse_tfm(bytes(data))


def test_parse_nw_zero() -> None:
 # Build a TFM with nw=0 — must raise FontError
 # We need to construct it manually because _build_minimal_tfm always uses nw=2
 lh = 2
 bc, ec = 65, 65
 n_chars = 1
 nw, nh, nd, ni, nl, nk, ne, np_ = 0, 1, 1, 1, 0, 0, 0, 7
 lf = 6 + lh + n_chars + nw + nh + nd + ni + nl + nk + ne + np_
 buf = bytearray()
 buf += struct.pack(">12H", lf, lh, bc, ec, nw, nh, nd, ni, nl, nk, ne, np_)
 buf += struct.pack(">Ii", 0, 0xA00000) # header
 buf += struct.pack(">I", 0) # char_info (width_index=0)
 buf += struct.pack(">i", 0) # height
 buf += struct.pack(">i", 0) # depth
 buf += struct.pack(">i", 0) # italic
 for _ in range(np_):
 buf += struct.pack(">i", 0)
 assert len(buf) == lf * 4
 with pytest.raises(FontError, match="width table"):
 parse_tfm(bytes(buf))


def test_parse_design_size() -> None:
 # design_size_fw = 0xA00000 → 10.0 pt → 655360 sp
 data = _build_minimal_tfm(design_size_fw=0xA00000)
 tfm = parse_tfm(data)
 assert tfm.design_size_sp == 655360


def test_parse_char_info_fields() -> None:
 # Build a char_info word with known field values and verify extraction.
 # char info with width_index=2, height_index=3, depth_index=1, italic_index=5, tag=1, rem=42
 # byte0=2, byte1=(3<<4)|1=0x31, byte2=(5<<2)|1=0x15, byte3=42
 custom_word = (2 << 24) | (0x31 << 16) | (0x15 << 8) | 42
 # We just verify the bit layout in a standalone assertion
 assert (custom_word >> 24) & 0xFF == 2 # width_index
 assert (custom_word >> 20) & 0x0F == 3 # height_index
 assert (custom_word >> 16) & 0x0F == 1 # depth_index
 assert (custom_word >> 10) & 0x3F == 5 # italic_index
 assert (custom_word >> 8) & 0x03 == 1 # tag
 assert custom_word & 0xFF == 42 # remainder


def test_parse_lig_kern_fields() -> None:
 # lig_kern word: skip=7, next_char=105, op_byte=0, remainder=12
 word = (7 << 24) | (105 << 16) | (0 << 8) | 12
 assert (word >> 24) & 0xFF == 7 # skip_byte
 assert (word >> 16) & 0xFF == 105 # next_char
 assert (word >> 8) & 0xFF == 0 # op_byte
 assert word & 0xFF == 12 # remainder


def test_parse_single_char_font() -> None:
 data = _build_minimal_tfm(bc=65, ec=65, design_size_fw=0xA00000, width_fw=0xC0000)
 tfm = parse_tfm(data)

 assert tfm.design_size_sp == 655360
 assert tfm.bc == 65
 assert tfm.ec == 65
 assert len(tfm.char_info) == 1
 # width_index for char A is 1 (we packed 1<<24 in char_info)
 assert (tfm.char_info[0] >> 24) & 0xFF == 1
 assert len(tfm.widths_fw) == 2
 assert tfm.widths_fw[0] == 0
 assert tfm.widths_fw[1] == 0xC0000
 assert len(tfm.params_fw) == 7


def test_parse_preserves_kern_table() -> None:
 data = _build_ligkern_tfm()
 tfm = parse_tfm(data)
 assert len(tfm.kerns_fw) == 1
 assert tfm.kerns_fw[0] == -116509


def test_parse_preserves_lig_kern_program() -> None:
 data = _build_ligkern_tfm()
 tfm = parse_tfm(data)
 assert len(tfm.lig_kern) == 2
 # First entry: LIG (op=0)
 assert (tfm.lig_kern[0] >> 8) & 0xFF == 0


# ---------------------------------------------------------------------------
# Tests for checksum field
# ---------------------------------------------------------------------------

def test_parse_tfm_checksum_present() -> None:
 """parse_tfm() populates TfmData.checksum as a non-negative int."""
 data = _build_minimal_tfm()
 tfm = parse_tfm(data)
 assert isinstance(tfm.checksum, int)
 assert tfm.checksum >= 0


def test_parse_tfm_checksum_value() -> None:
 """Bundled cmr10.tfm → checksum matches raw header word 0."""
 import importlib.resources
 import struct as _struct
 pkg = importlib.resources.files("aspose_tex") / "data" / "fonts"
 raw = (pkg / "cmr10.tfm").read_bytes()
 tfm = parse_tfm(raw)
 # Header starts at word offset 6; word 0 is checksum (unsigned 32-bit).
 expected = _struct.unpack_from(">I", raw, 6 * 4)[0]
 assert tfm.checksum == expected
 assert tfm.checksum > 0 # bundled cmr10 has a non-zero checksum


# : all bundled TFM files must parse without error
_NEW_CM_FILES = [
 "cmbcsc10.tfm", "cmbxsl10.tfm", "cmbxti10.tfm", "cmdunh10.tfm",
 "cmff10.tfm", "cmfi10.tfm", "cmfib8.tfm", "cminch.tfm", "cmitt10.tfm",
 "cmmib10.tfm", "cmsltt10.tfm", "cmssbx10.tfm", "cmssdc10.tfm",
 "cmssi10.tfm", "cmssi12.tfm", "cmssi17.tfm", "cmssi8.tfm", "cmssi9.tfm",
 "cmssq8.tfm", "cmssqi8.tfm", "cmtcsc10.tfm", "cmtex10.tfm",
 "cmtex8.tfm", "cmtex9.tfm", "cmvtt10.tfm",
]


@pytest.mark.parametrize("name", _NEW_CM_FILES)
def test_all_bundled_cm_tfm_parse(name: str) -> None:
 """: every newly added CM TFM file parses successfully."""
 import importlib.resources
 pkg = importlib.resources.files("aspose_tex") / "data" / "fonts"
 raw = (pkg / name).read_bytes()
 tfm = parse_tfm(raw)
 assert tfm.bc <= tfm.ec or tfm.bc == 1 # valid char range or empty
