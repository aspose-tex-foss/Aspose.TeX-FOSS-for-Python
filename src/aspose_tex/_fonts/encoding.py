"""TeX character code <-> PostScript glyph name mapping.

Encoding vectors are extracted from PFB font files. This module provides
lookup utilities used by PDF (encoding dictionaries, /Differences arrays)
and SVG (glyph selection) backends.

See for encoding design rationale.
"""
from __future__ import annotations

from aspose_tex._fonts.pfb_parser import PfbData


class FontEncoding:
 """Maps TeX character codes (0-255) to PostScript glyph names.

 Built from a PfbData's encoding vector. Provides forward lookup
 (code -> name) and reverse lookup (name -> code).

 Attributes:
 font_name: PostScript font name (from PfbData).

 Example::

 enc = FontEncoding(pfb_data)
 enc.glyph_name(65) # "A"
 enc.char_code("A") # 65
 enc.differences() # [(0, "Gamma"), (1, "Delta"), ...]
 """

 __slots__ = ("_code_to_name", "_name_to_code", "font_name")

 def __init__(self, pfb: PfbData) -> None:
 """
 Args:
 pfb: Parsed PFB data containing the encoding vector.
 """
 self.font_name = pfb.font_name
 self._code_to_name: dict[int, str] = dict(pfb.encoding)
 self._name_to_code: dict[str, int] = {
 name: code for code, name in pfb.encoding.items()
 }

 def glyph_name(self, code: int) -> str:
 """Return PostScript glyph name for a TeX character code.

 Args:
 code: Character code 0-255.

 Returns:
 Glyph name string, or ".notdef" if the code has no mapping.
 """
 return self._code_to_name.get(code, ".notdef")

 def char_code(self, name: str) -> int | None:
 """Return character code for a glyph name, or None.

 Args:
 name: PostScript glyph name (e.g. "A", "Gamma").

 Returns:
 Character code 0-255, or None if the name is not in this encoding.
 """
 return self._name_to_code.get(name)

 def differences(self) -> list[tuple[int, str]]:
 """Return encoding entries as (code, name) pairs sorted by code.

 Suitable for building a PDF /Differences array. Only includes
 entries where the glyph name differs from /.notdef.

 Returns:
 Sorted list of (code, glyph_name) tuples.
 """
 return sorted(self._code_to_name.items())

 def has_code(self, code: int) -> bool:
 """Return True if this encoding has a non-.notdef entry for code."""
 return code in self._code_to_name
