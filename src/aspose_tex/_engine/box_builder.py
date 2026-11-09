"""Box construction: HBoxBuilder, VBoxBuilder, glue setting, badness.

Implements:
- ``HBoxBuilder`` processes character tokens and pre-built nodes,
  producing an ``HlistNode``.
- ``VBoxBuilder`` stacks horizontal boxes (and other vertical-mode material)
  into a ``VlistNode``.
- ``set_glue_hbox`` / ``set_glue_vbox`` set the glue-set fields in-place.
- ``compute_badness`` implements the standard TeX badness formula.

See the project documentation for design rationale.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from aspose_tex._engine.nodes import (
    INF_BAD,
    OVERFULL_BAD,
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
    WhatsitNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._engine.tex_arith import glue_ratio

if TYPE_CHECKING:
    from aspose_tex._engine.nodes import Node
    from aspose_tex._fonts.font_manager import FontManager


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _measure_hlist(
    nodes: list,
    font_manager: FontManager,
) -> tuple[int, int, int]:
    """Compute ``(width, height, depth)`` of a horizontal list.

    - ``width``  = sum of all node widths.
    - ``height`` = max height across all nodes.
    - ``depth``  = max depth across all nodes.

    For ``CharNode``: look up metrics via ``font_manager``.
    For ``GlueNode``: natural width = ``node.glue.width``; h = d = 0.
    For ``KernNode``: width = ``node.width``; h = d = 0.
    For ``PenaltyNode``, ``WhatsitNode``: zero contribution.
    For ``RuleNode``: use stored dimensions (``RUNNING_DIMEN`` treated as 0).
    For box nodes: include their vertical shift (positive means up, §653).
    """
    total_w = 0
    max_h = 0
    max_d = 0
    for node in nodes:
        if isinstance(node, CharNode):
            m = font_manager.get_metrics(node.font_name)
            if m is not None:
                cm = m.char_metrics(node.char)
                total_w += cm.width
                if cm.height > max_h:
                    max_h = cm.height
                if cm.depth > max_d:
                    max_d = cm.depth
        elif isinstance(node, (HlistNode, VlistNode)):
            total_w += node.width
            max_h = max(max_h, node.height + node.shift_amount)
            max_d = max(max_d, node.depth - node.shift_amount)
        elif isinstance(node, GlueNode):
            total_w += node.glue.width
        elif isinstance(node, (KernNode, MathNode)):
            total_w += node.width
        elif isinstance(node, RuleNode):
            w = 0 if node.width == RUNNING_DIMEN else node.width
            h = 0 if node.height == RUNNING_DIMEN else node.height
            d = 0 if node.depth == RUNNING_DIMEN else node.depth
            total_w += w
            if h > max_h:
                max_h = h
            if d > max_d:
                max_d = d
        elif isinstance(node, DiscretionaryNode):
            w, h, d = _measure_hlist(list(node.nobreak), font_manager)
            total_w += w
            if h > max_h:
                max_h = h
            if d > max_d:
                max_d = d
        elif isinstance(node, LeadersNode):
            total_w += node.glue.width
            payload = node.payload
            if isinstance(payload, (HlistNode, VlistNode)):
                max_h = max(max_h, payload.height)
                max_d = max(max_d, payload.depth)
            elif isinstance(payload, RuleNode):
                max_h = max(max_h, 0 if payload.height == RUNNING_DIMEN else payload.height)
                max_d = max(max_d, 0 if payload.depth == RUNNING_DIMEN else payload.depth)
        # PenaltyNode, WhatsitNode — no contribution
    return total_w, max_h, max_d


def _measure_vlist(
    nodes: list,
    font_manager: FontManager,
) -> tuple[int, int, int]:
    """Compute ``(width, height, depth)`` of a vertical list.

    - ``width``  = max width across all box nodes.
    - ``height`` = accumulated height: each box contributes prev_depth + box.height;
                   glue/kerns absorb pending depth before adding their width.
    - ``depth``  = pending depth after the final node (0 after glue/kern).

    Algorithm:
    1. Iterate through nodes, tracking ``running_height`` and ``prev_depth``.
    2. For box nodes: ``running_height += prev_depth + node.height``;
       record ``prev_depth = node.depth`` and update ``max_width``.
    3. GlueNode/KernNode: add pending depth and width, then reset depth to 0.
    4. RuleNode: add pending depth and height, retain rule depth;
       RUNNING_DIMEN is treated as 0. Update ``max_width``.
    5. PenaltyNode, WhatsitNode, CharNode: no contribution.
    6. Return accumulated height and pending final depth (TeX §668-§670).
    """
    max_w = 0
    running_h = 0
    prev_depth = 0
    current_depth = 0

    for node in nodes:
        if isinstance(node, (HlistNode, VlistNode)):
            running_h += prev_depth + node.height
            prev_depth = node.depth
            current_depth = node.depth
            max_w = max(max_w, node.width + node.shift_amount)
        elif isinstance(node, GlueNode):
            running_h += prev_depth + node.glue.width
            prev_depth = current_depth = 0
        elif isinstance(node, LeadersNode):
            running_h += prev_depth + node.glue.width
            prev_depth = current_depth = 0
            payload = node.payload
            if isinstance(payload, (HlistNode, VlistNode)):
                max_w = max(max_w, payload.width + payload.shift_amount)
            elif isinstance(payload, RuleNode) and payload.width != RUNNING_DIMEN:
                max_w = max(max_w, payload.width)
        elif isinstance(node, KernNode):
            running_h += prev_depth + node.width
            prev_depth = current_depth = 0
        elif isinstance(node, RuleNode):
            h = 0 if node.height == RUNNING_DIMEN else node.height
            d = 0 if node.depth == RUNNING_DIMEN else node.depth
            w = 0 if node.width == RUNNING_DIMEN else node.width
            running_h += prev_depth + h
            prev_depth = d
            current_depth = d
            if w > max_w:
                max_w = w
        # PenaltyNode, WhatsitNode, CharNode — no contribution

    return max_w, running_h, current_depth


def _vertical_extent(node) -> int:
    """Return the natural vertical contribution of one vertical-list node."""
    if isinstance(node, (HlistNode, VlistNode)):
        return node.height + node.depth
    if isinstance(node, (GlueNode, LeadersNode)):
        return node.glue.width
    if isinstance(node, KernNode):
        return node.width
    if isinstance(node, RuleNode):
        h = 0 if node.height == RUNNING_DIMEN else node.height
        d = 0 if node.depth == RUNNING_DIMEN else node.depth
        return h + d
    return 0


def vsplit_at_height(
    box: VlistNode,
    target_height: int,
    *,
    splittopskip: Glue,
) -> tuple[VlistNode, VlistNode | None]:
    """Split *box* at *target_height* sp and return ``(top, residue)``.

    This is the simplified ``\\vsplit`` algorithm: walk the
    vertical list from the front, stop before the first node that would exceed
    the requested height. ``\\splittopskip`` adjusts the remainder's first
    baseline, never the returned top piece. Precise ``\\splitmaxdepth`` handling is
    deferred to a future release.
    """
    split_idx = 0
    running = 0
    for idx, node in enumerate(box.list):
        extent = _vertical_extent(node)
        if idx > 0 and running + extent > target_height:
            break
        running += extent
        split_idx = idx + 1
        if running >= target_height:
            break

    head = list(box.list[:split_idx])
    tail = list(box.list[split_idx:])
    # §968 prune_page_top applies to the residue, retaining marks/inserts while
    # discarding glue/kerns/penalties before its first box or rule.
    pruned = []
    for idx, node in enumerate(tail):
        if isinstance(node, (HlistNode, VlistNode, RuleNode)):
            pruned.append(GlueNode(Glue(
                max(0, splittopskip.width - node.height),
                splittopskip.stretch, splittopskip.stretch_order,
                splittopskip.shrink, splittopskip.shrink_order,
            )))
            pruned.extend(tail[idx:])
            break
        if not isinstance(node, (GlueNode, KernNode, PenaltyNode)):
            pruned.append(node)
    tail = pruned

    top = VlistNode(
        list=head,
        width=box.width,
        height=0,
        depth=0,
        shift_amount=0,
        glue_sign=GlueSign.NORMAL,
        glue_order=GlueOrder.NORMAL,
        glue_set=0.0,
    )
    top.width, top.height, top.depth = _measure_vlist(top.list, _NullFontManager())
    if top.height < target_height:
        set_glue_vbox(top, target_height=target_height)

    if not tail:
        return top, None
    residue = VlistNode(
        list=tail,
        width=box.width,
        height=0,
        depth=0,
        shift_amount=0,
        glue_sign=GlueSign.NORMAL,
        glue_order=GlueOrder.NORMAL,
        glue_set=0.0,
    )
    residue.width, residue.height, residue.depth = _measure_vlist(tail, _NullFontManager())
    return top, residue


class _NullFontManager:
    """Tiny measurement shim for vlist-only measurement paths."""

    def get_metrics(self, _font_name: str):  # pragma: no cover - defensive
        return None


# ---------------------------------------------------------------------------
# Interline glue (TeX:The Program §679)
# ---------------------------------------------------------------------------

# A ``prev_depth`` of this value (or below) means "ignore" — no interline glue
# is emitted before the next box (TeXbook §253 "ignore" marker; TeX §679).
# Mirrors ``box_primitives._PREVDEPTH_SENTINEL`` (the two are kept identical so
# the vbox and alignment interline paths agree).
IGNORE_PREV_DEPTH = -65_536_000  # -1000 pt in sp


def compute_interline_glue(
    *,
    prev_depth: int,
    next_height: int,
    baselineskip: Glue,
    lineskip: Glue,
    lineskiplimit: int,
) -> Glue | None:
    """Return the §679 interline glue to insert before a box, or ``None``.

    Implements TeX:The Program §679 (``append_to_vlist``): the glue that
    separates two successive baselines in a vertical list.  Let
    ``ideal = baselineskip.width - prev_depth - next_height`` be the glue that
    would place the next box's baseline exactly ``\\baselineskip`` below the
    previous box's baseline.  If that leaves at least ``\\lineskiplimit`` of
    space (``ideal >= lineskiplimit``), the ``\\baselineskip`` glue is used with
    its natural width replaced by ``ideal`` (stretch/shrink preserved);
    otherwise the boxes are too close and ``\\lineskip`` is inserted verbatim.

    Args:
        prev_depth: Depth of the previously contributed box (sp), or
            :data:`IGNORE_PREV_DEPTH` to suppress interline glue (first box,
            or immediately after a rule / the "ignore" marker).
        next_height: Height of the box about to be contributed (sp).
        baselineskip: The live ``\\baselineskip`` glue.
        lineskip: The live ``\\lineskip`` glue.
        lineskiplimit: The live ``\\lineskiplimit`` dimension (sp).

    Returns:
        The interline ``Glue`` to insert before the box, or ``None`` when no
        glue is due (``prev_depth <= IGNORE_PREV_DEPTH``).
    """
    if prev_depth <= IGNORE_PREV_DEPTH:
        return None
    ideal = baselineskip.width - prev_depth - next_height
    if ideal < lineskiplimit:
        return lineskip
    return Glue(
        ideal,
        baselineskip.stretch, baselineskip.stretch_order,
        baselineskip.shrink, baselineskip.shrink_order,
    )


# ---------------------------------------------------------------------------
# Badness
# ---------------------------------------------------------------------------

def compute_badness(shortage: int, total_flex: int) -> int:
    """Return TeX badness for a box that needs *shortage* sp of flex.

    TeX: The Program §108 ``badness(t, s)``, in its exact integer arithmetic:
    an approximation of ``100 * (t/s)**3`` that stays finite up to a ratio of
    about 4.34 and is ``INF_BAD`` (10000) beyond it or when there is no flex.
    The integer steps matter: TeX compares the result against ``\\tolerance``
    and ``\\hbadness``, and ``\\badness`` reports it verbatim.

    Args:
        shortage:   Absolute difference between target size and natural size
                    (``t >= 0``).
        total_flex: Total finite stretch (stretching) or shrink (shrinking)
                    in sp.

    Returns:
        Integer badness in range [0, 10000].

    Example::

        assert compute_badness(0, 1000) == 0
        assert compute_badness(1000, 1000) == 100
        assert compute_badness(1500, 1000) == 336  # 100 * 1.5**3 = 337.5
        assert compute_badness(5000, 1000) == INF_BAD
    """
    if shortage == 0:
        return 0
    if total_flex <= 0:
        return INF_BAD
    # r approximates alpha*t/s with alpha**3 ~ 100 * 2**18 (297**3 = 99.94 * 2**18);
    # the three branches keep t*297 inside TeX's 32-bit integers.
    if shortage <= 7230584:
        r = (shortage * 297) // total_flex
    elif total_flex >= 1663497:
        r = shortage // (total_flex // 297)
    else:
        r = shortage
    if r > 1290:  # 1290**3 < 2**31 < 1291**3
        return INF_BAD
    return (r * r * r + 0o400000) // 0o1000000


# ---------------------------------------------------------------------------
# Glue setting
# ---------------------------------------------------------------------------

def _collect_stretch(nodes: list) -> dict:
    """Sum stretch per GlueOrder from all GlueNodes in nodes."""
    totals: dict[GlueOrder, int] = {o: 0 for o in GlueOrder}
    for node in nodes:
        if isinstance(node, (GlueNode, LeadersNode)):
            totals[node.glue.stretch_order] += node.glue.stretch
    return totals


def _collect_shrink(nodes: list) -> dict:
    """Sum shrink per GlueOrder from all GlueNodes in nodes."""
    totals: dict[GlueOrder, int] = {o: 0 for o in GlueOrder}
    for node in nodes:
        if isinstance(node, (GlueNode, LeadersNode)):
            totals[node.glue.shrink_order] += node.glue.shrink
    return totals


def _highest_order(totals: dict) -> GlueOrder:
    """Return the highest GlueOrder with nonzero total, or NORMAL if none."""
    for order in (GlueOrder.FILLL, GlueOrder.FILL, GlueOrder.FIL, GlueOrder.NORMAL):
        # TeX §659/§665 selects nonzero totals, including negated fil glue.
        if totals[order] != 0:
            return order
    return GlueOrder.NORMAL


def _set_glue(box: HlistNode | VlistNode, need: int) -> int:
    """Set *box*'s glue-set fields for a *need* sp size change; return its badness.

    The badness is TeX's ``last_badness`` from ``hpack`` §649/§658/§664 and
    ``vpack`` §668/§673/§676: 0 for an exact fit, an empty list or infinite
    glue; ``badness(need, stretch)`` / ``badness(-need, shrink)`` for finite
    glue; ``OVERFULL_BAD`` when the finite shrink cannot absorb ``-need``.
    """
    if need == 0:
        box.glue_sign = GlueSign.NORMAL
        box.glue_order = GlueOrder.NORMAL
        box.glue_set = 0.0
        return 0

    if need > 0:
        totals = _collect_stretch(box.list)
        order = _highest_order(totals)
        total = totals[order]
        box.glue_sign = GlueSign.STRETCHING
        box.glue_order = order
        # No stretch available: the box stays at natural width (underfull).
        # Binary32 operands and quotient preserve TeX §109 arithmetic.
        box.glue_set = glue_ratio(need, total) if total else 0.0
        if order != GlueOrder.NORMAL or not box.list:
            return 0
        return compute_badness(need, total)

    totals = _collect_shrink(box.list)
    order = _highest_order(totals)
    total = totals[order]
    box.glue_sign = GlueSign.SHRINKING
    box.glue_order = order
    if total == 0:
        box.glue_set = 0.0
    else:
        # Finite glue cannot shrink past its minimum (§664 glue_set := 1.0).
        box.glue_set = (1.0 if order == GlueOrder.NORMAL and total < -need
                        else glue_ratio(-need, total))
    if order != GlueOrder.NORMAL or not box.list:
        return 0
    if total < -need:
        return OVERFULL_BAD
    return compute_badness(-need, total)


def set_glue_hbox(box: HlistNode, *, target_width: int) -> int:
    """Set glue-set fields on *box* in-place and return its badness.

    Computes the stretch or shrink ratio required to reach *target_width*
    from the box's natural width (stored before this call as ``box.width``).
    Sets ``box.glue_sign``, ``box.glue_order``, ``box.glue_set``, and
    then updates ``box.width = target_width``.

    Does NOT emit overfull/underfull warnings — that is the caller's
    responsibility.  See.

    Returns:
        TeX's ``last_badness`` for the box (§649-§664): the value
        ``\\badness`` reads, ``OVERFULL_BAD`` (1000000) when overfull.

    Example::

        badness = set_glue_hbox(box, target_width=20 * 65536)
    """
    badness = _set_glue(box, target_width - box.width)
    box.width = target_width
    return badness


def set_glue_vbox(box: VlistNode, *, target_height: int) -> int:
    """Set glue-set fields on *box* in-place (vertical analogue of ``set_glue_hbox``).

    Same algorithm as ``set_glue_hbox`` but operates on ``box.height``.
    Sets ``box.height = target_height`` after setting glue fields.

    Returns:
        TeX's ``last_badness`` for the box (§668-§676).
    """
    badness = _set_glue(box, target_height - box.height)
    box.height = target_height
    return badness


def _box_badness_message(
    box: HlistNode | VlistNode, badness: int, kind: str,
    threshold: int, fuzz: int, excess: int,
) -> str | None:
    """Apply hpack/vpack diagnostic thresholds (§660-667 / §674-677)."""
    if not box.list or box.glue_sign == GlueSign.NORMAL or box.glue_order != GlueOrder.NORMAL:
        return None
    if badness > INF_BAD:
        if excess <= fuzz and threshold >= 100:
            return None
        label = "Overfull"
    elif badness > threshold:
        label = ("Tight" if box.glue_sign == GlueSign.SHRINKING
                 else "Underfull" if badness > 100 else "Loose")
    else:
        return None
    no_flex = not any(isinstance(n, (GlueNode, LeadersNode)) for n in box.list)
    detail = "no flex available" if no_flex else f"badness {badness}"
    return f"{label} \\{kind} ({detail})"


def append_overfull_rule(
    box: HlistNode, badness: int, font_manager: FontManager, *,
    hfuzz: int, overfull_rule: int,
) -> bool:
    r"""Append TeX's ``\overfullrule`` marker to an overfull hbox (§666).

    ``hpack`` ends an hbox whose finite shrink falls more than ``\hfuzz``
    short of its size with a rule ``\overfullrule`` wide, of running height
    and depth, so it spans the box. The box's dimensions do not change — the
    marker sticks out past its right edge — and ``\overfullrule=0pt`` draws
    nothing. Call it after the overfull report, which measures the list
    without the marker.

    Args:
        box: The packed hbox; ``width`` is the size it was packed to.
        badness: The ``last_badness`` ``set_glue_hbox`` returned for *box*.
        font_manager: Supplies character widths for the natural width.
        hfuzz: Live ``\hfuzz`` in sp.
        overfull_rule: Live ``\overfullrule`` in sp.

    Returns:
        True when the marker was appended.

    Example::

        badness = set_glue_hbox(box, target_width=20 * 65536)
        append_overfull_rule(box, badness, fm, hfuzz=6554, overfull_rule=327680)
    """
    # Only §664's overfull branch (finite shrink short, nonempty list) rates
    # a box above inf_bad.
    if badness <= INF_BAD or overfull_rule <= 0:
        return False
    natural = _measure_hlist(box.list, font_manager)[0]
    if natural - box.width - _collect_shrink(box.list)[GlueOrder.NORMAL] <= hfuzz:
        return False
    box.list.append(RuleNode(width=overfull_rule, height=RUNNING_DIMEN, depth=RUNNING_DIMEN))
    return True


def short_display(nodes: Iterable[Node], font_manager: FontManager | None = None) -> str:
    r"""Return TeX's ``short_display`` of a horizontal list (§174-§175).

    The one-line form that follows a paragraph line's overfull/underfull
    report. A character prints ``\<font> `` when its font differs from the
    last one printed, then its source characters (a ligature prints what
    formed it) in ``^^`` notation outside 32..126. Boxes, inserts, marks,
    adjusts and whatsits print ``[]``, a rule ``|``, math ``$``, and glue or
    leaders a space unless all their components are zero (the engine has no
    shared ``zero_glue``, §8). A discretionary prints its pre then
    its post material, never its nobreak; kerns and penalties print nothing.

    Args:
        nodes: The list to display; nested boxes are not entered.
        font_manager: Resolves persistent font keys to live id_text.

    Returns:
        The display text.

    Example::

        from aspose_tex._engine.nodes import CharNode, DiscretionaryNode
        hyphen = DiscretionaryNode(pre=(CharNode(char=45, font_name="tenrm"),),
                                   post=(), nobreak=())
        nodes = [CharNode(char=97, font_name="tenrm"), hyphen,
                 CharNode(char=98, font_name="tenrm")]
        assert short_display(nodes) == "\\tenrm a-b"
    """
    out: list[str] = []
    _short_display(nodes, out, [None], font_manager)
    return "".join(out)


def _short_display(
    nodes: Iterable[Node], out: list[str], font: list[str | None], font_manager: FontManager | None,
) -> None:
    for node in nodes:
        if isinstance(node, CharNode):
            if node.font_name != font[0]:
                name = node.font_name
                if name.startswith("\x00font:"):
                    if font_manager is None:
                        raise ValueError("short_display requires a font manager for persistent keys")
                    name = font_manager.font_id_text(name)
                out.append(f"\\{name} ")
                font[0] = node.font_name
            out.extend(_print_ascii(code) for code in node.source or (node.char,))
        elif isinstance(node, (HlistNode, VlistNode, InsertNode, MarkNode, AdjustNode, WhatsitNode)):
            out.append("[]")
        elif isinstance(node, RuleNode):
            out.append("|")
        elif isinstance(node, (GlueNode, LeadersNode)):
            glue = node.glue
            if glue.width or glue.stretch or glue.shrink:
                out.append(" ")
        elif isinstance(node, MathNode):
            out.append("$")
        elif isinstance(node, DiscretionaryNode):
            _short_display(node.pre, out, font, font_manager)
            _short_display(node.post, out, font, font_manager)


def _print_ascii(code: int) -> str:
    """§49/§68: a character as TeX prints it, ``^^`` notation if unprintable."""
    if 32 <= code < 127:
        return chr(code)
    if code < 64:
        return f"^^{chr(code + 64)}"
    if code == 127:
        return "^^?"
    return f"^^{code:02x}"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

class HBoxBuilder:
    """Accumulates nodes for one horizontal box.

    Usage::

        builder = HBoxBuilder(font_manager)
        builder.add_char(ord('H'), 'tenrm')
        builder.add_char(ord('i'), 'tenrm')
        box = builder.build()

    Args:
        font_manager: Used to look up character metrics and lig/kern tables
                      when ``add_char`` is called.
    """

    def __init__(
        self,
        font_manager: FontManager,
        *,
        badness_sink: Callable[[int], None] | None = None,
    ) -> None:
        self._nodes: list = []
        self._font_manager = font_manager
        self._badness_sink = badness_sink
        #: TeX ``last_badness`` of the most recent :meth:`build` (§649).
        self.last_badness = 0
        # The CharNode the current lig/kern run ends in (§1034-1040); a
        # CharNode spliced in any other way (\unhbox, an accent) starts no run.
        self._run_tail: CharNode | None = None

    def end_run(self) -> None:
        """End the current lig/kern run, as a non-character command does (§1038).

        The next :meth:`add_char` starts a fresh run, so no ligature or font
        kern joins it to the character before the command.
        """
        self._run_tail = None

    def add_char(self, char: int, font_name: str) -> None:
        """Append a character, applying lig/kern with the previous character.

        Algorithm (applied only when the previous node is the ``CharNode``
        that ended the current run, in the *same* font):

        1. Check for a ligature between the previous char and *char*.
           If found, replace the last ``CharNode`` with the ligature char
           and restart the check (loop until no more ligatures).
        2. Check for a kern between the previous char and *char*.
           If nonzero, insert a ``KernNode(kern_sp, explicit=False)``.
        3. Append ``CharNode(char, font_name)``.
        """
        metrics = self._font_manager.get_metrics(font_name)

        # Measurement-only alignment adapters have no character admission.
        if metrics is not None and not self._font_manager.check_character(font_name, char):
            self.end_run()
            return

        # Lig/kern processing — only within the run, and in the same font
        if (metrics is not None and self._nodes
                and self._run_tail is not None and self._nodes[-1] is self._run_tail):
            prev = self._run_tail
            if prev.font_name == font_name:
                lig = metrics.ligature(prev.char, char)
                if lig is not None:
                    # Replace the previous CharNode with the ligature glyph.
                    # The current char is consumed by the ligature — do not append it.
                    self._run_tail = CharNode(char=lig, font_name=font_name,
                                              source=(*(prev.source or (prev.char,)), char))
                    self._nodes[-1] = self._run_tail
                    return
                # No ligature — check for kern
                kern_sp = metrics.kern(prev.char, char)
                if kern_sp:
                    self._nodes.append(KernNode(width=kern_sp, explicit=False))

        self._run_tail = CharNode(char=char, font_name=font_name)
        self._nodes.append(self._run_tail)

    def add_kern(self, width: int, *, explicit: bool = True) -> None:
        """Append a ``KernNode``.

        Args:
            width:    Space in sp.
            explicit: ``True`` for ``\\kern``; ``False`` for automatic font kern.
        """
        self._nodes.append(KernNode(width=width, explicit=explicit))

    def add_italic_correction(self) -> None:
        """Append the italic correction of the preceding character (``\\/``).

        TeX:The Program §1112 (``ital_corr``): appends a kern carrying the
        *per-character* ``char_italic`` of the tail char node.  A no-op unless
        the list ends in a ``CharNode``.  This is the eager-box counterpart of
        ``TeXInterpreter._exec_italic_correction``, which applies the same rule
        to the paragraph list.
        """
        if not self._nodes:
            return
        last = self._nodes[-1]
        if not isinstance(last, CharNode):
            return
        metrics = self._font_manager.get_metrics(last.font_name)
        if metrics is None:
            return
        self._nodes.append(
            KernNode(width=metrics.char_metrics(last.char).italic,
                     explicit=False, italic_correction=True),
        )

    def add_glue(self, glue: Glue) -> None:
        """Append a ``GlueNode``."""
        self._nodes.append(GlueNode(glue=glue))

    def add_penalty(self, penalty: int) -> None:
        """Append a ``PenaltyNode``."""
        self._nodes.append(PenaltyNode(penalty=penalty))

    def add_rule(self, width: int, height: int, depth: int) -> None:
        """Append a ``RuleNode``."""
        self._nodes.append(RuleNode(width=width, height=height, depth=depth))

    def add_box(self, box: HlistNode | VlistNode) -> None:
        """Append a sub-box node (nested ``\\hbox`` or ``\\vbox``)."""
        self._nodes.append(box)

    def build(
        self,
        *,
        target_width: int | None = None,
        spread: int | None = None,
    ) -> HlistNode:
        """Finalise and return the ``HlistNode``.

        1. Measure natural (width, height, depth) via ``_measure_hlist``.
        2. Compute ``final_width``:
           - ``target_width`` if given (``\\hbox to <d>``)
           - ``natural_width + spread`` if spread given (``\\hbox spread <d>``)
           - ``natural_width`` otherwise
        3. Construct HlistNode, call ``set_glue_hbox``, return.
        """
        nat_w, nat_h, nat_d = _measure_hlist(self._nodes, self._font_manager)

        if target_width is not None:
            final_width = target_width
        elif spread is not None:
            final_width = nat_w + spread
        else:
            final_width = nat_w

        box = HlistNode(
            list=self._nodes,
            width=nat_w,
            height=nat_h,
            depth=nat_d,
            shift_amount=0,
            glue_sign=GlueSign.NORMAL,
            glue_order=GlueOrder.NORMAL,
            glue_set=0.0,
        )
        self.last_badness = set_glue_hbox(box, target_width=final_width)
        if self._badness_sink is not None:
            self._badness_sink(self.last_badness)
        return box


class VBoxBuilder:
    """Accumulates nodes for one vertical box.

    Usage::

        vb = VBoxBuilder(font_manager)
        vb.add_hbox(hbox1)
        vb.add_hbox(hbox2)
        vbox = vb.build()
    """

    def __init__(
        self,
        font_manager: FontManager,
        *,
        badness_sink: Callable[[int], None] | None = None,
    ) -> None:
        self._nodes: list = []
        self._font_manager = font_manager
        self._badness_sink = badness_sink
        #: TeX ``last_badness`` of the most recent :meth:`build` (§649).
        self.last_badness = 0

    def add_hbox(self, box: HlistNode) -> None:
        """Append an ``HlistNode`` to the vertical list."""
        self._nodes.append(box)

    def add_vbox(self, box: VlistNode) -> None:
        """Append a ``VlistNode`` to the vertical list."""
        self._nodes.append(box)

    def add_kern(self, width: int) -> None:
        """Append a ``KernNode`` (vertical kern)."""
        self._nodes.append(KernNode(width=width, explicit=True))

    def add_glue(self, glue: Glue) -> None:
        """Append a ``GlueNode``."""
        self._nodes.append(GlueNode(glue=glue))

    def add_penalty(self, penalty: int) -> None:
        """Append a ``PenaltyNode``."""
        self._nodes.append(PenaltyNode(penalty=penalty))

    def add_rule(self, width: int, height: int, depth: int) -> None:
        """Append a ``RuleNode``."""
        self._nodes.append(RuleNode(width=width, height=height, depth=depth))

    def build(
        self,
        *,
        target_height: int | None = None,
        spread: int | None = None,
        max_depth: int | None = None,
    ) -> VlistNode:
        """Finalise and return the ``VlistNode``.

        1. Measure natural (width, height, depth) via ``_measure_vlist``.
        2. Limit the depth to *max_depth* (``\\boxmaxdepth``, §668): the excess
           moves into the natural height.
        3. Compute ``final_height``.
        4. Construct VlistNode, call ``set_glue_vbox``, return.
        """
        nat_w, nat_h, nat_d = _measure_vlist(self._nodes, self._font_manager)
        if max_depth is not None and nat_d > max_depth:
            nat_h += nat_d - max_depth
            nat_d = max(max_depth, 0)

        if target_height is not None:
            final_height = target_height
        elif spread is not None:
            final_height = nat_h + spread
        else:
            final_height = nat_h

        box = VlistNode(
            list=self._nodes,
            width=nat_w,
            height=nat_h,
            depth=nat_d,
            shift_amount=0,
            glue_sign=GlueSign.NORMAL,
            glue_order=GlueOrder.NORMAL,
            glue_set=0.0,
        )
        self.last_badness = set_glue_vbox(box, target_height=final_height)
        if self._badness_sink is not None:
            self._badness_sink(self.last_badness)
        return box
