"""Unit tests for DviWriter.

Tests verify DVI opcode emission, font definition placement, page structure,
movement commands, and postamble correctness.

All tests use synthetic in-memory data — no external TFM files or TeX Live needed
except where FontManager loads bundled cmr10.tfm.
"""
from __future__ import annotations

import io
import struct

import pytest

from aspose_tex._engine.nodes import (
 RUNNING_DIMEN,
 CharNode,
 GlueNode,
 GlueSign,
 HlistNode,
 KernNode,
 RuleNode,
 VlistNode,
 WhatsitNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._fonts.font_metrics import FontMetrics
from aspose_tex._output.dvi_writer import DviWriter
from aspose_tex.exceptions import FontError
from tests._verification.dvi_walker import walk_rules

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_mgr_with_cmr10() -> FontManager:
 """Return a FontManager with 'tenrm' loaded as cmr10 at 10pt."""
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 return mgr


def _make_writer(mgr: FontManager | None = None) -> tuple[DviWriter, io.BytesIO]:
 """Return (writer, buf) backed by BytesIO."""
 if mgr is None:
 mgr = _make_mgr_with_cmr10()
 buf = io.BytesIO()
 writer = DviWriter(buf, font_manager=mgr)
 return writer, buf


def _make_empty_vlist() -> VlistNode:
 """Return an empty VlistNode suitable for a blank page."""
 return VlistNode(
 list=[],
 width=0,
 height=0,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )


def _make_char_hbox(chars: str, font_name: str, metrics: FontMetrics) -> HlistNode:
 """Build a simple HlistNode containing CharNodes for the given text."""
 nodes = [CharNode(char=ord(c), font_name=font_name) for c in chars]
 total_width = sum(metrics.char_metrics(ord(c)).width for c in chars)
 height = max((metrics.char_metrics(ord(c)).height for c in chars), default=0)
 depth = max((metrics.char_metrics(ord(c)).depth for c in chars), default=0)
 return HlistNode(
 list=nodes,
 width=total_width,
 height=height,
 depth=depth,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )


def _make_page_with_hbox(hbox: HlistNode) -> VlistNode:
 """Wrap an HlistNode in a page-level VlistNode."""
 return VlistNode(
 list=[hbox],
 width=hbox.width,
 height=hbox.height,
 depth=hbox.depth,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )


def _parse_dvi_opcodes(data: bytes) -> list[tuple]:
 """Minimal DVI opcode parser — returns list of (opcode, *args) tuples.

 Only decodes opcodes needed for test assertions. Unknown opcodes
 are returned as (opcode,) with no further parsing.
 """
 result = []
 i = 0
 while i < len(data):
 op = data[i]
 i += 1
 if op <= 127:
 # set_char_k
 result.append(("set_char", op))
 elif op == 128:
 # set1: 1-byte char
 result.append(("set1", data[i]))
 i += 1
 elif op == 132:
 # set_rule: height(4) width(4)
 h, w = struct.unpack_from(">ii", data, i)
 result.append(("set_rule", h, w))
 i += 8
 elif op == 137:
 # put_rule: height(4) width(4) — paints without advancing h
 h, w = struct.unpack_from(">ii", data, i)
 result.append(("put_rule", h, w))
 i += 8
 elif op == 139:
 # bop: counts[10](40) prev(4)
 counts = struct.unpack_from(">10i", data, i)
 prev = struct.unpack_from(">i", data, i + 40)[0]
 result.append(("bop", *counts, prev))
 i += 44
 elif op == 140:
 result.append(("eop",))
 elif op == 141:
 result.append(("push",))
 elif op == 142:
 result.append(("pop",))
 elif 143 <= op <= 146:
 # right1-right4
 nbytes = op - 142
 val = int.from_bytes(data[i:i + nbytes], "big", signed=True)
 result.append(("right", val))
 i += nbytes
 elif 157 <= op <= 160:
 # down1-down4
 nbytes = op - 156
 val = int.from_bytes(data[i:i + nbytes], "big", signed=True)
 result.append(("down", val))
 i += nbytes
 elif 171 <= op <= 234:
 result.append(("fnt_num", op - 171))
 elif op == 235:
 result.append(("fnt1", data[i]))
 i += 1
 elif 239 <= op <= 242:
 # xxx1-xxx4
 nbytes = op - 238
 length = int.from_bytes(data[i:i + nbytes], "big")
 result.append(("xxx", data[i + nbytes:i + nbytes + length]))
 i += nbytes + length
 elif op == 243:
 # fnt_def1: k(1) c(4) s(4) d(4) a(1) l(1) name(a+l)
 k = data[i]
 c, s, d = struct.unpack_from(">III", data, i + 1)
 a = data[i + 13]
 l_ = data[i + 14]
 name = data[i + 15 + a:i + 15 + a + l_]
 result.append(("fnt_def1", k, c, s, d, a, l_, name))
 i += 15 + a + l_
 elif op == 247:
 # pre: i(1) num(4) den(4) mag(4) k(1) comment(k)
 id_ = data[i]
 num, den, mag = struct.unpack_from(">III", data, i + 1)
 k = data[i + 13]
 comment = data[i + 14:i + 14 + k]
 result.append(("pre", id_, num, den, mag, comment))
 i += 14 + k
 elif op == 248:
 # post: p(4) num(4) den(4) mag(4) l(4) u(4) s(2) t(2)
 p, num, den, mag, l_, u, s, t = struct.unpack_from(">IIIIIIhh", data, i)
 result.append(("post", p, num, den, mag, l_, u, s, t))
 i += 28
 elif op == 249:
 # post_post: q(4) i(1) then 223s
 q = struct.unpack_from(">I", data, i)[0]
 id_ = data[i + 4]
 result.append(("post_post", q, id_))
 # remainder is padding 223s — stop parsing
 break
 else:
 result.append((op,))
 return result


# ---------------------------------------------------------------------------
# Tests: preamble
# ---------------------------------------------------------------------------

def test_preamble_valid():
 writer, _buf = _make_writer()
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 pre = opcodes[0]
 assert pre[0] == "pre"
 assert pre[1] == 2 # id byte
 assert pre[2] == 25400000 # num
 assert pre[3] == 473628672 # den
 assert pre[4] == 1000 # mag


# ---------------------------------------------------------------------------
# Tests: single-page shipout
# ---------------------------------------------------------------------------

def test_shipout_single_char_bop_eop():
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 metrics = mgr.get_metrics("tenrm")
 hbox = _make_char_hbox("H", "tenrm", metrics)
 page = _make_page_with_hbox(hbox)
 writer.shipout(1, page)
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 op_names = [o[0] for o in opcodes]
 assert "bop" in op_names
 assert "eop" in op_names


def test_fnt_def_before_bop():
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 metrics = mgr.get_metrics("tenrm")
 hbox = _make_char_hbox("A", "tenrm", metrics)
 writer.shipout(1, _make_page_with_hbox(hbox))
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 fnt_def_idx = next(i for i, o in enumerate(opcodes) if o[0] == "fnt_def1")
 bop_idx = next(i for i, o in enumerate(opcodes) if o[0] == "bop")
 assert fnt_def_idx < bop_idx


def test_fnt_def_in_postamble():
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 metrics = mgr.get_metrics("tenrm")
 hbox = _make_char_hbox("A", "tenrm", metrics)
 writer.shipout(1, _make_page_with_hbox(hbox))
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 # Find post opcode then look for fnt_def1 after it.
 post_idx = next(i for i, o in enumerate(opcodes) if o[0] == "post")
 post_fnt_defs = [o for o in opcodes[post_idx:] if o[0] == "fnt_def1"]
 assert len(post_fnt_defs) >= 1


def test_set_char_opcode_for_ascii():
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 metrics = mgr.get_metrics("tenrm")
 hbox = _make_char_hbox("H", "tenrm", metrics) # ord('H') == 72
 writer.shipout(1, _make_page_with_hbox(hbox))
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 set_chars = [o for o in opcodes if o[0] == "set_char" and o[1] == ord("H")]
 assert len(set_chars) >= 1


def test_set1_opcode_for_high_char():
 """CharNode with char code 200 → opcode 128 (set1) then byte 200."""
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 # Build an hbox with a high char manually (won't have valid metrics but that's ok for opcode test).
 node = CharNode(char=200, font_name="tenrm")
 hbox = HlistNode(
 list=[node],
 width=0,
 height=100000,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 page = _make_page_with_hbox(hbox)
 writer.shipout(1, page)
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 set1_ops = [o for o in opcodes if o[0] == "set1" and o[1] == 200]
 assert len(set1_ops) >= 1


def test_right_movement_emitted():
 """KernNode(width=65536) before a CharNode → right command before set_char."""
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 kern = KernNode(width=65536, explicit=True)
 char_node = CharNode(char=ord("A"), font_name="tenrm")
 hbox = HlistNode(
 list=[kern, char_node],
 width=65536 + 100000,
 height=100000,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer.shipout(1, _make_page_with_hbox(hbox))
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 op_names = [o[0] for o in opcodes]
 # There should be a right command in the stream.
 assert "right" in op_names


def test_bop_page_counter():
 """Two pages: first BOP counts[0]=1, second BOP counts[0]=2."""
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 writer.shipout(1, _make_empty_vlist())
 writer.shipout(2, _make_empty_vlist())
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 bops = [o for o in opcodes if o[0] == "bop"]
 assert len(bops) == 2
 # counts[0] is the page_number argument (index 1 in tuple after opcode name)
 assert bops[0][1] == 1
 assert bops[1][1] == 2


def test_bop_prev_pointer():
 """Second BOP prev field == byte offset of first BOP."""
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 writer.shipout(1, _make_empty_vlist())
 writer.shipout(2, _make_empty_vlist())
 writer.finalize()
 data = writer.get_bytes()

 # Find raw offsets of BOP opcodes (opcode 139).
 bop_offsets = [i for i, b in enumerate(data) if b == 139]
 assert len(bop_offsets) >= 2

 # Second BOP prev field is at bop_offsets[1] + 1 + 40 bytes (counts) = bop_offsets[1] + 41
 prev_field_offset = bop_offsets[1] + 1 + 40
 prev_value = struct.unpack_from(">i", data, prev_field_offset)[0]
 assert prev_value == bop_offsets[0]


def test_eop_after_each_page():
 """Two pages shipped → two eop(140) opcodes."""
 writer, _buf = _make_writer()
 writer.shipout(1, _make_empty_vlist())
 writer.shipout(2, _make_empty_vlist())
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 eops = [o for o in opcodes if o[0] == "eop"]
 assert len(eops) == 2


def test_push_pop_balanced():
 """Every push(141) has a matching pop(142)."""
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 metrics = mgr.get_metrics("tenrm")
 hbox = _make_char_hbox("Hi", "tenrm", metrics)
 writer.shipout(1, _make_page_with_hbox(hbox))
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 pushes = sum(1 for o in opcodes if o[0] == "push")
 pops = sum(1 for o in opcodes if o[0] == "pop")
 assert pushes == pops
 assert pushes > 0


def test_rule_node_set_rule_opcode():
 """RuleNode in hlist → opcode 132 (set_rule) with height and width fields."""
 writer, _buf = _make_writer()
 rule = RuleNode(width=65536 * 72, height=26214, depth=0)
 hbox = HlistNode(
 list=[rule],
 width=65536 * 72,
 height=26214,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer.shipout(1, _make_page_with_hbox(hbox))
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 set_rules = [o for o in opcodes if o[0] == "set_rule"]
 assert len(set_rules) >= 1
 # height field = height + depth = 26214 + 0
 assert set_rules[0][1] == 26214
 assert set_rules[0][2] == 65536 * 72


def test_postamble_post_opcode():
 """After finalize, opcode 248 (post) appears after all eop commands."""
 writer, _buf = _make_writer()
 writer.shipout(1, _make_empty_vlist())
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 op_names = [o[0] for o in opcodes]
 eop_idx = max(i for i, n in enumerate(op_names) if n == "eop")
 post_idx = next(i for i, n in enumerate(op_names) if n == "post")
 assert post_idx > eop_idx


def test_postamble_page_count():
 """Post field t (total pages) == number of shipout calls."""
 writer, _buf = _make_writer()
 writer.shipout(1, _make_empty_vlist())
 writer.shipout(2, _make_empty_vlist())
 writer.shipout(3, _make_empty_vlist())
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 post = next(o for o in opcodes if o[0] == "post")
 # post tuple: ("post", p, num, den, mag, l_, u, s, t)
 t = post[8]
 assert t == 3


def test_postamble_post_post():
 """Opcode 249 follows postamble font defs; id byte == 2; ends with ≥4 x 223."""
 writer, _buf = _make_writer()
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 post_post = next((o for o in opcodes if o[0] == "post_post"), None)
 assert post_post is not None
 assert post_post[2] == 2 # id byte
 # Count trailing 223 bytes in raw data.
 n_pad = 0
 for b in reversed(data):
 if b == 223:
 n_pad += 1
 else:
 break
 assert n_pad >= 4


def test_file_and_memory_identical(tmp_path):
 """Writing the same content to Path and BytesIO produces identical DVI bytes."""
 mgr = _make_mgr_with_cmr10()
 metrics = mgr.get_metrics("tenrm")
 hbox = _make_char_hbox("Hi", "tenrm", metrics)
 page = _make_page_with_hbox(hbox)

 # Memory writer.
 buf = io.BytesIO()
 w_mem = DviWriter(buf, font_manager=mgr)
 w_mem.shipout(1, page)
 w_mem.finalize()
 mem_bytes = w_mem.get_bytes()

 # File writer.
 out_file = tmp_path / "out.dvi"
 w_file = DviWriter(out_file, font_manager=mgr)
 w_file.shipout(1, page)
 w_file.finalize()
 file_bytes = out_file.read_bytes()

 assert mem_bytes == file_bytes


def test_whatsit_xxx1_emitted():
 """WhatsitNode(data=b"test") → opcode 239, length=4, then b"test"."""
 writer, _buf = _make_writer()
 whatsit = WhatsitNode(data=b"test")
 hbox = HlistNode(
 list=[whatsit],
 width=0,
 height=0,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer.shipout(1, _make_page_with_hbox(hbox))
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 xxx_ops = [o for o in opcodes if o[0] == "xxx"]
 assert len(xxx_ops) >= 1
 assert xxx_ops[0][1] == b"test"


def test_multipage_max_height_tracked():
 """Two pages with different heights → post.l == max of the two."""
 writer, _buf = _make_writer()
 page1 = VlistNode(
 list=[], width=0, height=100000, depth=0, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 page2 = VlistNode(
 list=[], width=0, height=200000, depth=0, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 writer.shipout(1, page1)
 writer.shipout(2, page2)
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 post = next(o for o in opcodes if o[0] == "post")
 # post.l is the max page height+depth (index 5 in the tuple)
 assert post[5] == 200000


def test_max_stack_depth_tracked():
 """Page with 3-level nested boxes → post.s (stack depth) == 3 exactly."""
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)

 # Build 3-level nesting: vbox → hbox → hbox (nested)
 inner_hbox = HlistNode(
 list=[CharNode(char=ord("A"), font_name="tenrm")],
 width=100000, height=50000, depth=10000, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 outer_hbox = HlistNode(
 list=[inner_hbox],
 width=100000, height=50000, depth=10000, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 page = _make_page_with_hbox(outer_hbox)
 writer.shipout(1, page)
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 post = next(o for o in opcodes if o[0] == "post")
 # post.s is max stack depth (index 7 in tuple): outer push=1, hbox=2, inner hbox=3
 assert post[7] == 3


def test_max_stack_depth_one_hbox_page():
 """AC-1: single-hbox page → post.s == 2, not 3."""
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 hbox = HlistNode(
 list=[CharNode(char=ord("A"), font_name="tenrm")],
 width=100000, height=50000, depth=10000, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 page = _make_page_with_hbox(hbox)
 writer.shipout(1, page)
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 post = next(o for o in opcodes if o[0] == "post")
 # outer push=1, hbox push=2 → max stack depth == 2
 assert post[7] == 2


def test_get_bytes_before_finalize_raises():
 writer, _buf = _make_writer()
 with pytest.raises(RuntimeError, match="finalize"):
 writer.get_bytes()


def test_double_finalize_raises():
 writer, _buf = _make_writer()
 writer.finalize()
 with pytest.raises(RuntimeError, match="already called"):
 writer.finalize()


def test_unknown_font_raises():
 """CharNode with unknown font_name → FontError."""
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 node = CharNode(char=ord("A"), font_name="unknownfont")
 hbox = HlistNode(
 list=[node],
 width=0, height=0, depth=0, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 page = _make_page_with_hbox(hbox)
 with pytest.raises(FontError):
 writer.shipout(1, page)


def test_glue_node_in_hlist_lazy_movement():
 """GlueNode followed by CharNode → right command covers accumulated movement."""
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 glue = GlueNode(glue=Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
 char_node = CharNode(char=ord("A"), font_name="tenrm")
 hbox = HlistNode(
 list=[glue, char_node],
 width=65536 + 100000,
 height=100000,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer.shipout(1, _make_page_with_hbox(hbox))
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 # A right command should appear to move over the glue.
 assert any(o[0] == "right" for o in opcodes)


def test_vlist_down_movement():
 """VlistNode with two hboxes → down commands between them equal heights+depths."""
 mgr = _make_mgr_with_cmr10()
 writer, _buf = _make_writer(mgr)
 h1 = HlistNode(
 list=[],
 width=0, height=100000, depth=20000, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 h2 = HlistNode(
 list=[],
 width=0, height=80000, depth=10000, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 page = VlistNode(
 list=[h1, h2],
 width=0, height=200000, depth=10000, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 writer.shipout(1, page)
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 down_ops = [o for o in opcodes if o[0] == "down"]
 assert len(down_ops) >= 1


def test_vlist_rule_running_width_resolves_to_parent():
 """/: a vlist \\hrule with width==RUNNING_DIMEN emits the
 parent's concrete width, not the -2^30 running-dimension sentinel.

 Mirrors the hlist arm + PDF/SVG vlist arms. ``walk_rules`` returns
 ``(h, v, height, width)`` per set_rule; the width field must equal the
 enclosing page box's concrete width.
 """
 writer, _buf = _make_writer()
 page_width = 30785886 # concrete \hsize (default 6.5in in sp)
 rule = RuleNode(width=RUNNING_DIMEN, height=26214, depth=0) # 0.4pt \hrule
 page = VlistNode(
 list=[rule],
 width=page_width,
 height=26214,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer.shipout(1, page)
 writer.finalize()
 rules = walk_rules(writer.get_bytes())
 assert len(rules) == 1 and len(rules[0]) == 1
 _h, _v, height, width = rules[0][0]
 assert width == page_width
 assert width != RUNNING_DIMEN
 assert height == 26214 # height + depth, depth==0


def test_vlist_rule_running_height_resolves_to_parent():
 """/: locks "resolve all three" — a \\vrule-style RuleNode
 with height==RUNNING_DIMEN inside a vlist resolves to ``parent.height``.

 set_rule's height operand is ``height + depth``; with a running height
 resolving to the parent height and depth 0, it must equal parent.height.
 """
 writer, _buf = _make_writer()
 page_height = 7654321 # arbitrary concrete height in sp
 rule = RuleNode(width=65536, height=RUNNING_DIMEN, depth=0)
 page = VlistNode(
 list=[rule],
 width=65536,
 height=page_height,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer.shipout(1, page)
 writer.finalize()
 rules = walk_rules(writer.get_bytes())
 assert len(rules) == 1 and len(rules[0]) == 1
 _h, _v, height, width = rules[0][0]
 assert height == page_height # resolved from RUNNING_DIMEN
 assert height != RUNNING_DIMEN
 assert width == 65536


def test_zero_width_rule_suppressed_in_hlist():
 """/: a zero-width \\strut RuleNode in an hlist emits no
 set_rule (TeX §622 paints only when width>0 and height+depth>0), while
 the surrounding content keeps its position.

 Models ``\\strut`` = ``\\hbox{\\vrule height8.5pt depth3.5pt width\\z@}``:
 width 0, height+depth 12pt. A char placed after it lands at the same h as
 if the strut were absent (the strut advances h by 0).
 """
 mgr = _make_mgr_with_cmr10()
 metrics = mgr.get_metrics("tenrm")
 strut = RuleNode(width=0, height=8 * 65536 + 32768, depth=3 * 65536 + 32768)
 char = CharNode(char=ord("A"), font_name="tenrm")
 a_width = metrics.char_metrics(ord("A")).width
 hbox = HlistNode(
 list=[strut, char],
 width=a_width,
 height=8 * 65536 + 32768,
 depth=3 * 65536 + 32768,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer, _buf = _make_writer(mgr)
 writer.shipout(1, _make_page_with_hbox(hbox))
 writer.finalize()
 data = writer.get_bytes()
 opcodes = _parse_dvi_opcodes(data)
 # No set_rule for the zero-width strut.
 assert [o for o in opcodes if o[0] == "set_rule"] == []
 # The char is still shipped; no spurious 'right' was forced by the strut
 # (it advanced h by 0), so the char sits at the box origin.
 rights = [o for o in opcodes if o[0] == "right"]
 assert all(o[1] == 0 for o in rights), f"unexpected horizontal shift: {rights}"
 assert any(o[0] == "set_char" and o[1] == ord("A") for o in opcodes)


def test_zero_height_rule_suppressed_but_advances_reference_point():
 """/: a zero-height (height+depth==0) positive-width rule in
 an hlist emits no set_rule, but the reference point still advances by the
 rule width — the case ``width==0`` cannot exercise.

 A char placed after a 72pt-wide, zero-height rule must be shifted right by
 that width (TeX §622: a non-painting rule advances h by rule_wd).
 """
 mgr = _make_mgr_with_cmr10()
 rule_width = 65536 * 72
 rule = RuleNode(width=rule_width, height=0, depth=0)
 char = CharNode(char=ord("A"), font_name="tenrm")
 a_width = mgr.get_metrics("tenrm").char_metrics(ord("A")).width
 hbox = HlistNode(
 list=[rule, char],
 width=rule_width + a_width,
 height=0,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer, _buf = _make_writer(mgr)
 writer.shipout(1, _make_page_with_hbox(hbox))
 writer.finalize()
 opcodes = _parse_dvi_opcodes(writer.get_bytes())
 assert [o for o in opcodes if o[0] == "set_rule"] == []
 # The char is reached by a single 'right' of exactly the rule width.
 rights = [o for o in opcodes if o[0] == "right"]
 assert any(o[1] == rule_width for o in rights), (
 f"expected a right-shift of {rule_width} sp for the suppressed rule; "
 f"got {rights}"
 )


def test_painting_rule_still_emitted():
 """/ regression guard: a real \\footnoterule-shaped rule
 (positive width AND height) is still emitted exactly once with its
 dimensions intact — the guard must not over-suppress visible rules.
 """
 writer, _buf = _make_writer()
 rule = RuleNode(width=65536 * 144, height=26214, depth=0) # 0.4pt x 144pt
 hbox = HlistNode(
 list=[rule],
 width=65536 * 144,
 height=26214,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer.shipout(1, _make_page_with_hbox(hbox))
 writer.finalize()
 opcodes = _parse_dvi_opcodes(writer.get_bytes())
 set_rules = [o for o in opcodes if o[0] == "set_rule"]
 assert len(set_rules) == 1
 assert set_rules[0][1] == 26214 # height + depth
 assert set_rules[0][2] == 65536 * 144 # width


def test_zero_width_rule_suppressed_in_vlist():
 """/: a zero-width RuleNode in a vlist emits no set_rule,
 but v advances by height+depth so the following box lands unchanged
 (TeX §634).

 A char hbox placed after a zero-width 12pt-tall rule must sit 12pt lower
 than the page top, exactly as if the rule painted.
 """
 mgr = _make_mgr_with_cmr10()
 metrics = mgr.get_metrics("tenrm")
 strut = RuleNode(width=0, height=8 * 65536 + 32768, depth=3 * 65536 + 32768)
 strut_total = (8 * 65536 + 32768) + (3 * 65536 + 32768) # 12pt
 char_hbox = _make_char_hbox("A", "tenrm", metrics)
 page = VlistNode(
 list=[strut, char_hbox],
 width=char_hbox.width,
 height=strut_total + char_hbox.height,
 depth=char_hbox.depth,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer, _buf = _make_writer(mgr)
 writer.shipout(1, page)
 writer.finalize()
 opcodes = _parse_dvi_opcodes(writer.get_bytes())
 # No set_rule for the zero-width strut.
 assert [o for o in opcodes if o[0] == "set_rule"] == []
 # The reference point still advanced: the char hbox is reached by 'down'
 # movements summing to the strut total + the char's own height.
 downs = [o[1] for o in opcodes if o[0] == "down"]
 assert sum(downs) == strut_total + char_hbox.height, (
 f"v-advance {sum(downs)} != expected {strut_total + char_hbox.height}"
 )


def test_vlist_rule_emits_put_rule_no_h_advance():
 """/: a painting RuleNode in a vlist ships ``put_rule`` (137),
 not ``set_rule`` (132), and does NOT advance the horizontal reference point.

 Per TeX:The Program §624 (``vlist_out``) a vertically placed rule paints
 without moving h. A char hbox placed after the rule must land at the box
 origin (h=0): the only ``right`` movements emitted are zero. set_rule (132)
 would have advanced the DVI h register by the full rule width (~469pt),
 shifting the following material right in strict DVI viewers (Yap).
 """
 mgr = _make_mgr_with_cmr10()
 metrics = mgr.get_metrics("tenrm")
 rule_width = 65536 * 144 # 144pt — a wide \hrule
 rule = RuleNode(width=rule_width, height=26214, depth=0) # 0.4pt x 144pt
 char_hbox = _make_char_hbox("A", "tenrm", metrics)
 page = VlistNode(
 list=[rule, char_hbox],
 width=rule_width,
 height=26214 + char_hbox.height,
 depth=char_hbox.depth,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer, _buf = _make_writer(mgr)
 writer.shipout(1, page)
 writer.finalize()
 opcodes = _parse_dvi_opcodes(writer.get_bytes())
 # The vlist rule ships as put_rule (137), never set_rule (132).
 put_rules = [o for o in opcodes if o[0] == "put_rule"]
 assert len(put_rules) == 1, f"expected exactly one put_rule, got {opcodes}"
 assert put_rules[0][1] == 26214 # height + depth
 assert put_rules[0][2] == rule_width # width
 assert [o for o in opcodes if o[0] == "set_rule"] == []
 # The reference point did NOT advance horizontally: every 'right' is zero
 # (the following char hbox sits at the box origin h=0).
 rights = [o for o in opcodes if o[0] == "right"]
 assert all(o[1] == 0 for o in rights), (
 f"vlist rule must not advance h; unexpected horizontal shift: {rights}"
 )


def test_hlist_rule_emits_set_rule_and_advances_h():
 """/ regression pin for the §622/§624 distinction: a rule in
 an *hlist* still ships ``set_rule`` (132) and DOES advance the reference
 point by the rule width (the complement of the vlist ``put_rule`` rule).

 A char placed after a 72pt-wide rule is reached by a single ``right`` of
 exactly the rule width — confirming the hlist arm is untouched by the fix.
 """
 mgr = _make_mgr_with_cmr10()
 rule_width = 65536 * 72
 rule = RuleNode(width=rule_width, height=26214, depth=0)
 char = CharNode(char=ord("A"), font_name="tenrm")
 a_width = mgr.get_metrics("tenrm").char_metrics(ord("A")).width
 hbox = HlistNode(
 list=[rule, char],
 width=rule_width + a_width,
 height=26214,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer, _buf = _make_writer(mgr)
 writer.shipout(1, _make_page_with_hbox(hbox))
 writer.finalize()
 opcodes = _parse_dvi_opcodes(writer.get_bytes())
 # The hlist rule ships as set_rule (132), never put_rule (137).
 set_rules = [o for o in opcodes if o[0] == "set_rule"]
 assert len(set_rules) == 1, f"expected exactly one set_rule, got {opcodes}"
 assert set_rules[0][2] == rule_width
 assert [o for o in opcodes if o[0] == "put_rule"] == []
 # set_rule advances h by its width: the following char is reached without
 # any additional 'right' of the rule width (the rule itself moved h).
 rights = [o for o in opcodes if o[0] == "right"]
 assert all(o[1] != rule_width for o in rights), (
 f"hlist set_rule already advanced h; no extra right of {rule_width} "
 f"expected, got {rights}"
 )


def test_vlist_running_width_rule_ships_put_rule():
 """/ + : a full-\\hsize vlist \\hrule (width ==
 RUNNING_DIMEN) resolves to the parent width AND ships ``put_rule`` (137).

 Locks the interaction of the two fixes: the RUNNING_DIMEN resolution
 runs first, then the resolved rule is emitted with put_rule, not
 set_rule.
 """
 writer, _buf = _make_writer()
 page_width = 30785886 # concrete \hsize
 rule = RuleNode(width=RUNNING_DIMEN, height=26214, depth=0)
 page = VlistNode(
 list=[rule],
 width=page_width,
 height=26214,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer.shipout(1, page)
 writer.finalize()
 opcodes = _parse_dvi_opcodes(writer.get_bytes())
 put_rules = [o for o in opcodes if o[0] == "put_rule"]
 assert len(put_rules) == 1
 assert put_rules[0][2] == page_width # RUNNING_DIMEN resolved to parent
 assert put_rules[0][2] != RUNNING_DIMEN
 assert [o for o in opcodes if o[0] == "set_rule"] == []


def test_vlist_non_painting_rule_emits_no_opcode():
 """/ + : a zero-width vlist rule emits neither
 set_rule (132) nor put_rule (137); v still advances by height+depth.

 Confirms the put_rule change is orthogonal to the §622/§634 painting guard
 — a non-painting rule is suppressed entirely, regardless of opcode class.
 """
 mgr = _make_mgr_with_cmr10()
 metrics = mgr.get_metrics("tenrm")
 strut = RuleNode(width=0, height=8 * 65536 + 32768, depth=3 * 65536 + 32768)
 strut_total = (8 * 65536 + 32768) + (3 * 65536 + 32768) # 12pt
 char_hbox = _make_char_hbox("A", "tenrm", metrics)
 page = VlistNode(
 list=[strut, char_hbox],
 width=char_hbox.width,
 height=strut_total + char_hbox.height,
 depth=char_hbox.depth,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 writer, _buf = _make_writer(mgr)
 writer.shipout(1, page)
 writer.finalize()
 opcodes = _parse_dvi_opcodes(writer.get_bytes())
 assert [o for o in opcodes if o[0] in ("set_rule", "put_rule")] == []
 downs = [o[1] for o in opcodes if o[0] == "down"]
 assert sum(downs) == strut_total + char_hbox.height


def test_shipout_after_finalize_raises():
 writer, _buf = _make_writer()
 writer.finalize()
 with pytest.raises(RuntimeError, match="finalize"):
 writer.shipout(1, _make_empty_vlist())


def test_get_bytes_on_file_destination_raises(tmp_path):
 """get_bytes() raises RuntimeError when destination is a Path."""
 mgr = _make_mgr_with_cmr10()
 out_file = tmp_path / "out.dvi"
 writer = DviWriter(out_file, font_manager=mgr)
 writer.finalize()
 with pytest.raises(RuntimeError, match="in-memory"):
 writer.get_bytes()
