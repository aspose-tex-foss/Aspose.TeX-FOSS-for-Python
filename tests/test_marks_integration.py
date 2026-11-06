""" marks integration tests."""
from __future__ import annotations

from aspose_tex._engine.marks import MarksRegistry
from aspose_tex._engine.nodes import GlueSign, HlistNode, MarkNode, PenaltyNode, VlistNode
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


def test_page_builder_records_marks_before_output_and_keeps_until_next_fire_up() -> None:
    marks = MarksRegistry()
    routine = _Routine(marks)
    builder = PageBuilder(_config(), _Backend(), routine, marks_registry=marks)

    # §1000: a page holding only marks never fires, so a box comes first.
    builder.contribute(HlistNode(
        list=[], width=0, height=0, depth=0, shift_amount=0,
        glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
    ))
    builder.contribute(MarkNode(_tokens("A")))
    builder.contribute(MarkNode(_tokens("B")))
    builder.contribute(PenaltyNode(-10_000))
    builder.build_page()

    assert routine.snapshots == [("", "A", "B")]
    assert marks.top_mark() == ()
    assert _text(marks.first_mark()) == "A"
    assert _text(marks.bot_mark()) == "B"
    builder.contribute(HlistNode([], 0, 0, 0, 0, GlueSign.NORMAL, GlueOrder.NORMAL, 0.0))
    builder.contribute(PenaltyNode(-10_000))
    builder.build_page()
    assert routine.snapshots == [("", "A", "B"), ("B", "B", "B")]


def test_fire_up_sequence_and_split_retention():
    marks = MarksRegistry()
    marks.capture_split([MarkNode(_tokens('S')), MarkNode(_tokens('T'))])
    for page, expected in [(['A', 'B'], ('', 'A', 'B')),
                           ([], ('B', 'B', 'B')), (['C'], ('B', 'C', 'C'))]:
        marks.fire_up([MarkNode(_tokens(text)) for text in page])
        assert tuple(_text(value) for value in (marks.top_mark(), marks.first_mark(), marks.bot_mark())) == expected
        assert _text(marks.split_first_mark()) == 'S'
        assert _text(marks.split_bot_mark()) == 'T'


def test_empty_mark_is_not_null():
    marks = MarksRegistry()
    marks.fire_up([MarkNode(()), MarkNode(_tokens('X'))])
    assert marks.first_mark() == ()
    assert _text(marks.bot_mark()) == 'X'
    marks.fire_up([MarkNode(())])
    marks.fire_up([])
    assert marks.top_mark() == marks.first_mark() == marks.bot_mark() == ()
    assert marks._top is not None


def test_capture_split_records_first_and_bottom_split_marks() -> None:
    marks = MarksRegistry()

    marks.capture_split([MarkNode(_tokens("A")), MarkNode(_tokens("B"))])

    assert _text(marks.split_first_mark()) == "A"
    assert _text(marks.split_bot_mark()) == "B"
