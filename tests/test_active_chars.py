""" active-character dispatch tests."""
from __future__ import annotations

import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice


class _CaptureParagraphInterpreter(TeXInterpreter):
 def __init__(self) -> None:
 super().__init__()
 self.captured_paragraphs: list[list] = []

 def _end_paragraph(self) -> None:
 if self._par_list is not None:
 self.captured_paragraphs.append(self._par_list.nodes)
 super()._end_paragraph()


def _run_capture(tex: str) -> _CaptureParagraphInterpreter:
 interp = _CaptureParagraphInterpreter()
 interp.run_with_device(StringInputSource(tex), DviDevice())
 return interp


def _paragraph_text(interp: _CaptureParagraphInterpreter, idx: int = 0) -> str:
 return "".join(
 chr(node.char)
 for node in interp.captured_paragraphs[idx]
 if isinstance(node, CharNode)
 )


class TestActiveCharBasic:
 def test_active_char_macro_dispatches(self) -> None:
 interp = _run_capture(r"\catcode`\~=13 \def~{X}\noindent~\par\bye")

 assert _paragraph_text(interp) == "X"

 def test_default_catcode_stays_non_active(self) -> None:
 interp = _run_capture(r"\noindent!\par\bye")

 assert _paragraph_text(interp) == "!"


class TestActiveCharCharLet:
 def test_active_char_let_to_control_sequence_dispatches(self) -> None:
 interp = _run_capture(r"\catcode`\~=13 \let~=\par \noindent a~\noindent b\par\bye")

 assert _paragraph_text(interp, 0) == "a"
 assert _paragraph_text(interp, 1) == "b"


class TestActiveCharUndefined:
 def test_undefined_active_char_raises(self) -> None:
 with pytest.raises(EngineError, match="Undefined active character: !"):
 _run_capture(r"\catcode`\!=13 \noindent!\bye")


class TestActiveCharGroupScope:
 def test_active_char_definition_restores_with_group(self) -> None:
 interp = _run_capture(r"{\catcode`\!=13 \def!{X}}\noindent!\par\bye")

 assert _paragraph_text(interp) == "!"
