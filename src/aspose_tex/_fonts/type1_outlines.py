"""Type 1 glyph outline extraction for SVG output.

Decrypts eexec-encrypted charstrings from Type 1 (PFB) fonts and
interprets the charstring programs to produce SVG path data.

See for design rationale and operator table.
"""
from __future__ import annotations

import dataclasses
import struct
import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
 from aspose_tex._fonts.pfb_parser import PfbData


# ---------------------------------------------------------------------------
# GlyphOutline dataclass
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True, slots=True)
class GlyphOutline:
 """Glyph outline extracted from a Type 1 charstring.

 Attributes:
 width: Advance width in Type 1 units (1/1000 of design size).
 svg_path: SVG path data string (``d`` attribute value).
 Empty string if the glyph has no visible outline.
 """

 width: int
 svg_path: str


# ---------------------------------------------------------------------------
# Decryption (Adobe Type 1 Font Format §7.2, §7.3)
# ---------------------------------------------------------------------------

def decrypt_eexec(data: bytes) -> bytes:
 """Decrypt an eexec-encrypted binary segment.

 Implements the Type 1 eexec cipher (Adobe Type 1 Font Format §7.2):
 key = 55665
 for each byte b:
 plain = b ^ (key >> 8)
 key = ((b + key) * 52845 + 22719) & 0xFFFF
 Skips the first 4 plaintext bytes (random IV).

 Args:
 data: Raw eexec-encrypted bytes (binary_body from PFB).

 Returns:
 Decrypted bytes (without IV prefix).
 """
 key = 55665
 result = bytearray(len(data))
 for i, b in enumerate(data):
 result[i] = b ^ (key >> 8)
 key = ((b + key) * 52845 + 22719) & 0xFFFF
 return bytes(result[4:])


def decrypt_charstring(data: bytes, *, leniv: int = 4) -> bytes:
 """Decrypt a Type 1 charstring.

 Same cipher as eexec but with initial key = 4330.
 Skips the first *leniv* plaintext bytes.

 Args:
 data: Encrypted charstring bytes.
 leniv: Number of random IV bytes to skip (default 4).

 Returns:
 Decrypted charstring bytes.
 """
 key = 4330
 result = bytearray(len(data))
 for i, b in enumerate(data):
 result[i] = b ^ (key >> 8)
 key = ((b + key) * 52845 + 22719) & 0xFFFF
 return bytes(result[leniv:])


# ---------------------------------------------------------------------------
# Decrypted body parsing
# ---------------------------------------------------------------------------

def _parse_decrypted_body(text: bytes) -> tuple[list[bytes], dict[str, bytes]]:
 """Parse decrypted eexec output to extract Subrs and CharStrings.

 Returns:
 (subrs, charstrings) where:
 subrs: list indexed by subr number; each entry is encrypted bytes.
 charstrings: dict mapping glyph name to encrypted bytes.
 """
 subrs: list[bytes] = []
 charstrings: dict[str, bytes] = {}

 # Find /Subrs array
 subrs_idx = text.find(b"/Subrs")
 if subrs_idx != -1:
 # Parse "N array" after /Subrs
 rest = text[subrs_idx + 6:]
 # Skip whitespace and find the count
 rest = rest.lstrip()
 count_end = 0
 while count_end < len(rest) and rest[count_end:count_end + 1].isdigit():
 count_end += 1
 if count_end > 0:
 n_subrs = int(rest[:count_end])
 subrs = [b""] * n_subrs

 # Parse "dup <index> <len> RD <data> NP" entries
 pos = 0
 while pos < len(rest):
 # Find "dup <num> <len> RD" or "dup <num> <len> -|"
 dup_idx = rest.find(b"dup ", pos)
 if dup_idx == -1:
 break
 # Check if we've passed into /CharStrings
 cs_marker = rest.find(b"/CharStrings", pos)
 if cs_marker != -1 and dup_idx > cs_marker:
 break

 after_dup = dup_idx + 4
 # Parse subr index
 idx_end = after_dup
 while idx_end < len(rest) and rest[idx_end:idx_end + 1].isdigit():
 idx_end += 1
 if idx_end == after_dup:
 pos = after_dup
 continue
 subr_idx = int(rest[after_dup:idx_end])

 # Skip whitespace, parse length
 len_start = idx_end
 while len_start < len(rest) and rest[len_start:len_start + 1] in (b" ", b"\t", b"\n", b"\r"):
 len_start += 1
 len_end = len_start
 while len_end < len(rest) and rest[len_end:len_end + 1].isdigit():
 len_end += 1
 if len_end == len_start:
 pos = idx_end
 continue
 cs_len = int(rest[len_start:len_end])

 # Find RD or -| marker
 marker_search = rest[len_end:len_end + 20]
 rd_off = marker_search.find(b"RD")
 if rd_off == -1:
 rd_off = marker_search.find(b"-|")
 if rd_off == -1:
 pos = len_end
 continue

 data_start = len_end + rd_off + 2 + 1 # skip "RD" + single space
 data_end = data_start + cs_len
 if data_end > len(rest):
 break

 if 0 <= subr_idx < len(subrs):
 subrs[subr_idx] = rest[data_start:data_end]
 elif subr_idx >= len(subrs):
 # Extend subrs list if needed
 subrs.extend(b"" for _ in range(subr_idx - len(subrs) + 1))
 subrs[subr_idx] = rest[data_start:data_end]

 pos = data_end

 # Find /CharStrings
 cs_idx = text.find(b"/CharStrings")
 if cs_idx == -1:
 return subrs, charstrings

 rest = text[cs_idx:]
 pos = 0
 while pos < len(rest):
 # Find "/<glyphname> <len> RD <data> ND"
 slash_idx = rest.find(b"/", pos)
 if slash_idx == -1:
 break

 # Glyph name ends at whitespace
 name_start = slash_idx + 1
 name_end = name_start
 while name_end < len(rest) and rest[name_end:name_end + 1] not in (b" ", b"\t", b"\n", b"\r"):
 name_end += 1
 glyph_name = rest[name_start:name_end].decode("ascii", errors="replace")

 # Skip whitespace, parse length
 len_start = name_end
 while len_start < len(rest) and rest[len_start:len_start + 1] in (b" ", b"\t", b"\n", b"\r"):
 len_start += 1
 len_end = len_start
 while len_end < len(rest) and rest[len_end:len_end + 1].isdigit():
 len_end += 1
 if len_end == len_start:
 pos = name_end + 1
 continue
 cs_len = int(rest[len_start:len_end])

 # Find RD or -| marker
 marker_search = rest[len_end:len_end + 20]
 rd_off = marker_search.find(b"RD")
 if rd_off == -1:
 rd_off = marker_search.find(b"-|")
 if rd_off == -1:
 pos = name_end + 1
 continue

 data_start = len_end + rd_off + 2 + 1 # "RD" + single space
 data_end = data_start + cs_len
 if data_end > len(rest):
 break

 charstrings[glyph_name] = rest[data_start:data_end]
 pos = data_end

 return subrs, charstrings


# ---------------------------------------------------------------------------
# Adobe Standard Encoding (partial — for seac resolution in CM fonts)
# ---------------------------------------------------------------------------

_STANDARD_ENCODING: dict[int, str] = {
 32: "space", 33: "exclam", 34: "quotedbl", 35: "numbersign",
 36: "dollar", 37: "percent", 38: "ampersand", 39: "quoteright",
 40: "parenleft", 41: "parenright", 42: "asterisk", 43: "plus",
 44: "comma", 45: "hyphen", 46: "period", 47: "slash",
 48: "zero", 49: "one", 50: "two", 51: "three",
 52: "four", 53: "five", 54: "six", 55: "seven",
 56: "eight", 57: "nine", 58: "colon", 59: "semicolon",
 60: "less", 61: "equal", 62: "greater", 63: "question",
 64: "at", 65: "A", 66: "B", 67: "C",
 68: "D", 69: "E", 70: "F", 71: "G",
 72: "H", 73: "I", 74: "J", 75: "K",
 76: "L", 77: "M", 78: "N", 79: "O",
 80: "P", 81: "Q", 82: "R", 83: "S",
 84: "T", 85: "U", 86: "V", 87: "W",
 88: "X", 89: "Y", 90: "Z", 91: "bracketleft",
 92: "backslash", 93: "bracketright", 94: "asciicircum", 95: "underscore",
 96: "quoteleft", 97: "a", 98: "b", 99: "c",
 100: "d", 101: "e", 102: "f", 103: "g",
 104: "h", 105: "i", 106: "j", 107: "k",
 108: "l", 109: "m", 110: "n", 111: "o",
 112: "p", 113: "q", 114: "r", 115: "s",
 116: "t", 117: "u", 118: "v", 119: "w",
 120: "x", 121: "y", 122: "z", 123: "braceleft",
 124: "bar", 125: "braceright", 126: "asciitilde",
 161: "exclamdown", 162: "cent", 163: "sterling",
 164: "fraction", 165: "yen", 166: "florin",
 167: "section", 168: "currency", 169: "quotesingle",
 170: "quotedblleft", 171: "guillemotleft", 172: "guilsinglleft",
 173: "guilsinglright", 174: "fi", 175: "fl",
 177: "endash", 178: "dagger", 179: "daggerdbl",
 180: "periodcentered", 182: "paragraph", 183: "bullet",
 184: "quotesinglbase", 185: "quotedblbase", 186: "quotedblright",
 187: "guillemotright", 188: "ellipsis", 189: "perthousand",
 191: "questiondown",
 193: "grave", 194: "acute", 195: "circumflex", 196: "tilde",
 197: "macron", 198: "breve", 199: "dotaccent", 200: "dieresis",
 202: "ring", 203: "cedilla",
 205: "hungarumlaut", 206: "ogonek", 207: "caron",
 208: "emdash",
 225: "AE", 227: "ordfeminine",
 232: "Lslash",
 233: "Oslash", 234: "OE", 235: "ordmasculine",
 241: "ae",
 245: "dotlessi",
 248: "lslash", 249: "oslash", 250: "oe", 251: "germandbls",
}


# ---------------------------------------------------------------------------
# Charstring interpreter
# ---------------------------------------------------------------------------

def _interpret_charstring(
 data: bytes,
 subrs: list[bytes],
 *,
 glyph_name: str = "",
 _charstrings: dict[str, bytes] | None = None,
 _depth: int = 0,
) -> GlyphOutline:
 """Interpret a decrypted Type 1 charstring and produce a GlyphOutline.

 Args:
 data: Decrypted charstring bytes.
 subrs: List of encrypted subr charstrings.
 glyph_name: For diagnostics only.
 _charstrings: Full charstrings dict (for seac resolution).
 _depth: Recursion depth guard.

 Returns:
 GlyphOutline with width and SVG path data.
 """
 if _depth > 10:
 warnings.warn(
 f"SVG: charstring recursion limit for '{glyph_name}'",
 stacklevel=2,
 )
 return GlyphOutline(width=0, svg_path="")

 try:
 return _interpret_charstring_inner(
 data, subrs,
 glyph_name=glyph_name,
 charstrings=_charstrings,
 depth=_depth,
 )
 except Exception:
 warnings.warn(
 f"SVG: failed to extract glyph '{glyph_name}'",
 stacklevel=2,
 )
 return GlyphOutline(width=0, svg_path="")


def _interpret_charstring_inner(
 data: bytes,
 subrs: list[bytes],
 *,
 glyph_name: str,
 charstrings: dict[str, bytes] | None,
 depth: int,
) -> GlyphOutline:
 """Core charstring interpreter — may raise on malformed data."""
 stack: list[int | float] = []
 ps_stack: list[int | float] = [] # PostScript interpreter stack (for callothersubr/pop)
 call_stack: list[tuple[bytes, int]] = [] # (data, position) for subr returns
 commands: list[tuple] = []
 width = 0
 x, y = 0, 0 # current point
 sbx, sby = 0, 0 # sidebearing
 flex_active = False # True between OtherSubr 1 (flex start) and OtherSubr 0 (flex end)

 pos = 0

 while pos < len(data):
 b0 = data[pos]

 if b0 < 32:
 # Operator
 pos += 1
 if b0 == 1 or b0 == 3: # hstem
 stack.clear()
 elif b0 == 4: # vmoveto
 dy = stack[-1] if stack else 0
 stack.clear()
 x, y = x, y + int(dy)
 if not flex_active:
 commands.append(("M", x, y))
 elif b0 == 5: # rlineto
 dx = stack[-2] if len(stack) >= 2 else 0
 dy = stack[-1] if len(stack) >= 1 else 0
 stack.clear()
 x, y = x + int(dx), y + int(dy)
 commands.append(("L", x, y))
 elif b0 == 6: # hlineto
 dx = stack[-1] if stack else 0
 stack.clear()
 x = x + int(dx)
 commands.append(("L", x, y))
 elif b0 == 7: # vlineto
 dy = stack[-1] if stack else 0
 stack.clear()
 y = y + int(dy)
 commands.append(("L", x, y))
 elif b0 == 8: # rrcurveto
 if len(stack) >= 6:
 dx1, dy1, dx2, dy2, dx3, dy3 = [int(v) for v in stack[-6:]]
 x1, y1 = x + dx1, y + dy1
 x2, y2 = x1 + dx2, y1 + dy2
 x3, y3 = x2 + dx3, y2 + dy3
 commands.append(("C", x1, y1, x2, y2, x3, y3))
 x, y = x3, y3
 stack.clear()
 elif b0 == 9: # closepath
 commands.append(("Z",))
 stack.clear()
 elif b0 == 10: # callsubr
 subr_num = int(stack.pop()) if stack else 0
 if 0 <= subr_num < len(subrs) and subrs[subr_num]:
 call_stack.append((data, pos))
 data = decrypt_charstring(subrs[subr_num])
 pos = 0
 continue
 elif b0 == 11: # return
 if call_stack:
 data, pos = call_stack.pop()
 continue
 else:
 break
 elif b0 == 12: # escape — two-byte operator
 if pos >= len(data):
 break
 b1 = data[pos]
 pos += 1
 if b1 == 0 or b1 == 1 or b1 == 2: # dotsection
 stack.clear()
 elif b1 == 6: # seac
 if len(stack) >= 5 and charstrings is not None:
 _asb, adx, ady, bchar, achar = [int(v) for v in stack[-5:]]
 stack.clear()
 # Resolve base and accent glyphs
 bname = _STANDARD_ENCODING.get(bchar)
 aname = _STANDARD_ENCODING.get(achar)
 if bname and bname in charstrings:
 base = _interpret_charstring(
 decrypt_charstring(charstrings[bname]),
 subrs,
 glyph_name=bname,
 _charstrings=charstrings,
 _depth=depth + 1,
 )
 # Use base path commands directly
 commands.clear()
 if base.svg_path:
 commands.extend(_parse_svg_path(base.svg_path))
 width = base.width
 if aname and aname in charstrings:
 accent = _interpret_charstring(
 decrypt_charstring(charstrings[aname]),
 subrs,
 glyph_name=aname,
 _charstrings=charstrings,
 _depth=depth + 1,
 )
 if accent.svg_path:
 # Offset accent by (adx - asb, ady)
 offset_cmds = _offset_path(
 _parse_svg_path(accent.svg_path),
 adx - _asb + sbx, ady,
 )
 commands.extend(offset_cmds)
 else:
 stack.clear()
 # seac ends the charstring
 break
 elif b1 == 7: # sbw
 if len(stack) >= 4:
 sbx = int(stack[-4])
 sby = int(stack[-3])
 width = int(stack[-2])
 stack.clear()
 x, y = sbx, sby
 elif b1 == 12: # div
 if len(stack) >= 2:
 b_val = stack.pop()
 a_val = stack.pop()
 stack.append(int(a_val) // int(b_val) if int(b_val) != 0 else 0)
 elif b1 == 16: # callothersubr
 if len(stack) >= 2:
 subr_num = int(stack.pop())
 n_args = int(stack.pop())
 if subr_num == 1 and n_args == 0:
 # OtherSubr 1: Flex start (Adobe Type 1 §8.3).
 # The 7 rmoveto's that follow are Flex reference
 # points, not real path segments — suppress their
 # M emission until OtherSubr 0 closes the flex.
 flex_active = True
 elif subr_num == 2 and n_args == 0:
 # OtherSubr 2: Flex mid — no-op (the preceding
 # rmoveto already advanced the cursor).
 pass
 elif subr_num == 0 and n_args == 3:
 # OtherSubr 0: Flex end. Type 1 stack layout
 # (top → bottom): fy, fx, fd. Pop in that order.
 fy_end = int(stack.pop()) if stack else 0
 fx_end = int(stack.pop()) if stack else 0
 if stack:
 stack.pop() # fd (flex depth, unused)
 if flex_active:
 # Render the flex as a single line segment
 # from the pre-flex current point to the
 # endpoint. At integer Type 1 precision this
 # matches the low-depth flex rendering rule
 # (Adobe Type 1 §8.3) and is visually
 # indistinguishable at screen sizes.
 commands.append(("L", fx_end, fy_end))
 flex_active = False
 # Adobe's Flex subr (subr 0 in CM) ends with
 # 3 0 callothersubr pop pop setcurrentpoint
 # so we must leave fx,fy on the PS stack in the
 # order that makes pop/pop/setcurrentpoint resolve
 # to (x=fx, y=fy): push fy first, then fx on top.
 ps_stack.append(fy_end)
 ps_stack.append(fx_end)
 else:
 # Generic OtherSubr (e.g. 3 = hint replacement):
 # move args from the Type 1 stack to the PS
 # interpreter stack in source order so the
 # matching `pop` sequence retrieves them in LIFO.
 args = []
 for _ in range(n_args):
 if stack:
 args.append(stack.pop())
 else:
 args.append(0)
 ps_stack.extend(reversed(args))
 else:
 stack.clear()
 elif b1 == 17: # pop
 if ps_stack:
 stack.append(ps_stack.pop())
 else:
 stack.append(0)
 elif b1 == 33: # setcurrentpoint
 if len(stack) >= 2:
 x = int(stack[-2])
 y = int(stack[-1])
 stack.clear()
 else:
 # Unknown escape operator — ignore
 stack.clear()
 elif b0 == 13: # hsbw
 if len(stack) >= 2:
 sbx = int(stack[-2])
 width = int(stack[-1])
 stack.clear()
 x, y = sbx, 0
 elif b0 == 14: # endchar
 break
 elif b0 == 21: # rmoveto
 dx = stack[-2] if len(stack) >= 2 else 0
 dy = stack[-1] if len(stack) >= 1 else 0
 stack.clear()
 x, y = x + int(dx), y + int(dy)
 if not flex_active:
 commands.append(("M", x, y))
 elif b0 == 22: # hmoveto
 dx = stack[-1] if stack else 0
 stack.clear()
 x = x + int(dx)
 if not flex_active:
 commands.append(("M", x, y))
 elif b0 == 30: # vhcurveto
 if len(stack) >= 4:
 dy1, dx2, dy2, dx3 = [int(v) for v in stack[-4:]]
 x1, y1 = x, y + dy1
 x2, y2 = x1 + dx2, y1 + dy2
 x3, y3 = x2 + dx3, y2
 commands.append(("C", x1, y1, x2, y2, x3, y3))
 x, y = x3, y3
 stack.clear()
 elif b0 == 31: # hvcurveto
 if len(stack) >= 4:
 dx1, dx2, dy2, dy3 = [int(v) for v in stack[-4:]]
 x1, y1 = x + dx1, y
 x2, y2 = x1 + dx2, y1 + dy2
 x3, y3 = x2, y2 + dy3
 commands.append(("C", x1, y1, x2, y2, x3, y3))
 x, y = x3, y3
 stack.clear()
 else:
 # Unknown operator — ignore
 stack.clear()

 elif 32 <= b0 <= 246:
 stack.append(b0 - 139)
 pos += 1
 elif 247 <= b0 <= 250:
 pos += 1
 if pos >= len(data):
 break
 b1 = data[pos]
 pos += 1
 stack.append((b0 - 247) * 256 + b1 + 108)
 elif 251 <= b0 <= 254:
 pos += 1
 if pos >= len(data):
 break
 b1 = data[pos]
 pos += 1
 stack.append(-(b0 - 251) * 256 - b1 - 108)
 elif b0 == 255:
 pos += 1
 if pos + 3 >= len(data):
 break
 val = struct.unpack_from(">i", data, pos)[0]
 pos += 4
 stack.append(val)
 else:
 pos += 1

 return GlyphOutline(width=width, svg_path=_path_to_svg(commands))


def _path_to_svg(commands: list[tuple]) -> str:
 """Serialize path commands to SVG path data string.

 Args:
 commands: List of ('M', x, y), ('L', x, y),
 ('C', x1, y1, x2, y2, x3, y3), ('Z',) tuples.

 Returns:
 SVG path ``d`` attribute value. Coordinates are integers.
 """
 if not commands:
 return ""
 parts: list[str] = []
 for cmd in commands:
 if cmd[0] == "Z":
 parts.append("Z")
 elif cmd[0] == "M":
 parts.append(f"M {cmd[1]} {cmd[2]}")
 elif cmd[0] == "L":
 parts.append(f"L {cmd[1]} {cmd[2]}")
 elif cmd[0] == "C":
 parts.append(
 f"C {cmd[1]} {cmd[2]} {cmd[3]} {cmd[4]} {cmd[5]} {cmd[6]}"
 )
 return " ".join(parts)


def _parse_svg_path(svg_path: str) -> list[tuple]:
 """Parse an SVG path string back into command tuples (for seac)."""
 commands: list[tuple] = []
 tokens = svg_path.split()
 i = 0
 while i < len(tokens):
 t = tokens[i]
 if t == "M" and i + 2 < len(tokens):
 commands.append(("M", int(tokens[i + 1]), int(tokens[i + 2])))
 i += 3
 elif t == "L" and i + 2 < len(tokens):
 commands.append(("L", int(tokens[i + 1]), int(tokens[i + 2])))
 i += 3
 elif t == "C" and i + 6 < len(tokens):
 commands.append((
 "C",
 int(tokens[i + 1]), int(tokens[i + 2]),
 int(tokens[i + 3]), int(tokens[i + 4]),
 int(tokens[i + 5]), int(tokens[i + 6]),
 ))
 i += 7
 elif t == "Z":
 commands.append(("Z",))
 i += 1
 else:
 i += 1
 return commands


def _offset_path(commands: list[tuple], dx: int, dy: int) -> list[tuple]:
 """Offset all coordinates in path commands by (dx, dy)."""
 result: list[tuple] = []
 for cmd in commands:
 if cmd[0] == "M":
 result.append(("M", cmd[1] + dx, cmd[2] + dy))
 elif cmd[0] == "L":
 result.append(("L", cmd[1] + dx, cmd[2] + dy))
 elif cmd[0] == "C":
 result.append((
 "C",
 cmd[1] + dx, cmd[2] + dy,
 cmd[3] + dx, cmd[4] + dy,
 cmd[5] + dx, cmd[6] + dy,
 ))
 elif cmd[0] == "Z":
 result.append(cmd)
 return result


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------

def extract_glyph_outlines(pfb: PfbData) -> dict[int, GlyphOutline]:
 """Extract all glyph outlines from a Type 1 PFB font.

 Steps:
 1. Decrypt ``pfb.binary_body`` with ``decrypt_eexec``.
 2. Parse the decrypted text to extract ``/Subrs`` array and
 ``/CharStrings`` dictionary.
 3. For each CharString entry, decrypt with ``decrypt_charstring``
 and interpret the charstring to produce SVG path data.
 4. Map glyph names to character codes using ``pfb.encoding``.

 Args:
 pfb: Parsed PFB data (from ``parse_pfb``).

 Returns:
 Dict mapping character code (0-255) to ``GlyphOutline``.
 Only codes with valid charstrings are present.
 Codes whose glyphs fail to parse are omitted with a warning.
 """
 decrypted = decrypt_eexec(pfb.binary_body)
 subrs, charstrings = _parse_decrypted_body(decrypted)

 # Iterate over pfb.encoding so that every code gets an entry — CM fonts
 # map many glyph names to two codes (the TeX convention slot in 0..31 and
 # the PostScript slot in 161..255, e.g. ``ff`` at both 11 and 174). Each
 # charstring is interpreted at most once and the resulting GlyphOutline
 # is shared across all codes that reference it.
 outline_by_name: dict[str, GlyphOutline] = {}
 result: dict[int, GlyphOutline] = {}
 for code, glyph_name in pfb.encoding.items():
 encrypted_cs = charstrings.get(glyph_name)
 if encrypted_cs is None:
 continue
 outline = outline_by_name.get(glyph_name)
 if outline is None:
 outline = _interpret_charstring(
 decrypt_charstring(encrypted_cs),
 subrs,
 glyph_name=glyph_name,
 _charstrings=charstrings,
 _depth=0,
 )
 outline_by_name[glyph_name] = outline
 if outline.width > 0 or outline.svg_path:
 result[code] = outline

 return result
