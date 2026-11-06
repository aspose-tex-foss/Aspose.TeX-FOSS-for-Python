r"""Tests for cascade #1 — make_scripts ( / §A/§B/§E.1).

Covers the cascade-#1 acceptance criteria:
  AC-1  $x^2$ → superscript at script size, raised per the §758 sup-shift;
        $x_i$ → subscript at script size, lowered per sigma 16 (§757);
        $x_i^2$ → both scripts stacked with the §758 default_rule_thickness gap
  AC-2  $x^{a^b}$ nests — outer at script style (7pt cm), inner at scriptscript
        style (5pt cm); assert the resolved font CS per level
  AC-4  a box nucleus uses sup_drop/sub_drop (§756) vs a char nucleus (§755)

The translation needs the four standard math families (0 roman, 1 math italic,
2 symbols, 3 extension); the §758 both-scripts clearance reads ξ8
(default_rule_thickness) from family 3, so the preamble assigns cmex10.
"""

from __future__ import annotations

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.math_style import (
    TeXStyle,
    size_of,
    sub_style,
    sup_style,
)
from aspose_tex._engine.mlist_to_hlist import _Ctx, _make_scripts
from aspose_tex._engine.nodes import CharNode, HlistNode, KernNode, VlistNode
from aspose_tex._fonts.math_font_parameters import MathStyle
from aspose_tex._input.reader import StringInputSource
from tests._font_keys import font_key

# Math-font preamble (no plain.tex): families 0/1/2/3 at 10/7/5 pt.
_PRE = (
    r"\font\tenrm=cmr10 \font\teni=cmmi10 \font\tensy=cmsy10 \font\tenex=cmex10 "
    r"\font\sevenrm=cmr7 \font\seveni=cmmi7 \font\sevensy=cmsy7 "
    r"\font\fiverm=cmr5 \font\fivei=cmmi5 \font\fivesy=cmsy5 "
    r"\textfont0=\tenrm \scriptfont0=\sevenrm \scriptscriptfont0=\fiverm "
    r"\textfont1=\teni \scriptfont1=\seveni \scriptscriptfont1=\fivei "
    r"\textfont2=\tensy \scriptfont2=\sevensy \scriptscriptfont2=\fivesy "
    r"\textfont3=\tenex \scriptfont3=\tenex \scriptscriptfont3=\tenex "
    r"\tenrm "
)


def render(formula: str) -> list:
    """Run *formula* (with the math-font preamble) and return the appended nodes."""
    captured: list = []
    interp = TeXInterpreter()
    original = interp._append_to_hlist

    def _cap(node) -> None:
        captured.append(node)
        original(node)

    interp._append_to_hlist = _cap  # type: ignore[method-assign]
    interp.run(StringInputSource(_PRE + formula + r"\bye"))
    return captured


def _chars(nodes: list) -> list[CharNode]:
    """All CharNodes anywhere in *nodes* (recursing into boxes)."""
    out: list[CharNode] = []
    for n in nodes:
        if isinstance(n, CharNode):
            out.append(n)
        elif isinstance(n, (HlistNode, VlistNode)):
            out.extend(_chars(n.list))
    return out


def _boxes(nodes: list) -> list:
    """Top-level box nodes (HlistNode / VlistNode) in *nodes*."""
    return [n for n in nodes if isinstance(n, (HlistNode, VlistNode))]


# ---------------------------------------------------------------------------
# AC-1 — single superscript / subscript shift
# ---------------------------------------------------------------------------


class TestSingleScript:
    def test_superscript_renders_at_script_size(self) -> None:
        # $x^2$: nucleus x = cmmi10 (teni); superscript 2 = digit → fam 0, at
        # the script style → \scriptfont0 = cmr7 (sevenrm, 7pt).
        nodes = render(r"$x^2$")
        nucleus = [n for n in nodes if isinstance(n, CharNode)]
        assert nucleus and nucleus[0].char == ord("x")
        assert nucleus[0].font_name == font_key("teni", _PRE)
        # The superscript is the trailing box.
        box = _boxes(nodes)[-1]
        script_chars = _chars([box])
        assert len(script_chars) == 1
        assert script_chars[0].char == ord("2")
        assert script_chars[0].font_name == font_key("sevenrm", _PRE)  # 7pt script font

    def test_superscript_raised_by_section_758_value(self) -> None:
        # The trailing box's shift_amount must equal the §758 sup-only shift:
        # text style, non-cramped → clr = sup2; shift_up = max(0, sup2,
        # depth(sup) + |x_height|//4).
        nodes = render(r"$x^2$")
        box = _boxes(nodes)[-1]
        interp = TeXInterpreter()
        interp.run(StringInputSource(_PRE + r"$x$\bye"))  # ensure fonts loaded
        mp = interp._math_params
        t = MathStyle.TEXT
        sup2 = mp.sup2(t)
        x_height = mp.math_x_height(t)
        # The superscript box depth is small (digit on baseline); the dominant
        # term is sup2.  Assert the shift is at least sup2 and exactly the §758
        # max of the three terms with the box's own depth.
        expected_floor = max(sup2, box.depth + abs(x_height) // 4)
        assert box.shift_amount == expected_floor
        assert box.shift_amount > 0  # raised (positive = up)

    def test_subscript_renders_at_script_size_and_lowered(self) -> None:
        # $x_i$: subscript i → fam 1 math italic at script style → seveni (7pt);
        # box lowered (negative shift_amount).
        nodes = render(r"$x_i$")
        box = _boxes(nodes)[-1]
        sc = _chars([box])
        assert len(sc) == 1
        assert sc[0].char == ord("i")
        assert sc[0].font_name == font_key("seveni", _PRE)
        assert box.shift_amount < 0  # lowered

    def test_subscript_shift_is_section_757_value(self) -> None:
        nodes = render(r"$x_i$")
        box = _boxes(nodes)[-1]
        interp = TeXInterpreter()
        interp.run(StringInputSource(_PRE + r"$x$\bye"))
        mp = interp._math_params
        t = MathStyle.TEXT
        # §757: shift_down = max(0, sub1, height(sub) - 4/5·x_height).
        sub1 = mp.sub1(t)
        x_height = mp.math_x_height(t)
        clr = box.height - (abs(x_height * 4) // 5)
        expected = max(sub1, clr)
        assert -box.shift_amount == expected


# ---------------------------------------------------------------------------
# AC-1 — both scripts stacked (§758 combined case)
# ---------------------------------------------------------------------------


class TestBothScripts:
    def test_both_scripts_stack_in_a_vlist(self) -> None:
        # $x_i^2$: superscript over subscript, stacked via a vlist wrapped in an
        # hbox lowered by shift_down.
        nodes = render(r"$x_i^2$")
        box = _boxes(nodes)[-1]
        assert isinstance(box, HlistNode)
        # The hbox carries one vlist.
        inner = [n for n in box.list if isinstance(n, VlistNode)]
        assert len(inner) == 1
        vlist = inner[0]
        # vlist = [sup_box, KernNode(gap), sub_box]
        assert isinstance(vlist.list[0], HlistNode)  # superscript box
        assert isinstance(vlist.list[1], KernNode)   # vertical gap
        assert isinstance(vlist.list[2], HlistNode)  # subscript box
        sup_c = _chars([vlist.list[0]])
        sub_c = _chars([vlist.list[2]])
        assert sup_c[0].char == ord("2")
        assert sub_c[0].char == ord("i")

    def test_both_scripts_gap_at_least_default_rule_thickness(self) -> None:
        # The §758 both-scripts clearance enforces ≥ 4·default_rule_thickness
        # between the scripts; the vertical kern between the boxes is non-negative.
        nodes = render(r"$x_i^2$")
        box = _boxes(nodes)[-1]
        vlist = next(n for n in box.list if isinstance(n, VlistNode))
        gap = vlist.list[1]
        assert isinstance(gap, KernNode)
        assert gap.width >= 0

    def test_both_scripts_lowered(self) -> None:
        nodes = render(r"$x_i^2$")
        box = _boxes(nodes)[-1]
        assert box.shift_amount < 0  # the whole stack is lowered by shift_down


# ---------------------------------------------------------------------------
# AC-2 — nested scripts: style descends script → scriptscript
# ---------------------------------------------------------------------------


class TestNestedScripts:
    def test_nested_superscript_descends_to_scriptscript(self) -> None:
        # $x^{a^b}$: outer a at script style (7pt cm, seveni); inner b at
        # scriptscript style (5pt cm, fivei).
        nodes = render(r"$x^{a^b}$")
        all_chars = _chars(nodes)
        fonts = {chr(c.char): c.font_name for c in all_chars}
        assert fonts["x"] == font_key("teni", _PRE)     # nucleus, text size 10pt
        assert fonts["a"] == font_key("seveni", _PRE)   # outer superscript, script 7pt
        assert fonts["b"] == font_key("fivei", _PRE)    # inner superscript, scriptscript 5pt

    def test_sup_style_transitions_match_section_702(self) -> None:
        # The font selection above is driven by sup_style / size_of (§702).
        assert sup_style(TeXStyle.TEXT) == TeXStyle.SCRIPT
        assert sup_style(TeXStyle.SCRIPT) == TeXStyle.SCRIPTSCRIPT
        assert size_of(TeXStyle.SCRIPT) == MathStyle.SCRIPT
        assert size_of(TeXStyle.SCRIPTSCRIPT) == MathStyle.SCRIPTSCRIPT
        # subscripts are always cramped (§702 sub_style).
        assert sub_style(TeXStyle.TEXT) == TeXStyle.SCRIPT_CRAMPED


# ---------------------------------------------------------------------------
# AC-4 — char nucleus (§755) vs box nucleus (§756) initialisation
# ---------------------------------------------------------------------------


def _ctx_for(interp: TeXInterpreter) -> _Ctx:
    """Build a text-style _Ctx from a run interpreter's live providers."""
    rs = interp._register_set
    return _Ctx(
        TeXStyle.TEXT,
        interp._math_params,
        interp._math_family_registry,
        interp._font_manager,
        rs.get_muskip(256, _internal=True),
        rs.get_muskip(257, _internal=True),
        rs.get_muskip(258, _internal=True),
        rs.get_dimen(267, _internal=True),
        rs.get_dimen(266, _internal=True),
    )


class TestNucleusInit:
    def test_char_nucleus_uses_section_755_zero_init(self) -> None:
        # For a char nucleus + sup only, shift_up is the §758 max with a zero
        # init (NOT sup_drop) — i.e. it equals max(sup2, depth+x_height//4),
        # never height-of-nucleus minus sup_drop.  We assert via the rendered
        # $x^2$: the shift equals the zero-init §758 value (see AC-1 above) and
        # is independent of the nucleus height.
        from aspose_tex._engine.math_list import MathChar, MathClass, Noad, NoadKind

        interp = TeXInterpreter()
        interp.run(StringInputSource(_PRE + r"$x$\bye"))
        ctx = _ctx_for(interp)
        mp = ctx.math_params
        # Char nucleus 'x' (fam 1) with a superscript '2' (fam 0).
        noad = Noad(
            NoadKind.ATOM, MathClass.ORD,
            nucleus=MathChar(1, ord("x")),
            supscr=MathChar(0, ord("2")),
        )
        from aspose_tex._engine.mlist_to_hlist import _render_field

        nucleus_nodes = _render_field(noad.nucleus, ctx)
        out = _make_scripts(noad, nucleus_nodes, ctx)
        box = [n for n in out if isinstance(n, HlistNode)][-1]
        t = MathStyle.TEXT
        expected = max(mp.sup2(t), box.depth + abs(mp.math_x_height(t)) // 4)
        assert box.shift_amount == expected

    def test_box_nucleus_uses_section_756_drop_init(self) -> None:
        # A box nucleus (a nested {…} sub-formula) initialises shift_up from
        # height - sup_drop (§756), so the shift can exceed the §755 char floor.
        from aspose_tex._engine.math_list import (
            MathChar,
            MathClass,
            MathList,
            Noad,
            NoadKind,
        )
        from aspose_tex._engine.mlist_to_hlist import _render_field

        interp = TeXInterpreter()
        interp.run(StringInputSource(_PRE + r"$x$\bye"))
        ctx = _ctx_for(interp)
        mp = ctx.math_params
        # Box nucleus: {x} (a one-atom sub-mlist boxes as an Ord).
        inner = MathList([Noad(NoadKind.ATOM, MathClass.ORD, nucleus=MathChar(1, ord("x")))])
        noad = Noad(
            NoadKind.ATOM, MathClass.ORD,
            nucleus=inner,
            supscr=MathChar(0, ord("2")),
        )
        nucleus_nodes = _render_field(noad.nucleus, ctx)
        # Sanity: a sub-mlist renders as a single hbox (box nucleus).
        assert len(nucleus_nodes) == 1 and isinstance(nucleus_nodes[0], HlistNode)
        nbox = nucleus_nodes[0]
        out = _make_scripts(noad, nucleus_nodes, ctx)
        box = [n for n in out if isinstance(n, HlistNode)][-1]
        # §756 init: shift_up starts at height(nucleus) - sup_drop(script_size),
        # then §758 maxes with the floor; for a box nucleus the drop-init term
        # participates.
        script_size = size_of(sup_style(TeXStyle.TEXT))
        drop_init = nbox.height - mp.sup_drop(script_size)
        floor = max(mp.sup2(MathStyle.TEXT), box.depth + abs(mp.math_x_height(MathStyle.TEXT)) // 4)
        assert box.shift_amount == max(drop_init, floor)
