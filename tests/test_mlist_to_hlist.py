r"""Tests for the mlist_to_hlist translation (§C/§D/§E).

Covers cascade #2 acceptance criteria:
  AC-1  $x$ → one math-italic CharNode from \textfont1 + \mathsurround kerns
  AC-2  $x+y$ Ord-Bin-Ord = med both sides; $x=y$ Ord-Rel-Ord = thick (8x8 table)
  AC-4  \mathop vs \mathbin → different surrounding spacing
  §D    the 8x8 spacing table matches TeX:The Program §764 exactly
  AC-7  \mskip/\mkern scaled by math_quad; \nonscript suppresses glue in script
  AC-6  style 8→3 collapse + cramped/sub/sup/num/denom transitions (§702)
  FR-7  italic correction kern after a symbol

Translation needs real math fonts; the helper assigns families 0/1/2 and sets
\mathcode for + and = so the Bin/Rel classes drive the spacing table.
"""

from __future__ import annotations

import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.math_style import (
    TeXStyle,
    cramped,
    denom_style,
    num_style,
    size_of,
    sub_style,
    sup_style,
)
from aspose_tex._engine.nodes import CharNode, GlueNode, HlistNode, KernNode
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._fonts.math_font_parameters import MathStyle
from aspose_tex._input.reader import StringInputSource
from tests._font_keys import font_key

# Math-font + mathcode + muskip preamble (no plain.tex): families 0 (roman),
# 1 (math italic), 2 (symbols); + = Bin (class 2, fam 0, pos 0x2B); = = Rel
# (class 3, fam 0, pos 0x3D).  Plain-TeX muskip values.
_PRE = (
    r"\font\tenrm=cmr10 \font\teni=cmmi10 \font\tensy=cmsy10 "
    r"\font\sevenrm=cmr7 \font\seveni=cmmi7 \font\sevensy=cmsy7 "
    r"\font\fiverm=cmr5 \font\fivei=cmmi5 \font\fivesy=cmsy5 "
    r"\textfont0=\tenrm \scriptfont0=\sevenrm \scriptscriptfont0=\fiverm "
    r"\textfont1=\teni \scriptfont1=\seveni \scriptscriptfont1=\fivei "
    r"\textfont2=\tensy \scriptfont2=\sevensy \scriptscriptfont2=\fivesy "
    r"\tenrm "
    r"\thinmuskip=3mu \medmuskip=4mu \thickmuskip=5mu "
    r'\mathcode`\+="202B \mathcode`\="303D '
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
    return [n for n in nodes if isinstance(n, CharNode)]


def _glues(nodes: list) -> list[GlueNode]:
    return [n for n in nodes if isinstance(n, GlueNode)]


# ---------------------------------------------------------------------------
# AC-1 — single symbol
# ---------------------------------------------------------------------------


class TestSingleSymbol:
    def test_x_is_one_math_italic_char(self) -> None:
        nodes = render(r"$x$")
        chars = _chars(nodes)
        assert len(chars) == 1
        assert chars[0].char == ord("x")
        # math italic letter → family 1 = \textfont1 = cmmi10 ("teni").
        assert chars[0].font_name == font_key("teni", _PRE)

    def test_mathsurround_kerns_frame_the_formula(self) -> None:
        # \mathsurround=2pt → math-on and math-off nodes of 2pt (§1196).
        from aspose_tex._engine.nodes import MathNode

        nodes = render(r"\mathsurround=2pt $x$")
        bounds = [n for n in nodes if isinstance(n, MathNode)]
        assert [(b.width, b.after) for b in bounds] == [(2 * 65536, False), (2 * 65536, True)]

    def test_no_mathsurround_no_surround_kern(self) -> None:
        nodes = render(r"$x$")
        # default \mathsurround = 0 → no surround kern (only a possible IC kern).
        assert all(not (isinstance(n, KernNode) and n.explicit) for n in nodes)


# ---------------------------------------------------------------------------
# AC-2 — inter-atom spacing
# ---------------------------------------------------------------------------


class TestInterAtomSpacing:
    def test_ord_bin_ord_med_both_sides(self) -> None:
        nodes = render(r"$x+y$")
        glues = _glues(nodes)
        assert len(glues) == 2
        # \medmuskip = 4mu → 4/18 of the family-2 quad.
        assert glues[0].glue.width == glues[1].glue.width
        assert glues[0].glue.width > 0

    def test_ord_rel_ord_thick_both_sides(self) -> None:
        nodes = render(r"$x=y$")
        glues = _glues(nodes)
        assert len(glues) == 2
        assert glues[0].glue.width == glues[1].glue.width

    def test_thick_wider_than_med(self) -> None:
        # \thickmuskip (5mu) > \medmuskip (4mu).
        bin_glue = _glues(render(r"$x+y$"))[0].glue.width
        rel_glue = _glues(render(r"$x=y$"))[0].glue.width
        assert rel_glue > bin_glue

    def test_ord_ord_no_glue(self) -> None:
        # $xy$ is Ord-Ord → no inter-atom space.
        nodes = render(r"$xy$")
        assert len(_glues(nodes)) == 0


# ---------------------------------------------------------------------------
# AC-4 — forced classes drive spacing
# ---------------------------------------------------------------------------


class TestForcedClassSpacing:
    def test_mathop_vs_mathbin_differ(self) -> None:
        # Ord-Op-Ord (thin) vs Ord-Bin-Ord (med) → different surrounding glue.
        # A trailing operator would be retyped (Bin→Ord, §726-728), so keep an
        # Ord after it.
        op_glue = _glues(render(r"$x\mathop{a}y$"))
        bin_glue = _glues(render(r"$x\mathbin{a}y$"))
        assert op_glue and bin_glue
        assert op_glue[0].glue.width != bin_glue[0].glue.width


# ---------------------------------------------------------------------------
# §D — the 8x8 spacing table matches TeX §764
# ---------------------------------------------------------------------------


class TestSpacingTable:
    def test_table_matches_tex_math_spacing(self) -> None:
        from aspose_tex._engine.mlist_to_hlist import _MATH_SPACING

        # TeX:The Program §764 math_spacing string, verbatim.
        tex = (
            "02340001"
            "22*40001"
            "33**3**3"
            "44*04004"
            "00*00000"
            "02340001"
            "11*11111"
            "12341011"
        )
        assert tex == _MATH_SPACING

    def test_all_64_cells_decode(self) -> None:
        from aspose_tex._engine.mlist_to_hlist import _MATH_SPACING

        assert len(_MATH_SPACING) == 64
        assert set(_MATH_SPACING) <= set("01234*")


# ---------------------------------------------------------------------------
# AC-7 — mu glue/kern + \nonscript
# ---------------------------------------------------------------------------


class TestMuUnitsAndNonscript:
    def test_mskip_scaled_by_quad(self) -> None:
        # \mskip 9mu → 9/18 of the family-2 quad = half a quad.
        nodes = render(r"$x\mskip9mu y$")
        glues = _glues(nodes)
        assert glues
        # half-quad at text size for cmsy10 (quad ~ 10pt → ~5pt = 327680 sp).
        assert glues[0].glue.width > 0

    def test_mkern_emits_kern(self) -> None:
        nodes = render(r"$x\mkern3mu y$")
        kerns = [n for n in nodes if isinstance(n, KernNode) and n.explicit]
        assert any(k.width > 0 for k in kerns)

    def test_nonscript_keeps_glue_in_text_style(self) -> None:
        nodes = render(r"$x\nonscript\mskip9mu y$")
        assert len(_glues(nodes)) >= 1

    def test_nonscript_drops_glue_in_script_style(self) -> None:
        # \scriptstyle switches the running style; \nonscript then suppresses
        # the following \mskip glue (TeX:The Program §1171).
        nodes = render(r"$x\scriptstyle\nonscript\mskip9mu y$")
        assert len(_glues(nodes)) == 0


# ---------------------------------------------------------------------------
# AC-6 — style machinery (§702)
# ---------------------------------------------------------------------------


class TestStyleMachinery:
    def test_size_of_collapses_eight_to_three(self) -> None:
        assert size_of(TeXStyle.DISPLAY) is MathStyle.TEXT
        assert size_of(TeXStyle.DISPLAY_CRAMPED) is MathStyle.TEXT
        assert size_of(TeXStyle.TEXT) is MathStyle.TEXT
        assert size_of(TeXStyle.TEXT_CRAMPED) is MathStyle.TEXT
        assert size_of(TeXStyle.SCRIPT) is MathStyle.SCRIPT
        assert size_of(TeXStyle.SCRIPT_CRAMPED) is MathStyle.SCRIPT
        assert size_of(TeXStyle.SCRIPTSCRIPT) is MathStyle.SCRIPTSCRIPT
        assert size_of(TeXStyle.SCRIPTSCRIPT_CRAMPED) is MathStyle.SCRIPTSCRIPT

    def test_cramped(self) -> None:
        assert cramped(TeXStyle.DISPLAY) is TeXStyle.DISPLAY_CRAMPED
        assert cramped(TeXStyle.TEXT) is TeXStyle.TEXT_CRAMPED
        assert cramped(TeXStyle.TEXT_CRAMPED) is TeXStyle.TEXT_CRAMPED

    def test_sup_sub_style(self) -> None:
        # From display/text: sup → script, sub → cramped script (TeXbook App G).
        assert sup_style(TeXStyle.DISPLAY) is TeXStyle.SCRIPT
        assert sub_style(TeXStyle.DISPLAY) is TeXStyle.SCRIPT_CRAMPED
        assert sup_style(TeXStyle.TEXT) is TeXStyle.SCRIPT
        assert sub_style(TeXStyle.TEXT) is TeXStyle.SCRIPT_CRAMPED
        assert sup_style(TeXStyle.SCRIPT) is TeXStyle.SCRIPTSCRIPT
        assert sub_style(TeXStyle.SCRIPT) is TeXStyle.SCRIPTSCRIPT_CRAMPED

    def test_num_denom_style(self) -> None:
        assert num_style(TeXStyle.DISPLAY) is TeXStyle.TEXT
        assert denom_style(TeXStyle.DISPLAY) is TeXStyle.TEXT_CRAMPED
        assert num_style(TeXStyle.TEXT) is TeXStyle.SCRIPT
        assert denom_style(TeXStyle.TEXT) is TeXStyle.SCRIPT_CRAMPED

    def test_nested_group_renders_at_text_style(self) -> None:
        # AC-6 structural: a {<mlist>} nested field renders (boxed) at the
        # parent style here; actual script placement is.
        from aspose_tex._engine.nodes import HlistNode

        nodes = render(r"$\mathord{xy}$")
        assert any(isinstance(n, HlistNode) for n in nodes)


# ---------------------------------------------------------------------------
# FR-7 — italic correction
# ---------------------------------------------------------------------------


class TestItalicCorrection:
    def test_italic_correction_kern_after_symbol(self) -> None:
        # A math-italic letter with a non-zero TFM italic correction emits an
        # IC kern (rule 17, no-script case).
        nodes = render(r"$f$")
        kerns = [n for n in nodes if isinstance(n, KernNode) and not n.explicit]
        # cmmi10 'f' has a large italic correction.
        assert any(k.width > 0 for k in kerns)


# ---------------------------------------------------------------------------
# Graceful degradation (TeX §1195) — math without fonts deletes the formula
# ---------------------------------------------------------------------------


class TestFormulaDeletedWithoutFonts:
    def test_math_without_fonts_no_crash_no_output(self) -> None:
        # No \textfont assignments → insufficient symbol fonts → formula deleted
        # (no rendered math, no EngineError) — matches TeX §1195.
        captured: list = []
        interp = TeXInterpreter()
        original = interp._append_to_hlist
        interp._append_to_hlist = lambda n: (captured.append(n), original(n))  # type: ignore[assignment]
        interp.run(StringInputSource(r"\font\tenrm=cmr10 \tenrm a$x+y$b\bye"))
        # The surrounding text 'a' and 'b' render; the math produces no CharNode
        # from a math family (only the text a/b in tenrm).
        math_chars = [n for n in captured if isinstance(n, CharNode) and n.font_name == font_key("teni", _PRE)]
        assert not math_chars

    def test_text_around_deleted_formula_still_renders(self) -> None:
        nodes: list = []
        interp = TeXInterpreter()
        original = interp._append_to_hlist
        interp._append_to_hlist = lambda n: (nodes.append(n), original(n))  # type: ignore[assignment]
        interp.run(StringInputSource(r"\font\tenrm=cmr10 \tenrm a$x$b\bye"))
        text = [chr(n.char) for n in nodes if isinstance(n, CharNode)]
        assert "a" in text and "b" in text


class TestOrdinaryGlueInMath:
    r"""horizontal glue keeps its flex and its position.

    Before a math-mode ``\hfil`` was appended to the *enclosing*
    horizontal list, while the formula reached that list only at the ``$``-close
    — so every such glue jumped ahead of the whole formula.  In
    ``\displaylines``' ``$\hfil\displaystyle##\hfil$`` cell that put both
    centring glues on the same side and doubled the row's horizontal offset.
    """

    def test_hfil_keeps_infinite_stretch(self) -> None:
        # The pre- GLUE arm built a zero-flex glue from a scalar, which
        # cannot represent \hfil at all.
        nodes = render(r"$x\hfil y$")
        fils = [
            g for g in _glues(nodes)
            if g.glue.stretch_order == GlueOrder.FIL and g.glue.stretch == 65536
        ]
        assert len(fils) == 1

    def test_hfil_lands_between_the_two_atoms(self) -> None:
        nodes = render(r"$x\hfil y$")
        kinds = [
            "char" if isinstance(n, CharNode)
            else "fil" if isinstance(n, GlueNode) and n.glue.stretch_order == GlueOrder.FIL
            else None
            for n in nodes
        ]
        kinds = [k for k in kinds if k is not None]
        # Exactly one fil, and it sits between the two characters — not before
        # both of them, which is what the defect produced.
        assert kinds.count("fil") == 1
        fil_at = kinds.index("fil")
        assert kinds[:fil_at].count("char") == 1
        assert kinds[fil_at + 1:].count("char") == 1

    def test_hskip_lands_between_the_atoms(self) -> None:
        # The fifth dispatch site (_exec_hskip_cmd) takes the same helper.
        nodes = render(r"$x\hskip 10pt y$")
        seq = [
            "char" if isinstance(n, CharNode)
            else "skip" if isinstance(n, GlueNode) and n.glue.width == 10 * 65536
            else None
            for n in nodes
        ]
        seq = [s for s in seq if s is not None]
        assert seq.count("skip") == 1
        at = seq.index("skip")
        assert seq[:at].count("char") == 1
        assert seq[at + 1:].count("char") == 1

    def test_hfil_in_a_display_formula_lands_between_the_atoms(self) -> None:
        # contributes the natural formula hbox directly. Check the
        # formula's own glue without assuming a synthetic centring wrapper.
        boxes: list = []
        interp = TeXInterpreter()
        original = interp._contribute

        def _cap(node) -> None:
            boxes.append(node)
            original(node)

        interp._contribute = _cap  # type: ignore[method-assign]
        interp.run(StringInputSource(_PRE + r"$$x\hfil y$$" + r"\bye"))

        def kinds_of(nodes: list) -> list[str]:
            out = []
            for n in nodes:
                if isinstance(n, CharNode):
                    out.append("char")
                elif isinstance(n, GlueNode) and n.glue.stretch_order == GlueOrder.FIL:
                    out.append("fil")
            return out

        # The fil must sit BETWEEN the atoms; preceding glue was the original
        # regression. Accept a direct formula as well as a nested one.
        def find_formula(node):
            if isinstance(node, HlistNode) and kinds_of(node.list).count("char") == 2:
                return node
            for child in getattr(node, "list", []) or []:
                if isinstance(child, HlistNode):
                    if kinds_of(child.list).count("char") == 2:
                        return child
                    found = find_formula(child)
                    if found is not None:
                        return found
            return None

        formula = next(
            f for f in (find_formula(b) for b in boxes if isinstance(b, HlistNode))
            if f is not None
        )
        assert kinds_of(formula.list) == ["char", "fil", "char"]

    def test_mskip_still_scales_per_style(self) -> None:
        # The mu path must keep its own arm: \mskip is in mu, converted by
        # math_quad, and never carries an ordinary glue.
        nodes = render(r"$x\mskip 18mu y$")
        widths = [g.glue.width for g in _glues(nodes) if g.glue.width > 0]
        # 18mu == one math quad == the 10pt font's quad; a non-zero, finite,
        # zero-flex glue (not \hfil's infinite stretch).
        assert widths, r"no positive-width glue found for \mskip"
        assert all(
            g.glue.stretch_order == GlueOrder.NORMAL
            for g in _glues(nodes) if g.glue.width > 0
        )

    def test_hfil_outside_math_is_unchanged(self) -> None:
        # Guards the box_primitives scanner path deliberately does not
        # touch — it is what keeps \eqalignno horizontally exact.
        nodes = render(r"\hbox{$x$\hfil $y$}")
        assert any(
            isinstance(n, (CharNode, GlueNode)) for n in nodes
        ), "the hbox produced no nodes"


# ---------------------------------------------------------------------------
# mu → sp follows TeX §716 math_glue / mu_mult exactly
# ---------------------------------------------------------------------------

def _plain_messages(body: str) -> list[str]:
    r"""Run ``body`` under plain TeX and return the ``[…]``-bracketed messages."""
    import warnings

    from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

    job = TeXJob(StringInputSource(body + r"\end"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job.run()
    return [m[1:-1] for m in job.messages if m.startswith("[")]


class TestMuGlueRoundsLikeTeX:
    r"""Expected values are MiKTeX 24.4 plain ``\number\wd0`` of the same box.

    1 mu is ``x_over_n(math_quad, 18)`` truncated to whole sp *before* it is
    multiplied (§716), so cmsy10's 655361 sp quad gives 36408 sp per mu and
    ``\,`` (3mu) is 109224 sp — not ``3 * 655361 / 18`` = 109226.
    """

    @pytest.mark.parametrize(
        ("formula", "miktex_sp"),
        [
            (r"$a\,b$", 736898),          # \thinmuskip 3mu
            (r"$a+b$", 1428664),          # \medmuskip 4mu, both sides
            (r"$a=b$", 1501480),          # \thickmuskip 5mu, both sides
            (r"$a\!b$", 518450),          # negative thin space
            (r"$a\mkern7.5mu b$", 900734),  # fractional \mkern
            (r"$\scriptstyle a\,b$", 604245),        # cmsy7 quad
            (r"$\scriptscriptstyle a\,b$", 541699),  # cmsy5 quad
            (r"$\sin x$", 1288418),       # Op-Ord thin space
            (r"$a\mathpunct{,}b\mathinner{c}d$", 1762108),
        ],
    )
    def test_box_width_matches_miktex(self, formula: str, miktex_sp: int) -> None:
        widths = _plain_messages(
            rf"\setbox0\hbox{{{formula}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        )
        assert widths == [str(miktex_sp)]

    @pytest.mark.parametrize(
        ("muskip", "target"),
        [
            ("0mu plus 1fil", "100pt"),           # infinite stretch fills the box
            ("4mu plus 2mu minus 1fil", "1pt"),   # infinite shrink absorbs overflow
        ],
    )
    def test_infinite_components_are_not_scaled(self, muskip: str, target: str) -> None:
        r"""§716 copies a ``fil`` stretch/shrink unchanged; only finite parts are mu.

        Scaling ``1fil`` by 1/18 em truncated it to 0, so the box could not
        stretch (or shrink) and reported badness 10000; MiKTeX reports 0.
        """
        badness = _plain_messages(
            rf"\medmuskip={muskip} \setbox0\hbox to {target}{{$a+b$}}"
            r"\message{[\the\badness]}"
        )
        assert badness == ["0"]


# ---------------------------------------------------------------------------
# \mskip scans a full <muglue> (§1057/§1060, §716)
# ---------------------------------------------------------------------------

def _plain_glyph_h(body: str) -> list[tuple[int, int]]:
    r"""``(code, h)`` of every glyph on page 1 but the folio, as MiKTeX ``dvitype`` prints them."""
    import warnings

    from aspose_tex._fonts.font_manager import FontManager
    from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions
    from tests._verification.dvi_walker import walk_chars_with_positions

    job = TeXJob(StringInputSource(body + r"\bye"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = job.run()
    mgr = FontManager()

    def width(font: str, code: int) -> int:
        if mgr.get_metrics(font) is None:
            mgr.load_font(font, font)
        return mgr.get_metrics(font).char_metrics(code).width

    return [(c, h) for c, h, _v in walk_chars_with_positions(dvi, width)[0]][:-1]


class TestMskipFullMuglue:
    r"""Expected values are MiKTeX 24.4 plain measurements of the same input.

    ``\mskip`` used to scan only a ``<mudimen>``: ``plus 2mu`` was left in the
    stream and typeset, and a muskip's stretch and shrink were dropped.
    """

    def test_stretch_and_shrink_are_converted_per_style(self) -> None:
        # cmsy10's quad is 655361 sp, so 1mu = 36408 sp (§716).
        from aspose_tex._engine.registers import Glue

        glues = _glues(render(r"$x\mskip 5mu plus 2mu minus 1mu y$"))
        assert [g.glue for g in glues] == [Glue(182040, 72816, GlueOrder.NORMAL, 36408, GlueOrder.NORMAL)]

    def test_infinite_component_is_copied(self) -> None:
        glues = _glues(render(r"$x\mskip 3mu plus 2fil y$"))
        assert [(g.glue.stretch, g.glue.stretch_order) for g in glues] == [(131072, GlueOrder.FIL)]

    def test_ordinary_glue_still_emitted_verbatim(self) -> None:
        # guard: an sp glue in math is not run through the mu converter.
        glues = _glues(render(r"$x\hskip 3pt plus 1fil y$"))
        assert [(g.glue.width, g.glue.stretch, g.glue.stretch_order) for g in glues] == [
            (196608, 65536, GlueOrder.FIL),
        ]

    @pytest.mark.parametrize(
        ("formula", "miktex_sp"),
        [
            (r"$a\mskip 5mu plus 2mu b$", 809714),
            (r"$a\mskip 5mu minus 2mu b$", 809714),
            (r"$a\mskip 5mu plus 2mu minus 1mu b$", 809714),
            (r"$a\mskip-3mu plus 1mu minus 1mu b$", 518450),
            (r"$\scriptstyle a\mskip 18mu plus 9mu b$", 1051770),
            (r"$a\mskip\thickmuskip b$", 809714),
        ],
    )
    def test_natural_width_matches_miktex(self, formula: str, miktex_sp: int) -> None:
        widths = _plain_messages(
            rf"\setbox0\hbox{{{formula}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        )
        assert widths == [str(miktex_sp)]

    @pytest.mark.parametrize(
        ("setup", "box"),
        [
            # plain's \, is \mskip\thinmuskip: its fil stretch now reaches the box
            (r"\thinmuskip=0mu plus 1fil", r"\hbox to 100pt{$a\,b$}"),
            (r"\muskipdef\mm=3 \mm=6mu plus 1fil", r"\hbox to 30pt{$a\mskip\mm b$}"),
        ],
    )
    def test_infinite_stretch_fills_the_box(self, setup: str, box: str) -> None:
        badness = _plain_messages(rf"{{{setup} \setbox0{box}\message{{[\the\badness]}}}}")
        assert badness == ["0"]

    @pytest.mark.parametrize(
        ("body", "miktex_b_h"),
        [
            (r"\noindent\hbox to 20pt{$a\mskip 3mu plus 6mu b$}", 1029462),
            (r"\noindent\hbox to 12pt{$a\mskip 9mu minus 6mu b$}", 505174),
            (r"\noindent\hbox to 20pt{$\scriptstyle a\mskip 3mu plus 6mu b$}", 1080252),
            (r"\muskip0=4mu plus 2mu \noindent\hbox to 20pt{$a\mskip\muskip0 b$}", 1029462),
        ],
    )
    def test_set_glue_places_b_at_miktex_h(self, body: str, miktex_b_h: int) -> None:
        # dvitype h of `b`; the \badness of these boxes is checked against
        # MiKTeX in test_engine_box_builder.TestBadnessMatchesMiktex.
        assert _plain_glyph_h(body) == [(ord("a"), 0), (ord("b"), miktex_b_h)]


# ---------------------------------------------------------------------------
# spacing inside `{…}` math fields executes (TeX §1151/§1186)
# ---------------------------------------------------------------------------

class TestSpacingInsideMathFields:
    r"""Expected values are MiKTeX 24.4 plain ``\wd0`` of ``\hbox{<formula>}``.

    A script / radicand / accentee group was read by a symbol-only scanner:
    ``\,`` vanished and ``\mkern3mu`` typeset the letters ``3mu``.  The
    fraction-operand and ``\left…\right`` rows already went through the main
    loop and guard that path.
    """

    @pytest.mark.parametrize(
        ("formula", "miktex_sp"),
        [
            # superscripts (the first three are AC-1)
            (r"$x^{a\,b}$", 1011569),
            (r"$x^{a\mkern3mu b}$", 1011569),
            (r"$x^{a\hskip1pt b}$", 987600),
            (r"$x^{a\kern1pt b}$", 987600),
            (r"$x^{a\mskip3mu b}$", 1011569),
            (r"$x^{a\!b}$", 832559),
            (r"$x^{a\>b}$", 1041404),
            (r"$x^{a\;b}$", 1071239),
            (r"$x^{a\nonscript\;b}$", 922064),
            (r"$x^{a\nonscript\mskip9mu b}$", 922064),
            (r"$x^\bgroup a\,b\egroup$", 1011569),
            (r"$x^{a^{b\,c}}$", 1225102),
            # subscripts
            (r"$x_{a\,b}$", 1011569),
            (r"$x_{a\mkern3mu b}$", 1011569),
            (r"$x_{a\hskip1pt b}$", 987600),
            (r"$x_{a\kern-1pt b}$", 856528),
            (r"$x_{i\!j}$", 746611),
            (r"$\sum_{i=1}^{n\,m}$", 1603061),
            (r"$e^{-x\,dx}$", 1704221),
            (r"$\int_0^{\,1}$", 820415),
            # radicands
            (r"$\sqrt{a\,b}$", 1283033),
            (r"$\sqrt{a\mkern3mu b}$", 1283033),
            (r"$\sqrt{a\hskip1pt b}$", 1239345),
            (r"$\sqrt{a\kern2pt b}$", 1304881),
            (r"$\root 3\of {a\,b}$", 1324001),
            # accent / over / under nuclei
            (r"$\hat{a\,b}$", 736898),
            (r"$\overline{a\,b}$", 736898),
            (r"$\underline{a\mkern3mu b}$", 736898),
            # fraction operands and \left…\right interiors (main-loop guards)
            (r"${a\,b\over c}$", 761531),
            (r"${a\over b\mkern3mu c}$", 711468),
            (r"${a\hskip1pt b\over c}$", 737562),
            (r"$\left(a\,b\right)$", 1246624),
            (r"$\left(a\mkern3mu b\right)$", 1246624),
            (r"$\left(a\hskip1pt b\right)$", 1202936),
            # other material in a script group now executes too
            (r"$x^{1\over2}$", 787618),
            (r"$x^{\rm max}$", 1374440),
            (r"$x^{\fam0 ab}c$", 1241622),
            (r"$x^{\hbox{ab}}$", 1099095),
            (r"$x^{\displaystyle a\,b}$", 1144222),
            # \kern in math mode outside a field
            (r"$a\kern1pt b$", 693210),
        ],
    )
    def test_box_width_matches_miktex(self, formula: str, miktex_sp: int) -> None:
        widths = _plain_messages(
            rf"\setbox0\hbox{{{formula}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        )
        assert widths == [str(miktex_sp)]


# ---------------------------------------------------------------------------
# script-style spacing codes '1'/'2' decode per TeX §766
# ---------------------------------------------------------------------------

class TestScriptStyleSpacingCodes:
    r"""Expected values are MiKTeX 24.4 plain ``\wd0`` of ``\hbox{<formula>}``.

    §766: a '1' cell (Punct-*, Ord-Inner, ...) is a thin space suppressed in
    script styles; a '2' cell (Ord-Op, Op-Ord, ...) is a thin space in every
    style.  The decode had the two swapped, so only script sizes were wrong.
    """

    @pytest.mark.parametrize(
        ("formula", "miktex_sp"),
        [
            (r"$\scriptstyle a\mathop{b}$", 604245),     # Ord-Op '2'
            (r"$\scriptstyle \mathop{a}b$", 604245),     # Op-Ord '2'
            (r"$\scriptstyle \mathinner{a}b$", 514740),  # Inner-Ord '1'
            (r"$\scriptstyle a,b$", 670388),             # Punct-Ord '1'
            (r"$x^{a,b}$", 1077712),
            (r"$x_{\log x}$", 1471907),
            (r"$x^{\mathpunct{,}\,b}$", 882945),
            (r"$a\over b,c$", 777611),
            (r"$a,b$", 918943),                          # text style unchanged
            (r"$\displaystyle a,b$", 918943),
        ],
    )
    def test_box_width_matches_miktex(self, formula: str, miktex_sp: int) -> None:
        widths = _plain_messages(
            rf"\setbox0\hbox{{{formula}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        )
        assert widths == [str(miktex_sp)]


# ---------------------------------------------------------------------------
# a \mathchoice branch is spliced in place (TeX §731)
# ---------------------------------------------------------------------------

class TestMathChoiceSplicedInPlace:
    r"""Expected values are MiKTeX 24.4 plain ``\wd0`` of ``\hbox{<formula>}``.

    §731 replaces the choice node by the chosen branch's noads, so they space
    and retype against their neighbours.  Laying the branch out as one Inner
    atom put a stray thin space next to every ``\mathstrut`` / ``\phantom`` /
    ``\smash`` and turned a Bin or Rel branch into Inner spacing.
    """

    @pytest.mark.parametrize(
        ("formula", "miktex_sp"),
        [
            (r"$\mathchoice{a}{a}{a}{a}b$", 627674),
            (r"$\mathstrut a$", 346416),
            (r"$\sqrt{\mathstrut a}$", 1001777),
            (r"$\sqrt{\phantom{x}a}$", 1267107),
            (r"$\smash{a}b$", 627674),
            (r"$x^{\mathchoice{a}{a}{a}{a}b}$", 922064),
            (r"$a\mathchoice{+}{+}{+}{+}b$", 1428664),      # Bin keeps med space
            (r"$\mathchoice{}{}{}{}+b$", 790984),           # empty branch: + retyped
            (r"$\displaystyle a\mathchoice{=}{+}{,}{;}b$", 1501480),
            (r"$a\mathchoice{=}{+}{,}{;}b$", 1428664),
            (r"$x^{a\mathchoice{=}{+}{,}{;}b}$", 1077712),
            (r"$a\mathchoice{\left(b\right)}{\left(b\right)}{x}{x}c$", 1639459),
            (r"\vbox{\halign{#\cr$\mathstrut a$\cr}}", 346416),
        ],
    )
    def test_box_width_matches_miktex(self, formula: str, miktex_sp: int) -> None:
        widths = _plain_messages(
            rf"\setbox0\hbox{{{formula}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        )
        assert widths == [str(miktex_sp)]


# ---------------------------------------------------------------------------
# italic correction kept before a lone superscript (TeX §755)
# ---------------------------------------------------------------------------

class TestItalicCorrectionBeforeSuperscript:
    r"""Expected values are MiKTeX 24.4 plain ``\wd0`` of ``\hbox{<formula>}``.

    §755: when the subscript is empty a char nucleus keeps its italic
    correction as a kern (``delta`` = 0), so a superscript or prime starts
    after it; only a subscript makes the correction the superscript offset.
    """

    @pytest.mark.parametrize(
        ("formula", "miktex_sp"),
        [
            (r"$f^a$", 708438),
            (r"$f^{aa}$", 992710),
            (r"$f^\prime$", 575263),
            (r"$f'$", 575263),
            (r"$f^{\prime\prime}$", 726360),
            (r"$V^2$", 821932),
            (r"$\scriptstyle f^a$", 593509),
            (r"$\displaystyle f^a$", 708438),
            (r"$f^a b$", 989696),
            (r"$\rm f^a$", 545226),
            (r"$x^a$", 691596),   # no italic correction: unchanged
            (r"$f_a$", 637895),   # subscript only: correction dropped
        ],
    )
    def test_box_width_matches_miktex(self, formula: str, miktex_sp: int) -> None:
        widths = _plain_messages(
            rf"\setbox0\hbox{{{formula}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        )
        assert widths == [str(miktex_sp)]


# ---------------------------------------------------------------------------
# control space in math appends text-font interword glue (§1045)
# ---------------------------------------------------------------------------

class TestControlSpaceInMath:
    r"""Expected values are MiKTeX 24.4 plain measurements of the same input.

    §1045 sends ``mmode+ex_space`` to ``append_normal_space``: ``\spaceskip``
    or the current text font's fontdimens 2-4 go onto the math list, at text
    size even in a script.  The control space used to be dropped in math.
    """

    def test_glue_is_the_text_font_interword_glue(self) -> None:
        # cmr10 (the preamble's current font): space 3.33333pt plus 1.66666pt
        # minus 1.11111pt; no math spacing between two Ords.
        glues = _glues(render(r"$a\ b$"))
        assert [g.glue for g in glues] == [
            Glue(218453, 109226, GlueOrder.NORMAL, 72818, GlueOrder.NORMAL),
        ]

    @pytest.mark.parametrize(
        ("formula", "miktex_sp"),
        [
            (r"$a\ b$", 846127),
            (r"$\scriptstyle a\ b$", 733193),          # text-font space, not script
            (r"\tenbf $a\ b$", 878894),                # current font, not \fam0
            (r"\spaceskip=10pt plus 1pt $a\ b$", 1283034),
            (r"$x^{a\ b}$", 1140517),
            (r"$a\ \ b$", 1064580),
            (r"$a\ +b$", 1647117),
            (r"\vbox{\hbox{$a\ b$}}", 846127),
        ],
    )
    def test_box_width_matches_miktex(self, formula: str, miktex_sp: int) -> None:
        widths = _plain_messages(
            rf"\setbox0\hbox{{{formula}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        )
        assert widths == [str(miktex_sp)]

    def test_running_paragraph_places_b_at_miktex_h(self) -> None:
        assert _plain_glyph_h(r"\noindent $a\ b$") == [(ord("a"), 0), (ord("b"), 564869)]


# ---------------------------------------------------------------------------
# the sub+sup box is as wide as the shifted superscript (§758/§668)
# ---------------------------------------------------------------------------

class TestSubSupStackWidth:
    r"""Expected values are MiKTeX 24.4 plain ``\wd0`` of ``\hbox{<formula>}``.

    §758 moves the superscript right by the nucleus italic correction inside
    the sup/sub vlist, and vpack (§668) measures every box at its width plus
    its shift, so the scripts box is that much wider than the superscript.
    """

    @pytest.mark.parametrize(
        ("formula", "miktex_sp"),
        [
            (r"$f_a^b$", 654634),
            (r"$V_a^b$", 791165),
            (r"$f_a^b c$", 938245),
            (r"$P_i^2$", 805776),
            (r"$\scriptstyle f_a^b$", 547275),
            (r"$x^{f_a^b}$", 954599),
            (r"$f_a$", 637895),   # subscript only: no shift, unchanged
            (r"$x_a^b$", 691596),  # no italic correction: unchanged
        ],
    )
    def test_box_width_matches_miktex(self, formula: str, miktex_sp: int) -> None:
        widths = _plain_messages(
            rf"\setbox0\hbox{{{formula}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        )
        assert widths == [str(miktex_sp)]

    def test_running_paragraph_places_glyphs_at_miktex_h(self) -> None:
        assert _plain_glyph_h(r"\noindent $V_a^b x$") == [
            (ord("V"), 0), (ord("b"), 527929), (ord("a"), 382293), (ord("x"), 791165),
        ]


# ---------------------------------------------------------------------------
# an operator with a subscript drops its italic correction (§749)
# ---------------------------------------------------------------------------

class TestOpItalicCorrectionWithSubscript:
    r"""Expected values are MiKTeX 24.4 plain ``\wd0`` of ``\hbox{<formula>}``.

    §749 make_op: for a char nucleus with a subscript beside it (not
    ``\limits``) the italic correction comes off the operator box and becomes
    the superscript offset.  ``\mathop{f}`` has the char as its nucleus because
    a one-Ord group hands its nucleus up (§1186).
    """

    @pytest.mark.parametrize(
        ("formula", "miktex_sp"),
        [
            (r"$\int_a$", 626516),
            (r"$\displaystyle\int_a$", 681130),
            (r"$\int_a^b$", 700143),
            (r"$\int_a b$", 1016998),
            (r"$\int_a^b f$", 1200765),
            (r"$\oint_a$", 626516),
            (r"$x^{\int_a}$", 1003333),
            (r"$\mathop{f}_a$", 637895),
            (r"$\mathop{f}\nolimits_a$", 637895),
            (r"$\mathop{\rm f}_a$", 517290),
            (r"$\mathord{f}_a$", 637895),
            (r"${f}_a$", 637895),
            (r"${V}_a^b$", 791165),
            # controls: no subscript, \limits, no italic correction, two atoms
            (r"$\int^a$", 753947),
            (r"$\displaystyle\int^a b$", 1362883),
            (r"$\mathop{f}^a$", 708438),
            (r"$\int\limits_a$", 436907),
            (r"$\sum_a$", 1008811),
            (r"$\mathop{fg}_a$", 1044537),
            (r"$\mathop{\hbox{f}}_a$", 517290),
            (r"$\displaystyle\int_0^1 x$", 1433144),
        ],
    )
    def test_box_width_matches_miktex(self, formula: str, miktex_sp: int) -> None:
        widths = _plain_messages(
            rf"\setbox0\hbox{{{formula}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        )
        assert widths == [str(miktex_sp)]

    def test_integral_scripts_sit_at_miktex_h(self) -> None:
        assert _plain_glyph_h(r"\noindent $\int_a^b f$") == [
            (0x52, 0), (ord("b"), 436907), (ord("a"), 309476), (ord("f"), 809367),
        ]

    def test_mathop_subscript_tucks_under_the_slant(self) -> None:
        assert _plain_glyph_h(r"\noindent $\mathop{f}_a x$") == [
            (ord("f"), 0), (ord("a"), 320855), (ord("x"), 747119),
        ]


# ---------------------------------------------------------------------------
# groups nested inside a \mathchoice branch are not branches
# ---------------------------------------------------------------------------

class TestMathChoiceNestedGroups:
    r"""Expected values are MiKTeX 24.4 plain ``\wd0`` of ``\hbox{<formula>}``.

    Only a group closing back to the depth the ``\mathchoice`` armed at is a
    branch; a ``{…}`` or class-primitive argument inside a branch stays part
    of it, and a nested ``\mathchoice`` keeps its own capture.
    """

    @pytest.mark.parametrize(
        ("formula", "miktex_sp"),
        [
            (r"$a\mathchoice{\mathop{x}}{\mathop{x}}{\mathop{x}}{\mathop{x}}b$", 1220678),
            (r"$a\mathchoice{{x}}{{x}}{{x}}{{x}}b$", 1002230),
            (r"$a\mathchoice{\mathchoice{x}{x}{x}{x}}{y}{y}{y}b$", 972498),
            (r"$\displaystyle a\mathchoice{\mathchoice{x}{x}{x}{x}}{y}{y}{y}b$", 1002230),
            (r"$a\mathchoice{x}{\mathbin{+}}{y}{y}b$", 1428664),
            (r"$\displaystyle a\mathchoice{x}{\mathbin{+}}{y}{y}b$", 1002230),
            (r"$a\mathchoice{y}{\mathchoice{x}{\mathop{x}}{x}{x}}{y}{y}b$", 1220678),
            (r"$x^{a\mathchoice{{x}}{{x}}{{x}}{{x}}b}$", 1219252),
            (r"$a\mathop{x}b$", 1220678),  # control
        ],
    )
    def test_box_width_matches_miktex(self, formula: str, miktex_sp: int) -> None:
        widths = _plain_messages(
            rf"\setbox0\hbox{{{formula}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        )
        assert widths == [str(miktex_sp)]

    def test_running_paragraph_places_glyphs_at_miktex_h(self) -> None:
        body = r"\noindent $a\mathchoice{\mathop{x}}{\mathop{x}}{\mathop{x}}{\mathop{x}}b$"
        assert _plain_glyph_h(body) == [(ord("a"), 0), (ord("x"), 455640), (ord("b"), 939420)]


# ---------------------------------------------------------------------------
# a fraction spliced from a \mathchoice branch spaces as Ord (§761)
# ---------------------------------------------------------------------------

class TestSplicedFractionSpacesAsOrd:
    r"""Expected values are MiKTeX 24.4 plain ``\wd0`` of ``\hbox{<formula>}``.

    tex.web §761 keeps a bare ``fraction_noad`` at the default Ord type in the
    second pass; MiKTeX's ``\showbox`` has no ``\thinmuskip`` beside it.
    """

    def test_bare_fraction_noad_has_the_ord_spacing_class(self) -> None:
        from aspose_tex._engine.math_list import MathClass, Noad, NoadKind
        from aspose_tex._engine.mlist_to_hlist import _placeholder_class

        assert _placeholder_class(Noad(NoadKind.FRACTION)) == int(MathClass.ORD)

    @pytest.mark.parametrize(
        ("formula", "miktex_sp"),
        [
            (r"$\mathchoice{a\over b}{a\over b}{a\over b}{a\over b}c$", 725169),
            (r"$a\mathchoice{x\over y}{x\over y}{x\over y}{x\over y}c$", 1084501),
            (r"$a\mathchoice{x\over y}{x\over y}{x\over y}{x\over y}\mathinner{c}$", 1193725),
            (r"$a\mathchoice{x\over y}{x\over y}{x\over y}{x\over y},c$", 1375770),
            (r"$\displaystyle\mathchoice{a\over b}{a\over b}{a\over b}{a\over b}c$", 787313),
            # controls: the fraction alone, Ord-Bin, a {…} group, \left…\right
            (r"$\mathchoice{a\over b}{a\over b}{a\over b}{a\over b}$", 441558),
            (r"$\mathchoice{a\over b}{a\over b}{a\over b}{a\over b}+c$", 1526159),
            (r"$\mathinner{a}\mathchoice{x\over y}{x\over y}{x\over y}{x\over y}$", 910114),
            (r"$a{x\over y}\mathinner{c}$", 1193725),
            (r"$a\left(x\over y\right)b$", 2083388),
        ],
    )
    def test_box_width_matches_miktex(self, formula: str, miktex_sp: int) -> None:
        widths = _plain_messages(
            rf"\setbox0\hbox{{{formula}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        )
        assert widths == [str(miktex_sp)]

    def test_running_paragraph_places_c_at_miktex_h(self) -> None:
        body = r"\noindent $a\mathchoice{x\over y}{x\over y}{x\over y}{x\over y}c$"
        outer = [g for g in _plain_glyph_h(body) if g[0] in (ord("a"), ord("c"))]
        assert outer == [(ord("a"), 0), (ord("c"), 800890)]


# ---------------------------------------------------------------------------
# inter-atom spacing follows mid-formula style changes (§760-§763)
# ---------------------------------------------------------------------------

class TestSpacingFollowsStyleChanges:
    r"""Expected values are MiKTeX 24.4 plain ``\wd0`` of ``\hbox{<formula>}``.

    The second pass starts again from the formula's own style and switches
    size and mu at every style item, so the glue before ``\scriptstyle`` is
    text-size and may not be suppressed as script spacing.
    """

    @pytest.mark.parametrize(
        ("formula", "miktex_sp"),
        [
            (r"$a+\scriptstyle b,c$", 1622099),
            (r"$\scriptstyle a,b\textstyle c,d$", 1586374),
            (r"$a=\scriptstyle b$", 1268650),
            (r"$a\mathop{b}\scriptstyle c$", 1060612),
            (r"$x^{\scriptstyle a,b\textstyle c,d}$", 1993698),
            # controls: one style throughout, or no spacing across the change
            (r"$a,\scriptstyle b$", 758929),
            (r"$\scriptstyle a\,\textstyle b$", 655035),
            (r"$\scriptstyle a+b$", 917060),
        ],
    )
    def test_box_width_matches_miktex(self, formula: str, miktex_sp: int) -> None:
        widths = _plain_messages(
            rf"\setbox0\hbox{{{formula}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        )
        assert widths == [str(miktex_sp)]

    def test_running_paragraph_places_glyphs_at_miktex_h(self) -> None:
        assert _plain_glyph_h(r"\noindent $a+\scriptstyle b,c$") == [
            (ord("a"), 0), (ord("+"), 492048), (ord("b"), 1001774),
            (ord(";"), 1232242), (ord("c"), 1387890),
        ]
