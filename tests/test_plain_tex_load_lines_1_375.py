"""Plain TeX lines 1-375 / AC-8 load regression."""
from __future__ import annotations

from pathlib import Path

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice

_PLAIN_TEX_PATH = Path("src/aspose_tex/data/format/plain.tex")
_PLAIN_TEX_LINES_1_375 = "\n".join(
 _PLAIN_TEX_PATH.read_text(encoding="utf-8").splitlines()[:375]
) + "\n"


def test_plain_tex_lines_1_375_loads_without_engine_errors() -> None:
 """Plain.tex lines 1-375 load through the interpreter without engine errors.

 AC-8 contract: the slice must parse and dispatch without raising
 ``EngineError`` (in particular "Undefined control sequence") or
 ``NotImplementedError``. The contract is "loads", not "executes
 meaningfully" — math primitives may stay no-ops at this stage (
 covers them).
 """
 interp = TeXInterpreter()
 interp.run_with_device(StringInputSource(_PLAIN_TEX_LINES_1_375), DviDevice())
