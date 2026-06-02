"""Integration tests for PdfDevice end-to-end.

Validates TeXJob + PdfDevice emits a valid PDF 1.4 file, supports file /
memory output, multi-page documents, embeds fonts self-containedly, and
keeps character positions consistent with the DVI reference.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import PdfDevice, TeXJob, TeXOptions

_NO_FORMAT = TeXOptions(load_format=False)

# ---------------------------------------------------------------------------
# Basic end-to-end
# ---------------------------------------------------------------------------

def test_texjob_pdf_hello_world() -> None:
 result = TeXJob(
 StringInputSource("Hello\\bye"), PdfDevice(), options=_NO_FORMAT,
 ).run()
 assert result is not None
 assert result.startswith(b"%PDF-1.4")
 assert result.endswith(b"%%EOF\n")


def test_texjob_pdf_file_output(tmp_path: Path) -> None:
 out = tmp_path / "out.pdf"
 result = TeXJob(
 StringInputSource("Hello\\bye"), PdfDevice(out), options=_NO_FORMAT,
 ).run()
 assert result is None
 assert out.exists()
 data = out.read_bytes()
 assert data.startswith(b"%PDF-1.4")


def test_texjob_pdf_multipage() -> None:
 # \eject forces a page break; two ejects → three pages; simpler: use
 # \vfill\eject repeated. Use \vskip to force two pages:
 tex = r"Page one\vfill\eject Page two\bye"
 pdf = TeXJob(StringInputSource(tex), PdfDevice(), options=_NO_FORMAT).run()
 assert pdf is not None
 m = re.search(rb"/Type /Pages[^>]*?/Count (\d+)", pdf)
 assert m is not None
 assert int(m.group(1)) >= 2


def test_texjob_pdf_bytesio_and_file_identical(tmp_path: Path) -> None:
 from aspose_tex._output.pdf_writer import PdfWriter

 # We need identical output across Path / BytesIO. The PDF contains a
 # timestamp-based /CreationDate, so we patch PdfWriter to freeze it.
 original_now = PdfWriter._now_pdf_date
 PdfWriter._now_pdf_date = lambda self: b"D:20260101000000Z" # type: ignore[method-assign]
 try:
 buf = io.BytesIO()
 TeXJob(
 StringInputSource("Hi\\bye"), PdfDevice(buf), options=_NO_FORMAT,
 ).run()
 out = tmp_path / "out.pdf"
 TeXJob(
 StringInputSource("Hi\\bye"), PdfDevice(out), options=_NO_FORMAT,
 ).run()
 assert buf.getvalue() == out.read_bytes()
 finally:
 PdfWriter._now_pdf_date = original_now # type: ignore[method-assign]


def test_pdf_fonts_embedded_self_contained() -> None:
 pdf = TeXJob(
 StringInputSource("A\\bye"), PdfDevice(), options=_NO_FORMAT,
 ).run()
 assert pdf is not None
 # Every Font object refers to a FontFile stream with /Length1 /Length2 /Length3.
 font_descriptors = re.findall(rb"/Type /FontDescriptor[^>]*?/FontFile (\d+) 0 R", pdf)
 assert font_descriptors
 for desc in font_descriptors:
 # The referenced FontFile object must contain the segment lengths.
 obj_marker = desc + b" 0 obj"
 start = pdf.find(obj_marker)
 assert start != -1
 end = pdf.find(b"endobj", start)
 segment = pdf[start:end]
 assert b"/Length1" in segment
 assert b"/Length2" in segment
 assert b"/Length3" in segment


def test_pdf_rule_renders_as_rectangle() -> None:
 tex = r"\hrule height 2pt width 10pt\bye"
 pdf = TeXJob(StringInputSource(tex), PdfDevice(), options=_NO_FORMAT).run()
 assert pdf is not None
 # Rule width 10pt, height 2pt → operands "... 10 2 re".
 assert re.search(rb"\d[\d. -]* 10 2 re\nf\n", pdf) is not None


# ---------------------------------------------------------------------------
# DVI ↔ PDF positional consistency (AC-5)
# ---------------------------------------------------------------------------

def test_texjob_pdf_positions_match_dvi() -> None:
 """Synthesize the same page box; feed to DviWriter and PdfWriter; verify
 that horizontal char cursors agree (converted to a common frame).

 Rationale: running the full TeX interpreter exercises both backends on
 the same shipout VlistNode. We compare the h-coord (in sp) of the first
 typeset character: PDF emits ``x y Td`` in points, DVI emits ``right``
 advances plus ``set_char``. In both, h_sp = (x_pdf - 72) * 65536.
 """
 import io as _io

 from aspose_tex._engine.nodes import CharNode, GlueSign, HlistNode, VlistNode
 from aspose_tex._engine.registers import GlueOrder
 from aspose_tex._fonts.font_manager import FontManager
 from aspose_tex._output.dvi_writer import DviWriter
 from aspose_tex._output.pdf_writer import PdfWriter

 mgr_pdf = FontManager()
 mgr_pdf.load_font("tenrm", "cmr10")
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

 # PDF
 pdf_buf = _io.BytesIO()
 pw = PdfWriter(pdf_buf, mgr_pdf)
 pw.shipout(1, make_page())
 pw.finalize()
 pdf = pdf_buf.getvalue()
 m = re.search(rb"\n([\d.]+) ([\d.]+) Td\n\(Hi\) Tj", pdf)
 assert m is not None
 pdf_x_pt = float(m.group(1))
 pdf_h_sp = round((pdf_x_pt - 72) * 65536)

 # DVI
 dvi_buf = _io.BytesIO()
 dw = DviWriter(dvi_buf, mgr_dvi)
 dw.shipout(1, make_page())
 dw.finalize()
 dvi = dvi_buf.getvalue()

 # Walk the first page's commands until we hit set_char for 'H' and
 # track h.
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
 assert abs(found_h - pdf_h_sp) <= 65536, (
 f"h mismatch: dvi={found_h} sp, pdf={pdf_h_sp} sp"
 )
