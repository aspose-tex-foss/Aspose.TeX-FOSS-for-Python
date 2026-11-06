"""Knuth-Plass optimal paragraph line-breaking algorithm.

Implements:
the pure algorithmic core — no I/O, no side effects.

See the project documentation for design rationale.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING

from aspose_tex._engine.box_builder import (
    _box_badness_message,
    _collect_shrink,
    _measure_hlist,
    append_overfull_rule,
    compute_badness,
    set_glue_hbox,
)
from aspose_tex._engine.nodes import (
    INF_BAD,
    NEG_INF_PENALTY,
    RUNNING_DIMEN,
    AdjustNode,
    CharNode,
    DiscretionaryNode,
    GlueNode,
    GlueSign,
    HlistNode,
    InsertNode,
    KernNode,
    LeadersNode,
    MarkNode,
    MathNode,
    PenaltyNode,
    RuleNode,
    VlistNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._engine.tex_arith import print_scaled

if TYPE_CHECKING:
    from aspose_tex._fonts.font_manager import FontManager


# ---------------------------------------------------------------------------
# Fitness classes
# ---------------------------------------------------------------------------

_FITNESS_VERY_LOOSE: int = 0  # stretched, badness > 99
_FITNESS_LOOSE: int = 1       # stretched, 12 < badness <= 99
_FITNESS_DECENT: int = 2      # badness <= 12
_FITNESS_TIGHT: int = 3       # shrunk, badness > 12


# ---------------------------------------------------------------------------
# Public parameters dataclass
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True, slots=True)
class LinebreakParams:
    """All tunable parameters required by the line-breaker.

    All dimension fields are in scaled points (sp).

    Example::

        params = LinebreakParams(
            hsize=6054984,
            tolerance=200,
            pretolerance=100,
            linepenalty=10,
            adjdemerits=10000,
            leftskip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
            rightskip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
            parfillskip=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL),
        )
    """

    hsize: int
    tolerance: int
    pretolerance: int
    linepenalty: int
    adjdemerits: int
    leftskip: Glue
    rightskip: Glue
    parfillskip: Glue
    hbadness: int = 1000
    hfuzz: int = 6554  # plain TeX's 0.1pt, rounded to sp
    overfull_rule: int = 0  # \overfullrule: IniTeX's 0pt (plain sets 5pt)
    # §869 / §859 discretionary charges ( Component 7); plain TeX sets
    # 50 / 50 / 10000 / 5000.
    hyphenpenalty: int = 0
    exhyphenpenalty: int = 0
    doublehyphendemerits: int = 0
    finalhyphendemerits: int = 0
    hangindent: int = 0
    hangafter: int = 1
    parshape: tuple[tuple[int, int], ...] = ()
    prevgraf: int = 0


# ---------------------------------------------------------------------------
# Internal DP node
# ---------------------------------------------------------------------------

@dataclasses.dataclass(slots=True)
class _Active:
    """One candidate break-chain node in the DP active list."""

    position: int               # index into nodes where this break occurs; -1 = start
    line_number: int            # absolute next line evaluated after this break
    fitness: int                # 0..3 fitness class
    total_demerits: float       # accumulated demerits from start
    predecessor: _Active | None
    hyphenated: bool = False    # §859: this break is at a discretionary


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _line_geometry(params: LinebreakParams, line_number: int) -> tuple[int, int]:
    """Return indent and full target width for an absolute one-based line."""
    if line_number < 1:
        raise ValueError("Paragraph line numbers must be positive")
    if params.parshape:
        return params.parshape[min(line_number, len(params.parshape)) - 1]
    hanging = params.hangindent and (
        line_number > params.hangafter if params.hangafter >= 0
        else line_number <= -params.hangafter
    )
    if hanging:
        return max(params.hangindent, 0), params.hsize - abs(params.hangindent)
    return 0, params.hsize


def _node_natural_width(node: object, font_manager: FontManager) -> int:
    """Return the natural width contribution of a single node in sp.

    CharNode  → font character width from font_manager.
    GlueNode  → natural glue width only.
    KernNode  → kern width.
    HlistNode / VlistNode → stored width.
    RuleNode  → stored width (RUNNING_DIMEN treated as 0).
    DiscretionaryNode → M3 nobreak-branch width.
    PenaltyNode, WhatsitNode → 0.
    """
    if isinstance(node, CharNode):
        m = font_manager.get_metrics(node.font_name)
        if m is not None:
            return m.char_metrics(node.char).width
        return 0
    if isinstance(node, GlueNode):
        return node.glue.width
    if isinstance(node, (KernNode, MathNode)):
        return node.width
    if isinstance(node, (HlistNode, VlistNode)):
        return node.width
    if isinstance(node, RuleNode):
        return 0 if node.width == RUNNING_DIMEN else node.width
    if isinstance(node, DiscretionaryNode):
        return sum(_node_natural_width(child, font_manager) for child in node.nobreak)
    if isinstance(node, LeadersNode):
        return node.glue.width
    # PenaltyNode, WhatsitNode
    return 0


def _is_legal_breakpoint(nodes: list, i: int, *, in_math: bool = False) -> bool:
    """Return True if position i is a legal breakpoint.

    Legal:
    - GlueNode or LeadersNode at i, provided it is not inside a formula (§866: TeX's
      ``auto_breaking`` is false between math-on and math-off,) and
      the immediately preceding item is not a GlueNode, PenaltyNode,
      explicit KernNode or MathNode.
    - An explicit kern (including italic correction) or math-off node followed
      by glue (§866 ``kern_break``).
    - PenaltyNode at i with penalty < INF_PENALTY (10000).
    """
    node = nodes[i]
    if isinstance(node, KernNode):
        return (not in_math and (node.explicit or node.italic_correction)
                and i + 1 < len(nodes) and isinstance(nodes[i + 1], (GlueNode, LeadersNode)))
    if isinstance(node, MathNode):
        return node.after and i + 1 < len(nodes) and isinstance(nodes[i + 1], (GlueNode, LeadersNode))
    if isinstance(node, (GlueNode, LeadersNode)):
        if in_math:
            return False
        # The terminal parfillskip is preceded by an infinite penalty in
        # TeX's paragraph finalization (§816); callers provide just the fill
        # and sentinel here. Never make an artificial break before that fill.
        if (i == len(nodes) - 2 and isinstance(nodes[-1], PenaltyNode)
                and nodes[-1].penalty == NEG_INF_PENALTY):
            return False
        if i == 0:
            return False
        prev = nodes[i - 1]
        if isinstance(prev, (GlueNode, LeadersNode, PenaltyNode, MathNode)):
            return False
        return not (isinstance(prev, KernNode) and (prev.explicit or prev.italic_correction))
    if isinstance(node, PenaltyNode):
        return node.penalty < 10_000  # INF_PENALTY
    return isinstance(node, DiscretionaryNode)


def _math_mask(nodes: list) -> list[bool]:
    """Flag every node that lies between a math-on and a math-off node (§866)."""
    mask: list[bool] = []
    inside = False
    for node in nodes:
        if isinstance(node, MathNode):
            inside = not node.after
        mask.append(inside and not isinstance(node, MathNode))
    return mask


def _line_starts(nodes: list) -> list[int]:
    """First non-discardable node at/after each offset (post_line_break §879)."""
    starts = [len(nodes)] * (len(nodes) + 1)
    for i in range(len(nodes) - 1, -1, -1):
        node = nodes[i]
        # A subsequent forced breakpoint may end an empty line. §879 stops
        # at the next selected break; never discard that break out of the DP.
        forced = ((isinstance(node, PenaltyNode) and node.penalty == NEG_INF_PENALTY)
                  or (isinstance(node, KernNode)
                      and not (node.explicit or node.italic_correction)))
        discardable = isinstance(node, (GlueNode, LeadersNode, KernNode, MathNode, PenaltyNode))
        starts[i] = starts[i + 1] if not forced and discardable else i
    return starts


def _line_start(nodes: list, previous: int, starts: list[int]) -> tuple[int, tuple]:
    """Share post-break material and discard protection with reconstruction."""
    if previous == -1:
        return 0, ()
    node = nodes[previous]
    if isinstance(node, DiscretionaryNode) and node.post:
        return previous + 1, node.post
    return starts[previous + 1], ()


def _adjustment_ratio(
    need: int,
    stretch_total: int,
    shrink_total: int,
) -> float | None:
    """Return glue adjustment ratio r, or None if infeasible.

    need > 0  (line too short):  r = need / stretch_total; None if stretch_total == 0.
    need < 0  (line too long):   r = need / shrink_total (negative); None if
                                  shrink_total == 0 or r < -1.
    need == 0: return 0.0.
    """
    if need == 0:
        return 0.0
    if need > 0:
        if stretch_total == 0:
            return None
        return need / stretch_total
    # need < 0
    if shrink_total == 0:
        return None
    r = need / shrink_total  # negative
    if r < -1:
        return None
    return r


def _fitness_class(badness: int, stretched: bool) -> int:
    """Map a line's badness to fitness class 0..3 (TeX §853 / §855).

    TeX classifies by the integer badness, not the adjustment ratio, so the
    class boundaries sit exactly where ``compute_badness`` crosses 12 and 99.
    """
    if badness <= 12:
        return _FITNESS_DECENT
    if not stretched:
        return _FITNESS_TIGHT
    return _FITNESS_VERY_LOOSE if badness > 99 else _FITNESS_LOOSE


def _line_demerits(
    badness: int,
    penalty: int,
    linepenalty: int,
    prev_fitness: int,
    this_fitness: int,
    adjdemerits: int,
) -> float:
    """Compute per-line demerits per TeXbook p. 98.

    d = (linepenalty + badness)^2
    if penalty >= 0:     d += penalty^2
    elif penalty > NEG_INF_PENALTY:  d -= penalty^2
    if |this_fitness - prev_fitness| > 1: d += adjdemerits
    """
    raw = linepenalty + badness
    d = 100_000_000.0 if abs(raw) >= 10_000 else float(raw * raw)  # See pdftex.web §25248
    if penalty >= 0:
        d += float(penalty * penalty)
    elif penalty > NEG_INF_PENALTY:
        d -= float(penalty * penalty)
    if abs(this_fitness - prev_fitness) > 1:
        d += adjdemerits
    return d


def _build_line(
    nodes: list,
    start: int,
    end: int,
    params: LinebreakParams,
    font_manager: FontManager,
    warnings: list[str] | None,
    *,
    line_number: int,
    prefix_nodes: tuple = (),
    suffix_nodes: tuple = (),
    line_reports: list[tuple[str, list]] | None = None,
) -> HlistNode:
    """Build one typeset line from nodes[start:end].

    Prepends leftskip and appends rightskip (when non-trivial), then
    calls set_glue_hbox at the selected line's target width. Emits
    "Overfull hbox" / "Underfull hbox" strings into warnings if provided,
    and the line's TeX report into *line_reports* (§8).
    """
    indent, width = _line_geometry(params, line_number)
    # TeX's line keeps its unbroken discretionaries (§881); the box carries
    # their nobreak material instead, so the report shows `material`.
    material: list = []

    ls = params.leftskip
    if ls.width or ls.stretch != 0 or ls.shrink != 0:
        material.append(GlueNode(glue=ls))

    material.extend(prefix_nodes)
    material.extend(nodes[start:end])
    material.extend(suffix_nodes)
    rs = params.rightskip
    # TeX keeps even zero rightskip (§877): an otherwise empty forced line
    # is a nonempty list and receives the normal underfull diagnostic.
    material.append(GlueNode(glue=rs))
    line_nodes: list = []
    for node in material:
        if isinstance(node, DiscretionaryNode):
            line_nodes.extend(node.nobreak)
        else:
            line_nodes.append(node)

    nat_w, nat_h, nat_d = _measure_hlist(line_nodes, font_manager)

    box = HlistNode(
        list=line_nodes,
        width=nat_w,
        height=nat_h,
        depth=nat_d,
        shift_amount=indent,
        glue_sign=GlueSign.NORMAL,
        glue_order=GlueOrder.NORMAL,
        glue_set=0.0,
    )
    badness = set_glue_hbox(box, target_width=width)

    message = None
    excess = nat_w - width - _collect_shrink(line_nodes)[GlueOrder.NORMAL]
    if warnings is not None or line_reports is not None:
        message = _box_badness_message(
            box, badness, "hbox", params.hbadness, params.hfuzz, excess,
        )
    if warnings is not None and message is not None:
        warnings.append(message)
    # §666 appends the rule before the report's short display.
    if append_overfull_rule(
        box, badness, font_manager, hfuzz=params.hfuzz, overfull_rule=params.overfull_rule,
    ):
        material.append(box.list[-1])
    if line_reports is not None and message is not None:
        if badness > INF_BAD:
            message = f"Overfull \\hbox ({print_scaled(excess)}pt too wide)"  # §666
        # §655: hpack has already moved the line's inserts, marks and adjusts out.
        line_reports.append((message, [
            node for node in material if not isinstance(node, (InsertNode, MarkNode, AdjustNode))
        ]))

    return box


# ---------------------------------------------------------------------------
# Prefix-sum helpers
# ---------------------------------------------------------------------------

def _build_prefix_sums(
    nodes: list,
    font_manager: FontManager,
) -> tuple[list[int], dict, list[int]]:
    """Precompute prefix sums for width, stretch (per order), and NORMAL shrink.

    Returns (sum_width, sum_stretch, sum_shrink_normal) where index k holds
    the cumulative total for nodes[0..k-1].  Each list has length len(nodes)+1.
    """
    n = len(nodes)
    sum_width = [0] * (n + 1)
    sum_stretch: dict[GlueOrder, list[int]] = {
        o: [0] * (n + 1) for o in GlueOrder
    }
    sum_shrink_normal = [0] * (n + 1)

    for i, node in enumerate(nodes):
        sum_width[i + 1] = sum_width[i] + _node_natural_width(node, font_manager)
        for o in GlueOrder:
            sum_stretch[o][i + 1] = sum_stretch[o][i]
        sum_shrink_normal[i + 1] = sum_shrink_normal[i]

        if isinstance(node, (GlueNode, LeadersNode)):
            sum_stretch[node.glue.stretch_order][i + 1] += node.glue.stretch
            if node.glue.shrink_order == GlueOrder.NORMAL:
                sum_shrink_normal[i + 1] += node.glue.shrink

    return sum_width, sum_stretch, sum_shrink_normal


def _highest_stretch_order(st: dict, orders: list) -> GlueOrder:
    """Return the highest GlueOrder with nonzero stretch in the given order list."""
    for o in (GlueOrder.FILLL, GlueOrder.FILL, GlueOrder.FIL, GlueOrder.NORMAL):
        if o in orders and st[o] > 0:
            return o
    return GlueOrder.NORMAL


# ---------------------------------------------------------------------------
# Main algorithm
# ---------------------------------------------------------------------------

def _run_dp(
    nodes: list,
    params: LinebreakParams,
    sum_width: list[int],
    sum_stretch: dict,
    sum_shrink_normal: list[int],
    max_badness: int,
    font_manager: FontManager,
    *,
    final_pass: bool = False,
) -> _Active | None:
    """Run one DP pass.  Returns the best terminal active node, or None."""
    skip_width = params.leftskip.width + params.rightskip.width
    # TeX's background width (§827) includes the complete side glues in
    # every candidate. Compute their constant elasticity once per pass.
    skip_stretch = {order: 0 for order in GlueOrder}
    for skip in (params.leftskip, params.rightskip):
        skip_stretch[skip.stretch_order] += skip.stretch
    skip_shrink = params.leftskip.shrink + params.rightskip.shrink

    # Initial active node: position=-1 means "start of paragraph"
    active: list[_Active] = [
        _Active(
            position=-1,
            line_number=params.prevgraf + 1,
            fitness=_FITNESS_DECENT,
            total_demerits=0.0,
            predecessor=None,
        )
    ]
    final_active: _Active | None = None
    starts = _line_starts(nodes)
    in_math = _math_mask(nodes)
    last = len(nodes) - 1
    last_special_line = (len(params.parshape) - 1 if params.parshape else
                         abs(params.hangafter) if params.hangindent else 0)

    for i in range(len(nodes)):
        if not _is_legal_breakpoint(nodes, i, in_math=in_math[i]):
            continue

        node_i = nodes[i]
        if isinstance(node_i, PenaltyNode):
            penalty = node_i.penalty
        elif isinstance(node_i, DiscretionaryNode):
            # §869: an empty pre-break is an explicit hyphen's discretionary.
            penalty = params.hyphenpenalty if node_i.pre else params.exhyphenpenalty
            # §859 try_break: pi >= inf_penalty is no break at all.
            if penalty >= 10_000:
                continue
        else:
            penalty = 0
        is_disc = isinstance(node_i, DiscretionaryNode)
        # §873: the final break counts as hyphenated for §859.
        hyphenated = is_disc or (
            i == last and isinstance(node_i, PenaltyNode) and node_i.penalty == NEG_INF_PENALTY
        )

        is_forced = penalty == NEG_INF_PENALTY
        new_candidates: list[_Active] = []
        still_active: list[_Active] = []

        for a in active:
            j = a.position
            start, prefix_nodes = _line_start(nodes, j, starts)
            # §827 break_width removes post-break discardables from the active
            # width even at a penalty inside that discarded run. Such a legal
            # candidate must see the signed prefix correction (including a
            # negative terminal-fill stretch), rather than being skipped.
            if i < start and not isinstance(node_i, PenaltyNode):
                still_active.append(a)
                continue
            # Width of line from j+1 to i-1 (inclusive)
            # j==-1 means start: offset = sum_width[0] = 0
            j_offset = sum_width[start]
            w = sum_width[i] - j_offset
            #: the selected endpoints replace, never add to, nobreak.
            w += sum(_node_natural_width(n, font_manager) for n in prefix_nodes)
            if is_disc:
                w += sum(_node_natural_width(n, font_manager) for n in node_i.pre)

            # Stretch and shrink sums for the same range
            st: dict[GlueOrder, int] = {}
            for o in GlueOrder:
                st_offset = sum_stretch[o][start]
                st[o] = sum_stretch[o][i] - st_offset + skip_stretch[o]
            sh_offset = sum_shrink_normal[start]
            sh = sum_shrink_normal[i] - sh_offset + skip_shrink

            _indent, width = _line_geometry(params, a.line_number)
            need = width - w - skip_width

            # Determine dominant stretch order
            dominant = GlueOrder.NORMAL
            for o in (GlueOrder.FILLL, GlueOrder.FILL, GlueOrder.FIL):
                # TeX §851 tests nonzero infinite stretch, including the signed
                # correction from discarded material beyond this candidate.
                if st[o] != 0:
                    dominant = o
                    break

            if dominant != GlueOrder.NORMAL:
                # Infinite stretch — always feasible when need >= 0
                if need >= 0:
                    ratio: float | None = 0.0
                else:
                    ratio = _adjustment_ratio(need, 0, sh)
            else:
                ratio = _adjustment_ratio(need, st[GlueOrder.NORMAL], sh)

            # Compute badness
            if dominant != GlueOrder.NORMAL and need >= 0:
                # Infinite stretch available — perfect fit
                bad = 0
            elif need < 0 and ratio is None:
                # Overfull forced break: TeX §855 rates it inf_bad + 1.
                bad = INF_BAD + 1
            elif need >= 0:
                bad = compute_badness(need, st[GlueOrder.NORMAL])
            else:
                bad = compute_badness(-need, sh)

            # §854/§863: an overfull/forced break retires this active node.
            # On the final pass, keep the very last path when no feasible
            # candidate remains, charging no new (artificial) demerits.
            retire = bad > INF_BAD or is_forced
            artificial = (final_pass and retire and not new_candidates
                          and not still_active and a is active[-1])
            if not retire:
                still_active.append(a)
            if bad > min(INF_BAD, max_badness) and not artificial:
                continue

            fit = _fitness_class(bad, stretched=need > 0)
            d = 0.0 if artificial else _line_demerits(
                bad, penalty, params.linepenalty,
                a.fitness, fit, params.adjdemerits,
            )
            if hyphenated and a.hyphenated and not artificial:
                # §859: two hyphenated lines in a row, or a hyphenated
                # next-to-last line.
                d += params.doublehyphendemerits if is_disc else params.finalhyphendemerits
            candidate = _Active(
                position=i,
                line_number=a.line_number + 1,
                fitness=fit,
                total_demerits=a.total_demerits + d,
                predecessor=a,
                hyphenated=is_disc,
            )
            new_candidates.append(candidate)

        #: only equivalent future geometry and cost histories may merge.
        best_at: dict[tuple[int, int, int, bool], _Active] = {}
        for cand in new_candidates:
            key = (cand.position, min(cand.line_number, last_special_line + 1),
                   cand.fitness, cand.hyphenated)
            existing = best_at.get(key)
            # TeX §862 replaces an equal-cost predecessor with the later one.
            # Infinite side stretch makes these ties common even in plain text.
            if existing is None or cand.total_demerits <= existing.total_demerits:
                best_at[key] = cand

        deduped = list(best_at.values())
        active = still_active + deduped

        # Collect terminal candidates only at the TRUE end-of-paragraph sentinel
        # (the last node in the list), not at intermediate \penalty-10000 nodes.
        if i == len(nodes) - 1 and isinstance(node_i, PenaltyNode) and node_i.penalty == NEG_INF_PENALTY:
            for cand in deduped:
                if final_active is None or cand.total_demerits < final_active.total_demerits:
                    final_active = cand

    return final_active


def break_paragraph(
    nodes: list,
    params: LinebreakParams,
    font_manager: FontManager,
    *,
    warnings: list[str] | None = None,
    disc_breaks: list[bool] | None = None,
    hyphenate: Callable[[list], list] | None = None,
    line_reports: list[tuple[str, list]] | None = None,
) -> list[HlistNode]:
    """Run Knuth-Plass and return the typeset lines.

    The caller (exec_par) must have already appended parfillskip + a
    NEG_INF_PENALTY sentinel to nodes.  An empty list returns []; an
    all-discardable one (a paragraph of one interword space) still breaks
    into one line, as TeX §1096 does. Each returned HlistNode is packed at
    its absolute line's target width and carries that line's indent.

    Args:
        nodes:        Paragraph node list ending with parfillskip + sentinel.
        params:       All tunable parameters.
        font_manager: For character width lookups.
        warnings:     Optional list; warning strings are appended here.
        disc_breaks:  Optional list; one flag per returned line is appended,
                      True when that line ends at a discretionary break
                      (TeX §890 adds ``\\brokenpenalty`` after it,).
        hyphenate:    Optional hyphenation step (§6), called once with
                      the paragraph list when the second pass is entered (the
                      first pass found no break chain, or ``pretolerance < 0``
                      skipped it, §863); the second pass and the lines use the
                      list it returns.
        line_reports: Optional list; one ``(header, material)`` pair is
                      appended per line TeX reports (§8): the header
                      in TeX's form (``Underfull \\hbox (badness 10000)``,
                      ``Overfull \\hbox (4.72226pt too wide)``) and the line's
                      material with its unbroken discretionaries and
                      ``\\overfullrule`` marker, for ``short_display``.

    Returns:
        List of set HlistNode lines.

    Example::

        from aspose_tex._engine.registers import Glue, GlueOrder
        params = LinebreakParams(
            hsize=6054984, tolerance=200, pretolerance=100,
            linepenalty=10, adjdemerits=10000,
            leftskip=Glue(0,0,GlueOrder.NORMAL,0,GlueOrder.NORMAL),
            rightskip=Glue(0,0,GlueOrder.NORMAL,0,GlueOrder.NORMAL),
            parfillskip=Glue(0,65536,GlueOrder.FIL,0,GlueOrder.NORMAL),
        )
        lines = break_paragraph([], params, font_manager)
        assert lines == []
    """
    if not nodes:
        return []

    # §824-§826: paragraph shrink is always finite, even for side skips.
    shrink_error = False
    def finite(glue: Glue) -> Glue:
        nonlocal shrink_error
        if glue.shrink and glue.shrink_order != GlueOrder.NORMAL:
            shrink_error = True
            return dataclasses.replace(glue, shrink_order=GlueOrder.NORMAL)
        return glue

    params = dataclasses.replace(params, leftskip=finite(params.leftskip),
                                 rightskip=finite(params.rightskip))
    nodes = [dataclasses.replace(n, glue=finite(n.glue))
             if isinstance(n, (GlueNode, LeadersNode)) else n for n in nodes]
    if shrink_error and warnings is not None:
        warnings.append('! Infinite glue shrinkage found in a paragraph.')

    sum_width, sum_stretch, sum_shrink_normal = _build_prefix_sums(nodes, font_manager)

    # Pass 1: pretolerance; a negative value skips it (§863).
    final = None
    if params.pretolerance >= 0:
        final = _run_dp(
            nodes, params, sum_width, sum_stretch, sum_shrink_normal,
            params.pretolerance, font_manager,
        )

    # Pass 2: tolerance (if pass 1 failed), over the hyphenated list (§891).
    if final is None:
        if hyphenate is not None:
            nodes = hyphenate(nodes)
            sum_width, sum_stretch, sum_shrink_normal = _build_prefix_sums(nodes, font_manager)
        final = _run_dp(
            nodes, params, sum_width, sum_stretch, sum_shrink_normal,
            params.tolerance, font_manager,
            final_pass=True,
        )

    # If still None (degenerate), force a single line
    if final is None:
        # Build one line from all content
        line = _build_line(nodes, 0, len(nodes), params, font_manager, warnings,
                           line_number=params.prevgraf + 1, line_reports=line_reports)
        if disc_breaks is not None:
            disc_breaks.append(False)
        return [line]

    # Trace back the break chain
    chain = []
    node: _Active | None = final
    while node is not None and node.position != -1:
        chain.append(node.position)
        node = node.predecessor
    chain.reverse()  # now in order: [pos1, pos2, ..., posN]

    # Build lines
    lines: list[HlistNode] = []
    previous = -1
    starts = _line_starts(nodes)
    for line_number, pos in enumerate(chain, params.prevgraf + 1):
        start, prefix_nodes = _line_start(nodes, previous, starts)
        suffix_nodes = nodes[pos].pre if isinstance(nodes[pos], DiscretionaryNode) else ()
        if isinstance(nodes[pos], (KernNode, MathNode)):
            # §881 keeps the chosen kern/math-off, but cancels its width.
            suffix_nodes = (dataclasses.replace(nodes[pos], width=0),)
        line = _build_line(nodes, start, pos, params, font_manager, warnings,
                           line_number=line_number, prefix_nodes=prefix_nodes,
                           suffix_nodes=suffix_nodes, line_reports=line_reports)
        lines.append(line)
        if disc_breaks is not None:
            disc_breaks.append(isinstance(nodes[pos], DiscretionaryNode))
        previous = pos

    return lines
