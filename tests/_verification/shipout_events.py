"""Capture exact glyph/font/rule events before PDF/SVG coordinate serialization."""
from aspose_tex import DviDevice, PdfDevice, StringInputSource, SvgDevice, TeXJob
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _tfm_width


def dvi_events(data):
    """Read full-advance DVI glyph, rule and font events."""
    fonts, rules = [], []
    width = _tfm_width()

    def char_width(font, code):
        fonts.append([font, code])
        return width(font, code)

    pages = walk_chars_with_positions(data, char_width, advance_rules=True, rule_events=rules)
    return {"glyphs": [[list(g) for g in page] for page in pages],
            "rules": [list(r) for r in rules], "fonts": fonts}


def compile_events(source, backend, monkeypatch):
    """Compile unchanged source and capture page-partitioned events in sp."""
    pages, fonts, rules = [], [], []
    if backend == "pdf":
        from aspose_tex._output.pdf_writer import PdfWriter
        flush, rect, shipout = PdfWriter._flush_text_run, PdfWriter._emit_rect, PdfWriter.shipout

        def capture_page(writer, *args, **kwargs):
            pages.append([])
            return shipout(writer, *args, **kwargs)

        def capture(writer):
            if writer._run_font is not None:
                h, v = writer._run_h_sp, writer._run_v_sp
                for code in writer._run_chars:
                    pages[-1].append([code, h, v])
                    fonts.append([writer._run_font.tfm_name, code])
                    h += writer._run_font.metrics.char_metrics(code).width
            flush(writer)

        def capture_rect(writer, h, top, width, height):
            rules.append([h, top + height, height, width])
            rect(writer, h, top, width, height)

        monkeypatch.setattr(PdfWriter, "shipout", capture_page)
        monkeypatch.setattr(PdfWriter, "_flush_text_run", capture)
        monkeypatch.setattr(PdfWriter, "_emit_rect", capture_rect)
    elif backend == "svg":
        from aspose_tex._output.svg_writer import SvgWriter
        shipout = SvgWriter.shipout

        def capture_page(writer, *args, **kwargs):
            result = shipout(writer, *args, **kwargs)
            pages.append([[code, h, v] for _, code, h, v in writer._char_placements])
            fonts.extend([[font.tfm_name, code] for font, code, _, _ in writer._char_placements])
            rules.extend([[h, top + height, height, width]
                          for h, top, width, height in writer._rule_placements])
            return result

        monkeypatch.setattr(SvgWriter, "shipout", capture_page)
    device = {"dvi": DviDevice, "svg": SvgDevice, "pdf": PdfDevice}[backend]()
    data = TeXJob(StringInputSource(source), device).run()
    return dvi_events(data) if backend == "dvi" else {"glyphs": pages, "rules": rules, "fonts": fonts}
