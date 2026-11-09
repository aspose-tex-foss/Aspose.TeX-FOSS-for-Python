r""" math display and layout precision pack — MiKTeX-measured positions.

Every expected value is a MiKTeX 24.4 plain measurement of the same input:
page-1 glyphs ``(code, h, v)`` from the DVI via ``tests/_verification/dvi_walker``
(the folio dropped), and ``\wd``/``\ht``/``\dp`` of ``\setbox0\hbox{...}``
printed with ``\message``.

Fil-centred parts match MiKTeX exactly after cumulative rounding.
"""

from __future__ import annotations

import warnings

import pytest

from aspose_tex import DviDevice, TeXJob, TeXOptions
from aspose_tex._engine.math_list import DelimiterCode, MathChar, MathClass
from aspose_tex._input.reader import StringInputSource
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_math_list import capture_mlist

_MEAS = (
    r"\def\meas#1{\setbox0\hbox{#1}\dimen0=\wd0 \dimen2=\ht0 \dimen4=\dp0 "
    r"\message{[\number\dimen0,\number\dimen2,\number\dimen4]}}"
)


def _run(body: str) -> tuple[TeXJob, bytes]:
    job = TeXJob(StringInputSource(body + "\n\\bye\n"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = job.run()
    return job, dvi


def _tfm_char_width():
    """``char_width`` for the DVI walker: TFM widths at design size, as dvitype."""
    from aspose_tex._fonts.font_manager import FontManager

    mgr = FontManager()

    def width(font: str, code: int) -> int:
        if mgr.get_metrics(font) is None:
            mgr.load_font(font, font)
        return mgr.get_metrics(font).char_metrics(code).width

    return width


def _glyphs(body: str) -> list[tuple[int, int, int]]:
    """``(code, h, v)`` of every page-1 glyph but the folio."""
    _, dvi = _run(body)
    return walk_chars_with_positions(dvi, _tfm_char_width())[0][:-1]


def _assert_positions(actual: list, miktex: list) -> None:
    """All glyph coordinates match MiKTeX exactly."""
    assert [(c, v) for c, _h, v in actual] == [(c, v) for c, _h, v in miktex]
    assert all(a[1] == m[1] for a, m in zip(actual, miktex, strict=True))


def _dims(*formulas: str) -> list[tuple[int, int, int]]:
    """``(wd, ht, dp)`` of ``\\hbox{<formula>}`` for each formula."""
    job, _ = _run(_MEAS + "".join(r"\meas{" + f + "}" for f in formulas))
    out = []
    for m in job.messages:
        if m.startswith("["):
            out.append(tuple(int(x) for x in m.strip("[]").split(",")))
    return out


# ---------------------------------------------------------------------------
# \delimiter as a math char and as a \left/\right delimiter
# ---------------------------------------------------------------------------


class TestDelimiterSymbols:
    r"""``\{``/``\lbrace`` (``\delimiter"4266308``) typeset as braces (§1160, §1163)."""

    def test_box_dimensions(self) -> None:
        assert _dims(
            r"$\{x\}$",
            r"$\lbrace x\rbrace$",
            r"$\left\lbrace x\right\rbrace$",
            r"$\left\{x\right\}$",
            r"$\left\{x\over y\right\}$",
            r"$\mathopen\{x\mathclose\}$",
            r"$x^{\left\{x\over y\right\}}$",
            r"$\displaystyle\left\{x\over y\right\}$",
            r"$\left\langle x\over y\right\rangle$",
            r"$\{x\}^2$",
            r"$x_{\{a\}}$",
            r"$x^\lbrace$",
            r"$\bigl\{x\bigr\}$",
            r"$\Bigl\{x\Bigr\}$",
            r"$\left\delimiter" '"4266308 x\\right\\delimiter"5267309$',
        ) == [
            (1029918, 491520, 163840),
            (1029918, 491520, 163840),
            (1029918, 491520, 163840),
            (1029918, 491520, 163840),
            (1328290, 753669, 425990),
            (1029918, 491520, 163840),
            (1479387, 734534, 0),
            (1514884, 950279, 622600),
            (1255470, 753669, 425990),
            (1323921, 533465, 163840),
            (1228628, 282168, 233018),
            (675840, 581889, 0),
            (1139146, 557059, 229380),
            (1248372, 753669, 425990),
            (1029918, 491520, 163840),
        ]

    def test_parenthesis_and_bracket_unchanged(self) -> None:
        assert _dims(r"$\left(x\over y\right)$", r"$\left[x\over y\right]$") == [
            (1237266, 753669, 425990),
            (1073426, 753669, 425990),
        ]

    def test_small_braces_glyphs(self) -> None:
        # cmsy "66 / "67, as a symbol and as a class-primitive field.
        assert _glyphs(r"\noindent $\{x\}$ $\mathopen\{x\mathclose\}$") == [
            (102, 0, 655360), (120, 327681, 655360), (103, 702237, 655360),
            (102, 1248371, 655360), (120, 1576052, 655360), (103, 1950608, 655360),
        ]

    def test_left_right_and_superscript_glyphs(self) -> None:
        assert _glyphs(r"\noindent $\left\{x\right\}$ $x^{\lbrace}$") == [
            (102, 0, 655360), (120, 327681, 655360), (103, 702237, 655360),
            (120, 1248371, 655360), (102, 1622927, 417535),
        ]
        # \bigl picks the cmex "08 / "09 braces.
        assert _glyphs(r"\noindent $\bigl\{x\bigr\}$") == [
            (8, 0, 124514), (120, 382295, 655360), (9, 756851, 124514),
        ]

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # cmex "6E / "6F in text style, "1A / "1B in display style.
            (r"\noindent $\left\{x\over y\right\}$",
             [(110, 0, 26213), (120, 515551, 495633), (121, 523022, 979663),
              (111, 891382, 26213)]),
            (r"\noindent $\displaystyle\left\{x\over y\right\}$",
             [(26, 0, 26213), (120, 570164, 506923), (121, 585030, 1399823),
              (27, 1023363, 26213)]),
        ],
    )
    def test_grown_braces_around_a_fraction(self, body: str, miktex: list) -> None:
        _assert_positions(_glyphs(body), miktex)

    def test_builder_reads_the_delimiter_code(self) -> None:
        noads = capture_mlist(
            r'$\delimiter"4266308 x\left\delimiter"4266308 x\right\delimiter"5267309$'
        )
        assert noads[0].math_class == MathClass.OPEN
        assert noads[0].nucleus == MathChar(2, 0x66)
        assert noads[2].left_delim == DelimiterCode(2, 0x66, 3, 0x08)
        assert noads[2].right_delim == DelimiterCode(2, 0x67, 3, 0x09)

    def test_mathchar_as_a_field(self) -> None:
        # TeX §1151 scan_math reads \mathchar like \delimiter.
        assert _dims(r"$x^\mathchar" '"4266$') == [(675840, 581889, 0)]

    def test_brace_in_text_mode_is_an_error_as_in_plain(self) -> None:
        # plain's \{ is \delimiter, which TeX rejects outside math ("Missing $").
        from aspose_tex.exceptions import EngineError

        with pytest.raises(EngineError):
            _run(r"\setbox0\hbox{\{x\}}")


# ---------------------------------------------------------------------------
# the fraction bar and the \atop clearance use half() (§746-§748)
# ---------------------------------------------------------------------------


class TestFractionHalf:
    r"""Odd rule thicknesses and clearance deficits round up, as TeX's ``half``."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # The default rule thickness (26213 sp) is odd: y sat 1 sp low.
            (r"\noindent $x\over y$ $$x\over y$$",
             [(120, 78643, 397324), (121, 86114, 881354), (120, 15205654, 1318260),
              (121, 15220520, 2211160)]),
            (r"\noindent $\sqrt{x\over y}$ $$\sqrt{x\over y}$$",
             [(113, 0, 52426), (120, 734004, 457675), (121, 741475, 941705),
              (114, 14799330, 1323834), (120, 15533334, 1776463),
              (121, 15548200, 2669363)]),
            (r"\noindent $x\above 3sp y$ $$x\above 3sp y$$",
             [(120, 78643, 397324), (121, 86114, 881354), (120, 15205654, 1318260),
              (121, 15220520, 2211160)]),
            (r"\noindent $x\above 5sp y$ $$x\above 5sp y$$",
             [(120, 78643, 397324), (121, 86114, 881354), (120, 15205654, 1318260),
              (121, 15220520, 2211160)]),
            # Even thicknesses and \atop were already right: they stay put.
            (r"\noindent $x\above 1pt y$ $$x\above 1pt y$$",
             [(120, 78643, 393216), (121, 86114, 881355), (120, 15205654, 1318260),
              (121, 15220520, 2211161)]),
            (r"\noindent $x\atop y$ $$x\atop y$$",
             [(120, 78643, 364557), (121, 86114, 881355), (120, 15205654, 1318260),
              (121, 15220520, 2211161)]),
        ],
    )
    def test_numerator_and_denominator_positions(self, body: str, miktex: list) -> None:
        _assert_positions(_glyphs(body), miktex)

    def test_nested_and_delimited_fractions(self) -> None:
        assert _glyphs(r"\noindent ${1\over2}^{x\over y}$ $$x\atopwithdelims() y$$") == [
            (49, 78643, 450822), (50, 78643, 934852), (120, 497164, 141084),
            (121, 501298, 475108), (18, 14723234, 1026602), (120, 15205654, 1507312),
            (121, 15220520, 2400213), (19, 15580210, 1026602),
        ]

    def test_atop_clearance_deficit_is_halved_up(self) -> None:
        # A tall part forces the \atop clearance rule (§746): delta = half(...).
        _assert_positions(
            _glyphs(r"\noindent $x\atop{\displaystyle\int}$ ${\displaystyle\sum}\atop y$"),
            [(120, 257730, 521105), (90, 78643, 599744), (88, 1109743, 65536),
             (121, 1441936, 1324742)],
        )


# ---------------------------------------------------------------------------
# a Bin turned Ord (§728) runs make_ord (§752)
# ---------------------------------------------------------------------------


class TestBinTurnedOrdMakeOrd:
    r"""A Bin retyped by its left context forms ligatures and kerns like an Ord."""

    def test_glyphs_ligate(self) -> None:
        # cmr10 "0C is the fi ligature.
        assert _glyphs(r"\noindent $\rm\mathbin fi$ $\rm a=\mathbin fi$") == [
            (12, 0, 655360), (97, 582543, 655360), (61, 1092264, 655360),
            (12, 1784030, 655360),
        ]

    def test_box_widths(self) -> None:
        assert _dims(
            r"$\rm\mathbin fi$",
            r"$\rm a=\mathbin fi$",
            r"$\rm (\mathbin fi$",
            r"$\rm a,\mathbin fi$",
            r"$\rm \mathop{a}\mathbin fi$",
            r"$\rm \left(\mathbin fi\right)$",
            r"$\rm x\over \mathbin fi$",
            r"$\rm\mathbin f\mathbin f\mathbin i$",
            r"$\rm\mathbin{f}\!i$",
            r"$\mathbin AV$",
        ) == [
            (364090, 455111, 0),
            (1565577, 455111, 0),
            (618953, 491520, 163840),
            (983040, 455111, 127431),
            (800995, 455111, 0),
            (873816, 491520, 163840),
            (454019, 455554, 225995),
            (546135, 455111, 0),
            (324044, 455111, 0),
            (1019450, 447828, 0),
        ]

    def test_a_bin_after_an_ord_stays_a_bin(self) -> None:
        # The left context keeps these Bins: no ligature, Bin spacing.
        assert _dims(
            r"$\rm a\mathbin fi$", r"$\rm a+\mathbin fi$", r"$\rm a\mathbin f\mathbin i$",
        ) == [(1052213, 455111, 0), (1492761, 455111, 54613), (1052213, 455111, 0)]

    def test_controls_unchanged(self) -> None:
        assert _dims(
            r"$\rm f\mathop i$", r"$\rm f\mathpunct i$", r"$\rm f\mathinner{i}$",
        ) == [(364090, 455111, 0), (364090, 455111, 0), (542492, 455111, 0)]


# ---------------------------------------------------------------------------
# a void paragraph before $$ ships no line (§1145)
# ---------------------------------------------------------------------------


class TestDisplayAfterVoidParagraph:
    r"""``\noindent$$`` pops the empty paragraph: no empty line box, short skips."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\noindent $$\vbox{\hrule height 80pt}$$ x", [(120, 0, 6488064)]),
            (r"x\par\noindent $$\vbox{\hrule height 80pt}$$ x",
             [(120, 1310720, 655360), (120, 0, 7208960)]),
            (r"x\par\noindent $$y$$ x",
             [(120, 1310720, 655360), (121, 15220520, 1441792), (120, 0, 2686976)]),
            # At the top of the page the display is the first box (\topskip).
            (r"\noindent{}$$y$$ x", [(121, 15220520, 655360), (120, 0, 1900544)]),
            (r"\noindent $$\left\{x\over y\right\}$$",
             [(26, 14635490, 26213), (120, 15205654, 506923), (121, 15220520, 1399823),
              (27, 15658853, 26213)]),
        ],
    )
    def test_display_and_following_line(self, body: str, miktex: list) -> None:
        assert _glyphs(body) == miktex

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"x\par\noindent$$y\eqno(1)$$ x",
             [(120, 1310720, 655360), (121, 15220520, 1441792), (40, 29948456, 1441792),
              (49, 30203319, 1441792), (41, 30531000, 1441792), (120, 0, 2686976)]),
            (r"x\par\noindent $$y$$ x\par\noindent$$z$$ w",
             [(120, 1310720, 655360), (121, 15220520, 1441792), (120, 0, 2686976),
              (122, 15226133, 3473408), (119, 0, 4718592)]),
            (r"x\par\noindent$$y$$\par\noindent$$z$$ w",
             [(120, 1310720, 655360), (121, 15220520, 1441792), (122, 15226133, 2686976),
              (119, 0, 3932160)]),
        ],
    )
    def test_numbered_and_consecutive_displays(self, body: str, miktex: list) -> None:
        _assert_positions(_glyphs(body), miktex)

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # A paragraph holding anything — an indent box, an empty box, a glue —
            # still ships its (empty) pre-display line, as before.
            (r"x\par $$y$$ x",
             [(120, 1310720, 655360), (121, 15220520, 2228224), (120, 0, 3473408)]),
            (r"\noindent\hbox{}$$y$$ x", [(121, 15220520, 1441792), (120, 0, 2686976)]),
            (r"\indent$$y$$ x", [(121, 15220520, 1441792), (120, 0, 2686976)]),
            (r"x\par\noindent\hskip0pt$$y$$ x",
             [(120, 1310720, 655360), (121, 15220520, 2228224), (120, 0, 3473408)]),
            (r"\parindent=0pt x\par$$y$$ x",
             [(120, 0, 655360), (121, 15220520, 2228224), (120, 0, 3473408)]),
        ],
    )
    def test_non_void_paragraph_keeps_its_line(self, body: str, miktex: list) -> None:
        assert _glyphs(body) == miktex
