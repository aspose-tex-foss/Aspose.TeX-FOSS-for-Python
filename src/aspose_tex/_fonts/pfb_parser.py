"""PFB (Printer Font Binary) parser.

Reads the PFB container format used by Type 1 PostScript fonts.
Extracts segment data for PDF embedding and the encoding vector
for character code -> glyph name mapping.

See for format details.
"""
from __future__ import annotations

import dataclasses
import re
import struct

from aspose_tex.exceptions import FontError

# PFB segment markers
_PFB_MAGIC = 0x80
_SEG_ASCII = 0x01
_SEG_BINARY = 0x02
_SEG_EOF = 0x03

# Regex patterns for PostScript header parsing
_RE_FONT_NAME = re.compile(rb"/FontName\s+/(\S+)\s+def")
_RE_ENCODING_ENTRY = re.compile(rb"dup\s+(\d+)\s+/(\S+)\s+put")
_RE_STANDARD_ENCODING = re.compile(rb"/Encoding\s+StandardEncoding\s+def")


@dataclasses.dataclass(frozen=True, slots=True)
class PfbData:
 """Immutable parsed data from a PFB file.

 Attributes:
 ascii_header: Raw bytes of segment 0 (ASCII font dictionary).
 binary_body: Raw bytes of segment 1 (eexec-encrypted charstrings).
 ascii_trailer: Raw bytes of segment 2 (zeros padding / cleartomark).
 font_name: PostScript font name extracted from the header
 (e.g. "CMR10"). Empty string if not found.
 encoding: Dict mapping character code (int 0-255) to PostScript
 glyph name (str). Only populated entries are present;
 missing codes mean /.notdef.
 """

 ascii_header: bytes
 binary_body: bytes
 ascii_trailer: bytes
 font_name: str
 encoding: dict[int, str]


def parse_pfb(data: bytes) -> PfbData:
 """Parse a PFB binary blob into a PfbData structure.

 Args:
 data: Raw bytes of a .pfb file.

 Returns:
 Parsed PfbData with segments and encoding.

 Raises:
 FontError: If the data is not a valid PFB file (bad magic,
 truncated segments, missing required segments).

 Example::

 with open("cmr10.pfb", "rb") as f:
 pfb = parse_pfb(f.read())
 assert pfb.font_name == "CMR10"
 assert pfb.encoding[65] == "A"
 """
 if len(data) < 2:
 raise FontError("PFB data too short (need at least 2 bytes)")
 if data[0] != _PFB_MAGIC:
 raise FontError(
 f"Invalid PFB magic byte: 0x{data[0]:02X} (expected 0x80)"
 )

 ascii_parts: list[bytes] = []
 binary_parts: list[bytes] = []
 trailer_parts: list[bytes] = []
 pos = 0

 while pos < len(data):
 if data[pos] != _PFB_MAGIC:
 raise FontError(
 f"Expected PFB segment marker 0x80 at offset {pos}, "
 f"got 0x{data[pos]:02X}"
 )
 if pos + 1 >= len(data):
 raise FontError(f"Truncated PFB segment header at offset {pos}")

 seg_type = data[pos + 1]
 if seg_type == _SEG_EOF:
 break
 if seg_type not in (_SEG_ASCII, _SEG_BINARY):
 raise FontError(
 f"Unknown PFB segment type 0x{seg_type:02X} at offset {pos}"
 )
 if pos + 5 >= len(data):
 raise FontError(
 f"Truncated PFB segment length at offset {pos}"
 )

 seg_len = struct.unpack_from("<I", data, pos + 2)[0]
 seg_start = pos + 6
 seg_end = seg_start + seg_len

 if seg_end > len(data):
 raise FontError(
 f"PFB segment at offset {pos} declares length {seg_len} "
 f"but only {len(data) - seg_start} bytes remain"
 )

 seg_data = data[seg_start:seg_end]

 if seg_type == _SEG_ASCII:
 if binary_parts:
 # ASCII after binary = trailer
 trailer_parts.append(seg_data)
 else:
 ascii_parts.append(seg_data)
 else:
 binary_parts.append(seg_data)

 pos = seg_end

 if not ascii_parts:
 raise FontError("PFB file contains no ASCII segment")
 if not binary_parts:
 raise FontError("PFB file contains no binary segment")

 ascii_header = b"".join(ascii_parts)
 binary_body = b"".join(binary_parts)
 ascii_trailer = b"".join(trailer_parts)

 font_name = _extract_font_name(ascii_header)
 encoding = _extract_encoding(ascii_header)

 return PfbData(
 ascii_header=ascii_header,
 binary_body=binary_body,
 ascii_trailer=ascii_trailer,
 font_name=font_name,
 encoding=encoding,
 )


def _extract_font_name(header: bytes) -> str:
 """Extract /FontName from the ASCII header."""
 m = _RE_FONT_NAME.search(header)
 if m is None:
 return ""
 return m.group(1).decode("ascii", errors="replace")


def _extract_encoding(header: bytes) -> dict[int, str]:
 """Extract encoding vector from the ASCII header.

 If the font uses ``StandardEncoding def`` instead of an explicit
 array, returns an empty dict (the caller must handle this case).
 """
 if _RE_STANDARD_ENCODING.search(header):
 return {}

 encoding: dict[int, str] = {}
 for m in _RE_ENCODING_ENTRY.finditer(header):
 code = int(m.group(1))
 name = m.group(2).decode("ascii", errors="replace")
 if name != ".notdef" and 0 <= code <= 255:
 encoding[code] = name

 return encoding
