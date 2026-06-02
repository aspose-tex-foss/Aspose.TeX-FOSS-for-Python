"""Cross-format M2 integration tests.

Validates that DVI, PDF, and SVG backends agree on output for the same
TeX input: basic validity, multi-page page counts, file/memory I/O,
engine-level error handling, and horizontal character positions.
"""
from __future__ import annotations

import io
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import FontError
from aspose_tex.presentation import (
 DviDevice,
 PdfDevice,
 SvgDevice,
 TeXJob,
 TeXOptions,
)

_DVI_PRE = 0xF7 # 247
_DVI_POST = 0xF8 # 248
_DVI_POST_POST = 0xF9 # 249
_DVI_PAD = 0xDF # 223

_SVG_NS = "http://www.w3.org/2000/svg"
_NS = f"{{{_SVG_NS}}}"
_NO_FORMAT = TeXOptions(load_format=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dvi_total_pages(dvi: bytes) -> int:
 """Decode ``total_pages`` from the DVI postamble (pdftex.web §595).

 Walks backwards past the trailing 0xDF padding to find ``post_post``
 (0xF9), reads the i4 pointer to ``post``, then reads the u2
 ``total_pages`` field at ``post_offset + 27``.
 """
 end = len(dvi) - 1
 while end >= 0 and dvi[end] == _DVI_PAD:
 end -= 1
 # ``end`` now points at the DVI id byte; one before is post_post opcode.
 # Layout: post_post (u1) + post_offset (i4) + id (u1) + pad.
 post_post_offset = end - 5
 assert post_post_offset >= 0, "malformed DVI (no post_post)"
 assert dvi[post_post_offset] == _DVI_POST_POST, "post_post opcode not found"
 post_offset = struct.unpack(">i", dvi[post_post_offset + 1:post_post_offset + 5])[0]
 assert 0 <= post_offset < len(dvi), "post_offset out of range"
 assert dvi[post_offset] == _DVI_POST, "post opcode not found at post_offset"
 # post(u1) + last_bop(i4) + num(u4) + den(u4) + mag(u4) + max_v(i4) +
 # max_h(i4) + max_stack(u2) = 1 + 4*6 + 2 = 27, so total_pages is at +27.
 return struct.unpack(">H", dvi[post_offset + 27:post_offset + 29])[0]


def _dvi_first_set_char_h(dvi: bytes) -> int:
 """Walk the first page of a DVI stream and return ``h`` (sp) at the
 first ``set_char`` / ``set1`` opcode. Only the opcode families the
 M2 writers actually emit are handled.
 """
 assert dvi[0] == _DVI_PRE
 k = dvi[14]
 pos = 15 + k
 cur_h = 0
 stack: list[int] = []
 while pos < len(dvi):
 op = dvi[pos]
 pos += 1
 if op <= 127 or op == 128: # set_char_0..127, set1
 return cur_h
 elif op == 132: # set_rule
 pos += 8
 elif op == 139: # bop
 pos += 44
 cur_h = 0
 stack = []
 elif op == 141: # push
 stack.append(cur_h)
 elif op == 142: # pop
 cur_h = stack.pop()
 elif 143 <= op <= 146: # right1..right4
 n = op - 142
 cur_h += int.from_bytes(dvi[pos:pos + n], "big", signed=True)
 pos += n
 elif 157 <= op <= 160: # down1..down4
 pos += op - 156
 elif 171 <= op <= 234: # fnt_num_0..63
 pass
 elif op == 235: # fnt1
 pos += 1
 elif op == 243: # fnt_def1
 pos += 13
 a = dvi[pos]
 pos += 1
 ln = dvi[pos]
 pos += 1
 pos += a + ln
 elif op == 140 or op == 248: # eop / post (no set_char found)
 break
 else:
 break
 raise AssertionError("No set_char opcode found on first DVI page")


# ---------------------------------------------------------------------------
# AC-1: Hello World through TeXJob API for all three backends
# ---------------------------------------------------------------------------

class TestAllFormatsHelloWorld:
 _TEX = "Hello World\\bye"

 def test_dvi_valid(self) -> None:
 result = TeXJob(
 StringInputSource(self._TEX), DviDevice(), options=_NO_FORMAT,
 ).run()
 assert result is not None
 assert result[0] == _DVI_PRE

 def test_pdf_valid(self) -> None:
 result = TeXJob(
 StringInputSource(self._TEX), PdfDevice(), options=_NO_FORMAT,
 ).run()
 assert result is not None
 assert result.startswith(b"%PDF-1.4")
 assert result.endswith(b"%%EOF\n")

 def test_svg_valid(self) -> None:
 result = TeXJob(
 StringInputSource(self._TEX), SvgDevice(), options=_NO_FORMAT,
 ).run()
 assert result is not None
 root = ET.fromstring(result)
 assert root.tag == f"{_NS}svg"
 assert root.get("version") == "1.1"


# ---------------------------------------------------------------------------
# AC-2: multi-page documents produce the expected page count
# ---------------------------------------------------------------------------

class TestAllFormatsMultipage:
 @staticmethod
 def _paragraphs_tex() -> str:
 return "\n\n".join(f"Paragraph {i}." for i in range(1, 201)) + r"\bye"

 def test_dvi_multipage(self) -> None:
 result = TeXJob(
 StringInputSource(self._paragraphs_tex()),
 DviDevice(),
 options=_NO_FORMAT,
 ).run()
 assert result is not None
 total_pages = _dvi_total_pages(result)
 assert total_pages >= 2, f"expected >= 2 DVI pages, got {total_pages}"

 def test_pdf_multipage(self) -> None:
 result = TeXJob(
 StringInputSource(self._paragraphs_tex()),
 PdfDevice(),
 options=_NO_FORMAT,
 ).run()
 assert result is not None
 m = re.search(rb"/Type /Pages[^>]*?/Count (\d+)", result)
 assert m is not None, "Pages dict /Count not found"
 assert int(m.group(1)) >= 2

 def test_svg_multipage(self) -> None:
 tex = r"Page one\vfill\eject Page two\bye"
 device = SvgDevice()
 TeXJob(StringInputSource(tex), device, options=_NO_FORMAT).run()
 pages = device.get_all_pages()
 assert pages is not None
 assert len(pages) >= 2
 for page in pages:
 ET.fromstring(page) # each page is well-formed XML


# ---------------------------------------------------------------------------
# AC-3: file and memory I/O both work for all three formats
# ---------------------------------------------------------------------------

class TestAllFormatsFileAndMemoryIO:
 _TEX = "Hello World\\bye"

 def test_dvi_file_and_memory(self, tmp_path: Path) -> None:
 mem = TeXJob(
 StringInputSource(self._TEX), DviDevice(), options=_NO_FORMAT,
 ).run()
 assert mem is not None and mem[0] == _DVI_PRE

 out = tmp_path / "out.dvi"
 assert TeXJob(
 StringInputSource(self._TEX), DviDevice(out), options=_NO_FORMAT,
 ).run() is None
 assert out.exists()
 assert out.read_bytes()[0] == _DVI_PRE

 def test_pdf_file_and_memory(self, tmp_path: Path) -> None:
 mem = TeXJob(
 StringInputSource(self._TEX), PdfDevice(), options=_NO_FORMAT,
 ).run()
 assert mem is not None and mem.startswith(b"%PDF-1.4")

 out = tmp_path / "out.pdf"
 assert TeXJob(
 StringInputSource(self._TEX), PdfDevice(out), options=_NO_FORMAT,
 ).run() is None
 assert out.exists()
 assert out.read_bytes().startswith(b"%PDF-1.4")

 def test_svg_file_and_memory(self, tmp_path: Path) -> None:
 mem = TeXJob(
 StringInputSource(self._TEX), SvgDevice(), options=_NO_FORMAT,
 ).run()
 assert mem is not None
 ET.fromstring(mem)

 # SvgDevice destination is a base path; single page → {base}.svg.
 base = tmp_path / "out"
 assert TeXJob(
 StringInputSource(self._TEX), SvgDevice(base), options=_NO_FORMAT,
 ).run() is None
 svg_file = tmp_path / "out.svg"
 assert svg_file.exists()
 ET.fromstring(svg_file.read_bytes())


# ---------------------------------------------------------------------------
# Error handling: engine-level FontError is backend-independent
# ---------------------------------------------------------------------------

class TestErrorHandling:
 _TEX = r"\font\x=nonexistent_tfm_xyz\x A\bye"

 def test_missing_font_raises_font_error(self) -> None:
 with pytest.raises(FontError):
 TeXJob(
 StringInputSource(self._TEX), PdfDevice(), options=_NO_FORMAT,
 ).run()

 def test_missing_font_dvi_also_raises(self) -> None:
 with pytest.raises(FontError):
 TeXJob(
 StringInputSource(self._TEX), DviDevice(), options=_NO_FORMAT,
 ).run()


# ---------------------------------------------------------------------------
# Cross-format positional consistency (synthetic box; writers compared directly)
# ---------------------------------------------------------------------------

class TestCrossFormatPositionalConsistency:
 def test_dvi_pdf_svg_char_positions_agree(self) -> None:
 from aspose_tex._engine.nodes import (
 CharNode,
 GlueSign,
 HlistNode,
 VlistNode,
 )
 from aspose_tex._engine.registers import GlueOrder
 from aspose_tex._fonts.font_manager import FontManager
 from aspose_tex._output.dvi_writer import DviWriter
 from aspose_tex._output.pdf_writer import PdfWriter
 from aspose_tex._output.svg_writer import SvgWriter

 # Separate FontManagers: writers mutate current-font state.
 managers = [FontManager() for _ in range(3)]
 for mgr in managers:
 mgr.load_font("tenrm", "cmr10")
 mgr_dvi, mgr_pdf, mgr_svg = managers

 def make_page() -> VlistNode:
 hbox = HlistNode(
 list=[
 CharNode(char=ord("H"), font_name="tenrm"),
 CharNode(char=ord("i"), font_name="tenrm"),
 ],
 width=0, height=655360, depth=0, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 return VlistNode(
 list=[hbox], width=0, height=655360, depth=0, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )

 # DVI
 dvi_buf = io.BytesIO()
 dw = DviWriter(dvi_buf, mgr_dvi)
 dw.shipout(1, make_page())
 dw.finalize()
 h_dvi = _dvi_first_set_char_h(dvi_buf.getvalue())

 # PDF — first "x y Td\n(Hi) Tj" operand (points, origin at 72pt).
 pdf_buf = io.BytesIO()
 pw = PdfWriter(pdf_buf, mgr_pdf)
 pw.shipout(1, make_page())
 pw.finalize()
 m = re.search(rb"\n([\d.]+) ([\d.]+) Td\n\(Hi\) Tj", pdf_buf.getvalue())
 assert m is not None, "PDF content stream missing (Hi) Tj"
 h_pdf = round((float(m.group(1)) - 72) * 65536)

 # SVG — first <use> placement now uses bare x/y attrs
 # rather than transform="translate(x,y)"; pre-scaled path data
 # makes <use> Chromium-renderable for off-baseline placements.
 svg_buf = io.BytesIO()
 sw = SvgWriter(svg_buf, mgr_svg)
 sw.shipout(1, make_page())
 sw.finalize()
 root = ET.fromstring(sw.get_bytes())
 first_use = root.find(f".//{_NS}use")
 assert first_use is not None, "SVG missing <use> for first glyph"
 x_attr = first_use.get("x")
 assert x_attr is not None, (
 f"SVG <use> missing x attribute: {first_use.attrib!r}"
 )
 h_svg = round((float(x_attr) - 72) * 65536)

 # 65536 sp = 1 pt ( AC-5 / AC-5 tolerance).
 assert abs(h_dvi - h_pdf) <= 65536, f"DVI vs PDF: {h_dvi} vs {h_pdf} sp"
 assert abs(h_dvi - h_svg) <= 65536, f"DVI vs SVG: {h_dvi} vs {h_svg} sp"
