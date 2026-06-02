"""Project-wide exception hierarchy for aspose_tex."""


class AsposeTeXError(Exception):
 """Base exception for all aspose_tex errors."""


class InputError(AsposeTeXError):
 """Raised for input reading failures (file not found, stack underflow, etc.)."""


class EngineError(AsposeTeXError):
 """Raised for TeX engine errors (infinite recursion, undefined register, etc.)."""


class FontError(AsposeTeXError):
 """Raised for font-related failures (TFM not found, corrupt file, invalid char, etc.)."""
