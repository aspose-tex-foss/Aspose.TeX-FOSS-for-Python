"""Variable-size delimiters — ``var_delimiter`` (§B).

This module owns the delimiter-growth algorithm: given a delimiter
code and a target size, it selects the smallest glyph from the TFM successor
chain (``FontMetrics.next_larger``) whose height+depth covers the target, or —
when even the largest discrete glyph is too short — builds an *extensible*
delimiter by stacking the top/mid/bot/rep pieces of the TFM extensible recipe
(``FontMetrics.extensible_recipe``, added at cascade #1).  The built delimiter
is centred on the math axis.

``var_delimiter`` is the implementation the base-size interims left
waiting on: ``mlist_to_hlist._delimiter_box`` (radical sign + ``\\..withdelims``
fraction delimiters) and the new ``\\left``/``\\right`` rule-19 path both call it.

The heavy glyph-chain logic lives here; ``mlist_to_hlist`` stays the
orchestrator (mirrors the split).  ``make_op`` (large operators) is
added to this module by cascade #3.

References: TeX:The Program §706-§710 (``var_delimiter``/``char_box``/
``stack_into_box``), §711-§714 (extensible assembly), §546 (TFM exten format).
TeXbook Appendix G rule 19 (delimiters), Chapter 17.  §B.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aspose_tex._engine.math_list import (
    DelimiterCode,
    LimitMode,
    MathChar,
    Noad,
)
from aspose_tex._engine.math_style import (
    TeXStyle,
    size_of,
    sub_style,
    sup_style,
)
from aspose_tex._engine.nodes import (
    CharNode,
    GlueSign,
    HlistNode,
    KernNode,
    VlistNode,
)
from aspose_tex._engine.registers import GlueOrder
from aspose_tex._fonts.math_font_parameters import MathStyle

if TYPE_CHECKING:
    from aspose_tex._engine.mlist_to_hlist import _Ctx
    from aspose_tex._fonts.font_metrics import FontMetrics

_DelimBox = HlistNode | VlistNode


def var_delimiter(
    delim: DelimiterCode | None,
    target_size: int,
    style: TeXStyle,
    ctx: _Ctx,
) -> _DelimBox:
    """Build a delimiter box of at least *target_size* (height+depth) — TeX §706-§710.

    The returned box carries the delimiter glyph at its *natural* height/depth
    (the caller positions it — :func:`mlist_to_hlist._make_left_right` centres it
    on the axis via :func:`axis_center`; :func:`mlist_to_hlist._make_radical` and
    the fraction-delimiter path place it with their own §737/§743 arithmetic).

    Selection order (TeX §707-§708):

    1. Try the *small* variant, then the *large* (extension-font) one; a variant
       whose fam/pos are both 0 is absent.  Each variant is tried in the font of
       the current size and then of every larger size down to the text size
       (a script-size delimiter may come from ``\\textfont``), following the
       :meth:`FontMetrics.next_larger` successor chain in each font.
    2. A glyph becomes the best so far only when it is taller than the previous
       best; the first glyph whose ``height + depth >= target_size`` is returned
       as a one-glyph hbox (§709).
    3. A glyph with an extensible recipe (:meth:`FontMetrics.extensible_recipe`)
       ends the search: its top/(mid)/rep*/bot pieces are stacked until the
       assembly reaches *target_size* (§713-§714).
    4. Otherwise return the tallest glyph seen, or — if no glyph at all
       (``delim`` is ``None``, the null delimiter, or the variant fonts are
       undefined) — a ``\\nulldelimiterspace``-wide empty box (preserves the
       §E null-delimiter contract).

    NFR-1 cycle guard: each successor-chain walk is bounded by a visited-set, so
    a malformed self-linked / cyclic TFM chain terminates and returns the best
    glyph seen so far — it never spins.

    Args:
        delim:       The delimiter code (small + large fam/pos variants), or
                     ``None`` / the null delimiter for an absent delimiter.
        target_size: Required height+depth in scaled points.
        style:       The current math style (selects the glyph size).
        ctx:         The :class:`mlist_to_hlist._Ctx` translation context.

    Returns:
        An :class:`HlistNode` (discrete glyph or null-delimiter box) or
        :class:`VlistNode` (built-up extensible delimiter), at natural geometry
        (the caller axis-centres it where required — see :func:`axis_center`).
    """
    if delim is None or _is_null_delimiter(delim):
        return _null_delimiter_box(ctx)

    # §707-§708: try the small variant, then the large one; each in the fonts
    # of the current size and then every larger size down to the text size
    # (script tries \scriptfont, then \textfont).  Within a font follow the
    # successor chain.  A glyph replaces the best so far only when it is
    # taller; the first one tall enough wins, and an extensible glyph ends the
    # search at once.
    best: tuple[str, int] | None = None
    best_size = 0
    for fam, pos in (
        (delim.small_fam, delim.small_pos),
        (delim.large_fam, delim.large_pos),
    ):
        if fam == 0 and pos == 0:
            continue  # this variant is absent
        for size in _SIZES_DOWN_TO_TEXT[size_of(style)]:
            font_cs = ctx.family_registry.font_cs_for(fam, size)
            if font_cs is None:
                continue
            metrics = ctx.font_manager.get_metrics(font_cs)
            code: int | None = pos
            seen: set[int] = set()
            # NFR-1: a malformed cyclic chain stops at the first repeat.
            while code is not None and code not in seen and metrics.has_char(code):
                seen.add(code)
                recipe = metrics.extensible_recipe(code)
                if recipe is not None:
                    return _stack_extensible(recipe, metrics, font_cs, target_size, ctx)
                cm = metrics.char_metrics(code)
                glyph_size = cm.height + cm.depth
                if glyph_size > best_size:
                    best = (font_cs, code)
                    best_size = glyph_size
                    if glyph_size >= target_size:
                        return _char_box(font_cs, code, ctx)
                code = metrics.next_larger(code)

    # Nothing tall enough: the tallest glyph seen, else a null-delimiter box.
    if best is not None:
        return _char_box(*best, ctx)
    return _null_delimiter_box(ctx)


_SIZES_DOWN_TO_TEXT = {
    MathStyle.TEXT: (MathStyle.TEXT,),
    MathStyle.SCRIPT: (MathStyle.SCRIPT, MathStyle.TEXT),
    MathStyle.SCRIPTSCRIPT: (MathStyle.SCRIPTSCRIPT, MathStyle.SCRIPT, MathStyle.TEXT),
}


def _is_null_delimiter(delim: DelimiterCode) -> bool:
    """Return True for the null delimiter (``\\left.`` / ``\\right.``) — all-zero code."""
    return (
        delim.small_fam == 0
        and delim.small_pos == 0
        and delim.large_fam == 0
        and delim.large_pos == 0
    )


def _null_delimiter_box(ctx: _Ctx) -> HlistNode:
    """Return a ``\\nulldelimiterspace``-wide empty hbox (TeX §706, FR-5)."""
    return _pack([KernNode(width=ctx.nulldelimiterspace, explicit=False)], ctx)


def _char_box(font_cs: str, char_code: int, ctx: _Ctx) -> HlistNode:
    """Return a one-glyph hbox for *char_code* in *font_cs* (TeX §709 ``char_box``).

    The box adopts the glyph's TFM height/depth/width so the vertical-list
    measurement (which ignores a bare ``CharNode``) counts the delimiter.  The
    glyph's italic correction is added to the width per §709.
    """
    metrics = ctx.font_manager.get_metrics(font_cs)
    cm = metrics.char_metrics(char_code)
    box = HlistNode(
        list=[CharNode(char=char_code, font_name=font_cs)],
        width=cm.width + cm.italic,
        height=cm.height,
        depth=cm.depth,
        shift_amount=0,
        glue_sign=GlueSign.NORMAL,
        glue_order=GlueOrder.NORMAL,
        glue_set=0.0,
    )
    return box


def _stack_extensible(
    recipe: tuple[int, int, int, int],
    metrics: FontMetrics,
    font_cs: str,
    target_size: int,
    ctx: _Ctx,
) -> VlistNode:
    """Stack a built-up delimiter from a TFM extensible recipe (TeX §713-§714).

    The recipe names four piece char codes ``(top, mid, bot, rep)`` (0 = absent).
    The bottom, top, and — when present — middle pieces are placed once; the
    repeatable ``rep`` piece fills the gap.  Pieces abut with no glue (§714);
    the assembly grows by whole ``rep`` units until its height+depth reaches
    *target_size*.  When a middle piece is present (e.g. a large brace) the
    repeat count is doubled so both halves grow symmetrically.

    Args:
        recipe:      ``(top, mid, bot, rep)`` piece char codes.
        metrics:     Scaled metrics of the extension font.
        font_cs:     The extension-font control-sequence name.
        target_size: Required height+depth in scaled points.
        ctx:         The translation context.

    Returns:
        A :class:`VlistNode` whose pieces stack top-to-bottom, width = the widest
        piece, with explicit height/depth covering the assembled extent.
    """
    top, mid, bot, rep = recipe

    def piece_extent(code: int) -> int:
        if code == 0:
            return 0
        cm = metrics.char_metrics(code)
        return cm.height + cm.depth

    rep_extent = piece_extent(rep)
    fixed = piece_extent(top) + piece_extent(bot) + piece_extent(mid)

    # §714: add rep pieces until the assembly is at least target_size.  When a
    # middle piece exists, rep pieces are added in pairs (one each side of mid).
    if rep_extent <= 0:
        repeats = 0
    else:
        repeats = 0
        while fixed + repeats * rep_extent < target_size:
            repeats += 1
        if mid != 0 and repeats % 2 == 1:
            repeats += 1  # keep the two halves symmetric about the middle piece

    # Assemble top -> (rep * half) -> mid -> (rep * rest) -> bot, top-to-bottom.
    pieces: list[int] = []
    if top:
        pieces.append(top)
    if mid != 0:
        half = repeats // 2
        pieces.extend([rep] * half)
        pieces.append(mid)
        pieces.extend([rep] * (repeats - half))
    else:
        pieces.extend([rep] * repeats)
    if bot:
        pieces.append(bot)

    boxes = [_char_box(font_cs, code, ctx) for code in pieces if code]
    width = max((b.width for b in boxes), default=0)
    extent = sum(b.height + b.depth for b in boxes)
    out = VlistNode(
        list=boxes,
        width=width,
        height=extent,
        depth=0,
        shift_amount=0,
        glue_sign=GlueSign.NORMAL,
        glue_order=GlueOrder.NORMAL,
        glue_set=0.0,
    )
    return out


def axis_center(box: _DelimBox, style: TeXStyle, ctx: _Ctx) -> _DelimBox:
    """Centre a delimiter *box* vertically on the math axis (TeX §709).

    Moves the box up by ``raise_by = axis - (height - depth) / 2``.
    A single-glyph :class:`HlistNode` retains natural dimensions and records
    the shift once: both hpack (§653) and the writers account for it.
    A built-up :class:`VlistNode` uses the existing height-fold convention
    for its vertical position, with zero shift.

    Used by the ``\\left``/``\\right`` rule-19 path; the radical /
    fraction-delimiter callers keep the natural box geometry their own
    arithmetic expects.
    """
    axis = ctx.math_params.axis_height(size_of(style))
    # Distance the box must move up so its centre sits on the axis (§710).
    raise_by = axis - _half(box.height - box.depth)
    if isinstance(box, HlistNode):
        box.shift_amount = raise_by
    else:
        box.height += raise_by
        box.depth -= raise_by
        box.shift_amount = 0
    return box


def _pack(nodes: list, ctx: _Ctx) -> HlistNode:
    """Pack *nodes* into a natural-width hbox (delegates to the orchestrator)."""
    from aspose_tex._engine.mlist_to_hlist import _pack_hbox

    return _pack_hbox(nodes, ctx.font_manager)


# ---------------------------------------------------------------------------
# make_op — large operators (§E; TeX §749-§750, rule 13)
# ---------------------------------------------------------------------------


def make_op(noad: Noad, ctx: _Ctx) -> list:
    """Lay out a large operator (TeX:The Program §749-§750, App G rule 13).

    Replaces the §C.1 ``_center_op_on_axis`` interim with the full
    rule-13 treatment:

    1. **Size switch (§749).** In display style (``DISPLAY`` / ``DISPLAY_CRAMPED``)
       a single-symbol nucleus whose glyph has a ``next_larger`` successor is
       replaced by that larger glyph (the cmex "large" ``\\sum`` / ``\\int``).
       Text and smaller styles keep the base glyph.  Reuses
       :meth:`FontMetrics.next_larger` — the same chain ``var_delimiter`` walks.
    2. **Axis centre (§749).** A symbol nucleus's op box is raised so its
       centre sits on the math axis.  TeX's ``shift_amount = half(h - d) -
       axis_height`` is positive *down*; ours is positive up, so the sign is
       flipped.  A box or sub-list nucleus (``\\mathop{\\rm lim}``) stays on
       the baseline, as in TeX.
    3. **Limits (§750, rule 13).** Per :attr:`Noad.limits`:
       ``LIMITS`` (or ``DISPLAY_LIMITS`` in display style) stacks the superscript
       above and the subscript below the op box, each centred horizontally, with
       the ξ9-ξ13 ``big_op_spacing1..5`` clearances; ``NO_LIMITS`` (or
       ``DISPLAY_LIMITS`` outside display) falls through to the ordinary
       script-to-the-right path.

    Args:
        noad: The OP atom (``noad.nucleus`` symbol/box, ``subscr`` / ``supscr``).
        ctx:  The :class:`mlist_to_hlist._Ctx` translation context.

    Returns:
        The node list for the operator: a single axis-centred op box, or that box
        followed by a limit-stack / script box.
    """
    style = ctx.style
    display = style < TeXStyle.TEXT  # DISPLAY (0) or DISPLAY_CRAMPED (1)

    # (1) Size switch: in display, swap a single-symbol nucleus for its larger
    # cmex successor when one exists.
    op_nodes = _op_nucleus_nodes(noad, ctx, display)

    # (2) Axis centre (§749, symbol nucleus only): raise the op box so its
    # centre lands on the axis.
    op_box = _pack(op_nodes, ctx)
    if isinstance(noad.nucleus, MathChar):
        axis = ctx.math_params.axis_height(size_of(style))
        op_box.shift_amount = axis - _half(op_box.height - op_box.depth)

    # (3) Limit placement.
    if noad.supscr is None and noad.subscr is None:
        return [op_box]

    limits = _resolve_limits(noad.limits, display)
    if limits:
        return [_stack_limits(noad, op_box, ctx)]
    # NO_LIMITS: scripts to the right via the ordinary script path.  Centring is
    # already folded into op_box.shift_amount, which _make_scripts preserves on a
    # box nucleus.
    from aspose_tex._engine.mlist_to_hlist import _make_scripts

    # §749: a char nucleus's italic correction is `delta`; with a subscript
    # beside the op it comes off the op box (the subscript tucks under the
    # slant) and goes to make_scripts as the superscript offset (§756/§758).
    delta = _op_italic(noad, op_box, ctx)
    if noad.subscr is not None:
        op_box.width -= delta
    return _make_scripts(noad, [op_box], ctx, delta=delta)


def _resolve_limits(mode: LimitMode, display: bool) -> bool:
    """Return True when the operator stacks limits above/below (rule 13)."""
    if mode == LimitMode.LIMITS:
        return True
    if mode == LimitMode.NO_LIMITS:
        return False
    return display  # DISPLAY_LIMITS: above/below in display, right otherwise.


def _op_nucleus_nodes(noad: Noad, ctx: _Ctx, display: bool) -> list:
    """Render the operator nucleus, applying the §749 display size switch."""
    from aspose_tex._engine.mlist_to_hlist import _render_field

    nucleus = noad.nucleus
    if display and isinstance(nucleus, MathChar):
        size = size_of(ctx.style)
        font_cs = ctx.family_registry.font_cs_for(nucleus.fam, size)
        if font_cs is not None:
            metrics = ctx.font_manager.get_metrics(font_cs)
            if metrics.has_char(nucleus.position):
                larger = metrics.next_larger(nucleus.position)
                if larger is not None and metrics.has_char(larger):
                    # §749: use the larger successor glyph + its italic correction.
                    cm = metrics.char_metrics(larger)
                    nodes: list = [CharNode(char=larger, font_name=font_cs)]
                    if cm.italic:
                        nodes.append(KernNode(width=cm.italic, explicit=False))
                    return nodes
    return _render_field(nucleus, ctx)


def _stack_limits(noad: Noad, op_box: HlistNode, ctx: _Ctx) -> _DelimBox:
    """Stack sup above / sub below the op box, centred, with ξ9-ξ13 clearances (§750).

    TeX §750: the superscript box ``x`` sits above the operator with a gap
    ``shift_up = max(big_op_spacing1, big_op_spacing3 - depth(x))`` and a top
    margin ``big_op_spacing5``; the subscript box ``y`` sits below with a gap
    ``shift_down = max(big_op_spacing2, big_op_spacing4 - height(y))`` and a
    bottom margin ``big_op_spacing5``.  All three boxes are re-boxed to the
    widest width so the stack centres horizontally.

    Note the xi pairing: the *floor* is xi9/xi10 (``big_op_spacing1``/``2`` --
    the minimum gaps), and the *script-relative* term subtracts the adjacent
    script dimension from xi11/xi12 (``big_op_spacing3``/``4``).  Transcribed
    verbatim from §750 -- getting the pairing backwards inflates the subscript
    gap by xi12 - xi10 (~4.3 pt for cmex10), which is exactly the
    baseline divergence this fixes.
    """
    from aspose_tex._engine.mlist_to_hlist import (
        _clean_box,
        _rebox,
        _v_pack,
    )

    style = ctx.style
    mp = ctx.math_params
    t = size_of(style)
    delta = _op_italic(noad, op_box, ctx)  # §749 italic correction for centring

    sup = _clean_box(noad.supscr, sup_style(style), ctx) if noad.supscr else None
    sub = _clean_box(noad.subscr, sub_style(style), ctx) if noad.subscr else None

    # §750 y := clean_box(nucleus): the op box keeps its §749 axis shift inside
    # a wrapper, so the stack's reference point is the operator's own baseline
    # and its centre (not the stack's) sits on the axis.
    op_wrapped = _pack([op_box], ctx)
    width = op_wrapped.width
    if sup is not None:
        width = max(width, sup.width)
    if sub is not None:
        width = max(width, sub.width)
    op_centered = _rebox(op_wrapped, width, ctx)

    nodes: list = []
    height = op_centered.height
    depth = op_centered.depth
    if sup is not None:
        # §750: rebox to the common width first, then move the superscript
        # right by half the italic correction (a vlist shift, which leaves the
        # stack width alone) so it centres over the slanted operator.
        sup_box = _rebox(sup, width, ctx)
        sup_box.shift_amount = _half(delta)
        # §751 shift_up: floor xi9, script-relative term xi11 - depth(sup).
        gap = max(mp.big_op_spacing1(t), mp.big_op_spacing3(t) - sup_box.depth)
        nodes.append(KernNode(width=mp.big_op_spacing5(t), explicit=False))
        nodes.append(sup_box)
        nodes.append(KernNode(width=gap, explicit=False))
        height += mp.big_op_spacing5(t) + sup_box.height + sup_box.depth + gap
    nodes.append(op_centered)
    if sub is not None:
        sub_box = _rebox(sub, width, ctx)
        sub_box.shift_amount = -_half(delta)
        # §751 shift_down: floor xi10, script-relative term xi12 - height(sub).
        gap = max(mp.big_op_spacing2(t), mp.big_op_spacing4(t) - sub_box.height)
        nodes.append(KernNode(width=gap, explicit=False))
        nodes.append(sub_box)
        nodes.append(KernNode(width=mp.big_op_spacing5(t), explicit=False))
        depth += gap + sub_box.height + sub_box.depth + mp.big_op_spacing5(t)

    # §750 builds v by hand: width = the common width, height/depth measured
    # from the operator's baseline; no shift.
    stack = _v_pack(nodes, ctx)
    stack.width = width
    stack.height = height
    stack.depth = depth
    stack.shift_amount = 0
    return stack


def _half(x: int) -> int:
    """TeX's ``half`` (§100): ``x/2`` rounded, odd values rounded up."""
    return (x + 1) // 2


def _op_italic(noad: Noad, op_box: HlistNode, ctx: _Ctx) -> int:
    """Return the operator glyph's TFM italic correction (§749 ``delta``)."""
    nucleus = noad.nucleus
    if not isinstance(nucleus, MathChar):
        return 0
    size = size_of(ctx.style)
    font_cs = ctx.family_registry.font_cs_for(nucleus.fam, size)
    if font_cs is None:
        return 0
    metrics = ctx.font_manager.get_metrics(font_cs)
    code = nucleus.position
    if ctx.style < TeXStyle.TEXT:
        larger = metrics.next_larger(code)
        if larger is not None:
            code = larger
    if not metrics.has_char(code):
        return 0
    return metrics.char_metrics(code).italic
