"""Regression tests for the parskip-before-first-box guard."""
from __future__ import annotations

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode, GlueNode, HlistNode
from aspose_tex._engine.registers import GlueOrder
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice


def _initialized_interpreter() -> TeXInterpreter:
 interp = TeXInterpreter()
 interp.run_with_device(StringInputSource(""), DviDevice())
 return interp


def _end_one_letter_paragraph(interp: TeXInterpreter, char: str) -> None:
 interp._begin_paragraph(indent=False)
 interp._append_to_hlist(CharNode(ord(char), "tenrm"))
 interp._end_paragraph()


def _is_plain_parskip(node: object) -> bool:
 if not isinstance(node, GlueNode):
 return False
 glue = node.glue
 return (
 glue.width == 0
 and glue.stretch == 65_536
 and glue.stretch_order == GlueOrder.NORMAL
 and glue.shrink == 0
 and glue.shrink_order == GlueOrder.NORMAL
 )


def test_parskip_suppressed_before_first_box_on_page() -> None:
 """First paragraph on a page does not receive leading parskip glue."""
 interp = _initialized_interpreter()

 _end_one_letter_paragraph(interp, "A")

 assert not any(_is_plain_parskip(node) for node in interp._page_builder._mvl)


def test_parskip_emitted_after_first_box_on_page() -> None:
 """Second paragraph on a page receives parskip before interline glue."""
 interp = _initialized_interpreter()
 _end_one_letter_paragraph(interp, "A")

 _end_one_letter_paragraph(interp, "B")

 assert _is_plain_parskip(interp._page_builder._mvl[2])


def test_zero_width_stretch_parskip_is_not_optimized_away_after_first_box() -> None:
 """Plain TeX's 0pt plus 1pt parskip still emits after the first box."""
 interp = _initialized_interpreter()
 _end_one_letter_paragraph(interp, "A")

 _end_one_letter_paragraph(interp, "B")

 assert [type(node) for node in interp._page_builder._mvl] == [
 GlueNode,
 HlistNode,
 GlueNode,
 GlueNode,
 HlistNode,
 ]
