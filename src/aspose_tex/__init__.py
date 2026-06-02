"""aspose_tex — pure-Python TeX/LaTeX processing library."""

__version__ = "26.5"

import logging

from aspose_tex._input.reader import FileInputSource, InputSource, StringInputSource
from aspose_tex.presentation import (
 DviDevice,
 OutputDevice,
 OutputFormat,
 PdfDevice,
 SvgDevice,
 TeXJob,
 TeXOptions,
 create_input_source,
)

_logger = logging.getLogger("aspose_tex")
if not any(isinstance(handler, logging.NullHandler) for handler in _logger.handlers):
 _logger.addHandler(logging.NullHandler())

__all__ = [
 "DviDevice",
 "FileInputSource",
 "InputSource",
 "OutputDevice",
 "OutputFormat",
 "PdfDevice",
 "StringInputSource",
 "SvgDevice",
 "TeXJob",
 "TeXOptions",
 "__version__",
 "create_input_source",
]
