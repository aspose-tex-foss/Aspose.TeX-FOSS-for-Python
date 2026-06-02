"""Integration tests for the presentation layer.

Tests TeXJob end-to-end with DviDevice, file output, options, and
backward compatibility of the deprecated TeXInterpreter.run().
"""
from __future__ import annotations

import io
import struct
import warnings
from pathlib import Path

from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

_DVI_PRE_OPCODE = 247
_NO_FORMAT = TeXOptions(load_format=False)


# ---------------------------------------------------------------------------
# TeXJob + DviDevice
# ---------------------------------------------------------------------------


class TestTeXJobDvi:
 def test_hello_world(self) -> None:
 """TeXJob + DviDevice produces valid DVI for 'Hello\\bye'."""
 source = StringInputSource("Hello\\bye")
 device = DviDevice()
 job = TeXJob(source, device, options=_NO_FORMAT)
 result = job.run()

 assert result is not None
 assert len(result) > 0
 assert result[0] == _DVI_PRE_OPCODE

 def test_matches_interpreter_run(self) -> None:
 """TeXJob + DviDevice output is byte-identical to deprecated run()."""
 from aspose_tex._engine.interpreter import TeXInterpreter

 tex_input = "Hello\\bye"

 # New API
 device = DviDevice()
 job = TeXJob(StringInputSource(tex_input), device, options=_NO_FORMAT)
 new_result = job.run()

 # Deprecated API (suppress warning)
 with warnings.catch_warnings():
 warnings.simplefilter("ignore", DeprecationWarning)
 interp = TeXInterpreter()
 old_result = interp.run(StringInputSource(tex_input))

 assert new_result == old_result

 def test_file_output(self, tmp_path: Path) -> None:
 """TeXJob with DviDevice(Path) writes file; run() returns None."""
 out_file = tmp_path / "out.dvi"
 source = StringInputSource("Hello\\bye")
 device = DviDevice(out_file)
 job = TeXJob(source, device, options=_NO_FORMAT)
 result = job.run()

 assert result is None
 assert out_file.exists()
 content = out_file.read_bytes()
 assert content[0] == _DVI_PRE_OPCODE

 def test_bytesio_output(self) -> None:
 """TeXJob with DviDevice(BytesIO()) returns bytes."""
 buf = io.BytesIO()
 source = StringInputSource("Hello\\bye")
 device = DviDevice(buf)
 job = TeXJob(source, device, options=_NO_FORMAT)
 result = job.run()

 assert result is not None
 assert result[0] == _DVI_PRE_OPCODE

 def test_default_device(self) -> None:
 """TeXJob with DviDevice() (no args) returns bytes."""
 source = StringInputSource("Hello\\bye")
 device = DviDevice()
 job = TeXJob(source, device, options=_NO_FORMAT)
 result = job.run()

 assert result is not None
 assert len(result) > 0

 def test_options_magnification(self) -> None:
 """TeXJob with magnification=1200 produces DVI with mag=1200 in preamble."""
 source = StringInputSource("Hello\\bye")
 device = DviDevice()
 opts = TeXOptions(magnification=1200, load_format=False)
 job = TeXJob(source, device, options=opts)
 result = job.run()

 assert result is not None
 # DVI preamble: opcode(1) + id(1) + num(4) + den(4) + mag(4) = offset 10
 mag = struct.unpack(">I", result[10:14])[0]
 assert mag == 1200


# ---------------------------------------------------------------------------
# Deprecated TeXInterpreter.run()
# ---------------------------------------------------------------------------


class TestInterpreterRunDeprecated:
 def test_emits_deprecation_warning(self) -> None:
 """TeXInterpreter.run() emits DeprecationWarning."""
 from aspose_tex._engine.interpreter import TeXInterpreter

 source = StringInputSource("Hello\\bye")
 interp = TeXInterpreter()
 with warnings.catch_warnings(record=True) as w:
 warnings.simplefilter("always")
 interp.run(source)
 dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
 assert len(dep_warnings) == 1
 assert "deprecated" in str(dep_warnings[0].message).lower()

 def test_still_produces_dvi(self) -> None:
 """Deprecated run() still returns valid DVI bytes."""
 from aspose_tex._engine.interpreter import TeXInterpreter

 source = StringInputSource("Hello\\bye")
 interp = TeXInterpreter()
 with warnings.catch_warnings():
 warnings.simplefilter("ignore", DeprecationWarning)
 result = interp.run(source)

 assert len(result) > 0
 assert result[0] == _DVI_PRE_OPCODE


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


class TestImports:
 def test_import_from_aspose_tex(self) -> None:
 """All public classes importable from aspose_tex."""
 from aspose_tex import ( # noqa: F401
 DviDevice,
 OutputDevice,
 OutputFormat,
 PdfDevice,
 SvgDevice,
 TeXJob,
 TeXOptions,
 )

 def test_import_from_presentation(self) -> None:
 """All public classes importable from aspose_tex.presentation."""
 from aspose_tex.presentation import ( # noqa: F401
 DviDevice,
 OutputDevice,
 OutputFormat,
 PdfDevice,
 SvgDevice,
 TeXJob,
 TeXOptions,
 create_input_source,
 )

 def test_py_typed_exists(self) -> None:
 """PEP 561 py.typed marker exists."""
 import aspose_tex

 pkg_dir = Path(aspose_tex.__file__).parent
 py_typed = pkg_dir / "py.typed"
 assert py_typed.exists()
