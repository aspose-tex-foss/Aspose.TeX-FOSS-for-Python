""" marks integration tests."""
from __future__ import annotations

from aspose_tex._engine.marks import MarksRegistry
from aspose_tex._engine.nodes import GlueSign, MarkNode, PenaltyNode, VlistNode
from aspose_tex._engine.page_builder import OutputRoutineBase, PageBuilder, PageBuilderConfig
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken


class _Backend:
 def shipout(self, page_number, box) -> None:
 pass


class _Routine(OutputRoutineBase):
 def __init__(self, marks: MarksRegistry) -> None:
 self._marks = marks
 self.snapshots: list[tuple[str, str, str]] = []

 def execute(self, body_nodes: list, page_number: int, backend) -> None:
 self.snapshots.append((
 _text(self._marks.top_mark()),
 _text(self._marks.first_mark()),
 _text(self._marks.bot_mark()),
 ))
 backend.shipout(page_number, VlistNode([], 0, 0, 0, 0, GlueSign.NORMAL, GlueOrder.NORMAL, 0.0))


def _config() -> PageBuilderConfig:
 return PageBuilderConfig(
 vsize=65_536,
 topskip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 max_depth=0,
 baselineskip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 lineskip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 lineskiplimit=0,
 max_dead_cycles=25,
 )


def _tokens(text: str) -> tuple[CharToken, ...]:
 return tuple(CharToken(ch, Catcode.LETTER) for ch in text)


def _text(tokens) -> str:
 return "".join(tok.char for tok in tokens)


def test_page_builder_records_marks_before_output_and_resets_after() -> None:
 marks = MarksRegistry()
 routine = _Routine(marks)
 builder = PageBuilder(_config(), _Backend(), routine, marks_registry=marks)

 builder.contribute(MarkNode(_tokens("A")))
 builder.contribute(MarkNode(_tokens("B")))
 builder.contribute(PenaltyNode(-10_000))

 assert routine.snapshots == [("", "A", "B")]
 assert _text(marks.top_mark()) == "B"
 assert marks.first_mark() == ()
 assert marks.bot_mark() == ()


def test_capture_split_records_first_and_bottom_split_marks() -> None:
 marks = MarksRegistry()

 marks.capture_split([MarkNode(_tokens("A")), MarkNode(_tokens("B"))])

 assert _text(marks.split_first_mark()) == "A"
 assert _text(marks.split_bot_mark()) == "B"
