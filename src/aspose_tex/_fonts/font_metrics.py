"""Scaled font metrics computed from a TfmData.

See for design rationale and lig/kern program decoding.

char_info word layout (big-endian uint32):
 bits 31-24: width_index
 bits 23-20: height_index
 bits 19-16: depth_index
 bits 15-10: italic_index
 bits 9- 8: tag (0=normal, 1=lig/kern, 2=chain, 3=extensible)
 bits 7- 0: remainder
"""
from __future__ import annotations

import dataclasses

from aspose_tex._fonts.tfm_parser import TfmData
from aspose_tex.exceptions import FontError


@dataclasses.dataclass(frozen=True, slots=True)
class CharMetrics:
 """Character metrics for one glyph, in scaled points.

 Attributes:
 width: Advance width (always >= 0).
 height: Height above baseline (>= 0).
 depth: Depth below baseline (>= 0).
 italic: Italic correction (>= 0).
 """

 width: int
 height: int
 depth: int
 italic: int


class FontMetrics:
 """Scaled font metrics at a specific output size.

 Takes an immutable TfmData and a target size (in sp), and converts
 all fix_word values on demand using: sp = fix_word * at_size_sp >> 20.

 fontdimen values can be overridden via set_fontdimen() (used by the
 \\fontdimen assignment primitive).

 Example::

 metrics = FontMetrics(tfm, at_sp=10 * 65536)
 w = metrics.char_metrics(ord("A")).width
 kern = metrics.kern(ord("A"), ord("V")) # int | None
 lig = metrics.ligature(ord("f"), ord("i")) # int | None (replacement code)
 space = metrics.fontdimen(2) # interword space in sp
 """

 __slots__ = (
 "_at_sp",
 "_fontdimen_overrides",
 "_tfm",
 "_tfm_name",
 "hyphenchar",
 "skewchar",
 )

 def __init__(self, tfm: TfmData, at_sp: int, tfm_name: str = "") -> None:
 """
 Args:
 tfm: Parsed TFM data (immutable).
 at_sp: Requested font size in scaled points.
 tfm_name: TFM file stem (e.g. ``"cmr10"``). Used by DVI backend.
 """
 self._tfm = tfm
 self._at_sp = at_sp
 self._tfm_name = tfm_name
 self._fontdimen_overrides: dict[int, int] = {}
 self.hyphenchar = -1
 self.skewchar = -1

 # ------------------------------------------------------------------
 # Size properties
 # ------------------------------------------------------------------

 @property
 def design_size_sp(self) -> int:
 """Design size from the TFM file in scaled points."""
 return self._tfm.design_size_sp

 @property
 def at_size_sp(self) -> int:
 """Actual requested size in scaled points."""
 return self._at_sp

 @property
 def tfm_name(self) -> str:
 """TFM file stem (without extension), e.g. ``"cmr10"``."""
 return self._tfm_name

 @property
 def checksum(self) -> int:
 """TFM checksum (unsigned 32-bit) for DVI fnt_def."""
 return self._tfm.checksum

 # ------------------------------------------------------------------
 # Character metrics
 # ------------------------------------------------------------------

 def has_char(self, code: int) -> bool:
 """Return True if code is in bc..ec and its width_index != 0.

 A width_index of 0 means the character does not exist in this font
 (TeX convention).

 Args:
 code: Character code 0-255.
 """
 tfm = self._tfm
 if code < tfm.bc or code > tfm.ec:
 return False
 word = tfm.char_info[code - tfm.bc]
 width_index = (word >> 24) & 0xFF
 return width_index != 0

 def char_metrics(self, code: int) -> CharMetrics:
 """Return scaled metrics for character code.

 Args:
 code: Character code 0-255.

 Returns:
 CharMetrics with all fields in scaled points.

 Raises:
 FontError: If code not in bc..ec.

 Example::

 cm = metrics.char_metrics(65) # 'A'
 """
 tfm = self._tfm
 if code < tfm.bc or code > tfm.ec:
 raise FontError(
 f"character code {code} not in font range bc={tfm.bc}..ec={tfm.ec}"
 )
 word = tfm.char_info[code - tfm.bc]
 wi = (word >> 24) & 0xFF
 hi = (word >> 20) & 0x0F
 di = (word >> 16) & 0x0F
 ii = (word >> 10) & 0x3F
 at = self._at_sp
 return CharMetrics(
 width=tfm.widths_fw[wi] * at >> 20,
 height=tfm.heights_fw[hi] * at >> 20,
 depth=tfm.depths_fw[di] * at >> 20,
 italic=tfm.italics_fw[ii] * at >> 20,
 )

 # ------------------------------------------------------------------
 # Kerning & ligatures (lig_kern program decoding)
 # ------------------------------------------------------------------

 def kern(self, code1: int, code2: int) -> int | None:
 """Return kern amount between code1 and code2 in sp, or None.

 A negative value means the characters are pulled closer together.
 Implements op_byte >= 128 path of the lig/kern program.

 Args:
 code1: Left character code.
 code2: Right character code.

 Returns:
 Kern amount in scaled points, or None if no kern entry.
 """
 result = self._walk_lig_kern(code1, code2)
 if result is None:
 return None
 kind, value = result
 if kind == "kern":
 return value
 return None

 def ligature(self, code1: int, code2: int) -> int | None:
 """Return replacement character code if code1+code2 is a ligature.

 Implements only the /LIG/ type (op_byte == 0): both input characters
 are consumed and replaced by the remainder character. Other ligature
 types (LIG/, /LIG/>, etc.) are NOT supported in M1 — return None.

 Args:
 code1: Left character code.
 code2: Right character code.

 Returns:
 Replacement character code, or None if no matching ligature.
 """
 result = self._walk_lig_kern(code1, code2)
 if result is None:
 return None
 kind, value = result
 if kind == "lig":
 return value
 return None

 def _walk_lig_kern(self, code1: int, code2: int) -> tuple[str, int] | None:
 """Walk the lig/kern program for code1 looking for code2.

 Returns:
 ("kern", kern_sp) if a kern entry is found,
 ("lig", replacement_code) if a /LIG/ entry is found,
 None if code1 has no lig/kern program or no entry for code2.
 """
 tfm = self._tfm
 if code1 < tfm.bc or code1 > tfm.ec:
 return None

 word = tfm.char_info[code1 - tfm.bc]
 tag = (word >> 8) & 0x03 # bits 9..8
 if tag != 1:
 return None
 start = word & 0xFF # bits 7..0 = remainder

 lk = tfm.lig_kern
 # Handle skip_byte == 255 redirect on the first instruction.
 if start < len(lk):
 first = lk[start]
 if (first >> 24) & 0xFF == 255:
 start = ((first >> 8) & 0xFF) * 256 + (first & 0xFF)

 i = start
 while i < len(lk):
 instr = lk[i]
 skip = (instr >> 24) & 0xFF
 next_char = (instr >> 16) & 0xFF
 op_byte = (instr >> 8) & 0xFF
 remainder = instr & 0xFF

 if next_char == code2:
 if op_byte >= 128:
 # Kern entry
 kern_index = (op_byte - 128) * 256 + remainder
 kern_sp = tfm.kerns_fw[kern_index] * self._at_sp >> 20
 return ("kern", kern_sp)
 if op_byte == 0:
 # /LIG/ — both chars consumed, replaced by remainder
 return ("lig", remainder)
 # Other ligature type — not supported in M1
 return None

 if skip >= 128:
 break
 i += skip + 1

 return None

 # ------------------------------------------------------------------
 # fontdimen
 # ------------------------------------------------------------------

 def fontdimen(self, index: int) -> int:
 """Return fontdimen parameter at 1-based index, in scaled points.

 Overridden values (set via set_fontdimen) take precedence.
 Returns 0 if index is out of range.

 Standard indices:
 1 = slant per pt, 2 = interword space, 3 = space stretch,
 4 = space shrink, 5 = x-height, 6 = quad width, 7 = extra space.

 Args:
 index: 1-based parameter index.
 """
 if index in self._fontdimen_overrides:
 return self._fontdimen_overrides[index]
 params = self._tfm.params_fw
 if index < 1 or index > len(params):
 return 0
 return params[index - 1] * self._at_sp >> 20

 def set_fontdimen(self, index: int, value_sp: int) -> None:
 """Override fontdimen parameter (called by \\fontdimen assignment).

 Args:
 index: 1-based parameter index.
 value_sp: New value in scaled points.
 """
 self._fontdimen_overrides[index] = value_sp
