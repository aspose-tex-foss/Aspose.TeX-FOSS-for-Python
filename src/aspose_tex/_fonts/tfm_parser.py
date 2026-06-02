"""TFM binary parser.

Parses the TeX Font Metric binary format (Knuth 1986) into a TfmData
dataclass containing all metric tables.

See for format details and validation rules.

Note: the char_info word field layout is (big-endian uint32):
 byte 0 (bits 31-24): width_index
 byte 1 (bits 23-16): height_index (upper nibble) | depth_index (lower nibble)
 byte 2 (bits 15-8): italic_index (upper 6 bits) | tag (lower 2 bits)
 byte 3 (bits 7-0): remainder
"""
from __future__ import annotations

import dataclasses
import struct

from aspose_tex.exceptions import FontError


@dataclasses.dataclass(frozen=True, slots=True)
class TfmData:
 """Immutable raw data parsed from a single TFM file.

 All fix_word metric fields (widths_fw, heights_fw, depths_fw, italics_fw,
 kerns_fw, params_fw) are stored as raw signed Python ints representing
 fix_words (1.0 == 2**20). Conversion to scaled points is done in
 FontMetrics using: sp = fix_word * at_size_sp >> 20.

 The char_info and lig_kern tuples hold unsigned 32-bit words; callers
 extract sub-fields by bit-masking.

 Attributes:
 checksum: Unsigned 32-bit checksum from TFM header word 0.
 Used in DVI fnt_def commands.
 design_size_sp: Design size in scaled points (1 pt = 65536 sp).
 bc: First valid character code (0-255).
 ec: Last valid character code (bc-1 means no characters in font).
 widths_fw: Width table; index 0 is always 0 (nonexistent char).
 heights_fw: Height table.
 depths_fw: Depth table.
 italics_fw: Italic-correction table.
 char_info: One unsigned word per character in bc..ec.
 Bits 31-24 = width_index, 23-20 = height_index,
 19-16 = depth_index, 15-10 = italic_index,
 9-8 = tag, 7-0 = remainder.
 lig_kern: Raw lig/kern program words (unsigned).
 Byte 3 (bits 31-24) = skip_byte, byte 2 (bits 23-16) = next_char,
 byte 1 (bits 15-8) = op_byte, byte 0 (bits 7-0) = remainder.
 kerns_fw: Kern amounts table (signed fix_word).
 params_fw: Font parameter table (signed fix_word, 1-indexed via [i-1]).
 """

 checksum: int
 design_size_sp: int
 bc: int
 ec: int
 widths_fw: tuple[int, ...]
 heights_fw: tuple[int, ...]
 depths_fw: tuple[int, ...]
 italics_fw: tuple[int, ...]
 char_info: tuple[int, ...]
 lig_kern: tuple[int, ...]
 kerns_fw: tuple[int, ...]
 params_fw: tuple[int, ...]


def parse_tfm(data: bytes) -> TfmData:
 """Parse raw TFM bytes into a TfmData.

 Args:
 data: Contents of a .tfm file.

 Returns:
 Fully populated TfmData.

 Raises:
 FontError: If data is too short, the length fields are inconsistent,
 or any index value exceeds table bounds.

 Example::

 tfm = parse_tfm(Path("cmr10.tfm").read_bytes())
 assert tfm.design_size_sp == 655360 # 10 pt
 """
 if len(data) < 24:
 raise FontError("TFM file too short")

 lf, lh, bc, ec, nw, nh, nd, ni, nl, nk, ne, np_ = struct.unpack_from(">12H", data, 0)

 if len(data) != lf * 4:
 raise FontError(
 f"TFM file length mismatch: file is {len(data)} bytes but lf={lf} implies {lf * 4} bytes"
 )

 # Validate char range before computing n_chars for the section-size check.
 if bc > 255 or ec > 255:
 raise FontError(f"Invalid char range bc={bc}, ec={ec}")

 n_chars = (ec - bc + 1) if ec >= bc else 0
 expected_lf = 6 + lh + n_chars + nw + nh + nd + ni + nl + nk + ne + np_
 if lf != expected_lf:
 raise FontError(f"TFM file length mismatch: lf={lf}, expected={expected_lf}")

 if nw == 0:
 raise FontError("TFM width table must have at least one entry")

 if nw > 256 or nh > 16 or nd > 16 or ni > 64:
 raise FontError(
 f"TFM table bounds exceeded: nw={nw} (max 256), nh={nh} (max 16), "
 f"nd={nd} (max 16), ni={ni} (max 64)"
 )

 # Header starts at word offset 6 (after the 6 word-sized fields in the preamble).
 # Word 0 is the checksum (unsigned); word 1 is the design size (signed fix_word).
 if lh < 2:
 raise FontError("TFM header too short: must have at least 2 words (checksum + design size)")
 checksum: int = struct.unpack_from(">I", data, 6 * 4)[0]
 design_size_fw: int = struct.unpack_from(">i", data, (6 + 1) * 4)[0]
 if design_size_fw <= 0:
 raise FontError("TFM design size must be positive")
 design_size_sp = design_size_fw * 65536 >> 20

 off_char = 6 + lh
 off_width = off_char + n_chars
 off_height = off_width + nw
 off_depth = off_height + nh
 off_italic = off_depth + nd
 off_lig_kern = off_italic + ni
 off_kern = off_lig_kern + nl
 off_exten = off_kern + nk
 off_param = off_exten + ne

 widths: tuple[int, ...] = struct.unpack_from(f">{nw}i", data, off_width * 4) if nw else ()
 heights: tuple[int, ...] = struct.unpack_from(f">{nh}i", data, off_height * 4) if nh else ()
 depths: tuple[int, ...] = struct.unpack_from(f">{nd}i", data, off_depth * 4) if nd else ()
 italics: tuple[int, ...] = struct.unpack_from(f">{ni}i", data, off_italic * 4) if ni else ()
 kerns: tuple[int, ...] = struct.unpack_from(f">{nk}i", data, off_kern * 4) if nk else ()
 params: tuple[int, ...] = struct.unpack_from(f">{np_}i", data, off_param * 4) if np_ else ()

 char_info: tuple[int, ...] = (
 struct.unpack_from(f">{n_chars}I", data, off_char * 4) if n_chars else ()
 )
 lig_kern: tuple[int, ...] = (
 struct.unpack_from(f">{nl}I", data, off_lig_kern * 4) if nl else ()
 )

 return TfmData(
 checksum=checksum,
 design_size_sp=design_size_sp,
 bc=bc,
 ec=ec,
 widths_fw=widths,
 heights_fw=heights,
 depths_fw=depths,
 italics_fw=italics,
 char_info=char_info,
 lig_kern=lig_kern,
 kerns_fw=kerns,
 params_fw=params,
 )
