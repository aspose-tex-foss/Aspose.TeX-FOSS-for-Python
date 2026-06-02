"""Integration tests for SvgDevice end-to-end.

Validates TeXJob + SvgDevice emits a valid SVG 1.1 document, supports
file / memory output, multi-page documents, embeds glyph outlines
self-containedly, and keeps character positions consistent with the DVI
reference (AC-5).
"""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from pathlib import Path

from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import SvgDevice, TeXJob, TeXOptions

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
_NS = f"{{{SVG_NS}}}"
_XLINK_HREF = f"{{{XLINK_NS}}}href"
_NO_FORMAT = TeXOptions(load_format=False)


# ---------------------------------------------------------------------------
# Basic end-to-end
# ---------------------------------------------------------------------------

def test_texjob_svg_hello_world() -> None:
 result = TeXJob(
 StringInputSource(r"Hello\bye"), SvgDevice(), options=_NO_FORMAT,
 ).run()
 assert result is not None
 assert result.startswith(b"<?xml")
 # Valid XML with correct namespace
 root = ET.fromstring(result)
 assert root.tag == f"{_NS}svg"


def test_texjob_svg_file_output(tmp_path: Path) -> None:
 out = tmp_path / "out"
 result = TeXJob(
 StringInputSource(r"Hello\bye"), SvgDevice(out), options=_NO_FORMAT,
 ).run()
 assert result is None
 # Single page -> out.svg
 svg_file = tmp_path / "out.svg"
 assert svg_file.exists()
 data = svg_file.read_bytes()
 assert data.startswith(b"<?xml")


def test_texjob_svg_multipage() -> None:
 """Force page break; expect multiple pages in memory output."""
 tex = r"Page one\vfill\eject Page two\bye"
 device = SvgDevice()
 TeXJob(StringInputSource(tex), device, options=_NO_FORMAT).run()
 pages = device.get_all_pages()
 assert pages is not None
 assert len(pages) >= 2
 for page in pages:
 assert page.startswith(b"<?xml")
 ET.fromstring(page) # each page is valid XML


def test_texjob_svg_bytesio_produces_valid_svg() -> None:
 """BytesIO destination -> parseable XML with SVG namespace."""
 buf = io.BytesIO()
 device = SvgDevice(buf)
 TeXJob(StringInputSource(r"Hi\bye"), device, options=_NO_FORMAT).run()
 data = device.get_bytes()
 assert data is not None
 root = ET.fromstring(data)
 assert root.tag == f"{_NS}svg"
 assert root.get("version") == "1.1"


def test_svg_self_contained_no_external_fonts() -> None:
 """Generated SVG has <defs> with <path> elements; no external refs.

 : ``xlink:href`` is allowed but must only resolve to internal
 ``#g-*`` glyph ids; no ``@font-face`` or ``<image>`` references.
 """
 svg = TeXJob(
 StringInputSource(r"Hi\bye"), SvgDevice(), options=_NO_FORMAT,
 ).run()
 assert svg is not None
 root = ET.fromstring(svg)
 defs = root.find(f"{_NS}defs")
 assert defs is not None
 paths = defs.findall(f"{_NS}path")
 assert len(paths) >= 1 # At least one glyph embedded
 # No external refs
 assert b"@font-face" not in svg
 assert b"<image" not in svg
 for use in root.findall(f".//{_NS}use"):
 href = use.get(_XLINK_HREF)
 assert href is not None and href.startswith("#g-")


def test_svg_office_includes_ffi_ligature_use() -> None:
 """ AC-6: a word triggering a ligature must reach SVG as a
 ``<use href="#g-cmr10-10-N">`` element. ``office`` = o·f·f·i·c·e yields the
 ffi ligature at code 14 via cmr10's lig table (f+f→ff, ff+i→ffi), so the
 emitted SVG must reference ``#g-cmr10-10-14`` and raise no outline-missing
 warning on ligature slots (: ids encode the at-size, cmr10 at 10pt).
 """
 import warnings as _warnings

 with _warnings.catch_warnings(record=True) as caught:
 _warnings.simplefilter("always")
 svg = TeXJob(
 StringInputSource(r"office\bye"), SvgDevice(), options=_NO_FORMAT,
 ).run()
 assert svg is not None

 missing = [
 str(w.message)
 for w in caught
 if "no outline for char code" in str(w.message)
 and "cmr10" in str(w.message)
 ]
 assert not missing, f"unexpected outline-missing warnings: {missing}"

 root = ET.fromstring(svg)
 defs = root.find(f"{_NS}defs")
 assert defs is not None
 path_ids = {p.get("id") for p in defs.findall(f"{_NS}path")}
 assert "g-cmr10-10-14" in path_ids, (
 f"g-cmr10-10-14 (ffi) missing from <defs>; have {sorted(path_ids)}"
 )

 use_hrefs = [u.get(_XLINK_HREF) for u in root.findall(f".//{_NS}use")]
 assert "#g-cmr10-10-14" in use_hrefs, (
 "ffi ligature <use xlink:href=#g-cmr10-10-14> not emitted"
 )


def test_svg_all_cmr10_ligature_slots_render() -> None:
 """ AC-1..AC-3 coverage: a carrier string that exercises each of
 the five CM ligatures (ff, fi, fl, ffi, ffl) must emit a <use> reference
 at every slot 11..15 and no outline-missing warning for those slots.

 Ligature triggers in cmr10 (from TFM lig table):
 stiff -> ff (code 11)
 fit -> fi (code 12)
 flat -> fl (code 13)
 office -> ffi (code 14)
 afflict -> ffl (code 15)
 """
 import warnings as _warnings

 source = r"stiff fit flat office afflict\bye"
 with _warnings.catch_warnings(record=True) as caught:
 _warnings.simplefilter("always")
 svg = TeXJob(
 StringInputSource(source), SvgDevice(), options=_NO_FORMAT,
 ).run()
 assert svg is not None

 ligature_warnings = [
 str(w.message)
 for w in caught
 if "no outline for char code" in str(w.message)
 and "cmr10" in str(w.message)
 ]
 assert not ligature_warnings, ligature_warnings

 root = ET.fromstring(svg)
 defs = root.find(f"{_NS}defs")
 assert defs is not None
 defined = {p.get("id") for p in defs.findall(f"{_NS}path")}
 hrefs = {u.get(_XLINK_HREF) for u in root.findall(f".//{_NS}use")}
 for code in (11, 12, 13, 14, 15):
 assert f"g-cmr10-10-{code}" in defined, (
 f"code {code} path missing from <defs>"
 )
 assert f"#g-cmr10-10-{code}" in hrefs, (
 f"code {code} <use xlink:href> missing from body"
 )


def test_svg_rule_renders_as_rect() -> None:
 tex = r"\hrule height 2pt width 10pt\bye"
 svg = TeXJob(StringInputSource(tex), SvgDevice(), options=_NO_FORMAT).run()
 assert svg is not None
 root = ET.fromstring(svg)
 rects = root.findall(f".//{_NS}rect")
 assert len(rects) == 1
 rect = rects[0]
 assert rect.get("width") == "10"
 assert rect.get("height") == "2"
 assert rect.get("fill") == "black"


# ---------------------------------------------------------------------------
# DVI ↔ SVG positional consistency (AC-5)
# ---------------------------------------------------------------------------

def test_texjob_svg_positions_match_dvi() -> None:
 """Synthesize the same page box; feed to DviWriter and SvgWriter; verify
 that horizontal char cursors agree within 1pt tolerance.
 """
 import io as _io

 from aspose_tex._engine.nodes import CharNode, GlueSign, HlistNode, VlistNode
 from aspose_tex._engine.registers import GlueOrder
 from aspose_tex._fonts.font_manager import FontManager
 from aspose_tex._output.dvi_writer import DviWriter
 from aspose_tex._output.svg_writer import SvgWriter

 mgr_svg = FontManager()
 mgr_svg.load_font("tenrm", "cmr10")
 mgr_dvi = FontManager()
 mgr_dvi.load_font("tenrm", "cmr10")

 def make_page() -> VlistNode:
 hbox = HlistNode(
 list=[CharNode(char=ord("H"), font_name="tenrm"),
 CharNode(char=ord("i"), font_name="tenrm")],
 width=0, height=655360, depth=0, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 return VlistNode(
 list=[hbox], width=0, height=655360, depth=0, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )

 # SVG
 svg_buf = _io.BytesIO()
 sw = SvgWriter(svg_buf, mgr_svg)
 sw.shipout(1, make_page())
 sw.finalize()
 svg = sw.get_bytes()

 # First <use> element's x (: bare x/y attrs replaced
 # transform="translate(...)" so Chromium paints page folios).
 root = ET.fromstring(svg)
 first_use = root.find(f".//{_NS}use")
 assert first_use is not None
 x_attr = first_use.get("x")
 assert x_attr is not None, f"missing x attr on <use>: {first_use.attrib}"
 svg_x_pt = float(x_attr)
 # Convert SVG x back to h_sp. SVG uses _ORIGIN_X_PT = 72.
 svg_h_sp = round((svg_x_pt - 72) * 65536)

 # DVI
 dvi_buf = _io.BytesIO()
 dw = DviWriter(dvi_buf, mgr_dvi)
 dw.shipout(1, make_page())
 dw.finalize()
 dvi = dvi_buf.getvalue()

 # Walk to find first set_char's h
 assert dvi[0] == 247
 k = dvi[14]
 pos = 15 + k
 cur_h = 0
 stack: list[int] = []
 found_h: int | None = None
 while pos < len(dvi):
 op = dvi[pos]
 pos += 1
 if op <= 127:
 found_h = cur_h
 break
 elif op == 128:
 pos += 1
 found_h = cur_h
 break
 elif op == 139:
 pos += 44
 cur_h = 0
 stack = []
 elif op == 141:
 stack.append(cur_h)
 elif op == 142:
 cur_h = stack.pop()
 elif 143 <= op <= 146:
 n = op - 142
 cur_h += int.from_bytes(dvi[pos:pos + n], "big", signed=True)
 pos += n
 elif 157 <= op <= 160:
 pos += op - 156
 elif 171 <= op <= 234:
 pass
 elif op == 235:
 pos += 1
 elif op == 243:
 pos += 13
 a = dvi[pos]
 pos += 1
 ln = dvi[pos]
 pos += 1
 pos += a + ln
 elif op == 132:
 pos += 8
 elif op == 140 or op == 248:
 break
 else:
 break

 assert found_h is not None, "No set_char found in DVI output"
 # AC-5: within 1 pt (= 65536 sp) tolerance.
 assert abs(found_h - svg_h_sp) <= 65536, (
 f"h mismatch: dvi={found_h} sp, svg={svg_h_sp} sp"
 )
