"""Public API: TeXJob, TeXOptions, OutputDevice hierarchy, input helpers.

This module is the user-facing entry point for aspose_tex. All classes
defined here are re-exported from :mod:`aspose_tex` for convenience.

See and for design rationale.
"""
from __future__ import annotations

import abc
import io
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
 from aspose_tex._fonts.font_manager import FontManager
 from aspose_tex._input.reader import InputSource

# ---------------------------------------------------------------------------
# OutputFormat enum
# ---------------------------------------------------------------------------


class OutputFormat(Enum):
 """Supported output formats.

 Example::

 fmt = OutputFormat.PDF
 """

 DVI = "dvi"
 PDF = "pdf"
 SVG = "svg"


# ---------------------------------------------------------------------------
# TeXOptions
# ---------------------------------------------------------------------------


@dataclass
class TeXOptions:
 r"""Configuration for a TeX processing job.

 All fields have sensible defaults; construct with keyword arguments.

 Attributes:
 job_name: Job name used in log messages and default output
 filenames. Default ``"texput"``.
 magnification: TeX magnification factor * 1000 (1000 = no
 magnification). Default ``1000``.
 extra_font_paths: Additional directories to search for TFM (and PFB)
 files, appended after the bundled data directory.
 Default empty list.
 load_format: Format to load before user input. ``"plain"`` loads
 the bundled Plain TeX source, while ``False`` or
 ``None`` skips format loading. Default ``"plain"``.
 In the current M3 workstream, pass ``False`` for
 runnable M2-style documents until the remaining
 Plain TeX cascade lands.
 extra_format_paths:
 Additional directories to search for format and
 ``\input`` files after bundled format data and
 before the current working directory.

 Example::

 opts = TeXOptions(
 job_name="myfile", magnification=1200, load_format=False
 )
 opts = TeXOptions(extra_font_paths=[Path("/usr/share/texmf/fonts")])
 """

 job_name: str = "texput"
 magnification: int = 1000
 extra_font_paths: list[Path] = field(default_factory=list)
 load_format: bool | str | None = "plain"
 extra_format_paths: list[Path] = field(default_factory=list)


# ---------------------------------------------------------------------------
# OutputDevice ABC
# ---------------------------------------------------------------------------


class OutputDevice(abc.ABC):
 """Abstract base class for all output devices.

 An ``OutputDevice`` wraps a format-specific backend writer and manages
 its destination (file path or memory buffer). The TeX engine calls
 ``shipout()`` for each completed page, and ``finalize()`` when the
 document ends.

 Subclasses must implement ``_create_backend()`` to instantiate their
 format-specific writer.

 Example::

 device = DviDevice(Path("output.dvi"))
 job = TeXJob(source, device, options=TeXOptions(load_format=False))
 job.run()
 """

 def __init__(self, destination: Path | io.BytesIO | None = None) -> None:
 """
 Args:
 destination: ``Path`` for file output, ``BytesIO`` for in-memory
 output, or ``None`` to auto-create a ``BytesIO``.
 """
 if destination is None:
 destination = io.BytesIO()
 self._destination = destination

 @property
 def destination(self) -> Path | io.BytesIO:
 """The output destination (read-only after construction)."""
 return self._destination

 @abc.abstractmethod
 def _create_backend(
 self,
 font_manager: FontManager,
 *,
 mag: int,
 ) -> object:
 """Create the format-specific backend writer.

 Called once by the engine before processing begins.
 The returned object must satisfy the ``ShipoutBackend`` protocol
 (i.e. have a ``shipout(page_number, box)`` method).

 Args:
 font_manager: The engine's font manager (for font lookups).
 mag: Magnification * 1000.

 Returns:
 A backend writer instance.
 """
 ...

 @abc.abstractmethod
 def finalize(self) -> None:
 """Finalize the output (write postamble, close files, etc.).

 Called once by the engine after all pages have been shipped out.
 """
 ...

 def get_bytes(self) -> bytes | None:
 """Return the output content as bytes, if available.

 Returns:
 Bytes content when destination is ``BytesIO``; ``None`` when
 destination is a file ``Path`` (content is already on disk).

 Raises:
 RuntimeError: If ``finalize()`` has not been called.
 """
 if isinstance(self._destination, io.BytesIO):
 return self._destination.getvalue()
 return None


# ---------------------------------------------------------------------------
# DviDevice
# ---------------------------------------------------------------------------


class DviDevice(OutputDevice):
 """DVI output device -- wraps ``DviWriter``.

 Example::

 from aspose_tex import TeXJob, TeXOptions, DviDevice
 from aspose_tex._input.reader import StringInputSource

 device = DviDevice()
 job = TeXJob(
 StringInputSource("Hello\\\\bye"),
 device,
 options=TeXOptions(load_format=False),
 )
 dvi_bytes = job.run()

 With file output::

 device = DviDevice(Path("output.dvi"))
 job = TeXJob(
 StringInputSource("Hello\\\\bye"),
 device,
 options=TeXOptions(load_format=False),
 )
 job.run()
 # output.dvi is written to disk
 """

 def __init__(self, destination: Path | io.BytesIO | None = None) -> None:
 """
 Args:
 destination: ``Path`` for file output, ``BytesIO`` for in-memory
 output, or ``None`` for automatic in-memory output.
 """
 super().__init__(destination)
 self._backend: DviWriter | None = None # type: ignore[name-defined] # noqa: F821

 def _create_backend(
 self,
 font_manager: FontManager,
 *,
 mag: int,
 ) -> object:
 """Create a ``DviWriter`` backend.

 Args:
 font_manager: For font definition lookups.
 mag: Magnification * 1000.

 Returns:
 Configured ``DviWriter`` instance.
 """
 from aspose_tex._output.dvi_writer import DviWriter

 self._backend = DviWriter(
 self._destination, font_manager, mag=mag,
 )
 return self._backend

 def finalize(self) -> None:
 """Write DVI postamble and close streams.

 Raises:
 RuntimeError: If no backend has been created (job not run).
 """
 if self._backend is None:
 raise RuntimeError(
 "DviDevice.finalize(): no backend (was the job run?)"
 )
 self._backend.finalize()

 def get_bytes(self) -> bytes | None:
 """Return DVI content as bytes.

 Returns:
 Bytes when destination is ``BytesIO``; ``None`` for file output.

 Raises:
 RuntimeError: If ``finalize()`` has not been called.
 """
 if self._backend is None:
 raise RuntimeError(
 "DviDevice.get_bytes(): no backend (was the job run?)"
 )
 if isinstance(self._destination, io.BytesIO):
 return self._backend.get_bytes()
 return None


# ---------------------------------------------------------------------------
# PdfDevice stub
# ---------------------------------------------------------------------------


class PdfDevice(OutputDevice):
 """PDF output device -- wraps ``PdfWriter``.

 Example::

 from aspose_tex import TeXJob, TeXOptions, PdfDevice
 from aspose_tex._input.reader import StringInputSource

 device = PdfDevice(Path("hello.pdf"))
 job = TeXJob(
 StringInputSource("Hello\\\\bye"),
 device,
 options=TeXOptions(load_format=False),
 )
 job.run()
 """

 def __init__(self, destination: Path | io.BytesIO | None = None) -> None:
 """
 Args:
 destination: ``Path`` for file output, ``BytesIO`` for in-memory
 output, or ``None`` for automatic in-memory output.
 """
 super().__init__(destination)
 self._backend: PdfWriter | None = None # type: ignore[name-defined] # noqa: F821

 def _create_backend(
 self,
 font_manager: FontManager,
 *,
 mag: int,
 ) -> object:
 """Create a ``PdfWriter`` backend.

 Args:
 font_manager: For font metric and PFB lookups.
 mag: Magnification * 1000.

 Returns:
 Configured ``PdfWriter`` instance.
 """
 from aspose_tex._output.pdf_writer import PdfWriter

 self._backend = PdfWriter(
 self._destination, font_manager, mag=mag,
 )
 return self._backend

 def finalize(self) -> None:
 """Write PDF font objects, page tree, xref and trailer; close streams.

 Raises:
 RuntimeError: If no backend has been created (job not run).
 """
 if self._backend is None:
 raise RuntimeError(
 "PdfDevice.finalize(): no backend (was the job run?)"
 )
 self._backend.finalize()

 def get_bytes(self) -> bytes | None:
 """Return PDF content as bytes.

 Returns:
 Bytes when destination is ``BytesIO``; ``None`` for file output.

 Raises:
 RuntimeError: If ``finalize()`` has not been called.
 """
 if self._backend is None:
 raise RuntimeError(
 "PdfDevice.get_bytes(): no backend (was the job run?)"
 )
 if isinstance(self._destination, io.BytesIO):
 return self._backend.get_bytes()
 return None


# ---------------------------------------------------------------------------
# SvgDevice stub
# ---------------------------------------------------------------------------


class SvgDevice(OutputDevice):
 """SVG output device -- wraps ``SvgWriter``.

 For SVG, the destination can be a base ``Path`` (pages written as
 ``base.svg`` or ``base-N.svg``), or ``BytesIO`` for in-memory output.

 Example::

 from aspose_tex import TeXJob, TeXOptions, SvgDevice
 from aspose_tex._input.reader import StringInputSource

 device = SvgDevice(Path("output/hello"))
 job = TeXJob(
 StringInputSource("Hello\\\\bye"),
 device,
 options=TeXOptions(load_format=False),
 )
 job.run()
 # produces output/hello.svg
 """

 def __init__(self, destination: Path | io.BytesIO | None = None) -> None:
 """
 Args:
 destination: ``Path`` for file output, ``BytesIO`` for in-memory
 output, or ``None`` for automatic in-memory output.
 """
 super().__init__(destination)
 self._backend: SvgWriter | None = None # type: ignore[name-defined] # noqa: F821

 def _create_backend(
 self,
 font_manager: FontManager,
 *,
 mag: int,
 ) -> object:
 """Create a ``SvgWriter`` backend.

 Args:
 font_manager: For font metric and PFB lookups.
 mag: Magnification * 1000.

 Returns:
 Configured ``SvgWriter`` instance.
 """
 from aspose_tex._output.svg_writer import SvgWriter

 self._backend = SvgWriter(
 self._destination, font_manager, mag=mag,
 )
 return self._backend

 def finalize(self) -> None:
 """Write SVG pages to destination.

 Raises:
 RuntimeError: If no backend has been created (job not run).
 """
 if self._backend is None:
 raise RuntimeError(
 "SvgDevice.finalize(): no backend (was the job run?)"
 )
 self._backend.finalize()

 def get_bytes(self) -> bytes | None:
 """Return SVG content as bytes (first page).

 Returns:
 Bytes when destination is ``BytesIO``; ``None`` for file output.

 Raises:
 RuntimeError: If ``finalize()`` has not been called.
 """
 if self._backend is None:
 raise RuntimeError(
 "SvgDevice.get_bytes(): no backend (was the job run?)"
 )
 if isinstance(self._destination, io.BytesIO):
 return self._backend.get_bytes()
 return None

 def get_all_pages(self) -> list[bytes] | None:
 """Return all SVG pages as a list of byte strings.

 Returns None if destination is a file path.
 Only valid after the job has run.
 """
 if self._backend is None:
 raise RuntimeError(
 "SvgDevice.get_all_pages(): no backend (was the job run?)"
 )
 if isinstance(self._destination, io.BytesIO):
 return self._backend.get_all_pages()
 return None


# ---------------------------------------------------------------------------
# TeXJob
# ---------------------------------------------------------------------------


class TeXJob:
 """Main entry point for processing TeX input.

 Combines an input source, an output device, and processing options into
 a single runnable job.

 Example::

 from aspose_tex import TeXJob, TeXOptions, DviDevice
 from aspose_tex._input.reader import StringInputSource

 source = StringInputSource("Hello, World!\\\\bye")
 device = DviDevice()
 job = TeXJob(source, device, options=TeXOptions(load_format=False))
 dvi_bytes = job.run()

 With options::

 opts = TeXOptions(
 job_name="hello", magnification=1200, load_format=False
 )
 job = TeXJob(source, device, options=opts)
 result = job.run()

 File output::

 device = DviDevice(Path("output.dvi"))
 job = TeXJob(source, device, options=TeXOptions(load_format=False))
 job.run() # returns None; output is on disk
 """

 def __init__(
 self,
 source: InputSource,
 device: OutputDevice,
 options: TeXOptions | None = None,
 ) -> None:
 """
 Args:
 source: TeX input (``FileInputSource`` or ``StringInputSource``).
 device: Output device (``DviDevice``, ``PdfDevice``, ``SvgDevice``).
 options: Processing options. ``None`` uses defaults.
 """
 self._source = source
 self._device = device
 self._options = options or TeXOptions()
 self._messages: list[str] = []

 @property
 def messages(self) -> list[str]:
 """Messages collected during the most recent run.

 The list is cleared at the start of each ``run()`` call. It includes
 entries produced by ``\\message``, ``\\write 16``, and
 ``\\errmessage``. ``\\write -1`` logs through the ``aspose_tex``
 logger but does not append here. The returned list is a copy.

 Returns:
 A copy of the message list so callers cannot mutate job state.
 """
 return list(self._messages)

 def run(self) -> bytes | None:
 """Process the TeX input and produce output.

 Returns:
 Output bytes when the device destination is ``BytesIO``;
 ``None`` when output is directed to a file.

 Raises:
 EngineError: On TeX processing errors.
 FontError: On font loading failures.
 NotImplementedError: If the device backend is not yet implemented.
 """
 from aspose_tex._engine.interpreter import TeXInterpreter

 self._messages.clear()
 interpreter = TeXInterpreter(
 extra_font_paths=self._options.extra_font_paths,
 extra_format_paths=self._options.extra_format_paths,
 load_format=self._options.load_format,
 messages=self._messages,
 job_name=self._options.job_name,
 )
 interpreter.run_with_device(
 self._source,
 self._device,
 mag=self._options.magnification,
 )
 return self._device.get_bytes()


# ---------------------------------------------------------------------------
# Input convenience function
# ---------------------------------------------------------------------------


def create_input_source(source: Path | str | bytes) -> InputSource:
 """Create an ``InputSource`` from a file path, string, or bytes.

 This is a convenience factory for users who don't want to import
 the specific input source classes.

 Args:
 source: A ``Path`` to a ``.tex`` file, a TeX string, or TeX
 content as ``bytes``.

 Returns:
 A ``FileInputSource`` or ``StringInputSource``.

 Raises:
 TypeError: If *source* is not a supported type.

 Example::

 from aspose_tex.presentation import create_input_source
 src = create_input_source("Hello\\\\bye")
 src = create_input_source(Path("doc.tex"))
 src = create_input_source(b"Hello\\\\bye")
 """
 from aspose_tex._input.reader import FileInputSource, StringInputSource

 if isinstance(source, Path):
 return FileInputSource(source)
 if isinstance(source, (str, bytes)):
 return StringInputSource(source)
 raise TypeError(
 f"Expected Path, str, or bytes; got {type(source).__name__}"
 )
