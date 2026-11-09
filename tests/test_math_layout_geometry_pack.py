r""" math layout geometry pack — DVI glyph positions and box dimensions.

Every expected value is a MiKTeX 24.4 plain measurement of the same input:
page-1 glyphs ``(code, h, v)`` from the DVI via ``tests/_verification/dvi_walker``
(the folio dropped), and ``\wd``/``\ht``/``\dp`` of ``\setbox0\hbox{...}``
printed with ``\message``.  Widths alone hid, so the rows assert
vertical positions and heights/depths too.
"""

from __future__ import annotations

import warnings

import pytest

from aspose_tex import DviDevice, TeXJob, TeXOptions
from aspose_tex._input.reader import StringInputSource
from tests._verification.dvi_walker import walk_chars_with_positions

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


def _dims(*formulas: str) -> list[tuple[int, int, int]]:
    """``(wd, ht, dp)`` of ``\\hbox{<formula>}`` for each formula."""
    job, _ = _run(_MEAS + "".join(r"\meas{" + f + "}" for f in formulas))
    out = []
    for m in job.messages:
        if m.startswith("["):
            out.append(tuple(int(x) for x in m.strip("[]").split(",")))
    return out


# ---------------------------------------------------------------------------
# large operators centred on the axis (§749)
# ---------------------------------------------------------------------------


class TestOperatorOnTheAxis:
    r"""``make_op`` raises a symbol operator so its centre sits on the axis."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\noindent $\int x$", [(82, 0, 127428), (120, 546131, 655360)]),
            (r"\noindent $\sum x$", [(80, 0, 163836), (120, 800995, 655360)]),
            (
                r"\noindent $\int^a x$",
                [(82, 0, 127428), (97, 436907, 289446), (120, 863171, 655360)],
            ),
            (
                r"\noindent $\sum_a x$",
                [(80, 0, 163836), (97, 691771, 851971), (120, 1118035, 655360)],
            ),
            # The raised operator pushes the first baseline below \topskip.
            (
                r"\noindent $\int_a^b f$",
                [(82, 0, 156559), (98, 436907, 318577), (97, 309476, 917511),
                 (102, 809367, 684491)],
            ),
        ],
    )
    def test_text_style_glyph_positions(self, body: str, miktex: list) -> None:
        assert _glyphs(body) == miktex

    def test_display_integral_with_scripts(self) -> None:
        assert _glyphs(r"\noindent x $$\int_0^1 f\,dx$$") == [
            (120, 0, 655360), (90, 14255496, 854518), (49, 14910857, 1016536),
            (48, 14619586, 2343656), (102, 15314084, 1746543),
            (100, 15814706, 1746543), (120, 16155812, 1746543),
        ]

    def test_display_sum_limit_stack_baseline(self) -> None:
        # The stack's reference point is the operator's baseline, not the
        # centre of the whole stack: the display baseline follows from it.
        assert _glyphs(r"\noindent x $$\sum^n x$$") == [
            (120, 0, 655360), (110, 14989059, 983950), (88, 14677725, 1180557),
            (120, 15733582, 1803153),
        ]
        assert _glyphs(r"\noindent x $$\sum_{i=1}^n x_i$$")[-2:] == [
            (120, 15624488, 1803153), (105, 15999044, 1901456),
        ]

    def test_operator_box_dimensions(self) -> None:
        assert _dims(
            r"$\int$", r"$\sum$", r"$\int_a^b$", r"$\displaystyle\sum_{i=1}^n$",
            r"$\displaystyle\int$",
        ) == [
            (436907, 527932, 200253), (691771, 491524, 163844),
            (700143, 684491, 233020), (946633, 1082257, 838772),
            (655361, 892025, 564346),
        ]

    def test_sublist_operator_stays_on_the_baseline(self) -> None:
        # §749 centres only a symbol nucleus; \mathop{\rm lim} keeps its baseline.
        assert _dims(
            r"$\mathop{\rm lim}$", r"$\mathop{\rm lim}_x$", r"$\displaystyle\lim_{x\to0}$",
        ) == [(910225, 455111, 0), (1240181, 455111, 98303), (1080892, 455111, 470402)]
        assert _glyphs(r"\noindent $\mathop{\rm lim}_{x} y$")[:3] == [
            (108, 0, 655360), (105, 182045, 655360), (109, 364090, 655360),
        ]


# ---------------------------------------------------------------------------
# limits of a slanted operator skewed by half the italic correction
# ---------------------------------------------------------------------------


class TestLimitsSkew:
    r"""§750 reboxes the limits, then shifts them by ``±half(delta)``."""

    def test_text_style_int_limits(self) -> None:
        assert _glyphs(r"\noindent $\int\limits_a^b x$") == [
            (98, 166936, 384113), (82, 0, 515184), (97, 12602, 1636585),
            (120, 546131, 1043116),
        ]

    def test_display_mathop_letter_limits(self) -> None:
        assert _glyphs(r"\noindent $\displaystyle\mathop{f}_a^b$") == [
            (98, 115737, 384113), (102, 0, 970295), (97, 18291, 1490942),
        ]

    def test_display_int_limits(self) -> None:
        assert _glyphs(r"\noindent $\displaystyle\int\limits_a^b$") == [
            (98, 358083, 384113), (90, 0, 515184), (97, 39909, 2364771),
        ]


# ---------------------------------------------------------------------------
# height/depth of script-only formulas; the radical in a script
# ---------------------------------------------------------------------------


class TestScriptBoxExtent:
    r"""``\ht``/``\dp`` see a sup-only or sub-only script at its shifted place."""

    def test_listed_rows(self) -> None:
        assert _dims(
            r"$x^2$", r"$x_2$", r"$x^{\root n\of y}$", r"$x^{a+b}$",
            r"${\hbox{f}}_a$", r"$x^{a\textstyle +b}$",
        ) == [
            (668559, 533465, 0), (668559, 282168, 98303), (1259553, 571164, 0),
            (1324384, 556402, 0), (517290, 455111, 98303), (1773844, 692936, 0),
        ]

    def test_glyph_positions(self) -> None:
        assert _glyphs(r"\noindent $x^2$ $x_2$ $x^{\root n\of y}$") == [
            (120, 0, 655360), (50, 374556, 417535), (120, 887012, 655360),
            (50, 1261568, 753663), (120, 1774024, 655360), (110, 2297755, 306147),
            (112, 2288025, 128758), (121, 2718562, 417535),
        ]

    def test_nested_superscripts_line(self) -> None:
        assert _glyphs(r"\hsize=100pt \noindent a\par\noindent $x^{x^{x^2}}$\par") == [
            (97, 0, 655360), (120, 0, 1441792), (120, 374556, 1203967),
            (120, 671744, 1006193), (50, 931159, 873957),
        ]


class TestRadicalGeometry:
    r"""§737: ``clr + half(delta)``, a bar as thick as the sign is tall, and the
    sign raised by ``height(x) + clr`` — wrong in every style before,
    which is what put ``$x^{\root n\of y}$`` off."""

    def test_root_glyph_positions(self) -> None:
        assert _glyphs(r"\noindent $\root n\of y$") == [
            (110, 182040, 511401), (112, 106580, 247035), (121, 652715, 655360),
        ]
        assert _glyphs(r"\noindent $\scriptstyle\root n\of y$") == [
            (110, 149175, 543972), (112, 139445, 366583), (121, 569982, 655360),
        ]

    def test_radical_box_dimensions(self) -> None:
        assert _dims(
            r"$\root n\of y$", r"$\scriptstyle\root n\of y$", r"$\scriptstyle\sqrt y$",
            r"$x^{\sqrt y}$",
        ) == [
            (997539, 460751, 220821), (852229, 333339, 147693),
            (712784, 333339, 147693), (1120108, 571164, 0),
        ]

    def test_larger_and_built_up_signs(self) -> None:
        # Text and display, a fraction radicand, and a matrix tall enough for
        # the extensible (built-up) sign.
        assert _dims(
            r"$\sqrt x$", r"$\displaystyle\sqrt x$", r"$\sqrt{x\over y}$",
            r"$\displaystyle\sqrt{x\over y}$", r"$\sqrt{\displaystyle{a\over b}\over c}$",
            r"$\displaystyle\sqrt{\matrix{a\cr b\cr c\cr d\cr e\cr f\cr}}$",
            r"$\root 3\of{x\over y}$",
        ) == [
            (920691, 524466, 157106), (920691, 556461, 125111),
            (1109835, 715711, 490161), (1187203, 948411, 650681),
            (1316349, 1614869, 377443), (1301617, 2610857, 2133995),
            (1150803, 715711, 490161),
        ]


# ---------------------------------------------------------------------------
# delimiter search order (§707-§708) and axis centring (§710)
# ---------------------------------------------------------------------------


class TestDelimiterSearch:
    r"""A script-size delimiter is first sought in the small variant at script
    and then text size — ``\textfont0``'s ``(`` fits before cmex's."""

    def test_left_right_around_fraction_in_script_style(self) -> None:
        assert _dims(
            r"$\scriptstyle a\left(x\over y\right)b$", r"$\scriptstyle \left(x\over y\right)$",
            r"$x^{a\left(x\over y\right)b}$", r"$\scriptscriptstyle\left(x\over y\right)$",
        ) == [
            (1441167, 442368, 221624), (926427, 442368, 221624),
            (1848491, 734534, 0), (926427, 409600, 245760),
        ]

    def test_controls(self) -> None:
        assert _dims(
            r"$\scriptstyle \left(x\right)$", r"$\scriptstyle a\left(x\right)b$",
            r"$\scriptstyle {x\over y}$", r"$\scriptstyle \left.x\over y\right.$",
            r"$a\left(x\over y\right)b$", r"$\left(x^{x^{x^x}}\right)$",
            r"$\left[x\over y\right]$",
        ) == [
            (706790, 344064, 114688), (1221530, 344064, 114688),
            (416701, 317200, 221624), (573987, 317200, 221624),
            (2083388, 753669, 425990), (2071670, 753669, 425990),
            (1073426, 753669, 425990),
        ]

    def test_withdelims_fraction_delimiters_sit_on_the_axis(self) -> None:
        assert _dims(
            r"$\scriptstyle{x\atopwithdelims() y}$", r"${x\atopwithdelims() y}$",
            r"$\displaystyle{x\atopwithdelims() y}$",
            r"$\scriptscriptstyle{x\atopwithdelims() y}$",
            r"$\scriptstyle{x\overwithdelims[] y}$",
        ) == [
            (769141, 442368, 221624), (897938, 557059, 315196),
            (1339396, 950279, 622600), (769141, 409600, 245760),
            (623505, 442368, 221624),
        ]


# ---------------------------------------------------------------------------
# a class primitive's forced class belongs to its own argument group
# ---------------------------------------------------------------------------


class TestClassArgumentGroups:
    r"""A ``{…}`` nested in the argument of ``\mathop``/``\mathbin``/… stays an
    Ord inside the argument; the argument takes the forced class."""

    def test_listed_rows(self) -> None:
        assert _dims(
            r"$a\mathop{x{y}}b$", r"$a\mathop{{x}y}b$", r"$a\mathbin{{x}}b$",
            r"$a\mathrel{x{y}}b$", r"$a\mathop{{f}}_a$", r"$\mathop{{f}}_a$",
        ) == [
            (1565502, 455111, 127431), (1565502, 455111, 127431), (1293494, 455111, 0),
            (1711134, 455111, 127431), (1093535, 455111, 160198), (637895, 455111, 160198),
        ]

    def test_controls(self) -> None:
        # No nested group, a script field group, a \mathchoice and a nested
        # class primitive inside the argument.
        assert _dims(
            r"$a\mathop{xy}b$", r"$a\mathop{x^{y}}b$",
            r"$a\mathbin{\mathchoice{x}{x}{x}{x}}b$", r"$a\mathopen{\mathclose{x}y}b$",
            r"$a\mathpunct{{x}{y}}b$", r"$\mathop{x}{y}$",
        ) == [
            (1565502, 455111, 127431), (1535693, 455111, 0), (1293494, 455111, 0),
            (1347054, 455111, 127431), (1456278, 455111, 127431), (828604, 304924, 127431),
        ]


# ---------------------------------------------------------------------------
# make_ord: ligatures and kerns between symbols (§752-§753)
# ---------------------------------------------------------------------------


class TestMathLigatures:
    r"""An Ord symbol followed by a symbol of the same family runs the font's
    lig/kern program; a text-font char inside a word loses its italic
    correction (§755)."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\noindent $\rm fi$", [(12, 0, 655360)]),
            (r"\noindent $\rm ffi$", [(14, 0, 655360)]),
            (r"\noindent $\rm f{f}$", [(11, 0, 655360)]),
        ],
    )
    def test_listed_rows(self, body: str, miktex: list) -> None:
        assert _glyphs(body) == miktex

    def test_words_and_scripts(self) -> None:
        # The ligature takes the second char's scripts; \/ is a zero kern in
        # math (§1111), so it keeps f and i apart.
        assert _glyphs(r"\noindent $\rm diff$ $\mathop{\rm aff}$ $\rm f\/i$ $\rm ff^2i$") == [
            (100, 0, 655360), (105, 364090, 655360), (11, 546135, 655360),
            (97, 1197856, 655360), (11, 1525537, 655360), (102, 2177258, 655360),
            (105, 2428481, 655360), (11, 2828979, 655360), (50, 3262247, 417535),
            (105, 3556250, 655360),
        ]

    def test_kerns_and_other_fonts(self) -> None:
        assert _glyphs(
            r"\noindent $\rm AV$ $\rm Te\ x$ $\it ff$ $\rm f\mathbin{i}j$ $\displaystyle\rm fl$"
        ) == [
            (65, 0, 655360), (86, 418702, 655360), (84, 1137777, 655360),
            (101, 1556479, 655360), (120, 2066203, 655360), (11, 2630542, 655360),
            (12, 3389846, 655360), (106, 3753936, 655360), (13, 4172639, 655360),
        ]

    def test_box_widths(self) -> None:
        assert _dims(r"$\rm fi$", r"$\rm ffi$", r"$\rm f{f}$", r"$\rm diff$", r"$\rm ``$") == [
            (364090, 455111, 0), (546135, 455111, 0), (433268, 455111, 0),
            (979403, 455111, 0), (327681, 455111, 0),
        ]

    def test_controls(self) -> None:
        # Kerns in roman and math italic, a script on the first char, a glue,
        # an empty group, \over, a lone f (keeps its italic correction).
        assert _dims(
            r"$\rm AV$", r"$AV$", r"$\rm Te$", r"$\rm f\mathord{f}i$", r"$\rm f^2i$",
            r"$\rm ff_2$", r"$\it ffi$", r"$\rm f\,i$", r"$\rm f{}i$", r"$xyz$",
            r"$\rm Wo$", r"$\scriptstyle\rm fi$", r"$\rm f\over i$", r"$f\/i$", r"$\rm f$",
            r"$\rm fx$", r"$\rm f\mathbin{i}$", r"$\mathop{\rm aff}$", r"$\bf ffl$",
        ) == [
            (919324, 447828, 0), (1019450, 447828, 0), (709973, 447828, 0),
            (546135, 455111, 0), (727271, 533465, 0), (676298, 455111, 98303),
            (645527, 455111, 127431), (542492, 455111, 0), (433268, 455111, 0),
            (1052978, 282168, 127431), (946633, 447828, 0), (296733, 318577, 0),
            (356399, 576613, 225995), (617178, 455111, 127431), (251223, 455111, 0),
            (546136, 455111, 0), (364090, 455111, 0), (760949, 455111, 0),
            (628050, 455111, 0),
        ]
