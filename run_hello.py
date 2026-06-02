"""M2 smoke: drive hello.tex and smoke_m2.tex through the public API.

Generates DVI, PDF and SVG outputs via ``TeXJob`` + ``DviDevice`` /
``PdfDevice`` / ``SvgDevice``. Runs each job in
memory, then writes the resulting bytes to ``testdata/`` so the byte
payload is deterministic across invocations (SvgWriter, when given a
``Path`` destination, picks the file name; we pin it explicitly here).

Outputs written:
 testdata/hello_ours.dvi
 testdata/hello_ours.pdf
 testdata/hello_ours.svg (1-page document)
 testdata/smoke_m2_ours.dvi
 testdata/smoke_m2_ours.pdf
 testdata/smoke_m2_ours-1.svg (multi-page: one file per page)
 testdata/smoke_m2_ours-2.svg
"""

from __future__ import annotations

from pathlib import Path

from aspose_tex import (
 DviDevice,
 FileInputSource,
 PdfDevice,
 SvgDevice,
 TeXJob,
)
from aspose_tex._output.pdf_writer import PdfWriter

# Freeze the PDF /CreationDate so running the script twice yields
# byte-identical outputs (AC-2). The real timestamp is otherwise embedded
# in both /CreationDate and the /ID hash; see PdfWriter._now_pdf_date.
PdfWriter._now_pdf_date = lambda self: b"D:20260101000000Z" # type: ignore[method-assign]


def _render(tex_path: Path, out_base: Path) -> None:
 """Run *tex_path* through all three devices and write outputs.

 Args:
 tex_path: Source ``.tex`` file.
 out_base: Output base path (e.g. ``testdata/hello_ours``); the
 extension is appended per device.
 """
 # DVI
 dvi_dev = DviDevice()
 TeXJob(FileInputSource(tex_path), dvi_dev).run()
 out_dvi = out_base.with_suffix(".dvi")
 out_dvi.write_bytes(dvi_dev.get_bytes() or b"")
 print(f"OK DVI {len(dvi_dev.get_bytes() or b''):>7} bytes -> {out_dvi}")

 # PDF
 pdf_dev = PdfDevice()
 TeXJob(FileInputSource(tex_path), pdf_dev).run()
 out_pdf = out_base.with_suffix(".pdf")
 out_pdf.write_bytes(pdf_dev.get_bytes() or b"")
 print(f"OK PDF {len(pdf_dev.get_bytes() or b''):>7} bytes -> {out_pdf}")

 # SVG — always through in-memory device so we control file names and
 # so that running the script twice yields identical bytes on disk.
 svg_dev = SvgDevice()
 TeXJob(FileInputSource(tex_path), svg_dev).run()
 pages = svg_dev.get_all_pages() or []
 if len(pages) == 1:
 out_svg = out_base.with_suffix(".svg")
 out_svg.write_bytes(pages[0])
 print(f"OK SVG {len(pages[0]):>7} bytes -> {out_svg}")
 else:
 for i, page_bytes in enumerate(pages, 1):
 out_svg = out_base.parent / f"{out_base.name}-{i}.svg"
 out_svg.write_bytes(page_bytes)
 print(f"OK SVG {len(page_bytes):>7} bytes -> {out_svg}")


def main() -> None:
 testdata = Path("testdata")
 samples = [
 (testdata / "hello.tex", testdata / "hello_ours"),
 (testdata / "smoke_m2.tex", testdata / "smoke_m2_ours"),
 ]
 for tex_path, out_base in samples:
 if not tex_path.exists():
 print(f"SKIP missing input: {tex_path}")
 continue
 print(f"--- {tex_path} ---")
 _render(tex_path, out_base)


if __name__ == "__main__":
 main()
