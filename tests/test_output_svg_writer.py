"""Unit tests for SvgWriter.

Tests validate SVG 1.1 structure, namespace, viewBox, glyph <defs>,
<use> elements, <rect> for rules, multi-page output, coordinate
transforms, and error handling.
"""
from __future__ import annotations

import io
import warnings
import xml.etree.ElementTree as ET

import pytest

from aspose_tex._engine.nodes import (
 CharNode,
 GlueSign,
 HlistNode,
 RuleNode,
 VlistNode,
 WhatsitNode,
)
from aspose_tex._engine.registers import GlueOrder
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._output.svg_writer import SvgWriter, _scale_path_d
from aspose_tex.exceptions import FontError

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
_NS = f"{{{SVG_NS}}}"
_XLINK_HREF = f"{{{XLINK_NS}}}href"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mgr_with_cmr10() -> FontManager:
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 return mgr


def _make_writer(destination=None, **kwargs) -> tuple[SvgWriter, io.BytesIO]:
 mgr = kwargs.pop("font_manager", None) or _make_mgr_with_cmr10()
 if destination is None:
 destination = io.BytesIO()
 w = SvgWriter(destination, font_manager=mgr, **kwargs)
 return w, destination


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


def _parse_svg(data: bytes) -> ET.Element:
 return ET.fromstring(data)


# ---------------------------------------------------------------------------
# Basic structure tests
# ---------------------------------------------------------------------------

class TestBasicStructure:
 def test_empty_document_produces_no_pages(self):
 """finalize() with no shipout -> get_all_pages() returns []."""
 writer, _ = _make_writer()
 writer.finalize()
 assert writer.get_all_pages() == []

 def test_single_page_valid_svg_structure(self):
 writer, _ = _make_writer()
 writer.shipout(1, _empty_vlist())
 writer.finalize()
 data = writer.get_bytes()
 assert data.startswith(b'<?xml')
 root = _parse_svg(data)
 assert root.tag == f"{_NS}svg"
 assert root.get("version") == "1.1"
 assert root.get("width") is not None
 assert root.get("height") is not None
 assert root.get("viewBox") is not None

 def test_svg_namespace_correct(self):
 writer, _ = _make_writer()
 writer.shipout(1, _empty_vlist())
 writer.finalize()
 data = writer.get_bytes()
 assert b'xmlns="http://www.w3.org/2000/svg"' in data

 def test_svg_dimensions_empty_page_falls_back_to_full_page(self):
 """: empty pages fall back to the configured page size.

 With no painted placements, the content bbox is undefined; the
 writer keeps the original page-sized canvas so the SVG still
 has a sensible layout box.
 """
 writer, _ = _make_writer()
 writer.shipout(1, _empty_vlist())
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 assert root.get("width") == "612pt"
 assert root.get("height") == "792pt"
 assert root.get("viewBox") == "0 0 612 792"

 def test_svg_dimensions_empty_page_custom_page_size(self):
 """Empty page on a custom page size keeps the custom dimensions."""
 writer, _ = _make_writer(page_width_pt=300, page_height_pt=400)
 writer.shipout(1, _empty_vlist())
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 assert root.get("width") == "300pt"
 assert root.get("height") == "400pt"
 assert root.get("viewBox") == "0 0 300 400"

 def test_svg_viewbox_is_content_tight_when_page_has_content(self):
 """: a non-empty page emits a content-tight viewBox.

 With content present, ``width`` / ``height`` and the four
 ``viewBox`` numbers must reflect the painted bbox (plus a small
 padding) — they must NOT reproduce the full configured page
 dimensions. This is the dvisvgm-style emission shape that
 Chrome 147 paints reliably; the page-sized viewBox caused the
 folio-not-rendered defect.
 """
 writer, _ = _make_writer()
 page = _page([_hbox([CharNode(char=72, font_name="tenrm")])])
 writer.shipout(1, page)
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 # Configured page is 612x792; bbox of one ``H`` glyph at ORIGIN_*
 # is ~(72, 65) to ~(80, 72). Content-tight viewBox must be much
 # smaller than the page in both dimensions.
 vb = root.get("viewBox") or ""
 assert vb != "0 0 612 792", (
 " regression: viewBox is still the full page; "
 "content-tight viewBox is required so Chromium paints "
 "off-baseline placements (e.g. the page folio)."
 )
 parts = vb.split()
 assert len(parts) == 4
 vw = float(parts[2])
 vh = float(parts[3])
 assert vw < 100, f"content-tight width should be << page; got {vw}"
 assert vh < 100, f"content-tight height should be << page; got {vh}"

 def test_svg_viewbox_encloses_far_off_placement(self):
 """ AC-2: a glyph placed far from body text (the folio
 case) must still fall inside the emitted viewBox."""
 writer, _ = _make_writer()
 # Body char at top of page ...
 body = _hbox([CharNode(char=72, font_name="tenrm")])
 # ... and a "folio" char placed via a separate hbox shifted
 # downward through a glue node. The simplest construction: two
 # hboxes inside a vlist, separated by a kern-like glue. We do
 # not have GlueNode at module scope here — use a high-baseline
 # second hbox via an outer vlist with explicit child placement.
 from aspose_tex._engine.nodes import KernNode
 kern = KernNode(width=600 * 65536, explicit=True) # 600pt down
 folio = _hbox([CharNode(char=49, font_name="tenrm")])
 page = _page([body, kern, folio])
 writer.shipout(1, page)
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 vb = root.get("viewBox") or ""
 parts = vb.split()
 assert len(parts) == 4
 vx, vy, vw, vh = (float(s) for s in parts)
 # Two <use> placements: pull their (x, y) and verify both are
 # inside the viewBox rectangle.
 uses = root.findall(f".//{_NS}use")
 assert len(uses) == 2
 for use in uses:
 ux = float(use.get("x") or 0)
 uy = float(use.get("y") or 0)
 assert vx <= ux <= vx + vw, (
 f"<use x={ux}> falls outside viewBox x=[{vx},{vx + vw}]"
 )
 assert vy <= uy <= vy + vh, (
 f"<use y={uy}> falls outside viewBox y=[{vy},{vy + vh}]"
 )

 def test_svg_is_wellformed_xml(self):
 writer, _ = _make_writer()
 page = _page([_hbox([CharNode(char=72, font_name="tenrm")])])
 writer.shipout(1, page)
 writer.finalize()
 # Should not raise
 _parse_svg(writer.get_bytes())

 def test_svg_output_self_contained(self):
 """SVG has no external references — xlink:href only points to local #g-* ids."""
 writer, _ = _make_writer()
 page = _page([_hbox([CharNode(char=72, font_name="tenrm")])])
 writer.shipout(1, page)
 writer.finalize()
 data = writer.get_bytes()
 assert b"<image" not in data
 assert b"@font-face" not in data
 # Every xlink:href must reference an internal glyph id
 # (: switched from bare ``href`` to ``xlink:href`` for SVG 1.1
 # canonical form; Chromium-friendly and Inkscape-compatible).
 root = _parse_svg(data)
 for use in root.findall(f".//{_NS}use"):
 href = use.get(_XLINK_HREF)
 assert href is not None and href.startswith("#g-"), (
 f"unexpected use href: {href!r}"
 )
 # No external schemes — only the SVG and xlink namespaces are http URIs.
 ns_only = data.count(b'"http://www.w3.org/2000/svg"') + \
 data.count(b'"http://www.w3.org/1999/xlink"')
 assert b"http://" not in data or data.count(b"http://") == ns_only


# ---------------------------------------------------------------------------
# Glyph definitions and placements
# ---------------------------------------------------------------------------

class TestGlyphs:
 def test_single_char_has_defs_and_use(self):
 writer, _ = _make_writer()
 page = _page([_hbox([CharNode(char=72, font_name="tenrm")])])
 writer.shipout(1, page)
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 defs = root.find(f"{_NS}defs")
 assert defs is not None
 paths = defs.findall(f"{_NS}path")
 assert len(paths) == 1
 assert paths[0].get("id") is not None
 uses = root.findall(f".//{_NS}use")
 assert len(uses) == 1
 assert uses[0].get(_XLINK_HREF) is not None

 def test_glyph_path_id_format(self):
 writer, _ = _make_writer()
 page = _page([_hbox([CharNode(char=72, font_name="tenrm")])])
 writer.shipout(1, page)
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 path = root.find(f"{_NS}defs/{_NS}path")
 assert path is not None
 # : glyph id encodes the at-size (cmr10 loaded at 10pt).
 assert path.get("id") == "g-cmr10-10-72"

 def test_use_href_references_defs(self):
 writer, _ = _make_writer()
 page = _page([_hbox([
 CharNode(char=72, font_name="tenrm"),
 CharNode(char=101, font_name="tenrm"),
 ])])
 writer.shipout(1, page)
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 defs = root.find(f"{_NS}defs")
 ids = {p.get("id") for p in defs.findall(f"{_NS}path")}
 for use in root.findall(f".//{_NS}use"):
 href = use.get(_XLINK_HREF)
 assert href.startswith("#")
 assert href[1:] in ids

 def test_use_emits_x_y_xlink_href_no_transform(self):
 """: ``<use>`` uses bare ``x``/``y`` + ``xlink:href`` (no ``transform``).

 Folding ``transform="translate(...) scale(0.01,-0.01)"`` into the
 path data and emitting placements with bare ``x`` / ``y``
 attributes mirrors dvisvgm's output and renders reliably across
 Chromium browsers — the form Chrome silently dropped for the
 page-folio glyph in .
 """
 writer, _ = _make_writer()
 page = _page([_hbox([CharNode(char=72, font_name="tenrm")])])
 writer.shipout(1, page)
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 use = root.find(f".//{_NS}use")
 assert use is not None
 assert use.get("transform") is None, (
 " regression: <use> must not carry a transform attribute"
 )
 assert use.get("x") is not None
 assert use.get("y") is not None
 assert use.get(_XLINK_HREF) == "#g-cmr10-10-72"

 def test_char_position_matches_expected(self):
 """CharNode at top of hbox at v=655360 (10pt) -> y = 72 + 10 = 82."""
 writer, _ = _make_writer()
 # A single char in an hbox at v=10pt. v_ref after HlistNode.height=0
 # is the v_cursor which has 0 added (no height added). We need to
 # position it via the vlist's structure.
 # Simplest: place CharNode directly, the y will be _ORIGIN_Y_PT.
 page = _page([_hbox([CharNode(char=72, font_name="tenrm")])])
 writer.shipout(1, page)
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 use = root.find(f".//{_NS}use")
 # Origin offset (72, 72) is now expressed via x/y attrs.
 assert use.get("x") == "72"
 assert use.get("y") == "72"

 def test_multiple_chars_same_font_shared_defs(self):
 """'Hello' with H+e+l+l+o: 'l' appears twice but <defs> has only one <path> for it."""
 writer, _ = _make_writer()
 page = _page([_hbox([
 CharNode(char=72, font_name="tenrm"), # H
 CharNode(char=101, font_name="tenrm"), # e
 CharNode(char=108, font_name="tenrm"), # l
 CharNode(char=108, font_name="tenrm"), # l
 CharNode(char=111, font_name="tenrm"), # o
 ])])
 writer.shipout(1, page)
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 defs = root.find(f"{_NS}defs")
 paths = defs.findall(f"{_NS}path")
 ids = [p.get("id") for p in paths]
 # Each unique glyph appears once (: at-size-encoded ids)
 assert ids.count("g-cmr10-10-108") == 1
 # But <use> appears for each placement
 uses = root.findall(f".//{_NS}use")
 l_uses = [u for u in uses if u.get(_XLINK_HREF) == "#g-cmr10-10-108"]
 assert len(l_uses) == 2

 def test_def_path_data_pre_scaled_to_pt_units(self):
 """: glyph path data is pre-scaled into user (pt) units.

 Before the fix, the path emitted ``M 613 605 ...`` in font-design
 units (max coord ~700) and a per-``<use>`` ``scale(0.01,-0.01)``
 produced the visual size; after the fix the scale is folded in,
 so coords in the ``d`` attribute should fit inside roughly the
 font size in pt (≤ 20 pt for cmr10 at 10pt — leaves headroom for
 bearing offsets).
 """
 writer, _ = _make_writer()
 page = _page([_hbox([CharNode(char=72, font_name="tenrm")])])
 writer.shipout(1, page)
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 path = root.find(f"{_NS}defs/{_NS}path")
 assert path is not None
 d = path.get("d") or ""
 # Tokenize and find max abs coord (skip command letters).
 max_abs = 0.0
 for tok in d.split():
 try:
 v = abs(float(tok))
 except ValueError:
 continue
 if v > max_abs:
 max_abs = v
 assert max_abs < 20, (
 f" regression: path coord magnitude {max_abs} suggests "
 f"path is still in font-design units (expected pt-units)"
 )

 def test_ensure_font_leaves_scaled_paths_empty(self):
 """: loading a font must not pre-scale its whole glyph table."""
 writer, _ = _make_writer()
 rec = writer._ensure_font("tenrm")
 assert rec.outlines
 assert rec.scaled_d == {}

 def test_scaled_path_populates_only_used_glyphs(self):
 """: shipout scales and caches only glyphs referenced by the page."""
 writer, _ = _make_writer()
 page = _page([_hbox([
 CharNode(char=72, font_name="tenrm"),
 CharNode(char=101, font_name="tenrm"),
 CharNode(char=72, font_name="tenrm"),
 ])])
 writer.shipout(1, page)
 writer.finalize()

 rec = writer._fonts["tenrm"]
 assert set(rec.scaled_d) == {72, 101}
 assert rec.scaled_d[72]
 assert rec.scaled_d[101]

 def test_scaled_path_cache_hit_reuses_existing_string(self, monkeypatch):
 """: repeated glyph references do not repeat path-scaling work."""
 import aspose_tex._output.svg_writer as svg_writer

 writer, _ = _make_writer()
 rec = writer._ensure_font("tenrm")
 calls: list[tuple[str, float]] = []

 def fake_scale_path_d(d: str, scale: float) -> str:
 calls.append((d, scale))
 return "M 0 0 Z"

 monkeypatch.setattr(svg_writer, "_scale_path_d", fake_scale_path_d)

 first = writer._scaled_glyph_path_d(rec, 72)
 second = writer._scaled_glyph_path_d(rec, 72)

 assert first == "M 0 0 Z"
 assert second == first
 assert calls == [(rec.outlines[72].svg_path, rec.at_size_pt / 1000.0)]

 def test_lazy_scaled_paths_preserve_emitted_defs(self):
 """ keeps the pre-scaled path emitted for used glyphs."""
 writer, _ = _make_writer()
 page = _page([_hbox([CharNode(char=72, font_name="tenrm")])])
 writer.shipout(1, page)
 writer.finalize()

 rec = writer._fonts["tenrm"]
 root = _parse_svg(writer.get_bytes())
 path = root.find(f"{_NS}defs/{_NS}path")

 assert path is not None
 assert path.get("d") == rec.scaled_d[72]

 def test_multi_size_same_tfm_distinct_glyph_ids(self):
 """: cmr10 loaded at 10pt and 7pt must not collide on a path id.

 Before the fix, the glyph id scheme ``g-{tfm}-{code}`` reused
 ``g-cmr10-72`` for both sizes; whichever font emitted last
 overwrote the other's outline in ``<defs>``, corrupting one
 placement. With the at-size folded into the id the document
 carries two distinct path sets and each ``<use>`` resolves to the
 ``<path>`` for its own size.
 """
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10") # cmr10 @ 10pt
 mgr.load_font("sevenrm", "cmr10", at_sp=7 * 65536) # cmr10 @ 7pt
 writer, _ = _make_writer(font_manager=mgr)
 page = _page([_hbox([
 CharNode(char=72, font_name="tenrm"), # H @ 10pt
 CharNode(char=72, font_name="sevenrm"), # H @ 7pt
 ])])
 writer.shipout(1, page)
 writer.finalize()
 root = _parse_svg(writer.get_bytes())

 defs = root.find(f"{_NS}defs")
 ids = [p.get("id") for p in defs.findall(f"{_NS}path")]
 # Two distinct path definitions for the same (tfm, code) at
 # different sizes.
 assert "g-cmr10-10-72" in ids
 assert "g-cmr10-7-72" in ids
 assert len(ids) == len(set(ids)), f"duplicate path ids: {ids}"
 assert len(ids) == 2

 # Each <use> references the path for its own size, and both
 # references resolve to a defined <path>.
 hrefs = [u.get(_XLINK_HREF) for u in root.findall(f".//{_NS}use")]
 assert "#g-cmr10-10-72" in hrefs
 assert "#g-cmr10-7-72" in hrefs
 defined = set(ids)
 for href in hrefs:
 assert href[1:] in defined, f"dangling href {href!r}"

 # The two outlines differ in scale (7pt path coords are smaller
 # than the 10pt ones), proving they are not the same definition.
 d10 = next(p.get("d") for p in defs.findall(f"{_NS}path")
 if p.get("id") == "g-cmr10-10-72")
 d7 = next(p.get("d") for p in defs.findall(f"{_NS}path")
 if p.get("id") == "g-cmr10-7-72")
 assert d10 != d7

 def test_xlink_namespace_declared(self):
 """: root ``<svg>`` declares the ``xlink`` namespace prefix.

 SVG 1.1 canonical form requires ``xmlns:xlink`` for ``xlink:href``.
 """
 writer, _ = _make_writer()
 writer.shipout(1, _empty_vlist())
 writer.finalize()
 data = writer.get_bytes()
 assert b'xmlns:xlink="http://www.w3.org/1999/xlink"' in data


# ---------------------------------------------------------------------------
# Rules (<rect>)
# ---------------------------------------------------------------------------

class TestRules:
 def test_rule_renders_as_rect(self):
 writer, _ = _make_writer()
 rule = RuleNode(width=10 * 65536, height=2 * 65536, depth=0)
 page = _page([_hbox([rule])])
 writer.shipout(1, page)
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 rects = root.findall(f".//{_NS}rect")
 assert len(rects) == 1
 rect = rects[0]
 assert rect.get("fill") == "black"
 assert rect.get("x") is not None
 assert rect.get("y") is not None
 assert rect.get("width") is not None
 assert rect.get("height") is not None

 def test_rule_coords_correct(self):
 """10pt x 2pt rule in hbox at top -> rect at (72, 70) size 10x2."""
 writer, _ = _make_writer()
 rule = RuleNode(width=10 * 65536, height=2 * 65536, depth=0)
 page = _page([_hbox([rule])])
 writer.shipout(1, page)
 writer.finalize()
 root = _parse_svg(writer.get_bytes())
 rect = root.find(f".//{_NS}rect")
 # v_ref at top of hbox after height=0 is 0, so rule is at y = ORIGIN_Y - height = 72 - 2 = 70
 assert rect.get("x") == "72"
 assert rect.get("y") == "70"
 assert rect.get("width") == "10"
 assert rect.get("height") == "2"


# ---------------------------------------------------------------------------
# Multi-page
# ---------------------------------------------------------------------------

class TestMultiPage:
 def test_multipage_produces_multiple_svgs(self):
 writer, _ = _make_writer()
 writer.shipout(1, _empty_vlist())
 writer.shipout(2, _empty_vlist())
 writer.finalize()
 pages = writer.get_all_pages()
 assert len(pages) == 2

 def test_multipage_each_standalone(self):
 writer, _ = _make_writer()
 writer.shipout(1, _empty_vlist())
 writer.shipout(2, _empty_vlist())
 writer.finalize()
 for page_bytes in writer.get_all_pages():
 assert page_bytes.startswith(b'<?xml')
 root = _parse_svg(page_bytes)
 assert root.tag == f"{_NS}svg"

 def test_multipage_file_output_numbered(self, tmp_path):
 writer, _ = _make_writer(destination=tmp_path / "base")
 writer.shipout(1, _empty_vlist())
 writer.shipout(2, _empty_vlist())
 writer.finalize()
 assert (tmp_path / "base-1.svg").exists()
 assert (tmp_path / "base-2.svg").exists()

 def test_singlepage_file_output_no_number(self, tmp_path):
 writer, _ = _make_writer(destination=tmp_path / "base")
 writer.shipout(1, _empty_vlist())
 writer.finalize()
 assert (tmp_path / "base.svg").exists()
 assert not (tmp_path / "base-1.svg").exists()

 def test_file_extension_stripped(self, tmp_path):
 """base path with .svg extension: still writes base.svg (single page)."""
 writer, _ = _make_writer(destination=tmp_path / "base.svg")
 writer.shipout(1, _empty_vlist())
 writer.finalize()
 assert (tmp_path / "base.svg").exists()

 def test_file_and_memory_identical(self, tmp_path):
 """Same input to Path and BytesIO -> identical SVG bytes."""
 writer_mem, _ = _make_writer()
 writer_file, _ = _make_writer(destination=tmp_path / "base")

 page = _page([_hbox([CharNode(char=72, font_name="tenrm")])])
 writer_mem.shipout(1, page)
 writer_file.shipout(1, page)
 writer_mem.finalize()
 writer_file.finalize()

 file_bytes = (tmp_path / "base.svg").read_bytes()
 mem_bytes = writer_mem.get_bytes()
 assert file_bytes == mem_bytes

 def test_get_bytes_returns_first_page(self):
 writer, _ = _make_writer()
 writer.shipout(1, _empty_vlist())
 writer.shipout(2, _empty_vlist())
 writer.finalize()
 assert writer.get_bytes() == writer.get_all_pages()[0]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors:
 def test_shipout_after_finalize_raises(self):
 writer, _ = _make_writer()
 writer.finalize()
 with pytest.raises(RuntimeError):
 writer.shipout(1, _empty_vlist())

 def test_double_finalize_raises(self):
 writer, _ = _make_writer()
 writer.finalize()
 with pytest.raises(RuntimeError):
 writer.finalize()

 def test_get_bytes_before_finalize_raises(self):
 writer, _ = _make_writer()
 writer.shipout(1, _empty_vlist())
 with pytest.raises(RuntimeError):
 writer.get_bytes()

 def test_get_bytes_with_path_raises(self, tmp_path):
 writer, _ = _make_writer(destination=tmp_path / "base")
 writer.shipout(1, _empty_vlist())
 writer.finalize()
 with pytest.raises(RuntimeError):
 writer.get_bytes()

 def test_unknown_font_raises_fonterror(self):
 mgr = FontManager() # no fonts loaded
 buf = io.BytesIO()
 writer = SvgWriter(buf, font_manager=mgr)
 page = _page([_hbox([CharNode(char=72, font_name="unknowncs")])])
 with pytest.raises(FontError):
 writer.shipout(1, page)

 def test_whatsit_logs_warning_not_fatal(self):
 writer, _ = _make_writer()
 page = _page([WhatsitNode(data=b"some payload")])
 with warnings.catch_warnings(record=True) as w:
 warnings.simplefilter("always")
 writer.shipout(1, page)
 writer.finalize()
 # SVG should still be valid
 _parse_svg(writer.get_bytes())
 # Warning was emitted
 assert any("whatsit" in str(warning.message).lower() or
 "special" in str(warning.message).lower() for warning in w)


# ---------------------------------------------------------------------------
# _scale_path_d helper
# ---------------------------------------------------------------------------

class TestScalePathD:
 """Unit tests for the path pre-scaling helper introduced in ."""

 def test_empty_input_returns_empty(self):
 assert _scale_path_d("", 0.01) == ""

 def test_moveto_lineto_closepath(self):
 # Source path uses font-design units (y-up); _scale_path_d folds in
 # both the user-unit scale and the y-down flip.
 d = "M 100 200 L 300 200 Z"
 out = _scale_path_d(d, 0.01)
 assert out == "M 1 -2 L 3 -2 Z"

 def test_curveto_six_operands(self):
 d = "M 0 0 C 100 100 200 100 300 0 Z"
 out = _scale_path_d(d, 0.01)
 assert out == "M 0 0 C 1 -1 2 -1 3 0 Z"

 def test_decimal_format_strips_trailing_zeros(self):
 # 271 * 0.01 = 2.71 (two decimals, no trailing zero).
 d = "M 271 666 Z"
 out = _scale_path_d(d, 0.01)
 assert out == "M 2.71 -6.66 Z"

 def test_unknown_command_raises(self):
 with pytest.raises(ValueError):
 _scale_path_d("M 0 0 Q 1 1 2 2", 0.01)

 def test_y_negation_round_trip(self):
 # Positive source y becomes negative output y.
 out = _scale_path_d("M 50 100", 0.01)
 assert out == "M 0.5 -1"
 # Negative source y becomes positive output y (kept symmetric).
 out_neg = _scale_path_d("M 50 -100", 0.01)
 assert out_neg == "M 0.5 1"
