"""Unit tests for the presentation layer.

Tests TeXOptions, OutputFormat, OutputDevice, DviDevice, PdfDevice, SvgDevice,
and create_input_source in isolation — no TeX processing.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from aspose_tex.presentation import (
    DviDevice,
    OutputFormat,
    PdfDevice,
    SvgDevice,
    TeXJob,
    TeXOptions,
    create_input_source,
)

# ---------------------------------------------------------------------------
# TeXOptions
# ---------------------------------------------------------------------------


class TestTeXOptions:
    def test_defaults(self) -> None:
        opts = TeXOptions()
        assert opts.job_name == "texput"
        assert opts.magnification == 1000
        assert opts.extra_font_paths == []
        assert opts.load_format == "plain"
        assert opts.extra_format_paths == []

    def test_custom_values(self) -> None:
        opts = TeXOptions(
            job_name="foo",
            magnification=1200,
            extra_font_paths=[Path("/usr/share/texmf/fonts")],
            load_format=False,
            extra_format_paths=[Path("/usr/share/texmf/tex")],
        )
        assert opts.job_name == "foo"
        assert opts.magnification == 1200
        assert opts.extra_font_paths == [Path("/usr/share/texmf/fonts")]
        assert opts.load_format is False
        assert opts.extra_format_paths == [Path("/usr/share/texmf/tex")]


# ---------------------------------------------------------------------------
# OutputFormat
# ---------------------------------------------------------------------------


class TestOutputFormat:
    def test_dvi_value(self) -> None:
        assert OutputFormat.DVI.value == "dvi"

    def test_pdf_value(self) -> None:
        assert OutputFormat.PDF.value == "pdf"

    def test_svg_value(self) -> None:
        assert OutputFormat.SVG.value == "svg"


# ---------------------------------------------------------------------------
# DviDevice
# ---------------------------------------------------------------------------


class TestDviDevice:
    def test_default_destination_is_bytesio(self) -> None:
        device = DviDevice()
        assert isinstance(device.destination, io.BytesIO)

    def test_path_destination(self) -> None:
        device = DviDevice(Path("out.dvi"))
        assert device.destination == Path("out.dvi")

    def test_bytesio_destination(self) -> None:
        buf = io.BytesIO()
        device = DviDevice(buf)
        assert device.destination is buf

    def test_finalize_without_run_raises(self) -> None:
        device = DviDevice()
        with pytest.raises(RuntimeError, match="no backend"):
            device.finalize()

    def test_get_bytes_without_run_raises(self) -> None:
        device = DviDevice()
        with pytest.raises(RuntimeError, match="no backend"):
            device.get_bytes()


# ---------------------------------------------------------------------------
# PdfDevice
# ---------------------------------------------------------------------------


class TestPdfDevice:
    def test_default_destination_is_bytesio(self) -> None:
        device = PdfDevice()
        assert isinstance(device.destination, io.BytesIO)

    def test_path_destination(self) -> None:
        device = PdfDevice(Path("out.pdf"))
        assert device.destination == Path("out.pdf")

    def test_bytesio_destination(self) -> None:
        buf = io.BytesIO()
        device = PdfDevice(buf)
        assert device.destination is buf

    def test_finalize_without_run_raises(self) -> None:
        device = PdfDevice()
        with pytest.raises(RuntimeError, match="no backend"):
            device.finalize()

    def test_get_bytes_without_run_raises(self) -> None:
        device = PdfDevice()
        with pytest.raises(RuntimeError, match="no backend"):
            device.get_bytes()


# ---------------------------------------------------------------------------
# SvgDevice
# ---------------------------------------------------------------------------


class TestSvgDevice:
    def test_default_destination_is_bytesio(self) -> None:
        device = SvgDevice()
        assert isinstance(device.destination, io.BytesIO)

    def test_path_destination(self) -> None:
        device = SvgDevice(Path("out"))
        assert device.destination == Path("out")

    def test_bytesio_destination(self) -> None:
        buf = io.BytesIO()
        device = SvgDevice(buf)
        assert device.destination is buf

    def test_finalize_without_run_raises(self) -> None:
        device = SvgDevice()
        with pytest.raises(RuntimeError, match="no backend"):
            device.finalize()

    def test_get_bytes_without_run_raises(self) -> None:
        device = SvgDevice()
        with pytest.raises(RuntimeError, match="no backend"):
            device.get_bytes()

    def test_get_all_pages_without_run_raises(self) -> None:
        device = SvgDevice()
        with pytest.raises(RuntimeError, match="no backend"):
            device.get_all_pages()


# ---------------------------------------------------------------------------
# page_size configuration
# ---------------------------------------------------------------------------


class TestDevicePageSize:
    """Device-level page_size wiring for PdfDevice / SvgDevice.

    End-to-end MediaBox / viewBox assertions plus the construction-time
    ValueError contract (page_size is resolved in __init__, so a bad value
    raises from the constructor, before any job runs).
    """

    _NO_FORMAT = TeXOptions(load_format=False)

    # -- resolution stored on the device (plumbing) ----------------------

    def test_pdf_default_is_letter(self) -> None:
        assert PdfDevice()._page_size_pt == (612.0, 792.0)

    def test_pdf_preset_stored(self) -> None:
        assert PdfDevice(page_size="a4")._page_size_pt == (595.276, 841.89)

    def test_svg_preset_stored(self) -> None:
        assert SvgDevice(page_size="a4")._page_size_pt == (595.276, 841.89)

    def test_pdf_explicit_tuple_stored(self) -> None:
        assert PdfDevice(page_size=(612, 1008))._page_size_pt == (612.0, 1008.0)

    def test_preset_case_insensitive(self) -> None:
        assert PdfDevice(page_size="A4")._page_size_pt == (595.276, 841.89)

    # -- end-to-end /MediaBox (AC-1, AC-2, AC-6) -------------------------

    def _run_pdf(self, **kwargs) -> bytes:
        from aspose_tex._input.reader import StringInputSource

        result = TeXJob(
            StringInputSource("Hello\\bye"),
            PdfDevice(**kwargs),
            options=self._NO_FORMAT,
        ).run()
        assert result is not None
        return result

    def test_pdf_mediabox_a4(self) -> None:
        assert b"/MediaBox [0 0 595.276 841.89]" in self._run_pdf(page_size="a4")

    def test_pdf_mediabox_explicit_legal_tuple(self) -> None:
        pdf = self._run_pdf(page_size=(612, 1008))
        assert b"/MediaBox [0 0 612 1008]" in pdf

    def test_pdf_mediabox_default_unchanged(self) -> None:
        # AC-6: omitting page_size keeps US Letter, byte-for-byte with today.
        assert b"/MediaBox [0 0 612 792]" in self._run_pdf()

    # -- end-to-end SVG (AC-3) -------------------------------------------

    def test_svg_a4_threaded_into_writer(self) -> None:
        # AC-3: SVG uses a content-tight viewBox, so a content-full
        # page does NOT surface the paper size in its root attributes.  The
        # device-level guarantee is that the configured size is threaded into
        # the writer; the empty-page fallback rendering (viewBox == page size)
        # is covered by test_output_svg_writer's
        # test_svg_dimensions_empty_page_custom_page_size.  See
        # Context 3 — do not "fix" this to assert A4 on a content-full page.
        from aspose_tex._fonts.font_manager import FontManager

        device = SvgDevice(page_size="a4")
        backend = device._create_backend(FontManager(), mag=1000)
        assert backend._page_width_pt == 595.276
        assert backend._page_height_pt == 841.89

    def test_pdf_a4_threaded_into_writer(self) -> None:
        from aspose_tex._fonts.font_manager import FontManager

        device = PdfDevice(page_size="a4")
        backend = device._create_backend(FontManager(), mag=1000)
        assert backend._page_width_pt == 595.276
        assert backend._page_height_pt == 841.89

    # -- error contract at construction (AC-5) ---------------------------

    def test_pdf_unknown_preset_raises_at_construction(self) -> None:
        with pytest.raises(ValueError) as exc:
            PdfDevice(page_size="foolscap")
        msg = str(exc.value)
        assert "foolscap" in msg
        assert "a4" in msg  # lists valid presets

    def test_svg_unknown_preset_raises_at_construction(self) -> None:
        with pytest.raises(ValueError, match="foolscap"):
            SvgDevice(page_size="foolscap")

    @pytest.mark.parametrize("bad", [(0, 100), (100,), ("x", "y"), (True, 100)])
    def test_pdf_malformed_tuple_raises(self, bad) -> None:
        with pytest.raises(ValueError):
            PdfDevice(page_size=bad)

    # -- backward compatibility (AC-8) -----------------------------------

    def test_positional_construction_still_works(self) -> None:
        buf = io.BytesIO()
        assert PdfDevice(buf).destination is buf
        assert SvgDevice(buf).destination is buf

    def test_public_import_surface_unchanged(self) -> None:
        import aspose_tex

        for name in (
            "TeXJob", "TeXOptions", "DviDevice", "PdfDevice", "SvgDevice",
            "OutputDevice", "OutputFormat", "InputSource", "FileInputSource",
            "StringInputSource", "create_input_source",
        ):
            assert hasattr(aspose_tex, name)


# ---------------------------------------------------------------------------
# create_input_source
# ---------------------------------------------------------------------------


class TestCreateInputSource:
    def test_string_input(self) -> None:
        from aspose_tex._input.reader import StringInputSource

        src = create_input_source("hello")
        assert isinstance(src, StringInputSource)

    def test_bytes_input(self) -> None:
        from aspose_tex._input.reader import StringInputSource

        src = create_input_source(b"hello")
        assert isinstance(src, StringInputSource)

    def test_path_input(self) -> None:
        from aspose_tex._input.reader import FileInputSource

        src = create_input_source(Path("f.tex"))
        assert isinstance(src, FileInputSource)

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(TypeError, match="Expected Path, str, or bytes"):
            create_input_source(42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# OutputDevice base class
# ---------------------------------------------------------------------------


class TestOutputDeviceBase:
    def test_default_destination_is_bytesio(self) -> None:
        device = DviDevice()
        assert isinstance(device._destination, io.BytesIO)
