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
 create_input_source(42) # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# OutputDevice base class
# ---------------------------------------------------------------------------


class TestOutputDeviceBase:
 def test_default_destination_is_bytesio(self) -> None:
 device = DviDevice()
 assert isinstance(device._destination, io.BytesIO)
