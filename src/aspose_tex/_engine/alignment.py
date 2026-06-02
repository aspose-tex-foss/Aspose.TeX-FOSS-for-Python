"""Alignment subsystem registration stubs.

Plain TeX defines macros whose bodies contain ``\\halign``, ``\\valign``,
``\\cr``, ``\\span``, ``\\omit``, and alignment-tab tokens. This module only
registers those primitives so macro bodies can load; real alignment execution
is not yet implemented.
"""
from __future__ import annotations

from collections.abc import Callable

from aspose_tex.exceptions import EngineError

STUB_ERROR_HALIGN = "\\halign execution is not yet implemented"
STUB_ERROR_VALIGN = "\\valign execution is not yet implemented"


def _exec_halign() -> None:
 """Raise the not-yet-implemented error for ``\\halign`` execution."""
 raise NotImplementedError(STUB_ERROR_HALIGN)


def _exec_valign() -> None:
 """Raise the not-yet-implemented error for ``\\valign`` execution."""
 raise NotImplementedError(STUB_ERROR_VALIGN)


def _exec_cr() -> None:
 """Raise the outside-alignment error for ``\\cr``."""
 raise EngineError("\\cr outside \\halign/\\valign")


def _exec_crcr() -> None:
 """Raise the outside-alignment error for ``\\crcr``."""
 raise EngineError("\\crcr outside \\halign/\\valign")


def _exec_noalign() -> None:
 """Raise the outside-alignment error for ``\\noalign``."""
 raise EngineError("\\noalign outside \\halign/\\valign")


def _exec_span() -> None:
 """Raise the outside-alignment error for ``\\span``."""
 raise EngineError("\\span outside \\halign/\\valign")


def _exec_omit() -> None:
 """Raise the outside-alignment error for ``\\omit``."""
 raise EngineError("\\omit outside \\halign/\\valign")


def build_stub_handlers() -> dict[str, Callable[[], None]]:
 """Return alignment primitive stubs keyed by control-sequence name.

 Returns:
 Mapping suitable for merging into ``TeXInterpreter._primitives``.
 """
 return {
 "halign": _exec_halign,
 "valign": _exec_valign,
 "cr": _exec_cr,
 "crcr": _exec_crcr,
 "noalign": _exec_noalign,
 "span": _exec_span,
 "omit": _exec_omit,
 }
