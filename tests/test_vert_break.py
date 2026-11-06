"""Unit tests for ``vert_break`` and ``prune_page_top`` (TeX §968-§977,)."""
from __future__ import annotations

from aspose_tex._engine.nodes import (
    INF_PENALTY,
    GlueNode,
    GlueSign,
    HlistNode,
    KernNode,
    MarkNode,
    PenaltyNode,
    RuleNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._engine.vert_break import precedes_break, prune_page_top, vert_break

_PT = 65_536


def _box(height: int, depth: int = 0) -> HlistNode:
    return HlistNode(
        list=[], width=0, height=height * _PT, depth=depth * _PT, shift_amount=0,
        glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
    )


def _glue(width: int = 0, stretch: int = 0, order: GlueOrder = GlueOrder.NORMAL) -> GlueNode:
    return GlueNode(Glue(width * _PT, stretch * _PT, order, 0, GlueOrder.NORMAL))


class TestVertBreak:
    def test_cheapest_penalty_wins(self) -> None:
        nodes = [_box(20), _glue(stretch=10), _box(20), PenaltyNode(-100), _box(20), _glue(), _box(20)]
        # glue@1: no stretch yet -> deplorable; penalty@3: badness 100 - 100 = 0;
        # glue@5 is past 50pt -> awful, the search stops.
        assert vert_break(nodes, 50 * _PT, 0) == (3, 40 * _PT)

    def test_ties_go_to_the_later_breakpoint(self) -> None:
        nodes = [_box(10), _glue(stretch=1, order=GlueOrder.FIL), _box(10),
                 PenaltyNode(0), PenaltyNode(0), _box(10)]
        assert vert_break(nodes, 25 * _PT, 0) == (4, 20 * _PT)

    def test_the_implicit_end_is_returned_as_none(self) -> None:
        assert vert_break([_box(10), _glue(), _box(10)], 100 * _PT, 0) == (None, 20 * _PT)

    def test_glue_after_a_penalty_is_not_a_breakpoint(self) -> None:
        nodes = [_box(10), PenaltyNode(INF_PENALTY), _glue(), _box(10), _box(10)]
        assert vert_break(nodes, 15 * _PT, 0) == (None, 30 * _PT)
        # Without the penalty the glue is the only (deplorable) break.
        assert vert_break([_box(10), _glue(), _box(10), _box(10)], 15 * _PT, 0) == (1, 10 * _PT)

    def test_kern_breaks_only_before_glue(self) -> None:
        assert vert_break([_box(10), KernNode(2 * _PT, True)], 100 * _PT, 0) == (None, 12 * _PT)
        nodes = [_box(10), KernNode(2 * _PT, True), _glue(), _box(10)]
        assert vert_break(nodes, 11 * _PT, 0) == (1, 10 * _PT)

    def test_excess_depth_moves_into_the_height(self) -> None:
        nodes = [_box(10, depth=5), PenaltyNode(0), _box(10)]
        assert vert_break(nodes, 20 * _PT, 2 * _PT) == (1, 15 * _PT)

    def test_overfull_first_breakpoint_still_returns_the_best_seen(self) -> None:
        nodes = [_box(30), PenaltyNode(0), _box(30)]
        # The penalty is already too full: awful cost, chosen and the search stops.
        assert vert_break(nodes, 10 * _PT, 0) == (1, 30 * _PT)


class TestPruneTop:
    _SPLIT = Glue(10 * _PT, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)

    def test_drops_discardables_and_inserts_splittopskip(self) -> None:
        box = _box(3)
        pruned = prune_page_top(
            [_glue(4), KernNode(_PT, True), PenaltyNode(100), box, _glue(2)], self._SPLIT,
        )
        assert pruned[0] == _glue(7)
        assert pruned[1:] == [box, _glue(2)]

    def test_keeps_marks_and_floors_the_glue_at_zero(self) -> None:
        mark = MarkNode(tokens=())
        rule = RuleNode(width=0, height=12 * _PT, depth=0)
        assert prune_page_top([PenaltyNode(0), mark, rule], self._SPLIT) == [mark, _glue(0), rule]

    def test_all_discardable_list_becomes_empty(self) -> None:
        assert prune_page_top([_glue(4), PenaltyNode(0)], self._SPLIT) == []


def test_precedes_break() -> None:
    assert precedes_break(_box(1)) is True
    assert precedes_break(MarkNode(tokens=())) is True
    assert precedes_break(_glue()) is False
    assert precedes_break(None) is False
