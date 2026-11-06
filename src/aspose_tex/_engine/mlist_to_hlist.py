"""Translate a math list (noads) into an hlist of boxes/glyphs/kerns/glue.

/ §C/§D.  This is the Appendix-G core of real math
typesetting: a single recursive pass per style turns each :class:`Noad` from
:mod:`math_list` into ``CharNode`` / ``KernNode`` / ``GlueNode`` / ``HlistNode``
material, then walks adjacent atom-class pairs inserting inter-atom math glue
from the 8x8 spacing table.  No new node type is added (the backends render the
produced nodes unchanged).

Scope: Ord/Op/Bin/Rel/Open/Close/Punct/Inner atoms, symbol-to-glyph
selection via the math families, italic correction (no-script case, rule 17),
the minimal Op axis-shift (rule 13), the full 8x8 spacing table (rule 18) with
mu-to-sp conversion, and the style/glue/kern/nonscript carriers.  Scripts,
fractions, accents, radicals, and delimiters are parsed into the noad structure
by cascade #1 but laid out by; here they go through the
*placeholder path* (§C.6 — render the available nucleus, skip the geometry,
never raise).

References: TeX:The Program §720-§760 (``mlist_to_hlist``), §726-§728 (Bin
retyping), §749 (Op centring), §764-§767 (math glue / mu units), §716 (mu
arithmetic).  TeXbook Chapter 18 p.170 (the spacing table), Appendix G rules
1-12, 17-18.  §C/§D.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from aspose_tex._engine.box_builder import _measure_hlist, set_glue_hbox
from aspose_tex._engine.math_delimiters import _half
from aspose_tex._engine.math_list import (
    DEFAULT_FRACTION_THICKNESS,
    DelimiterCode,
    MathChar,
    MathClass,
    MathList,
    Noad,
    NoadKind,
)
from aspose_tex._engine.math_style import (
    TeXStyle,
    cramped,
    denom_style,
    num_style,
    size_of,
    sub_style,
    sup_style,
)
from aspose_tex._engine.nodes import (
    INF_PENALTY,
    CharNode,
    GlueNode,
    GlueSign,
    HlistNode,
    KernNode,
    LeadersNode,
    PenaltyNode,
    RuleNode,
    VlistNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._engine.tex_arith import UNITY, x_over_n, xn_over_d

if TYPE_CHECKING:
    from aspose_tex._fonts.font_manager import FontManager
    from aspose_tex._fonts.math_family_registry import MathFamilyRegistry
    from aspose_tex._fonts.math_font_parameters import MathFontParameters


# ---------------------------------------------------------------------------
# §D — the 8x8 inter-atom math-spacing table (TeX:The Program §764, rule 18)
# ---------------------------------------------------------------------------
#
# This is TeX's ``math_spacing`` string, transcribed verbatim.  Each cell is
# indexed [left_class][right_class] over Ord/Op/Bin/Rel/Open/Close/Punct/Inner
# (0..7).  The code (§766 decode) is:
#   '0' -> no space
#   '1' -> thin  (\thinmuskip),  inserted only in display/text (suppressed in script)
#   '2' -> thin  (\thinmuskip),  ALWAYS inserted
#   '3' -> med   (\medmuskip),   suppressed in script & scriptscript
#   '4' -> thick (\thickmuskip), suppressed in script & scriptscript
#   '*' -> impossible (Bin is retyped to Ord before lookup); treated as no space.
# Single source of truth — do NOT re-derive (TeX:The Program §764).

_MATH_SPACING = (
    "02340001"  # Ord  -> Ord/Op/Bin/Rel/Open/Close/Punct/Inner
    "22*40001"  # Op
    "33**3**3"  # Bin
    "44*04004"  # Rel
    "00*00000"  # Open
    "02340001"  # Close
    "11*11111"  # Punct
    "12341011"  # Inner
)

# Decoded per code: (muskip_selector, suppressed_in_script).
_CODE_NONE = 0
_CODE_THIN_COND = 1
_CODE_THIN_ALWAYS = 2
_CODE_MED_COND = 3
_CODE_THICK_COND = 4

# The eight spacing-table classes (0..7).  Translation-time atom classes
# Radical/Vcenter/Accent/Over/Under (8..12) act as Ord for spacing (TeX §761).
_SPACING_CLASS_MAX = 7


def _spacing_class(math_class: MathClass) -> int:
    """Map a noad class to its 0..7 spacing-table row/column (Ord for 8..12)."""
    if math_class <= _SPACING_CLASS_MAX:
        return int(math_class)
    return int(MathClass.ORD)


# ---------------------------------------------------------------------------
# §C.4 — mu-to-sp conversion (TeX:The Program §716, §764)
# ---------------------------------------------------------------------------

_MU_UNIT = 18  # 1 em = 18 mu


def mu_to_sp(mu_value: int, style: TeXStyle, math_params: MathFontParameters) -> int:
    """Convert a mu value to sp at *style* (1 mu = 1/18 em of family-2 quad).

    TeX:The Program §716-717 ``mu_mult``: the size of 1 mu is first truncated
    to whole sp, ``m = x_over_n(math_quad, 18)`` (§732), then split into
    ``n = m div 2^16`` and ``f = m mod 2^16`` and applied as
    ``nx_plus_y(n, w, xn_over_d(w, f, 2^16))``.  Truncating ``m`` first is what
    makes ``\\,`` 109224 sp in cmsy10 rather than ``3 * quad / 18`` = 109226.

    Example::

        mu_to_sp(3 * 65536, TeXStyle.TEXT, params)   # -> 109224 (cmsy10)
    """
    m = x_over_n(math_params.math_quad(size_of(style)), _MU_UNIT)
    n, f = divmod(m, UNITY)  # floor division keeps f >= 0, as §716's fix-up does
    return n * mu_value + xn_over_d(mu_value, f, UNITY)


# ---------------------------------------------------------------------------
# §C — the translation pass
# ---------------------------------------------------------------------------


def mlist_to_hlist(
    mlist: list[Noad],
    style: TeXStyle,
    *,
    math_params: MathFontParameters,
    family_registry: MathFamilyRegistry,
    font_manager: FontManager,
    thin_mu: Glue,
    med_mu: Glue,
    thick_mu: Glue,
    scriptspace: int = 0,
    nulldelimiterspace: int = 0,
    delimiterfactor: int = 0,
    delimitershortfall: int = 0,
    penalties: bool = False,
    binoppenalty: int = 0,
    relpenalty: int = 0,
) -> list:
    """Translate *mlist* into an hlist of nodes at *style* (§C).

    Args:
        mlist:           The noad list (from :class:`math_list.MathListBuilder`).
        style:           The current math style (font size + crampedness).
        math_params:     sigma/xi provider for the math axis / quad.
        family_registry: Resolves ``(family, style)`` to a font CS / FontMetrics.
        font_manager:    For glyph metrics (italic correction, height/depth).
        thin_mu / med_mu / thick_mu: live ``\\thinmuskip`` / ``\\medmuskip`` /
            ``\\thickmuskip`` glue (components in mu; converted to sp here).
        scriptspace:     ``\\scriptspace`` — trailing kern after sub/superscripts
            (§A; TeX:The Program §758).
        nulldelimiterspace: ``\\nulldelimiterspace`` — width of a null delimiter
            box (§C/§E; the base-size interim, §0).
        delimiterfactor: ``\\delimiterfactor`` — the rule-19 delimiter scale,
            in thousandths (plain.tex = 901; §C, TeX §762).
        delimitershortfall: ``\\delimitershortfall`` — the rule-19 maximum amount
            a delimiter may fall short of its target (plain.tex = 5pt; §762).
        penalties:       TeX's ``mlist_penalties`` (§761): append the §767
            Bin/Rel penalties.  True only for a formula in a paragraph; every
            nested translation leaves it False (§720,).
        binoppenalty / relpenalty: ``\\binoppenalty`` / ``\\relpenalty``.

    Returns:
        A list of hlist nodes (``CharNode`` / ``KernNode`` / ``GlueNode`` /
        ``HlistNode`` / ``VlistNode`` / ``RuleNode``).
    """
    ctx = _Ctx(
        style, math_params, family_registry, font_manager,
        thin_mu, med_mu, thick_mu, scriptspace, nulldelimiterspace,
        delimiterfactor, delimitershortfall,
    )
    # §C: collapse each \left … \right span into a single Inner noad
    # (rule 19) before translation — the input is balanced (check_left_right
    # _balanced ran at $-close), so the pre-pass always sees matched boundaries.
    mlist = _group_left_right(mlist)
    # Pass 1: translate each atom's nucleus; record (spacing_class, nodes).
    items = _translate_atoms(mlist, ctx)
    _bin_to_ord_fixup(items)
    # Pass 2: emit translated nodes interleaved with inter-atom spacing.  It
    # restarts from the list's own style and re-tracks every style change
    # (§760 cur_style:=style), since pass 1 left ctx at the last one.
    ctx.style = style
    out = _emit_with_spacing(
        items, ctx,
        penalties=(binoppenalty, relpenalty) if penalties else None,
    )
    return out


class _Ctx:
    """Per-call translation context (style + providers + live muskips/dimens)."""

    __slots__ = (
        "delimiterfactor", "delimitershortfall",
        "family_registry", "font_manager", "math_params",
        "med_mu", "nulldelimiterspace", "scriptspace", "style",
        "thick_mu", "thin_mu",
    )

    def __init__(
        self, style, math_params, family_registry, font_manager,
        thin_mu, med_mu, thick_mu, scriptspace=0, nulldelimiterspace=0,
        delimiterfactor=0, delimitershortfall=0,
    ):
        self.style = style
        self.math_params = math_params
        self.family_registry = family_registry
        self.font_manager = font_manager
        self.thin_mu = thin_mu
        self.med_mu = med_mu
        self.thick_mu = thick_mu
        self.scriptspace = scriptspace
        self.nulldelimiterspace = nulldelimiterspace
        self.delimiterfactor = delimiterfactor
        self.delimitershortfall = delimitershortfall

    def at_style(self, style: TeXStyle) -> _Ctx:
        """Return a shallow copy of this context bound to *style* (§A.2).

        Used to render sub/superscripts (and num/denom) at the next-smaller
        style without mutating the running context.
        """
        return _Ctx(
            style, self.math_params, self.family_registry, self.font_manager,
            self.thin_mu, self.med_mu, self.thick_mu,
            self.scriptspace, self.nulldelimiterspace,
            self.delimiterfactor, self.delimitershortfall,
        )


class _Item:
    """A pass-1 translation result: an atom's class + its rendered nodes.

    ``kind`` distinguishes an atom (participates in spacing) from a raw
    contribution (a GLUE/KERN noad, or a STYLE marker) that emits directly.
    """

    __slots__ = ("math_class", "noad", "nodes")

    def __init__(self, math_class: int | None, nodes: list, noad: Noad):
        self.math_class = math_class  # 0..7 spacing class, or None for raw GLUE/KERN/STYLE
        self.nodes = nodes
        self.noad = noad


def _translate_atoms(mlist: list[Noad], ctx: _Ctx, items: list[_Item] | None = None) -> list[_Item]:
    if items is None:
        items = []
    # make_ord rewrites the list (ligatures merge noads), so work on a copy:
    # the builder's mlist may be translated again (e.g. measured, then set).
    mlist = list(mlist)
    text_chars: set[int] = set()  # id() of noads TeX marks math_text_char (§752)
    i = 0
    while i < len(mlist):
        noad = mlist[i]
        if noad.kind == NoadKind.ATOM:
            # §728: a Bin with no Bin-capable left neighbour is an Ord before
            # make_ord runs (goto reswitch), so it forms ligatures/kerns too.
            as_ord = noad.math_class == MathClass.ORD or (
                noad.math_class == MathClass.BIN and _bin_starts_as_ord(items)
            )
            kern = _make_ord(mlist, i, ctx, text_chars) if as_ord else None
            noad = mlist[i]
            nodes = _translate_nucleus(noad, ctx)
            if id(noad) in text_chars:
                _drop_text_char_italic(noad, nodes, ctx)
            math_class = int(MathClass.ORD) if as_ord else _spacing_class(noad.math_class)
            items.append(_Item(math_class, nodes, noad))
            if kern:
                carrier = Noad(NoadKind.KERN, width=kern)
                items.append(_Item(None, [KernNode(width=kern, explicit=False)], carrier))
        elif noad.kind in (NoadKind.GLUE, NoadKind.KERN):
            items.append(_Item(None, _translate_glue_kern(noad, ctx), noad))
        elif noad.kind == NoadKind.ADJUST:
            items.append(_Item(None, [noad.adjustment], noad))
        elif noad.kind == NoadKind.RULE:
            items.append(_Item(None, [noad.rule], noad))
        elif noad.kind == NoadKind.PENALTY:
            items.append(_Item(None, [PenaltyNode(penalty=noad.penalty)], noad))
        elif noad.kind == NoadKind.STYLE:
            # A style marker changes the running style for the rest of the list.
            if noad.style is not None:
                ctx.style = _STYLE_NAME_TO_TEX[noad.style]
            items.append(_Item(None, [], noad))
        elif noad.kind == NoadKind.CHOICE and noad.choices is not None:
            # TeX:The Program §731: the branch for the current style replaces
            # the choice node in place, so its noads take part in Bin retyping
            # and inter-atom spacing with their neighbours (no Inner wrapper).
            branch = _choice_for_style(noad.choices, ctx.style)
            _translate_atoms(_group_left_right(branch.noads), ctx, items)
        else:
            # FRACTION / BOUNDARY — §C.6 placeholder path (no layout
            # yet; render the available nucleus/numerator so nothing is lost).
            items.append(_Item(_placeholder_class(noad), _translate_placeholder(noad, ctx), noad))
        i += 1
    return items


# Left-neighbour classes after which a Bin is an Ord (§728; ``left_noad`` is
# the start of our separately translated \left…\right inner list).
_BIN_AS_ORD_AFTER = frozenset({
    int(MathClass.BIN), int(MathClass.OP), int(MathClass.REL),
    int(MathClass.OPEN), int(MathClass.PUNCT),
})


def _bin_starts_as_ord(items: list[_Item]) -> bool:
    """Whether a Bin translated next is an Ord by TeX §728's left-context rule.

    *items* holds the atoms already translated, each with its class as TeX's
    ``r_type`` would record it; raw glue/kern/style items do not count.
    """
    for item in reversed(items):
        if item.math_class is not None:
            return item.math_class in _BIN_AS_ORD_AFTER
    return True  # the first atom of a list: r_type starts as op_noad


# Noad classes a make_ord successor may have: ord_noad..punct_noad (§752).
_LIG_KERN_SUCCESSORS = frozenset({
    MathClass.ORD, MathClass.OP, MathClass.BIN, MathClass.REL,
    MathClass.OPEN, MathClass.CLOSE, MathClass.PUNCT,
})


def _make_ord(mlist: list[Noad], i: int, ctx: _Ctx, text_chars: set[int]) -> int | None:
    """Apply the font's lig/kern program between ``mlist[i]`` and its successor.

    TeX:The Program §752-§753 ``make_ord``: a script-less Ord whose nucleus is a
    symbol, followed by an Ord..Punct atom whose nucleus is a symbol of the same
    family, is marked a text char and looked up in the font's lig/kern program
    with the successor's character.  A ligature replaces both by one noad that
    keeps the successor's scripts, and the result is examined again; a kern is
    returned for the caller to place after the noad.  ``mlist`` is rewritten
    in place.  Only plain ``=:`` ligatures are read, as on the text path
    (:meth:`FontMetrics.ligature`).

    Returns:
        The kern after ``mlist[i]`` in sp, or ``None``.
    """
    while True:
        q = mlist[i]
        if q.subscr is not None or q.supscr is not None or not isinstance(q.nucleus, MathChar):
            return None
        if id(q) in text_chars or i + 1 >= len(mlist):
            return None
        p = mlist[i + 1]
        if (
            p.kind != NoadKind.ATOM
            or p.math_class not in _LIG_KERN_SUCCESSORS
            or not isinstance(p.nucleus, MathChar)
            or id(p) in text_chars
            or p.nucleus.fam != q.nucleus.fam
        ):
            return None
        text_chars.add(id(q))
        font_cs = ctx.family_registry.font_cs_for(q.nucleus.fam, size_of(ctx.style))
        if font_cs is None:
            return None
        metrics = ctx.font_manager.get_metrics(font_cs)
        lig = metrics.ligature(q.nucleus.position, p.nucleus.position)
        if lig is None:
            return metrics.kern(q.nucleus.position, p.nucleus.position)
        # =: the ligature takes the successor's scripts and replaces both noads;
        # the merged noad is a plain symbol again and is re-examined (§753).
        mlist[i] = dataclasses.replace(
            q, nucleus=MathChar(q.nucleus.fam, lig), subscr=p.subscr, supscr=p.supscr,
        )
        del mlist[i + 1]


def _drop_text_char_italic(noad: Noad, nodes: list, ctx: _Ctx) -> None:
    """Remove a text char's italic correction in a text font (§755).

    A symbol inside a word of a font with a nonzero interword space
    (``\\fontdimen2``, i.e. not a math italic font) gets no italic correction.
    """
    mc = noad.nucleus
    font_cs = ctx.family_registry.font_cs_for(mc.fam, size_of(ctx.style))
    if font_cs is None or ctx.font_manager.get_metrics(font_cs).fontdimen(2) == 0:
        return
    if len(nodes) == 2 and isinstance(nodes[1], KernNode) and not nodes[1].explicit:
        del nodes[1]


_STYLE_NAME_TO_TEX = {
    "display": TeXStyle.DISPLAY,
    "text": TeXStyle.TEXT,
    "script": TeXStyle.SCRIPT,
    "scriptscript": TeXStyle.SCRIPTSCRIPT,
}


def _translate_nucleus(noad: Noad, ctx: _Ctx) -> list:
    """Translate an ATOM's nucleus to nodes (rules 11/12/16/17; minimal rule 13).

    The accent / radical / over-under atom classes (App G rules 11/12/16) build
    a composite box around the nucleus first; scripts (``noad.subscr`` /
    ``supscr``) are then attached by :func:`_make_scripts` (rule 18).
    """
    # App G rules 11/12/16: these classes rebuild the nucleus into a composite
    # box (radical sign / accent / over-or-under bar) before scripts attach.
    if noad.math_class == MathClass.ACCENT:
        nodes = _make_math_accent(noad, ctx)
        if _scripts_go_inside_accent(noad):
            return nodes
    elif noad.math_class == MathClass.RADICAL:
        nodes = _make_radical(noad, ctx)
    elif noad.math_class == MathClass.INNER and (
        noad.left_delim is not None or noad.right_delim is not None
    ):
        # §C: a \left … \right group (collapsed by _group_left_right)
        # sizes its delimiters to span the inner box (rule 19, TeX §762).
        nodes = _make_left_right(noad, ctx)
    elif noad.math_class == MathClass.OVER:
        nodes = _make_over_under(noad, ctx, over=True)
    elif noad.math_class == MathClass.UNDER:
        nodes = _make_over_under(noad, ctx, over=False)
    elif noad.math_class == MathClass.VCENTER:
        # §C2 (TeX:The Program §735 make_vcenter): centre the \vcenter
        # box on the math axis.
        nodes = _make_vcenter(noad, ctx)
    elif noad.math_class == MathClass.OP:
        # §E (rule 13, §749-§750): make_op owns the size switch, axis
        # centring AND its own script placement (limits above/below vs right).
        from aspose_tex._engine.math_delimiters import make_op

        return make_op(noad, ctx)
    else:
        nodes = _render_field(noad.nucleus, ctx)
    # App G rule 18 (§750-§758): attach sub/superscripts to the nucleus.
    if noad.subscr is not None or noad.supscr is not None:
        nodes = _make_scripts(noad, nodes, ctx)
    return nodes


def _render_field(field, ctx: _Ctx) -> list:
    """Render a math field (MathChar / MathList / box / None) to nodes."""
    if field is None:
        return []
    if isinstance(field, MathChar):
        return _render_symbol(field, ctx)
    if isinstance(field, MathList):
        sub = mlist_to_hlist(
            field.noads, ctx.style,
            math_params=ctx.math_params, family_registry=ctx.family_registry,
            font_manager=ctx.font_manager,
            thin_mu=ctx.thin_mu, med_mu=ctx.med_mu, thick_mu=ctx.thick_mu,
            scriptspace=ctx.scriptspace, nulldelimiterspace=ctx.nulldelimiterspace,
            delimiterfactor=ctx.delimiterfactor, delimitershortfall=ctx.delimitershortfall,
        )
        return [_pack_hbox(sub, ctx.font_manager)]
    if isinstance(field, (HlistNode,)):
        return [field]
    # VlistNode or any already-built box: append as-is.
    return [field]


def _make_vcenter(noad: Noad, ctx: _Ctx) -> list:
    """Centre a ``\\vcenter`` box on the math axis (TeX:The Program §735).

    ``make_vcenter``: ``delta = height + depth``;
    ``height := axis_height(cur_size) + half(delta)``; ``depth := delta - height``,
    set directly on the box.  The box (a vlist built by
    ``build_math_vcenter_box``) is positioned by the DVI writer from its height,
    so no ``shift_amount`` is set — this is the direct-set §735 form, NOT
    ``math_delimiters.axis_center`` (which folds + sets ``shift_amount`` for a
    single-glyph delimiter, §709).  §C2.
    """
    box = noad.nucleus
    if not isinstance(box, (HlistNode, VlistNode)):
        # Defensive: a non-box VCENTER nucleus (should not happen — add_vcenter
        # always stores a built box) renders as an ordinary field.
        return _render_field(box, ctx)
    axis = ctx.math_params.axis_height(size_of(ctx.style))
    delta = box.height + box.depth
    box.height = axis + _half(delta)
    box.depth = delta - box.height
    return [box]


def _render_symbol(mc: MathChar, ctx: _Ctx) -> list:
    """Render a symbol noad to a CharNode + italic-correction kern (rules 11/12/17)."""
    from aspose_tex.exceptions import EngineError

    size = size_of(ctx.style)
    font_cs = ctx.family_registry.font_cs_for(mc.fam, size)
    if font_cs is None:
        raise EngineError(f"\\textfont {mc.fam} is undefined")
    if not ctx.font_manager.check_character(font_cs, mc.position):
        return []
    nodes: list = [CharNode(char=mc.position, font_name=font_cs)]
    # Italic correction (rule 17, no-script case): add the glyph's TFM IC.
    metrics = ctx.font_manager.get_metrics(font_cs)
    ic = metrics.char_metrics(mc.position).italic
    if ic:
        nodes.append(KernNode(width=ic, explicit=False))
    return nodes


# ---------------------------------------------------------------------------
# §A — make_scripts: super/subscript attachment (TeX:The Program §750-§758)
# ---------------------------------------------------------------------------


def _make_scripts(noad: Noad, nucleus_nodes: list, ctx: _Ctx, *, delta: int = 0) -> list:
    """Attach sub/superscript to a nucleus (TeX §750-§758, App G rule 18).

    Returns the nucleus followed by a single box carrying the shifted scripts.
    Reads sigma 13-19 from ``ctx.math_params`` at the current style; renders each
    script at the next-smaller style (``sub_style`` / ``sup_style`` of
    :mod:`math_style`).  The arithmetic is transcribed verbatim from §755-§758.

    Args:
        noad:          The atom carrying ``subscr`` / ``supscr``.
        nucleus_nodes: The already-rendered nucleus (rule 17 IC kern still
                       attached for a char nucleus — kept when the subscript
                       is empty, else stripped and reused as the superscript
                       offset ``delta``, §755).
        ctx:           The translation context at the nucleus style.
        delta:         The superscript offset for a box nucleus — the italic
                       correction :func:`math_delimiters.make_op` removed from
                       an operator box (§749).  A char nucleus derives its own.

    Returns:
        ``[nucleus..., scripts_box]`` (or just the nucleus if both scripts are
        empty after rendering).
    """
    style = ctx.style
    t = size_of(style)           # nucleus / current-style size for the sigma values
    script_size = size_of(sup_style(style))  # sigma 18/19 drops live at the script size
    mp = ctx.math_params

    # §755-§756: split a char nucleus from a box nucleus.  A char nucleus
    # (a single CharNode, optionally followed by its rule-17 IC kern) leaves the
    # initial shifts at 0 and uses the IC as the horizontal offset `delta`; a box
    # nucleus initialises the shifts from sup_drop/sub_drop (§756).
    is_char_nucleus = (
        len(nucleus_nodes) >= 1
        and isinstance(nucleus_nodes[0], CharNode)
        and all(isinstance(n, KernNode) for n in nucleus_nodes[1:])
    )
    if is_char_nucleus and noad.subscr is None:
        # §755: with an empty subscript the italic correction stays a kern after
        # the glyph (delta = 0), so a lone superscript starts after it.
        shift_up = 0
        shift_down = 0
        out_nucleus: list = list(nucleus_nodes)
    elif is_char_nucleus:
        shift_up = 0
        shift_down = 0
        # With a subscript the rule-17 IC kern becomes the superscript offset
        # `delta` (§755); strip it so it does not also advance the nucleus width.
        out_nucleus = [nucleus_nodes[0]]
        for n in nucleus_nodes[1:]:
            if isinstance(n, KernNode) and not n.explicit:
                delta = n.width
            else:
                out_nucleus.append(n)
    else:
        nbox = _pack_hbox(nucleus_nodes, ctx.font_manager)
        shift_up = nbox.height - mp.sup_drop(script_size)
        shift_down = nbox.depth + mp.sub_drop(script_size)
        out_nucleus = [nbox]

    x_height = mp.math_x_height(t)
    sup_field = noad.supscr
    sub_field = noad.subscr

    if sup_field is None:
        # §757 — subscript only.
        sub_box = _clean_box(sub_field, sub_style(style), ctx)
        sub_box.width += ctx.scriptspace
        clr = sub_box.height - (abs(x_height * 4) // 5)
        shift_down = max(shift_down, mp.sub1(t), clr)
        sub_box.shift_amount = -shift_down  # lower (positive shift_amount = up)
        return [*out_nucleus, sub_box]

    # §758 — superscript present (alone or with a subscript).
    sup_box = _clean_box(sup_field, sup_style(style), ctx)
    sup_box.width += ctx.scriptspace
    if style & 1:                                   # cramped -> sigma 15
        clr = mp.sup3(t)
    elif style < TeXStyle.TEXT:                     # display -> sigma 13
        clr = mp.sup1(t)
    else:                                           # text -> sigma 14
        clr = mp.sup2(t)
    shift_up = max(shift_up, clr, sup_box.depth + abs(x_height) // 4)

    if sub_field is None:
        # Superscript only (§758): raise the box by shift_up.  TeX applies the
        # `delta` offset only in the both-scripts case, never here.
        sup_box.shift_amount = shift_up
        return [*out_nucleus, sup_box]

    # Both scripts (§758 the combined case).
    sub_box = _clean_box(sub_field, sub_style(style), ctx)
    sub_box.width += ctx.scriptspace
    shift_down = max(shift_down, mp.sub2(t))
    theta = mp.default_rule_thickness(t)
    clr = 4 * theta - ((shift_up - sup_box.depth) - (sub_box.height - shift_down))
    if clr > 0:
        shift_down += clr
        clr = (abs(x_height * 4) // 5) - (shift_up - sup_box.depth)
        if clr > 0:
            shift_up += clr
            shift_down -= clr
    # The superscript is moved right by `delta`; stack sup over sub with a kern
    # carrying the residual vertical gap, then lower the whole by shift_down.
    sup_box.shift_amount = delta  # horizontal offset inside the vlist
    gap = (shift_up - sup_box.depth) - (sub_box.height - shift_down)
    stack = _v_pack([sup_box, KernNode(width=gap, explicit=False), sub_box], ctx)
    # The vlist reference point is the subscript baseline; lower it by shift_down
    # via an hbox wrapper (VlistNode.shift_amount is horizontal in an hlist).
    wrapper = _pack_hbox([stack], ctx.font_manager)
    wrapper.shift_amount = -shift_down
    # hpack accounts for the wrapper's shift; keep its natural dimensions.
    return [*out_nucleus, wrapper]


# ---------------------------------------------------------------------------
# §E.1 — box-stacking helpers (shared by scripts, fractions, radicals, accents)
# ---------------------------------------------------------------------------


def _v_pack(nodes: list, ctx: _Ctx) -> VlistNode:
    """Pack a vertical list to natural height/depth (TeX vpack §668).

    The reference point is the baseline of the last box in *nodes* (the standard
    TeX vlist convention used by :func:`box_builder._measure_vlist`).
    """
    from aspose_tex._engine.box_builder import _measure_vlist

    w, h, d = _measure_vlist(nodes, ctx.font_manager)
    return VlistNode(
        list=nodes, width=w, height=h, depth=d, shift_amount=0,
        glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
    )


def _v_stack(top: object, bottom: object, gap: int, ctx: _Ctx,
             *, ref: str = "baseline") -> VlistNode:
    """Stack two boxes with *gap* sp between them (TeX vpack §668).

    With ``ref="baseline"`` the vlist reference point is the bottom box's
    baseline; with ``ref="axis"`` the result is shifted so the *gap centre*
    (used as the fraction-bar / over-under centreline) is reported by the
    caller via the returned box geometry.  Reused by's large-operator
    limit stacking.
    """
    stack = _v_pack([top, KernNode(width=gap, explicit=False), bottom], ctx)
    return stack


def _clean_box(field, style: TeXStyle, ctx: _Ctx) -> HlistNode:
    """Render a math field to a single hbox at *style* (TeX §720 ``clean_box``).

    A ``None`` field becomes an empty hbox; any other field is translated
    through the ordinary :func:`_render_field` path at *style* and packed.
    """
    sub_ctx = ctx.at_style(style)
    nodes = _render_field(field, sub_ctx)
    if len(nodes) == 1 and isinstance(nodes[0], HlistNode):
        return nodes[0]
    return _pack_hbox(nodes, ctx.font_manager)


def _shift_box(box: object, amount: int) -> object:
    """Return *box* with ``shift_amount = amount`` (positive = up)."""
    box.shift_amount = amount
    return box


def _rebox(box: HlistNode, width: int, ctx: _Ctx) -> HlistNode:
    """Re-box *box* to *width*, centring it with ``\\hss`` glue (TeX §715 ``rebox``)."""
    if box.width == width:
        return box
    hss = Glue(0, 65536, GlueOrder.FIL, 65536, GlueOrder.FIL)
    inner = [GlueNode(glue=hss), box, GlueNode(glue=hss)]
    nat_w, nat_h, nat_d = _measure_hlist(inner, ctx.font_manager)
    out = HlistNode(
        list=inner, width=nat_w, height=nat_h, depth=nat_d, shift_amount=0,
        glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
    )
    set_glue_hbox(out, target_width=width)
    return out


# ---------------------------------------------------------------------------
# §C — make_fraction (TeX:The Program §743-§749, App G rule 15)
# ---------------------------------------------------------------------------


def _make_fraction(noad: Noad, ctx: _Ctx) -> list:
    """Lay out a fraction noad (TeX §743-§749, App G rule 15).

    Reads ``noad.numerator`` / ``noad.denominator`` (MathList), ``noad.thickness``
    (``None`` = ``\\atop``; ``DEFAULT_FRACTION_THICKNESS`` = ``\\over``; else a
    ``\\above`` dimen) and ``noad.left_delim`` / ``right_delim`` (base-size
    interim, §0).  Returns a single Inner box centred on the math axis.
    """
    style = ctx.style
    t = size_of(style)
    mp = ctx.math_params
    theta = mp.default_rule_thickness(t)
    axis = mp.axis_height(t)
    display = style < TeXStyle.TEXT

    x = _clean_box(noad.numerator, num_style(style), ctx)     # numerator box
    z = _clean_box(noad.denominator, denom_style(style), ctx)  # denominator box
    # Equalise widths (§743): re-box the narrower to the max width, centred.
    width = max(x.width, z.width)
    x = _rebox(x, width, ctx)
    z = _rebox(z, width, ctx)

    if noad.thickness is None:                       # \atop — no bar
        rule_thickness = 0
    elif noad.thickness == DEFAULT_FRACTION_THICKNESS:  # \over
        rule_thickness = theta
    else:                                            # \above <dimen>
        rule_thickness = noad.thickness

    # Rule-15 shift selection (§746/§747).
    if display:
        shift_up = mp.num1(t)
        shift_down = mp.denom1(t)
    else:
        shift_up = mp.num2(t) if rule_thickness != 0 else mp.num3(t)
        shift_down = mp.denom2(t)

    # TeX's half() rounds odd values up (§100); a floor here puts the parts of
    # a fraction with an odd thickness or clearance deficit 1 sp off.
    if rule_thickness == 0:                           # \atop clearance (§746)
        clr = (7 if display else 3) * theta
        delta = _half(clr - ((shift_up - x.depth) - (z.height - shift_down)))
        if delta > 0:
            shift_up += delta
            shift_down += delta
    else:                                             # bar at axis (§747)
        clr = (3 if display else 1) * rule_thickness
        half_bar = _half(rule_thickness)
        delta = clr - ((shift_up - x.depth) - (axis + half_bar))
        if delta > 0:
            shift_up += delta
        delta = clr - ((axis - half_bar) - (z.height - shift_down))
        if delta > 0:
            shift_down += delta

    frac = _stack_fraction(x, z, shift_up, shift_down, rule_thickness, axis, width, ctx)
    # Delimiters (§748): var_delimiter at delim1/delim2, centred on the axis
    # (TeX's var_delimiter does that itself, §710; ours returns natural boxes).
    from aspose_tex._engine.math_delimiters import axis_center

    delim_size = mp.delim1(t) if display else mp.delim2(t)
    left = axis_center(_delimiter_box(noad.left_delim, delim_size, style, ctx), style, ctx)
    right = axis_center(_delimiter_box(noad.right_delim, delim_size, style, ctx), style, ctx)
    return [_pack_hbox([left, frac, right], ctx.font_manager)]


def _stack_fraction(x: HlistNode, z: HlistNode, shift_up: int, shift_down: int,
                    rule_thickness: int, axis: int, width: int, ctx: _Ctx) -> VlistNode:
    """Assemble the fraction vlist with its reference point on the math axis.

    Places the numerator *x* ``shift_up`` above the axis and the denominator *z*
    ``shift_down`` below it, with (for ``\\over`` / ``\\above``) a ``RuleNode``
    bar of *rule_thickness* centred at *axis*.  The returned vlist's
    height/depth are set so its baseline sits on the axis (so it renders centred
    in the surrounding hlist).
    """
    nodes: list = [x]
    num_bottom = shift_up - x.depth
    if rule_thickness == 0:                           # \atop — single gap
        gap = num_bottom - (-shift_down + z.height)
        nodes.append(KernNode(width=gap, explicit=False))
    else:
        # §748: the kerns meet the bar at axis ± half(thickness); for an odd
        # thickness the two edges are thickness + 1 apart, as in TeX.
        bar_top = axis + _half(rule_thickness)
        bar_bottom = axis - _half(rule_thickness)
        nodes.append(KernNode(width=num_bottom - bar_top, explicit=False))
        nodes.append(RuleNode(width=width, height=rule_thickness, depth=0))
        nodes.append(KernNode(width=bar_bottom - (-shift_down + z.height), explicit=False))
    nodes.append(z)
    box = _v_pack(nodes, ctx)
    box.width = width
    box.height = shift_up + x.height
    box.depth = shift_down + z.depth
    return box


# ---------------------------------------------------------------------------
# §D.1 — make_math_accent (TeX:The Program §738, App G rule 12)
# ---------------------------------------------------------------------------


def _make_math_accent(noad: Noad, ctx: _Ctx) -> list:
    """Centre an accent glyph over the nucleus (TeX §738, App G rule 12)."""
    from aspose_tex.exceptions import EngineError

    style = ctx.style
    t = size_of(style)
    mp = ctx.math_params
    fam = noad.accent_fam if noad.accent_fam is not None else 0
    pos = noad.accent_pos if noad.accent_pos is not None else 0
    font_cs = ctx.family_registry.font_cs_for(fam, t)
    if font_cs is None:
        raise EngineError(f"\\textfont {fam} is undefined")
    metrics = ctx.font_manager.get_metrics(font_cs)

    # Nucleus as a clean box at the cramped style (§738).
    nuc = _clean_box(noad.nucleus, cramped(style), ctx)

    # §738 successor walk: advance along the accent-glyph chain while a wider
    # variant still fits the nucleus width (cycle-guarded — TFM chains are
    # acyclic, but guard against a malformed font).
    accent_pos = pos
    seen: set[int] = set()
    while True:
        nxt = metrics.next_larger(accent_pos)
        if nxt is None or nxt in seen:
            break
        nxt_w = metrics.char_metrics(nxt).width
        if nxt_w > nuc.width:
            break
        seen.add(accent_pos)
        accent_pos = nxt

    acc_m = metrics.char_metrics(accent_pos)
    # §738 skew: the accent rides on the nucleus's skew_char kern (if any).
    skew = _skew_kern(noad.nucleus, ctx)
    width = nuc.width
    height = nuc.height
    delta = min(height, mp.math_x_height(t))
    # §742: a char nucleus takes the accent's scripts into its box, set at the
    # current style; the accent keeps its place over the bare char, so only
    # delta and h follow the taller box.  _translate_nucleus attaches nothing after.
    if _scripts_go_inside_accent(noad):
        scripted = Noad(
            NoadKind.ATOM, MathClass.ORD, nucleus=noad.nucleus,
            subscr=noad.subscr, supscr=noad.supscr,
        )
        nuc = _clean_box(MathList([scripted]), style, ctx)
        delta += nuc.height - height
        height = nuc.height
    # §738 shift_amount(y) = s + half(w - width(y)): TeX's half rounds odd
    # values up, and the char_box width includes the italic correction (§709).
    h_offset = _half(width - (acc_m.width + acc_m.italic)) + skew
    accent_glyph = [CharNode(char=accent_pos, font_name=font_cs)]
    if acc_m.italic:
        accent_glyph.append(KernNode(width=acc_m.italic, explicit=False))
    accent_box = _pack_hbox(accent_glyph, ctx.font_manager)
    if h_offset:
        accent_box = _pack_hbox(
            [KernNode(width=h_offset, explicit=False), accent_box], ctx.font_manager
        )
    # Stack: accent above the nucleus, lowered by `delta` so it rides close
    # (§738 — the accent box bottom sits `delta` into the nucleus top).
    gap = -delta
    stack = _v_pack([accent_box, KernNode(width=gap, explicit=False), nuc], ctx)
    stack.width = nuc.width
    # §738: a stack lower than the nucleus box is topped up with a kern, so the
    # accent stays where delta put it.
    if stack.height < height:
        stack.list.insert(0, KernNode(width=height - stack.height, explicit=False))
        stack.height = height
    return [stack]


def _scripts_go_inside_accent(noad: Noad) -> bool:
    """Return whether §742 moves an accent noad's scripts into its nucleus box."""
    return isinstance(noad.nucleus, MathChar) and (
        noad.subscr is not None or noad.supscr is not None
    )


def _skew_kern(field, ctx: _Ctx) -> int:
    """Return the nucleus skew_char kern for an accent (§738), or 0."""
    if not isinstance(field, MathChar):
        return 0
    size = size_of(ctx.style)
    font_cs = ctx.family_registry.font_cs_for(field.fam, size)
    if font_cs is None:
        return 0
    metrics = ctx.font_manager.get_metrics(font_cs)
    skewchar = getattr(metrics, "skewchar", -1)
    if skewchar is None or skewchar < 0:
        return 0
    kern = metrics.kern(field.position, skewchar)
    return kern or 0


# ---------------------------------------------------------------------------
# §D.2 — make_radical (TeX:The Program §737, App G rule 11; base-size interim §0)
# ---------------------------------------------------------------------------


def _make_radical(noad: Noad, ctx: _Ctx) -> list:
    """Draw a radical sign over the radicand (TeX §737, App G rule 11).

    The radical sign grows to the radicand via :func:`_delimiter_box`
    ; the vinculum is an :func:`_overbar` as thick as the sign is
    tall, so it continues the sign's top stroke.
    """
    style = ctx.style
    t = size_of(style)
    mp = ctx.math_params
    theta = mp.default_rule_thickness(t)

    x = _clean_box(noad.nucleus, cramped(style), ctx)
    # §737 clearance: display uses theta + 1/4·|x_height|; text uses theta + 1/4·theta.
    clr = (
        theta + abs(mp.math_x_height(t)) // 4
        if style < TeXStyle.TEXT
        else theta + abs(theta) // 4
    )

    target = x.height + x.depth + clr + theta
    y = _delimiter_box(noad.left_delim, target, style, ctx)
    y_box = y if isinstance(y, (HlistNode, VlistNode)) else _pack_hbox([y], ctx.font_manager)
    # TeX's height(y)/depth(y): a built-up sign (§713) has its reference point
    # at the top piece's baseline, while our VlistNode reports the whole extent
    # as height.
    top = y_box.list[0] if isinstance(y_box, VlistNode) and y_box.list else y_box
    y_height = top.height
    y_depth = y_box.height + y_box.depth - y_height
    delta = y_depth - (x.height + x.depth + clr)
    if delta > 0:
        clr += _half(delta)  # §737: clr + half(delta) — widen the clearance
    # The vinculum is as thick as the sign is tall, so the bar continues the
    # sign's top stroke (§737 overbar(x, clr, height(y))).
    bar = _overbar(x, clr, y_height, ctx)
    # §737 shift_amount(y) := -(height(x) + clr): the sign's baseline sits at
    # the bottom of the bar (our shift is positive up).
    y_box.shift_amount = x.height + clr + y_height - y_box.height
    return [_pack_hbox([y_box, bar], ctx.font_manager)]


# ---------------------------------------------------------------------------
# §D.3 — \overline / \underline + the shared _overbar (§734-§735, App G rule 16)
# ---------------------------------------------------------------------------


def _overbar(box: HlistNode, gap: int, rule_thickness: int, ctx: _Ctx) -> VlistNode:
    """Put a rule of *rule_thickness* above *box* with *gap* clearance (TeX §705).

    Layout top-to-bottom: a kern of *rule_thickness* (so the rule has air above
    it), the rule, a kern of *gap*, then *box*.  Reused by :func:`_make_radical`
    (the vinculum) and :func:`_make_over_under`.
    """
    nodes = [
        KernNode(width=rule_thickness, explicit=False),
        RuleNode(width=box.width, height=rule_thickness, depth=0),
        KernNode(width=gap, explicit=False),
        box,
    ]
    out = _v_pack(nodes, ctx)
    out.width = box.width
    out.height = box.height + gap + rule_thickness + rule_thickness
    out.depth = box.depth
    return out


def _make_over_under(noad: Noad, ctx: _Ctx, *, over: bool) -> list:
    """Lay out ``\\overline`` / ``\\underline`` (TeX §734-§735, App G rule 16)."""
    style = ctx.style
    t = size_of(style)
    theta = ctx.math_params.default_rule_thickness(t)
    x = _clean_box(noad.nucleus, cramped(style), ctx)
    if over:
        # §734: rule above the box, 3·theta clearance, theta-thick rule.
        return [_overbar(x, 3 * theta, theta, ctx)]
    # §735 under_bar: box on top, then 3·theta gap, then a theta-thick rule.
    nodes = [
        x,
        KernNode(width=3 * theta, explicit=False),
        RuleNode(width=x.width, height=theta, depth=0),
    ]
    out = _v_pack(nodes, ctx)
    out.width = x.width
    out.height = x.height
    out.depth = x.depth + 3 * theta + theta
    return [out]


# ---------------------------------------------------------------------------
# §E — the delimiter seam (FR-6, FR-9 — base-size interim; fills)
# ---------------------------------------------------------------------------


def _delimiter_box(delim: DelimiterCode | None, target_size: int,
                   style: TeXStyle, ctx: _Ctx):
    """Return a box for a delimiter of at least *target_size* (height + depth).

    (§B): grows the delimiter to *target_size* via the §706-§710
    ``var_delimiter`` successor-chain + extensible-recipe algorithm, centred on
    the math axis; a null / undefined delimiter returns a
    ``\\nulldelimiterspace``-wide empty box.  Called unchanged by
    :func:`_make_radical` (the radical sign) and the ``\\..withdelims`` fraction
    path (their §0/§C base-size interims are now filled).
    """
    from aspose_tex._engine.math_delimiters import var_delimiter

    return var_delimiter(delim, target_size, style, ctx)


def _delimiter_content_extents(nodes: list, font_manager: FontManager) -> tuple[int, int]:
    """Measure delimiter material, excluding immediate leader glue.

    Args:
        nodes: Translated children, retaining nested atom boxes.
        font_manager: Font metrics used by ordinary hpack measurement.

    Returns:
        Height and depth contributing to delimiter sizing.
    """
    _, height, depth = _measure_hlist(
        [node for node in nodes if not isinstance(node, LeadersNode)], font_manager,
    )
    return height, depth


def _make_left_right(noad: Noad, ctx: _Ctx) -> list:
    """Size a ``\\left … \\right`` group's delimiters to span the inner box (rule 19).

    TeX §762 ``make_left_right``: translate the inner mlist, measure its
    height/depth about the math axis, derive the delimiter target from
    ``\\delimiterfactor`` / ``\\delimitershortfall``, size both delimiters via
    :func:`_delimiter_box` (``var_delimiter``), and return
    one packed nucleus containing both delimiters and the translated contents.
    """
    from aspose_tex._engine.math_delimiters import axis_center, var_delimiter

    style = ctx.style
    axis = ctx.math_params.axis_height(size_of(style))
    inner = _clean_box(noad.nucleus, style, ctx)
    # §762 make_left_right: measure the inner box's extents ABOUT THE AXIS, then
    # derive the delimiter target exactly as TeX does.
    #   delta1 = height - axis   (span above the axis)
    #   delta2 = depth  + axis   (span below the axis)
    #   delta  = max(delta1, delta2)               (the larger half-span)
    # TeX: ``delta := x_over_n(delta, 500); delta := delimiterfactor*delta``
    # i.e. ``(delta // 500) * delimiterfactor`` -- the factor is per-500, NOT a
    # plain factor/1000 of the half-span; and the shortfall floor is the FULL
    # axis span (delta1 + delta2), not 2*delta (delta1 and delta2 differ when the
    # box is not symmetric about the axis, so 2*delta over/under-shoots).
    height, depth = _delimiter_content_extents(inner.list, ctx.font_manager)
    delta1 = height - axis
    delta2 = depth + axis
    delta = max(delta1, delta2)
    factor_target = (delta // 500) * ctx.delimiterfactor
    shortfall_target = delta1 + delta2 - ctx.delimitershortfall
    target = max(factor_target, shortfall_target)
    # The delimiters are centred on the math axis (§762/§709); the inner box
    # keeps its own baseline.
    left_box = axis_center(var_delimiter(noad.left_delim, target, style, ctx), style, ctx)
    right_box = axis_center(var_delimiter(noad.right_delim, target, style, ctx), style, ctx)
    #: the inner box is measurement-only. One whole nucleus owns
    # the leader grid and running-rule inheritance, including delimiters.
    return [_pack_hbox([left_box, *inner.list, right_box], ctx.font_manager)]


# ---------------------------------------------------------------------------
# §C — _group_left_right: collapse \left … \right spans (§C, TeX §1191)
# ---------------------------------------------------------------------------


def _group_left_right(mlist: list[Noad]) -> list[Noad]:
    """Collapse each ``\\left … \\right`` span into one Inner noad (TeX §1191, rule 19).

    Scans *mlist* for a ``BOUNDARY``/OPEN noad, finds its matching
    ``BOUNDARY``/CLOSE (respecting nesting depth — the input is already balanced
    by ``check_left_right_balanced``), and replaces the ``[open, inner…, close]``
    run with a single ``Noad(ATOM, INNER, nucleus=MathList(inner),
    left_delim=…, right_delim=…)``.  Nested groups are collapsed recursively so
    ``\\left(\\left[ x \\right]\\right)`` sizes both pairs.  Returns a new list;
    the input is not mutated.
    """
    out: list[Noad] = []
    i = 0
    n = len(mlist)
    while i < n:
        noad = mlist[i]
        if noad.kind == NoadKind.BOUNDARY and noad.math_class == MathClass.OPEN:
            depth = 1
            j = i + 1
            while j < n:
                cand = mlist[j]
                if cand.kind == NoadKind.BOUNDARY and cand.math_class == MathClass.OPEN:
                    depth += 1
                elif cand.kind == NoadKind.BOUNDARY and cand.math_class == MathClass.CLOSE:
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            # Recurse into the inner span so nested \left/\right also collapse.
            inner = _group_left_right(mlist[i + 1:j])
            close = mlist[j] if j < n else None
            out.append(
                Noad(
                    NoadKind.ATOM,
                    math_class=MathClass.INNER,
                    nucleus=MathList(inner),
                    left_delim=noad.left_delim,
                    right_delim=close.right_delim if close is not None else None,
                )
            )
            i = j + 1
        else:
            out.append(noad)
            i += 1
    return out


def _translate_glue_kern(noad: Noad, ctx: _Ctx) -> list:
    """Translate a GLUE/KERN carrier noad (mu units → sp)."""
    if noad.kind == NoadKind.KERN:
        width = mu_to_sp(noad.width, ctx.style, ctx.math_params) if noad.mu_glue else noad.width
        return [KernNode(width=width, explicit=True)]
    # GLUE
    if noad.leaders is not None:
        return [noad.leaders]
    if noad.nonscript:
        return []  # \nonscript is a marker handled in _emit_with_spacing.
    if noad.glue is not None:
        if noad.mu_glue:
            # \mskip: every finite component converts per style (§716 math_glue).
            return [GlueNode(glue=_mu_glue_to_sp(noad.glue, ctx))]
        #: an ordinary glue (\hfil and friends) is already in sp and
        # carries stretch/shrink orders the scalar path cannot express — emit it
        # verbatim (§1196 passes a glue_node through unchanged).
        return [GlueNode(glue=noad.glue)]
    width = mu_to_sp(noad.glue_value, ctx.style, ctx.math_params) if noad.mu_glue else noad.glue_value
    return [GlueNode(glue=Glue(width, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))]


def _placeholder_class(noad: Noad) -> int:
    """Spacing class for a not-yet-laid-out FRACTION/BOUNDARY noad."""
    if noad.kind == NoadKind.BOUNDARY:
        return _spacing_class(noad.math_class)  # Open / Close from the boundary
    # tex.web §761 leaves a bare fraction_noad at the default t:=ord_noad (only
    # its size changes), so one spliced from a \mathchoice branch spaces as
    # Ord.  Rule 15e's "Inner" is never visible: a fraction anywhere else is a
    # whole list, a {…} group (Ord) or a \left…\right interior (Inner).
    return int(MathClass.ORD)


def _translate_placeholder(noad: Noad, ctx: _Ctx) -> list:
    """Lay out a FRACTION (rule 15); BOUNDARY delimiter grows at."""
    if noad.kind == NoadKind.FRACTION:
        return _make_fraction(noad, ctx)
    # BOUNDARY (\left/\right): grows the delimiter; nothing to render.
    return []


def _choice_for_style(choices, style: TeXStyle) -> MathList:
    """Select the ``\\mathchoice`` sub-mlist for *style* (display/text/script/ss)."""
    tier = style // 2
    return choices[min(tier, 3)]


# ---------------------------------------------------------------------------
# §C.2 — Bin → Ord retyping (TeX:The Program §726-§728)
# ---------------------------------------------------------------------------


def _bin_to_ord_fixup(items: list[_Item]) -> None:
    """Retype a Bin atom to Ord in the contexts TeX §726-§728 require.

    A Bin becomes Ord when it is first, follows Bin/Op/Rel/Open/Punct, or is
    followed by Rel/Close/Punct (or is last).  Operates only on the atoms (the
    raw GLUE/KERN/STYLE items are skipped for adjacency).
    """
    atom_idx = [i for i, it in enumerate(items) if it.math_class is not None]
    bin_ = int(MathClass.BIN)
    prevent_after = {int(MathClass.BIN), int(MathClass.OP), int(MathClass.REL),
                     int(MathClass.OPEN), int(MathClass.PUNCT)}
    demote_before = {int(MathClass.REL), int(MathClass.CLOSE), int(MathClass.PUNCT)}
    for k, idx in enumerate(atom_idx):
        it = items[idx]
        if it.math_class != bin_:
            continue
        prev_cls = items[atom_idx[k - 1]].math_class if k > 0 else None
        next_cls = items[atom_idx[k + 1]].math_class if k + 1 < len(atom_idx) else None
        if prev_cls is None or prev_cls in prevent_after or next_cls is None or next_cls in demote_before:
            it.math_class = int(MathClass.ORD)


# ---------------------------------------------------------------------------
# §C.3 — pass 2: emit nodes interleaved with inter-atom spacing (rule 18)
# ---------------------------------------------------------------------------


def _emit_with_spacing(
    items: list[_Item], ctx: _Ctx, *, penalties: tuple[int, int] | None = None,
) -> list:
    out: list = []
    prev_class: int | None = None
    nonscript_pending = False
    script_style = size_of(ctx.style) in _SCRIPT_SIZES
    for index, it in enumerate(items):
        if it.math_class is None:
            # Raw GLUE/KERN/STYLE contribution.
            if it.noad.kind == NoadKind.STYLE and it.noad.style is not None:
                # §763: a style node changes the size and mu used for the
                # spacing that follows it, not for the spacing before it.
                ctx.style = _STYLE_NAME_TO_TEX[it.noad.style]
                script_style = size_of(ctx.style) in _SCRIPT_SIZES
            if it.noad.kind == NoadKind.GLUE and it.noad.nonscript:
                nonscript_pending = True
                continue
            if nonscript_pending and it.noad.kind == NoadKind.GLUE:
                # \nonscript drops the following glue in script styles.
                nonscript_pending = False
                if script_style:
                    continue
            nonscript_pending = False
            out.extend(it.nodes)
            continue
        nonscript_pending = False
        # Inter-atom spacing before this atom.
        if prev_class is not None:
            glue = _inter_atom_glue(prev_class, it.math_class, ctx, script_style)
            if glue is not None:
                out.append(glue)
        out.extend(it.nodes)
        prev_class = it.math_class
        if penalties is not None:
            penalty = _atom_penalty(items, index, penalties)
            if penalty is not None:
                out.append(PenaltyNode(penalty))
    return out


def _atom_penalty(items: list[_Item], index: int, penalties: tuple[int, int]) -> int | None:
    """Return the §767 penalty to put after ``items[index]``, or None.

    A Bin or Rel atom that is not last gets ``\\binoppenalty`` /
    ``\\relpenalty`` when that is below ``INF_PENALTY`` and the next item is
    neither a Rel atom nor a penalty ( Component 6).
    """
    math_class = items[index].math_class
    if math_class == int(MathClass.BIN):
        penalty = penalties[0]
    elif math_class == int(MathClass.REL):
        penalty = penalties[1]
    else:
        return None
    if index + 1 >= len(items) or penalty >= INF_PENALTY:
        return None
    following = items[index + 1]
    if following.math_class == int(MathClass.REL):
        return None
    if any(isinstance(node, PenaltyNode) for node in following.nodes[:1]):
        return None
    return penalty


_SCRIPT_SIZES = frozenset({size_of(TeXStyle.SCRIPT), size_of(TeXStyle.SCRIPTSCRIPT)})


def _inter_atom_glue(left: int, right: int, ctx: _Ctx, script_style: bool) -> GlueNode | None:
    """Return the math-glue node for the ordered class pair, or None (rule 18).

    Decodes the TeX ``math_spacing`` cell (§766): '1' = thin suppressed in
    script; '2' = thin always; '3' = med suppressed in script; '4' = thick
    suppressed in script; '0'/'*' = none.
    """
    cell = _MATH_SPACING[left * 8 + right]
    if cell in ("0", "*"):
        return None
    code = int(cell)
    if code == _CODE_THIN_ALWAYS:
        mu_glue = ctx.thin_mu
    elif code == _CODE_THIN_COND:
        if script_style:
            return None
        mu_glue = ctx.thin_mu
    elif code == _CODE_MED_COND:
        if script_style:
            return None
        mu_glue = ctx.med_mu
    else:  # _CODE_THICK_COND
        if script_style:
            return None
        mu_glue = ctx.thick_mu
    return GlueNode(glue=_mu_glue_to_sp(mu_glue, ctx))


def _mu_glue_to_sp(mu: Glue, ctx: _Ctx) -> Glue:
    """Convert a mu-unit Glue's components to sp at the current style.

    §716 ``math_glue``: only finite components are measured in mu; a ``fil``
    stretch or shrink is copied unchanged.
    """
    def conv(value: int, order: GlueOrder) -> int:
        if order != GlueOrder.NORMAL:
            return value
        return mu_to_sp(value, ctx.style, ctx.math_params)

    return Glue(
        mu_to_sp(mu.width, ctx.style, ctx.math_params),
        conv(mu.stretch, mu.stretch_order),
        mu.stretch_order,
        conv(mu.shrink, mu.shrink_order),
        mu.shrink_order,
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _pack_hbox(nodes: list, font_manager: FontManager) -> HlistNode:
    """Pack a node list into a natural-width HlistNode (no glue stretch)."""
    nat_w, nat_h, nat_d = _measure_hlist(nodes, font_manager)
    box = HlistNode(
        list=nodes, width=nat_w, height=nat_h, depth=nat_d, shift_amount=0,
        glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
    )
    set_glue_hbox(box, target_width=nat_w)
    return box
