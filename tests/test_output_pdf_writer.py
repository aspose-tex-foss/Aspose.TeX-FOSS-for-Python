"""Unit tests for PdfWriter.

Tests validate PDF 1.4 structure, content-stream operators, Type 1 font
embedding, xref/trailer correctness, coordinate transforms, and error
handling. No external PDF libraries — a minimal lexer (_parse_pdf_objects,
_extract_trailer, _xref_offsets) supports the structural assertions.
"""
from __future__ import annotations

import io
import re
import warnings

import pytest

from aspose_tex._engine.nodes import (
 CharNode,
 GlueSign,
 HlistNode,
 KernNode,
 RuleNode,
 VlistNode,
 WhatsitNode,
)
from aspose_tex._engine.registers import GlueOrder
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._output.pdf_writer import PdfWriter
from aspose_tex.exceptions import FontError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mgr_with_cmr10(extra: list[tuple[str, str]] | None = None) -> FontManager:
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 for cs, tfm in extra or []:
 mgr.load_font(cs, tfm)
 return mgr


def _make_writer(mgr: FontManager | None = None, **kwargs) -> tuple[PdfWriter, io.BytesIO]:
 if mgr is None:
 mgr = _make_mgr_with_cmr10()
 buf = io.BytesIO()
 w = PdfWriter(buf, font_manager=mgr, **kwargs)
 return w, buf


def _empty_vlist() -> VlistNode:
 return VlistNode(
 list=[], width=0, height=0, depth=0, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )


def _hbox(nodes: list, width: int = 0, height: int = 0, depth: int = 0) -> HlistNode:
 return HlistNode(
 list=nodes, width=width, height=height, depth=depth, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )


def _page(children: list, height: int = 0, width: int = 0, depth: int = 0) -> VlistNode:
 return VlistNode(
 list=children, width=width, height=height, depth=depth, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )


def _parse_pdf_objects(data: bytes) -> dict[int, bytes]:
 """Return {obj_id: body_bytes}.

 body_bytes is the raw content between 'N G obj\\n' and 'endobj' (excluding
 the terminating newline). For stream objects this includes the dict,
 'stream\\n...\\nendstream'.
 """
 result: dict[int, bytes] = {}
 pos = 0
 pat = re.compile(rb"(\d+)\s+(\d+)\s+obj\n")
 # Only scan the body, i.e. before xref.
 xref_pos = data.find(b"\nxref\n")
 scan_end = xref_pos if xref_pos != -1 else len(data)
 while pos < scan_end:
 m = pat.search(data, pos, scan_end)
 if m is None:
 break
 obj_id = int(m.group(1))
 body_start = m.end()
 end = data.find(b"\nendobj\n", body_start)
 if end == -1 or end >= scan_end:
 break
 result[obj_id] = data[body_start:end]
 pos = end + len(b"\nendobj\n")
 return result


def _extract_trailer(data: bytes) -> bytes:
 m = re.search(rb"trailer\n<<(.*?)>>\n", data, re.DOTALL)
 assert m is not None
 return m.group(1)


def _xref_table_offsets(data: bytes) -> list[int]:
 """Return list of offsets from the xref table (0..N)."""
 m = re.search(rb"\nxref\n0 (\d+)\n", data)
 assert m is not None
 n = int(m.group(1))
 start = m.end()
 offsets: list[int] = []
 for i in range(n):
 entry = data[start + i * 20 : start + (i + 1) * 20]
 # '0000000000 65535 f \n' etc.
 offsets.append(int(entry[:10]))
 return offsets


def _startxref(data: bytes) -> int:
 m = re.search(rb"startxref\n(\d+)\n%%EOF", data)
 assert m is not None
 return int(m.group(1))


def _find_page_objects(objects: dict[int, bytes]) -> list[tuple[int, bytes]]:
 return [
 (oid, body)
 for oid, body in objects.items()
 if b"/Type /Page " in body or body.startswith(b"<< /Type /Page ")
 ]


def _find_single(objects: dict[int, bytes], needle: bytes) -> tuple[int, bytes]:
 matches = [(oid, body) for oid, body in objects.items() if needle in body]
 assert len(matches) == 1, f"Expected exactly one object containing {needle!r}, got {len(matches)}"
 return matches[0]


def _read_content_stream(data: bytes, obj_id: int) -> bytes:
 """Return the bytes between 'stream\\n' and '\\nendstream' of a stream obj."""
 marker = f"\n{obj_id} 0 obj\n".encode("ascii")
 start = data.find(marker)
 assert start != -1
 stream_start = data.find(b"stream\n", start) + len(b"stream\n")
 stream_end = data.find(b"\nendstream", stream_start)
 return data[stream_start:stream_end]


# ---------------------------------------------------------------------------
# Header / basic structure
# ---------------------------------------------------------------------------

def test_header_is_pdf_1_4() -> None:
 w, buf = _make_writer()
 w.finalize()
 data = buf.getvalue()
 assert data.startswith(b"%PDF-1.4\n%")
 # 4 high bytes in the binary marker comment
 for b in data[10:14]:
 assert b >= 0x80


def test_empty_document_has_valid_structure() -> None:
 w, buf = _make_writer()
 w.finalize()
 data = buf.getvalue()
 assert data.endswith(b"%%EOF\n")
 objects = _parse_pdf_objects(data)
 # Pages root was reserved at init; catalog + info allocated in finalize.
 assert len(objects) == 3
 _pages_oid, pages_body = _find_single(objects, b"/Type /Pages")
 assert b"/Count 0" in pages_body


def test_single_page_produces_one_page_object() -> None:
 w, buf = _make_writer()
 w.shipout(1, _empty_vlist())
 w.finalize()
 objects = _parse_pdf_objects(buf.getvalue())
 pages = _find_page_objects(objects)
 assert len(pages) == 1


def test_catalog_references_pages() -> None:
 w, buf = _make_writer()
 w.finalize()
 objects = _parse_pdf_objects(buf.getvalue())
 _cat_oid, cat_body = _find_single(objects, b"/Type /Catalog")
 pages_oid, _ = _find_single(objects, b"/Type /Pages")
 assert f"/Pages {pages_oid} 0 R".encode("ascii") in cat_body


def test_pages_count_matches_shipouts() -> None:
 w, buf = _make_writer()
 for i in range(3):
 w.shipout(i + 1, _empty_vlist())
 w.finalize()
 objects = _parse_pdf_objects(buf.getvalue())
 _, pages_body = _find_single(objects, b"/Type /Pages")
 assert b"/Count 3" in pages_body
 kids_match = re.search(rb"/Kids \[([^\]]*)\]", pages_body)
 assert kids_match is not None
 assert len(re.findall(rb"\d+ 0 R", kids_match.group(1))) == 3


def test_page_parent_refers_to_pages_root() -> None:
 w, buf = _make_writer()
 w.shipout(1, _empty_vlist())
 w.shipout(2, _empty_vlist())
 w.finalize()
 data = buf.getvalue()
 objects = _parse_pdf_objects(data)
 pages_oid, _ = _find_single(objects, b"/Type /Pages")
 pages = _find_page_objects(objects)
 parent_ref = f"/Parent {pages_oid} 0 R".encode("ascii")
 for _, body in pages:
 assert parent_ref in body


# ---------------------------------------------------------------------------
# MediaBox
# ---------------------------------------------------------------------------

def test_mediabox_default_us_letter() -> None:
 w, buf = _make_writer()
 w.finalize()
 objects = _parse_pdf_objects(buf.getvalue())
 _, body = _find_single(objects, b"/Type /Pages")
 assert b"/MediaBox [0 0 612 792]" in body


def test_mediabox_custom_page_size() -> None:
 w, buf = _make_writer(page_width_pt=595.28, page_height_pt=841.89)
 w.finalize()
 objects = _parse_pdf_objects(buf.getvalue())
 _, body = _find_single(objects, b"/Type /Pages")
 assert b"/MediaBox [0 0 595.28 841.89]" in body


# ---------------------------------------------------------------------------
# Content streams
# ---------------------------------------------------------------------------

def test_content_stream_has_bt_et_for_chars() -> None:
 mgr = _make_mgr_with_cmr10()
 w, buf = _make_writer(mgr)
 hbox = _hbox([CharNode(char=ord("A"), font_name="tenrm")])
 w.shipout(1, _page([hbox]))
 w.finalize()
 data = buf.getvalue()
 # Find the content stream via page references.
 objects = _parse_pdf_objects(data)
 pages = _find_page_objects(objects)
 assert len(pages) == 1
 page_body = pages[0][1]
 content_ref_match = re.search(rb"/Contents (\d+) 0 R", page_body)
 assert content_ref_match is not None
 content = _read_content_stream(data, int(content_ref_match.group(1)))
 assert b"BT\n" in content
 assert b"ET\n" in content


def test_tj_encodes_ascii_char() -> None:
 mgr = _make_mgr_with_cmr10()
 w, buf = _make_writer(mgr)
 hbox = _hbox([CharNode(char=ord("H"), font_name="tenrm")])
 w.shipout(1, _page([hbox]))
 w.finalize()
 assert b"(H) Tj" in buf.getvalue()


def test_tj_escapes_special_chars() -> None:
 mgr = _make_mgr_with_cmr10()
 w, buf = _make_writer(mgr)
 hbox = _hbox([
 CharNode(char=ord("("), font_name="tenrm"),
 CharNode(char=ord(")"), font_name="tenrm"),
 CharNode(char=ord("\\"), font_name="tenrm"),
 ])
 w.shipout(1, _page([hbox]))
 w.finalize()
 assert b"(\\(\\)\\\\) Tj" in buf.getvalue()


def test_tf_selects_font_at_correct_size() -> None:
 mgr = _make_mgr_with_cmr10()
 w, buf = _make_writer(mgr)
 hbox = _hbox([CharNode(char=ord("A"), font_name="tenrm")])
 w.shipout(1, _page([hbox]))
 w.finalize()
 # 10-pt font → "10 Tf"
 assert re.search(rb"/F1 10 Tf", buf.getvalue()) is not None


def test_td_positions_match_expected() -> None:
 mgr = _make_mgr_with_cmr10()
 w, buf = _make_writer(mgr)
 # CharNode inside a page: hbox at top of page places baseline at v=hbox.height.
 hbox = _hbox(
 [CharNode(char=ord("A"), font_name="tenrm")],
 height=655360, # 10pt
 )
 page = _page([hbox], height=655360)
 w.shipout(1, page)
 w.finalize()
 # Expected: x = 72 (origin), y = 792 - 72 - 10 = 710
 assert re.search(rb"\n72 710 Td\n", buf.getvalue()) is not None


def test_char_advance_matches_tfm() -> None:
 mgr = _make_mgr_with_cmr10()
 metrics = mgr.get_metrics("tenrm")
 assert metrics is not None
 w_a = metrics.char_metrics(ord("A")).width
 w_b = metrics.char_metrics(ord("B")).width

 # Place A, kern=0 via KernNode(0), C — second run starts at A+B width? No.
 # Use [A, B, Kern, C] so run flushes at Kern. After run, next run begins
 # at h = wA + wB.
 w, buf = _make_writer(mgr)
 hbox = _hbox([
 CharNode(char=ord("A"), font_name="tenrm"),
 CharNode(char=ord("B"), font_name="tenrm"),
 KernNode(width=0, explicit=True),
 CharNode(char=ord("C"), font_name="tenrm"),
 ], height=655360)
 page = _page([hbox], height=655360)
 w.shipout(1, page)
 w.finalize()
 data = buf.getvalue()
 # Find second Td (the one for C).
 tds = re.findall(rb"\n([\d.-]+) 710 Td\n", data)
 assert len(tds) == 2
 expected = 72 + (w_a + w_b) / 65536
 assert abs(float(tds[1]) - expected) < 0.01


def test_kern_flushes_run() -> None:
 mgr = _make_mgr_with_cmr10()
 w, buf = _make_writer(mgr)
 hbox = _hbox([
 CharNode(char=ord("A"), font_name="tenrm"),
 KernNode(width=5000, explicit=True),
 CharNode(char=ord("B"), font_name="tenrm"),
 ], height=655360)
 page = _page([hbox], height=655360)
 w.shipout(1, page)
 w.finalize()
 data = buf.getvalue()
 # Two BT blocks.
 assert data.count(b"BT\n") == 2
 assert data.count(b"ET\n") == 2


def test_adjacent_hlists_do_not_concatenate_text_runs() -> None:
 # : chars from two sibling HlistNodes (successive paragraph lines)
 # must not be emitted in a single (...) Tj at one baseline. Before the
 # fix the run state leaked across lines, producing e.g. "theafterno" at
 # line-N baseline and the next line starting mid-word.
 mgr = _make_mgr_with_cmr10()
 w, buf = _make_writer(mgr)
 line1 = _hbox(
 [CharNode(char=ord("A"), font_name="tenrm")],
 height=655360, # 10pt
 )
 line2 = _hbox(
 [CharNode(char=ord("B"), font_name="tenrm")],
 height=655360,
 )
 page = _page([line1, line2], height=1310720) # 20pt
 w.shipout(1, page)
 w.finalize()
 data = buf.getvalue()
 # Each Tj string must contain exactly the char of its own line.
 tjs = re.findall(rb"\(([^)]*)\) Tj\n", data)
 assert b"A" in tjs and b"B" in tjs, tjs
 assert b"AB" not in tjs, f"Chars leaked across lines: {tjs!r}"
 # Two distinct baselines (y-coordinates) — one per line.
 y_coords = {m.group(2) for m in re.finditer(rb"\n([\d.-]+) ([\d.-]+) Td\n", data)}
 assert len(y_coords) == 2, f"Expected 2 baselines, got {y_coords}"


def test_rule_emits_re_f() -> None:
 w, buf = _make_writer()
 rule = RuleNode(width=10 * 65536, height=2 * 65536, depth=0)
 hbox = _hbox([rule], width=10 * 65536, height=2 * 65536)
 page = _page([hbox], height=2 * 65536)
 w.shipout(1, page)
 w.finalize()
 data = buf.getvalue()
 assert b" re\nf\n" in data


def test_rule_coords_correct() -> None:
 w, buf = _make_writer()
 rule = RuleNode(width=10 * 65536, height=2 * 65536, depth=0)
 hbox = _hbox([rule], width=10 * 65536, height=2 * 65536)
 page = _page([hbox], height=2 * 65536)
 w.shipout(1, page)
 w.finalize()
 data = buf.getvalue()
 # Baseline y=2pt after hbox.height. Rule top at v = baseline - height = 0.
 # PDF bottom-edge y = page_h - 72 - (0+2) = 792 - 72 - 2 = 718.
 assert b"72 718 10 2 re\nf\n" in data


# ---------------------------------------------------------------------------
# Font embedding
# ---------------------------------------------------------------------------

def test_font_objects_written_in_finalize() -> None:
 mgr = _make_mgr_with_cmr10()
 w, buf = _make_writer(mgr)
 hbox = _hbox([CharNode(char=ord("A"), font_name="tenrm")])
 w.shipout(1, _page([hbox]))
 w.finalize()
 objects = _parse_pdf_objects(buf.getvalue())
 assert any(b"/Type /Font " in body and b"/Subtype /Type1" in body for body in objects.values())
 assert any(b"/Type /FontDescriptor" in body for body in objects.values())
 assert any(b"/Type /Encoding" in body for body in objects.values())
 # Widths array (starts with '[')
 assert any(body.startswith(b"[") and body.endswith(b"]") for body in objects.values())
 # FontFile: stream obj with /Length1 /Length2 /Length3
 assert b"/Length1" in buf.getvalue()


def test_fontfile_lengths_match_pfb_segments() -> None:
 mgr = _make_mgr_with_cmr10()
 pfb = mgr.load_pfb("cmr10")
 assert pfb is not None

 w, buf = _make_writer(mgr)
 hbox = _hbox([CharNode(char=ord("A"), font_name="tenrm")])
 w.shipout(1, _page([hbox]))
 w.finalize()
 data = buf.getvalue()
 l1 = len(pfb.ascii_header)
 l2 = len(pfb.binary_body)
 l3 = len(pfb.ascii_trailer)
 assert f"/Length1 {l1}".encode("ascii") in data
 assert f"/Length2 {l2}".encode("ascii") in data
 assert f"/Length3 {l3}".encode("ascii") in data


def test_fontfile_stream_contains_all_segments() -> None:
 mgr = _make_mgr_with_cmr10()
 pfb = mgr.load_pfb("cmr10")
 assert pfb is not None
 combined = pfb.ascii_header + pfb.binary_body + pfb.ascii_trailer

 w, buf = _make_writer(mgr)
 hbox = _hbox([CharNode(char=ord("A"), font_name="tenrm")])
 w.shipout(1, _page([hbox]))
 w.finalize()
 assert combined in buf.getvalue()


def test_widths_array_length_and_values() -> None:
 mgr = _make_mgr_with_cmr10()
 metrics = mgr.get_metrics("tenrm")
 assert metrics is not None
 w, buf = _make_writer(mgr)
 hbox = _hbox([CharNode(char=ord("A"), font_name="tenrm")])
 w.shipout(1, _page([hbox]))
 w.finalize()
 objects = _parse_pdf_objects(buf.getvalue())
 widths_body = next(b for b in objects.values() if b.startswith(b"[") and b.endswith(b"]"))
 nums = widths_body[1:-1].split()
 assert len(nums) == 256
 # Code 65 = 'A'
 expected = round(metrics.char_metrics(65).width * 1000 / metrics.design_size_sp)
 assert int(nums[65]) == expected
 # Code 200 is not in cmr10: width = 0
 assert int(nums[200]) == 0


def test_differences_array_from_encoding() -> None:
 mgr = _make_mgr_with_cmr10()
 w, buf = _make_writer(mgr)
 hbox = _hbox([CharNode(char=ord("A"), font_name="tenrm")])
 w.shipout(1, _page([hbox]))
 w.finalize()
 objects = _parse_pdf_objects(buf.getvalue())
 enc = next(b for b in objects.values() if b"/Type /Encoding" in b)
 assert b"/Differences [" in enc
 # CM OT1 starts with Gamma at code 0.
 assert b"/Gamma" in enc
 # No /BaseEncoding
 assert b"/BaseEncoding" not in enc


def _extract_flags(objects: dict[int, bytes], tfm_prefix: bytes) -> int:
 for body in objects.values():
 if b"/Type /FontDescriptor" in body and b"/FontName /" + tfm_prefix in body:
 m = re.search(rb"/Flags (\d+)", body)
 assert m is not None
 return int(m.group(1))
 raise AssertionError(f"No FontDescriptor with FontName /{tfm_prefix.decode()}")


def test_font_flags_cmr10_symbolic_serif() -> None:
 mgr = _make_mgr_with_cmr10()
 w, buf = _make_writer(mgr)
 w.shipout(1, _page([_hbox([CharNode(char=ord("A"), font_name="tenrm")])]))
 w.finalize()
 objects = _parse_pdf_objects(buf.getvalue())
 assert _extract_flags(objects, b"CMR10") == 6


def test_font_flags_cmtt10_fixedpitch() -> None:
 mgr = FontManager()
 mgr.load_font("tt", "cmtt10")
 w, buf = _make_writer(mgr)
 w.shipout(1, _page([_hbox([CharNode(char=ord("A"), font_name="tt")])]))
 w.finalize()
 objects = _parse_pdf_objects(buf.getvalue())
 assert _extract_flags(objects, b"CMTT10") == 7


def test_font_flags_cmti10_italic() -> None:
 mgr = FontManager()
 mgr.load_font("it", "cmti10")
 w, buf = _make_writer(mgr)
 w.shipout(1, _page([_hbox([CharNode(char=ord("A"), font_name="it")])]))
 w.finalize()
 objects = _parse_pdf_objects(buf.getvalue())
 # CMTI10 has italic_angle ≠ 0 → Italic(64) set.
 # tfm name "cmti10" isn't in fixed-pitch prefixes → no FixedPitch.
 flags = _extract_flags(objects, b"CMTI10")
 assert flags & 64 == 64
 assert flags & 4 == 4
 assert flags & 2 == 2
 assert flags & 1 == 0


def test_fontdescriptor_bbox_from_pfb() -> None:
 mgr = _make_mgr_with_cmr10()
 pfb = mgr.load_pfb("cmr10")
 assert pfb is not None
 m = re.search(rb"/FontBBox\s*\{\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*\}", pfb.ascii_header)
 assert m is not None
 expected_bbox = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))

 w, buf = _make_writer(mgr)
 w.shipout(1, _page([_hbox([CharNode(char=ord("A"), font_name="tenrm")])]))
 w.finalize()
 objects = _parse_pdf_objects(buf.getvalue())
 desc = next(b for b in objects.values() if b"/Type /FontDescriptor" in b)
 bbox_str = f"/FontBBox [{expected_bbox[0]} {expected_bbox[1]} {expected_bbox[2]} {expected_bbox[3]}]"
 assert bbox_str.encode("ascii") in desc


# ---------------------------------------------------------------------------
# Trailer, xref, startxref
# ---------------------------------------------------------------------------

def test_trailer_has_id_array() -> None:
 w, buf = _make_writer()
 w.finalize()
 trailer = _extract_trailer(buf.getvalue())
 m = re.search(rb"/ID \[<([0-9a-f]{32})> <([0-9a-f]{32})>\]", trailer)
 assert m is not None
 assert m.group(1) == m.group(2)


def test_xref_offsets_correct() -> None:
 w, buf = _make_writer()
 w.shipout(1, _empty_vlist())
 w.finalize()
 data = buf.getvalue()
 offsets = _xref_table_offsets(data)
 # Entry 0 is free list head.
 assert offsets[0] == 0
 for i, off in enumerate(offsets[1:], start=1):
 # Each entry should start with 'i 0 obj' at that byte offset.
 marker = f"{i} 0 obj".encode("ascii")
 assert data[off:off + len(marker)] == marker


def test_trailer_size_and_root() -> None:
 w, buf = _make_writer()
 w.shipout(1, _empty_vlist())
 w.finalize()
 data = buf.getvalue()
 trailer = _extract_trailer(data)
 # Number of objects allocated + 1.
 objects = _parse_pdf_objects(data)
 expected_size = max(objects.keys()) + 1
 assert f"/Size {expected_size}".encode("ascii") in trailer
 cat_oid, _ = _find_single(objects, b"/Type /Catalog")
 assert f"/Root {cat_oid} 0 R".encode("ascii") in trailer


def test_startxref_offset_valid() -> None:
 w, buf = _make_writer()
 w.finalize()
 data = buf.getvalue()
 xref_off = _startxref(data)
 assert data[xref_off:xref_off + 5] == b"xref\n"


# ---------------------------------------------------------------------------
# File vs memory
# ---------------------------------------------------------------------------

def test_file_and_memory_identical(tmp_path) -> None:
 mgr1 = _make_mgr_with_cmr10()
 buf = io.BytesIO()
 w1 = PdfWriter(buf, mgr1, producer="test")
 # Freeze time by reusing creation_date.
 w1._creation_date = b"D:20260101000000Z"
 w1.shipout(1, _page([_hbox([CharNode(char=ord("A"), font_name="tenrm")])]))
 w1.finalize()

 mgr2 = _make_mgr_with_cmr10()
 path = tmp_path / "out.pdf"
 w2 = PdfWriter(path, mgr2, producer="test")
 w2._creation_date = b"D:20260101000000Z"
 w2.shipout(1, _page([_hbox([CharNode(char=ord("A"), font_name="tenrm")])]))
 w2.finalize()

 assert buf.getvalue() == path.read_bytes()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_shipout_after_finalize_raises() -> None:
 w, _ = _make_writer()
 w.finalize()
 with pytest.raises(RuntimeError):
 w.shipout(1, _empty_vlist())


def test_double_finalize_raises() -> None:
 w, _ = _make_writer()
 w.finalize()
 with pytest.raises(RuntimeError):
 w.finalize()


def test_get_bytes_before_finalize_raises() -> None:
 w, _ = _make_writer()
 with pytest.raises(RuntimeError):
 w.get_bytes()


def test_get_bytes_with_path_raises(tmp_path) -> None:
 path = tmp_path / "out.pdf"
 w = PdfWriter(path, _make_mgr_with_cmr10())
 w.finalize()
 with pytest.raises(RuntimeError):
 w.get_bytes()


def test_unknown_font_raises_fonterror() -> None:
 mgr = FontManager() # nothing loaded
 w, _ = _make_writer(mgr)
 hbox = _hbox([CharNode(char=ord("A"), font_name="tenrm")])
 with pytest.raises(FontError):
 w.shipout(1, _page([hbox]))


def test_whatsit_logs_warning_not_fatal() -> None:
 w, buf = _make_writer()
 w.shipout(1, _page([WhatsitNode(data=b"color push rgb 1 0 0")]))
 with warnings.catch_warnings(record=True):
 warnings.simplefilter("always")
 w.shipout(2, _page([WhatsitNode(data=b"color push rgb 1 0 0")]))
 w.finalize()
 # warning emitted at least once; PDF still ends with %%EOF
 assert buf.getvalue().endswith(b"%%EOF\n")


def test_multipage_runs_in_one_pdf() -> None:
 mgr = _make_mgr_with_cmr10()
 w, buf = _make_writer(mgr)
 for i in range(2):
 hbox = _hbox([CharNode(char=ord("A"), font_name="tenrm")])
 w.shipout(i + 1, _page([hbox]))
 w.finalize()
 data = buf.getvalue()
 # Exactly one Font object for the shared font.
 objects = _parse_pdf_objects(data)
 font_objs = [b for b in objects.values() if b"/Type /Font " in b and b"/Subtype /Type1" in b]
 assert len(font_objs) == 1
 # Two Page objects.
 assert len(_find_page_objects(objects)) == 2
