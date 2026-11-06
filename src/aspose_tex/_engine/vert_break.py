r"""Vertical-list breaking shared by the page builder.

``vert_break`` is TeX: The Program §970-§977 — the best place to break a
vertical list into a piece of height ``h`` with maximum depth ``d`` — and
``prune_page_top`` is §968, which tidies the top of the remainder.  The page
builder uses them to split an insertion that does not fit the page
(§1010) and to start the held-over part of a split insertion (§1021).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aspose_tex._engine.box_builder import compute_badness
from aspose_tex._engine.nodes import (
    INF_BAD,
    INF_PENALTY,
    NEG_INF_PENALTY,
    RUNNING_DIMEN,
    GlueNode,
    HlistNode,
    KernNode,
    LeadersNode,
    PenaltyNode,
    RuleNode,
    VlistNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aspose_tex._engine.nodes import Node

# TeX: The Program §833/§974 cost constants.
AWFUL_BAD: int = 0o7777777777
DEPLORABLE: int = 100_000
EJECT_PENALTY: int = NEG_INF_PENALTY

_BOX_LIKE = (HlistNode, VlistNode, RuleNode)
_DISCARDABLE = (GlueNode, LeadersNode, KernNode, PenaltyNode)


def precedes_break(node: Node | None) -> bool:
    """TeX's ``precedes_break``: may glue after *node* be a breakpoint?

    In a vertical list every node except glue, kern, penalty and math is
    "non-discardable" (``type(node) < math_node``).  ``None`` stands for the
    head of an empty list, which TeX makes a glue node so that an initial glue
    is never a breakpoint (§991).

    Example::

        precedes_break(HlistNode(...))   # True
        precedes_break(None)             # False
    """
    return node is not None and not isinstance(node, _DISCARDABLE)


def _height(node: HlistNode | VlistNode | RuleNode) -> int:
    return 0 if node.height == RUNNING_DIMEN else node.height


def _depth(node: HlistNode | VlistNode | RuleNode) -> int:
    return 0 if node.depth == RUNNING_DIMEN else node.depth


def vert_break(nodes: Sequence[Node], h: int, d: int) -> tuple[int | None, int]:
    """Find the best break of a vertical list for height *h*, depth *d* (§970).

    The list is followed by an implicit ``\\penalty-10000``.  Legal breakpoints
    are glue after a non-discardable node, a kern followed by glue (a kern at
    the end counts as followed by a penalty) and penalties below 10000.  Each
    is costed like a page break (§974-§976); ties go to the later breakpoint,
    and the search stops at an overfull break or a forced one.

    Args:
        nodes: The vertical list.
        h:     The height the piece before the break should have (sp).
        d:     The maximum depth of that piece (sp).

    Returns:
        ``(index, best_height_plus_depth)`` — the index in *nodes* of the best
        breakpoint, or ``None`` when the best break is the implicit one at the
        end, and the natural height plus depth of the piece before it.

    Example::

        index, size = vert_break(insert_node.vlist, 100 * 65536, 0)
    """
    least_cost = AWFUL_BAD
    best_place: int | None = None
    best_height_plus_depth = 0
    cur_height = 0
    prev_dp = 0
    stretch = {order: 0 for order in GlueOrder}
    shrink = 0
    prev: Node | None = None
    index = 0
    while True:
        node = nodes[index] if index < len(nodes) else None
        pi: int | None = None
        if node is None:
            pi = EJECT_PENALTY
        elif isinstance(node, _BOX_LIKE):
            cur_height += prev_dp + _height(node)
            prev_dp = _depth(node)
        elif isinstance(node, (GlueNode, LeadersNode)):
            if precedes_break(prev):
                pi = 0
        elif isinstance(node, KernNode):
            follower = nodes[index + 1] if index + 1 < len(nodes) else None
            if isinstance(follower, (GlueNode, LeadersNode)):
                pi = 0
        elif isinstance(node, PenaltyNode):
            pi = node.penalty

        if pi is not None and pi < INF_PENALTY:
            if cur_height < h:
                if any(stretch[order] for order in (
                    GlueOrder.FIL, GlueOrder.FILL, GlueOrder.FILLL,
                )):
                    badness = 0
                else:
                    badness = compute_badness(h - cur_height, stretch[GlueOrder.NORMAL])
            elif cur_height - h > shrink:
                badness = AWFUL_BAD
            else:
                badness = compute_badness(cur_height - h, shrink)
            if badness < AWFUL_BAD:
                if pi <= EJECT_PENALTY:
                    badness = pi
                elif badness < INF_BAD:
                    badness = badness + pi
                else:
                    badness = DEPLORABLE
            if badness <= least_cost:
                best_place = index if node is not None else None
                least_cost = badness
                best_height_plus_depth = cur_height + prev_dp
            if badness == AWFUL_BAD or pi <= EJECT_PENALTY:
                return best_place, best_height_plus_depth

        if isinstance(node, (GlueNode, LeadersNode)):
            # §976: infinite shrink is counted as finite, as TeX does after
            # its "Infinite glue shrinkage found in box being split" error.
            stretch[node.glue.stretch_order] += node.glue.stretch
            shrink += node.glue.shrink
            cur_height += prev_dp + node.glue.width
            prev_dp = 0
        elif isinstance(node, KernNode):
            cur_height += prev_dp + node.width
            prev_dp = 0
        if prev_dp > d:
            cur_height += prev_dp - d
            prev_dp = d
        prev = node
        index += 1


def prune_page_top(nodes: Sequence[Node], split_top_skip: Glue) -> list:
    """Tidy the top of a vertical list that starts a new piece (§968).

    Glue, kerns and penalties before the first box or rule are dropped;
    whatsits, marks and insertions are kept; the first box or rule gets
    ``\\splittopskip`` glue in front of it, shortened by its height (never
    below zero).

    Args:
        nodes:          The vertical list after a break.
        split_top_skip: The ``\\splittopskip`` glue to put before the first box.

    Returns:
        The pruned list (empty when only discardable material was left).

    Example::

        rest = prune_page_top(vlist[break_index:], insert_node.split_top_skip)
    """
    pruned: list = []
    for index, node in enumerate(nodes):
        if isinstance(node, _BOX_LIKE):
            width = max(0, split_top_skip.width - _height(node))
            pruned.append(GlueNode(Glue(
                width,
                split_top_skip.stretch, split_top_skip.stretch_order,
                split_top_skip.shrink, split_top_skip.shrink_order,
            )))
            pruned.extend(nodes[index:])
            return pruned
        if not isinstance(node, _DISCARDABLE):
            pruned.append(node)
    return pruned
