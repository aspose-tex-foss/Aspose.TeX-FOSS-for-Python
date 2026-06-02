"""DVI output backend.

Implements the DVI (DeVice Independent) file format writer as defined in
 and . Receives completed page boxes from the page builder
via the ShipoutBackend protocol and emits valid DVI version 2 binary.

See for full design rationale and opcode reference.
"""
from __future__ import annotations

import dataclasses
import io
import struct
from pathlib import Path
from typing import TYPE_CHECKING

from aspose_tex._engine.nodes import (
 RUNNING_DIMEN,
 CharNode,
 GlueNode,
 GlueSign,
 HlistNode,
 InsertNode,
 KernNode,
 PenaltyNode,
 RuleNode,
 VlistNode,
 WhatsitNode,
)
from aspose_tex._engine.registers import GlueOrder
from aspose_tex.exceptions import FontError

if TYPE_CHECKING:
 from aspose_tex._engine.registers import Glue
 from aspose_tex._fonts.font_manager import FontManager

# ---------------------------------------------------------------------------
# DVI opcode constants
# ---------------------------------------------------------------------------

_SET_CHAR_MAX = 127 # set_char_0 .. set_char_127 → opcodes 0-127
_SET1 = 128
_SET_RULE = 132
_PUT_RULE = 137
_BOP = 139
_EOP = 140
_PUSH = 141
_POP = 142
_RIGHT1 = 143
_DOWN1 = 157
_FNT_NUM_BASE = 171 # fnt_num_0 .. fnt_num_63 → opcodes 171-234
_FNT1 = 235
_XXX1 = 239
_FNT_DEF1 = 243
_PRE = 247
_POST = 248
_POST_POST = 249

_DVI_ID = 2 # DVI version 2
_DVI_NUM = 25400000 # standard TeX preamble numerator
_DVI_DEN = 473628672 # standard TeX preamble denominator


# ---------------------------------------------------------------------------
# Glue helper
# ---------------------------------------------------------------------------

def _actual_glue_width(glue: Glue, sign: GlueSign, order: GlueOrder, ratio: float) -> int:
 """Compute the actual set width of a GlueNode given the enclosing box's glue parameters."""
 if sign == GlueSign.NORMAL:
 return glue.width
 elif sign == GlueSign.STRETCHING and glue.stretch_order == order:
 return glue.width + round(glue.stretch * ratio)
 elif sign == GlueSign.SHRINKING and glue.shrink_order == order:
 return glue.width - round(glue.shrink * ratio)
 else:
 return glue.width


def _rule_paints(width: int, height: int, depth: int) -> bool:
 """Whether a rule actually paints, per TeX:The Program §622 / §634.

 A rule is shipped to the output stream only when both its total height
 (``height + depth``) and its ``width`` are positive. A non-painting rule —
 e.g. a zero-width ``\\strut`` (``\\vrule width\\z@``) or a zero-height rule —
 advances the reference point but emits no ``set_rule`` opcode. Dimensions
 are in sp and must already be RUNNING_DIMEN-resolved.
 """
 return width > 0 and (height + depth) > 0


# ---------------------------------------------------------------------------
# DviFontDef
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True, slots=True)
class DviFontDef:
 """Font metadata for a DVI ``fnt_def`` command.

 Attributes:
 font_num: DVI-internal font number (0-based, assigned by DviWriter).
 cs_name: TeX control-sequence name (e.g. ``"tenrm"``).
 tfm_name: TFM file stem (e.g. ``"cmr10"``).
 checksum: Unsigned 32-bit TFM checksum.
 design_size_sp: Design size in sp.
 scaled_size_sp: Actual size in sp.

 Example::

 fdef = DviFontDef(
 font_num=0,
 cs_name="tenrm",
 tfm_name="cmr10",
 checksum=1274110073,
 design_size_sp=655360,
 scaled_size_sp=655360,
 )
 """

 font_num: int
 cs_name: str
 tfm_name: str
 checksum: int
 design_size_sp: int
 scaled_size_sp: int


# ---------------------------------------------------------------------------
# DviWriter
# ---------------------------------------------------------------------------

class DviWriter:
 """Writes DVI version 2 output; implements ``ShipoutBackend``.

 Usage::

 import io
 buf = io.BytesIO()
 writer = DviWriter(buf, font_manager=mgr)
 page_builder = PageBuilder(config, backend=writer)
 # ... feed content to page_builder ...
 page_builder.end_of_document()
 writer.finalize()
 dvi_bytes = writer.get_bytes() # if using BytesIO destination

 With file output::

 writer = DviWriter(Path("output.dvi"), font_manager=mgr)
 # ... use writer as backend ...
 writer.finalize()
 """

 def __init__(
 self,
 destination: Path | io.RawIOBase | io.BytesIO,
 font_manager: FontManager,
 *,
 mag: int = 1000,
 comment: str = "",
 ) -> None:
 """Initialise the DVI writer.

 Args:
 destination: ``pathlib.Path`` for file output, or a binary I/O
 object (e.g. ``io.BytesIO``) for in-memory output.
 font_manager: Used to look up TFM name, checksum, and sizes for
 ``fnt_def`` commands.
 mag: DVI magnification * 1000 (default 1000 = no magnification).
 comment: Preamble identification comment (≤ 255 bytes after UTF-8
 encoding; truncated silently if longer).
 """
 self._font_manager = font_manager
 self._mag = mag
 self._font_registry: dict[str, DviFontDef] = {}
 self._next_font_num = 0
 self._cur_font_num: int | None = None
 self._last_bop_offset = -1
 self._post_offset: int | None = None
 self._page_count = 0
 self._max_height = 0
 self._max_width = 0
 self._max_stack_depth = 0
 self._finalized = False
 self._owns_file = False
 self._cur_h = 0
 self._cur_v = 0
 self._stack_depth = 0
 # Source of truth for whether get_bytes() is valid
 self._is_memory = not isinstance(destination, Path)

 if isinstance(destination, Path):
 self._stream: io.BytesIO | io.BufferedWriter = destination.open("wb") # type: ignore[assignment]
 self._owns_file = True
 else:
 self._stream = destination # type: ignore[assignment]

 self._write_preamble(comment)

 # ------------------------------------------------------------------
 # ShipoutBackend interface
 # ------------------------------------------------------------------

 def shipout(self, page_number: int, box: VlistNode) -> None:
 """Receive one completed page and write BOP … EOP to the DVI stream.

 Called by ``PlainOutputRoutine`` (via ``PageBuilder``).

 Args:
 page_number: Value of ``\\pageno`` at the time of shipout.
 box: Finalized page VlistNode from ``PlainOutputRoutine``.

 Raises:
 RuntimeError: If called after ``finalize()``.
 FontError: If a ``CharNode`` references a font not registered in
 ``FontManager``.
 """
 if self._finalized:
 raise RuntimeError("DviWriter.shipout() called after finalize()")

 # Ensure all fonts referenced on this page are defined.
 for cs_name in self._collect_fonts(box):
 if cs_name not in self._font_registry:
 info = self._font_manager.font_def_info(cs_name)
 if info is None:
 raise FontError(f"DVI: font '{cs_name}' not registered in FontManager")
 tfm_name, checksum, design_size_sp, at_size_sp = info
 fdef = DviFontDef(
 font_num=self._next_font_num,
 cs_name=cs_name,
 tfm_name=tfm_name,
 checksum=checksum,
 design_size_sp=design_size_sp,
 scaled_size_sp=at_size_sp,
 )
 self._font_registry[cs_name] = fdef
 self._next_font_num += 1
 self._emit_fnt_def(fdef)

 # BOP: counts[0] = page_number, counts[1..9] = 0, prev = last_bop_offset
 bop_offset = self._tell()
 self._put_u1(_BOP)
 self._put_i4(page_number)
 for _ in range(9):
 self._put_i4(0)
 self._put_i4(self._last_bop_offset)
 self._last_bop_offset = bop_offset

 # Reset cursors and traverse the page box.
 self._cur_h = 0
 self._cur_v = 0
 self._cur_font_num = None
 self._stack_depth = 0

 self._put_u1(_PUSH)
 self._stack_depth = 1
 depth = self._traverse_vlist(box.list, box, h_ref=0, v_ref=0)
 self._put_u1(_POP)

 max_depth = max(self._stack_depth, depth) # depth already includes outer push

 self._put_u1(_EOP)

 # Update statistics.
 self._page_count += 1
 page_h = box.height + box.depth
 if page_h > self._max_height:
 self._max_height = page_h
 if box.width > self._max_width:
 self._max_width = box.width
 if max_depth > self._max_stack_depth:
 self._max_stack_depth = max_depth

 # ------------------------------------------------------------------
 # Finalisation
 # ------------------------------------------------------------------

 def finalize(self) -> None:
 """Write the DVI postamble and close the output stream.

 Must be called exactly once, after all ``shipout`` calls.

 Raises:
 RuntimeError: If called more than once.
 """
 if self._finalized:
 raise RuntimeError("DviWriter.finalize() already called")
 self._finalized = True

 self._post_offset = self._tell()
 self._put_u1(_POST)
 self._put_i4(self._last_bop_offset)
 self._put_u4(_DVI_NUM)
 self._put_u4(_DVI_DEN)
 self._put_u4(self._mag)
 self._put_u4(self._max_height)
 self._put_u4(self._max_width)
 self._put_u2(self._max_stack_depth)
 self._put_u2(self._page_count)

 # Repeat all font definitions (required by DVI spec).
 for fdef in self._font_registry.values():
 self._emit_fnt_def(fdef)

 # post_post: post_offset, id=2, then ≥4 bytes of 223 padded to 4-byte boundary.
 post_post_offset = self._tell()
 self._put_u1(_POST_POST)
 self._put_i4(self._post_offset)
 self._put_u1(_DVI_ID)

 # Need at least 4 x 223 bytes, then pad to 4-byte boundary.
 n_pad = 4
 while (post_post_offset + 1 + 4 + 1 + n_pad) % 4 != 0:
 n_pad += 1
 self._put_bytes(bytes([223] * n_pad))

 if self._owns_file:
 self._stream.close() # type: ignore[attr-defined]
 elif hasattr(self._stream, "flush"):
 self._stream.flush()

 def get_bytes(self) -> bytes:
 """Return the full DVI content as bytes.

 Only valid after ``finalize()`` and only when ``destination`` was
 a binary I/O object (not a ``Path``).

 Returns:
 Complete DVI file bytes.

 Raises:
 RuntimeError: If ``finalize()`` has not been called, or if
 destination is a file path.
 """
 if not self._finalized:
 raise RuntimeError("DviWriter.finalize() must be called before get_bytes()")
 if not self._is_memory:
 raise RuntimeError("get_bytes() is only available for in-memory destinations")
 return self._stream.getvalue() # type: ignore[attr-defined]

 # ------------------------------------------------------------------
 # Preamble
 # ------------------------------------------------------------------

 def _write_preamble(self, comment: str) -> None:
 """Emit ``pre`` (247): id=2, num=25400000, den=473628672, mag, comment."""
 comment_bytes = comment.encode("utf-8")[:255]
 self._put_u1(_PRE)
 self._put_u1(_DVI_ID)
 self._put_u4(_DVI_NUM)
 self._put_u4(_DVI_DEN)
 self._put_u4(self._mag)
 self._put_u1(len(comment_bytes))
 self._put_bytes(comment_bytes)

 # ------------------------------------------------------------------
 # Font helpers
 # ------------------------------------------------------------------

 def _collect_fonts(self, node: object) -> list[str]:
 """Recursively collect all font cs_names referenced by CharNodes in depth-first order."""
 seen: set[str] = set()
 result: list[str] = []

 def _walk(n: object) -> None:
 if isinstance(n, CharNode):
 if n.font_name not in seen:
 seen.add(n.font_name)
 result.append(n.font_name)
 elif isinstance(n, (HlistNode, VlistNode)):
 for child in n.list:
 _walk(child)

 _walk(node)
 return result

 def _emit_fnt_def(self, fdef: DviFontDef) -> None:
 """Emit fnt_def1 (243) command for the given font."""
 name_bytes = fdef.tfm_name.encode("ascii")
 self._put_u1(_FNT_DEF1)
 self._put_u1(fdef.font_num)
 self._put_u4(fdef.checksum)
 self._put_u4(fdef.scaled_size_sp)
 self._put_u4(fdef.design_size_sp)
 self._put_u1(0) # area_len = 0
 self._put_u1(len(name_bytes))
 self._put_bytes(name_bytes)

 def _emit_fnt_select(self, font_num: int) -> None:
 """Emit fnt_num_k (171-234) or fnt1 (235) to select a font."""
 if font_num <= 63:
 self._put_u1(_FNT_NUM_BASE + font_num)
 else:
 self._put_u1(_FNT1)
 self._put_u1(font_num)

 # ------------------------------------------------------------------
 # Node traversal
 # ------------------------------------------------------------------

 def _traverse_vlist(
 self,
 nodes: list,
 parent: VlistNode,
 h_ref: int,
 v_ref: int,
 ) -> int:
 """Traverse a vertical list and emit DVI commands.

 Returns the maximum push/pop nesting depth encountered inside.
 """
 v_cursor = v_ref
 # DVI v starts at v_ref; we track where DVI v actually is.
 dvi_v = v_ref
 max_depth = 0

 for node in nodes:
 if isinstance(node, (HlistNode, VlistNode)):
 # Advance v_cursor to baseline of this box.
 v_cursor += node.height
 delta_v = v_cursor - dvi_v
 self._emit_down(delta_v)
 dvi_v = v_cursor

 self._put_u1(_PUSH)
 self._stack_depth += 1
 if self._stack_depth > max_depth:
 max_depth = self._stack_depth

 if node.shift_amount != 0:
 self._emit_right(node.shift_amount)

 if isinstance(node, HlistNode):
 d = self._traverse_hlist(node.list, node, h_ref=h_ref, v_ref=dvi_v)
 else:
 # Enter the child vbox at its TOP edge — matches PDF/SVG
 # writers and Knuth's vlist_out which does
 # `cur_v := cur_v - height(this_box)` on entry so content
 # is laid out from the top going down.
 inner_top_v = dvi_v - node.height
 delta_up = inner_top_v - dvi_v
 if delta_up != 0:
 self._emit_down(delta_up)
 d = self._traverse_vlist(node.list, node, h_ref=h_ref, v_ref=inner_top_v)

 if d > max_depth:
 max_depth = d

 self._put_u1(_POP)
 self._stack_depth -= 1

 # Restore DVI h/v to where they were before push (pop semantics).
 # After pop, DVI h=h_ref, v=dvi_v.
 v_cursor += node.depth

 elif isinstance(node, GlueNode):
 actual = _actual_glue_width(
 node.glue, parent.glue_sign, parent.glue_order, parent.glue_set
 )
 v_cursor += actual

 elif isinstance(node, KernNode):
 v_cursor += node.width

 elif isinstance(node, PenaltyNode):
 pass # skip

 elif isinstance(node, InsertNode):
 pass # \holdinginserts M3 pass-through: silent no-op.

 elif isinstance(node, RuleNode):
 # Resolve RUNNING_DIMEN against the enclosing box, mirroring the
 # hlist arm (above) and the PDF/SVG vlist arms. A full-\hsize
 # \hrule carries width == RUNNING_DIMEN and must paint the
 # parent's concrete width, not the -2^30 sentinel.
 height = node.height if node.height != RUNNING_DIMEN else parent.height
 depth = node.depth if node.depth != RUNNING_DIMEN else parent.depth
 width = node.width if node.width != RUNNING_DIMEN else parent.width
 # TeX §634: ship a vlist rule only when it paints; the
 # reference point still advances by height+depth either way
 #.
 if _rule_paints(width, height, depth):
 v_cursor += height
 delta_v = v_cursor - dvi_v
 self._emit_down(delta_v)
 dvi_v = v_cursor
 # TeX:The Program §624 (vlist_out): a vertically placed rule
 # ships with put_rule, which paints WITHOUT advancing the
 # horizontal reference point. set_rule (§622, hlist_out)
 # would advance the DVI h register by the rule width, which
 # shifts the following material right in strict DVI viewers
 # (Yap). The DVI h register is left untouched here — only v
 # advances by height/depth.
 self._put_u1(_PUT_RULE)
 self._put_i4(height + depth)
 self._put_i4(width)
 v_cursor += depth
 else:
 v_cursor += height + depth

 elif isinstance(node, WhatsitNode):
 if isinstance(node.data, bytes):
 self._emit_xxx(node.data)

 return max_depth

 def _traverse_hlist(
 self,
 nodes: list,
 parent: HlistNode,
 h_ref: int,
 v_ref: int,
 ) -> int:
 """Traverse a horizontal list and emit DVI commands.

 Returns the maximum push/pop nesting depth encountered inside.
 """
 h_cursor = h_ref
 # DVI h starts at h_ref.
 dvi_h = h_ref
 max_depth = 0

 for node in nodes:
 if isinstance(node, CharNode):
 # Lazy movement: emit right to reach h_cursor.
 delta_h = h_cursor - dvi_h
 if delta_h != 0:
 self._emit_right(delta_h)
 dvi_h = h_cursor

 # Font selection if changed.
 fdef = self._font_registry.get(node.font_name)
 if fdef is None:
 raise FontError(f"DVI: font '{node.font_name}' not registered in FontManager")
 if self._cur_font_num != fdef.font_num:
 self._emit_fnt_select(fdef.font_num)
 self._cur_font_num = fdef.font_num

 # Emit character.
 c = node.char
 if c <= _SET_CHAR_MAX:
 self._put_u1(c)
 else:
 self._put_u1(_SET1)
 self._put_u1(c)

 # Advance h by character width.
 metrics = self._font_manager.get_metrics(node.font_name)
 char_width = metrics.char_metrics(c).width if metrics is not None and metrics.has_char(c) else 0
 h_cursor += char_width
 dvi_h += char_width # set_char/set1 advance DVI h automatically

 elif isinstance(node, KernNode):
 h_cursor += node.width

 elif isinstance(node, GlueNode):
 actual = _actual_glue_width(
 node.glue, parent.glue_sign, parent.glue_order, parent.glue_set
 )
 h_cursor += actual

 elif isinstance(node, PenaltyNode):
 pass # skip

 elif isinstance(node, InsertNode):
 pass # Defensive no-op if an insert reaches an hlist.

 elif isinstance(node, HlistNode):
 delta_h = h_cursor - dvi_h
 if delta_h != 0:
 self._emit_right(delta_h)
 dvi_h = h_cursor

 self._put_u1(_PUSH)
 self._stack_depth += 1
 if self._stack_depth > max_depth:
 max_depth = self._stack_depth

 if node.shift_amount != 0:
 self._emit_down(-node.shift_amount)

 d = self._traverse_hlist(node.list, node, h_ref=dvi_h, v_ref=v_ref)
 if d > max_depth:
 max_depth = d

 self._put_u1(_POP)
 self._stack_depth -= 1

 h_cursor += node.width

 elif isinstance(node, VlistNode):
 delta_h = h_cursor - dvi_h
 if delta_h != 0:
 self._emit_right(delta_h)
 dvi_h = h_cursor

 self._put_u1(_PUSH)
 self._stack_depth += 1
 if self._stack_depth > max_depth:
 max_depth = self._stack_depth

 self._emit_down(-node.height)

 d = self._traverse_vlist(node.list, node, h_ref=dvi_h, v_ref=v_ref - node.height)
 if d > max_depth:
 max_depth = d

 self._put_u1(_POP)
 self._stack_depth -= 1

 h_cursor += node.width

 elif isinstance(node, RuleNode):
 delta_h = h_cursor - dvi_h
 if delta_h != 0:
 self._emit_right(delta_h)
 dvi_h = h_cursor

 height = node.height if node.height != RUNNING_DIMEN else parent.height
 depth = node.depth if node.depth != RUNNING_DIMEN else parent.depth
 width = node.width if node.width != RUNNING_DIMEN else parent.width
 rule_height = height + depth

 # TeX §622: ship the rule only when it paints; the reference
 # point (h_cursor) still advances by width either way, but the
 # DVI h register advances only when a set_rule is emitted
 #.
 if _rule_paints(width, height, depth):
 self._put_u1(_SET_RULE)
 self._put_i4(rule_height)
 self._put_i4(width)
 dvi_h += width # set_rule advances DVI h by width
 h_cursor += width

 elif isinstance(node, WhatsitNode):
 if isinstance(node.data, bytes):
 self._emit_xxx(node.data)

 return max_depth

 # ------------------------------------------------------------------
 # Movement commands
 # ------------------------------------------------------------------

 def _emit_right(self, delta: int) -> None:
 """Emit right1/right2/right3/right4 for horizontal movement."""
 if delta == 0:
 return
 if -128 <= delta <= 127:
 self._put_u1(_RIGHT1)
 self._put_i1(delta)
 elif -32768 <= delta <= 32767:
 self._put_u1(_RIGHT1 + 1)
 self._put_i2(delta)
 elif -(1 << 23) <= delta < (1 << 23):
 self._put_u1(_RIGHT1 + 2)
 self._put_i3(delta)
 else:
 self._put_u1(_RIGHT1 + 3)
 self._put_i4(delta)

 def _emit_down(self, delta: int) -> None:
 """Emit down1/down2/down3/down4 for vertical movement."""
 if delta == 0:
 return
 if -128 <= delta <= 127:
 self._put_u1(_DOWN1)
 self._put_i1(delta)
 elif -32768 <= delta <= 32767:
 self._put_u1(_DOWN1 + 1)
 self._put_i2(delta)
 elif -(1 << 23) <= delta < (1 << 23):
 self._put_u1(_DOWN1 + 2)
 self._put_i3(delta)
 else:
 self._put_u1(_DOWN1 + 3)
 self._put_i4(delta)

 def _emit_xxx(self, data: bytes) -> None:
 """Emit xxx1-xxx4 (239-242) special command."""
 n = len(data)
 if n <= 255:
 self._put_u1(_XXX1)
 self._put_u1(n)
 elif n <= 65535:
 self._put_u1(_XXX1 + 1)
 self._put_u2(n)
 elif n < (1 << 24):
 self._put_u1(_XXX1 + 2)
 self._put_u3(n)
 else:
 self._put_u1(_XXX1 + 3)
 self._put_u4(n)
 self._put_bytes(data)

 # ------------------------------------------------------------------
 # Low-level byte writers
 # ------------------------------------------------------------------

 def _put_u1(self, v: int) -> None:
 self._stream.write(struct.pack("B", v & 0xFF))

 def _put_i1(self, v: int) -> None:
 self._stream.write(struct.pack("b", v))

 def _put_u2(self, v: int) -> None:
 self._stream.write(struct.pack(">H", v & 0xFFFF))

 def _put_i2(self, v: int) -> None:
 self._stream.write(struct.pack(">h", v))

 def _put_u3(self, v: int) -> None:
 self._stream.write(struct.pack(">I", v & 0xFFFFFF)[1:])

 def _put_i3(self, v: int) -> None:
 # Encode as 3-byte big-endian signed.
 b = struct.pack(">i", v)
 self._stream.write(b[1:])

 def _put_u4(self, v: int) -> None:
 self._stream.write(struct.pack(">I", v & 0xFFFFFFFF))

 def _put_i4(self, v: int) -> None:
 self._stream.write(struct.pack(">i", v))

 def _put_bytes(self, b: bytes) -> None:
 self._stream.write(b)

 def _tell(self) -> int:
 return self._stream.tell()
