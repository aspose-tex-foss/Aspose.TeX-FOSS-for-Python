r""" math-inside-alignments pack — MiKTeX 24.4 plain measurements.

Every expected value is a MiKTeX measurement of the same input: page-1 glyphs
``(code, h, v)`` in sp with the folio dropped (``_page1``), or the ``[…]``
values a ``\message`` prints (``_messages``).
The display-brace pin and its shared full-event oracle match MiKTeX exactly.
"""

from __future__ import annotations

import pytest

from aspose_tex import DviDevice
from aspose_tex._engine.alignment import (
    _AlignmentState,
    _CellRecord,
    _measure_columns,
)
from aspose_tex._engine.nodes import GlueSign, HlistNode
from aspose_tex._engine.registers import GlueOrder
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_leaders_shipout import _compile
from tests.test_paragraph_start_pack import _page1
from tests.test_plain_tie import _messages, _tfm_width

_DIMS = r"\dimen0=\wd0 \dimen1=\ht0 \dimen2=\dp0 \message{[\number\dimen0,\number\dimen1,\number\dimen2]}"


# ---------------------------------------------------------------------------
# Component 1 — members already exact
# ---------------------------------------------------------------------------


class TestAlreadyExactMembers:
    """Pins for the members other work fixed before this pack was designed."""

    def test_inline_cases_width(self) -> None:
        """: ``$\\cases{…}$`` is MiKTeX's width, not twice it."""
        body = r"\setbox0\hbox{$\cases{a&b\cr c&d\cr}$}" + _DIMS
        assert _messages(body) == ["[1990642,784612,456931]"]

    def test_display_cases_extent(self) -> None:
        """: the ``\\cases`` display block is not 1.848pt short."""
        body = (
            r"\hsize=6.5in \nopagenumbers \noindent lead "
            r"$$f(x)=\cases{0&if $x<0$\cr 1&if $x\ge0$\cr}$$ tail"
        )
        assert _page1(body) == [
            (108, 0, 655360), (101, 182045, 655360), (97, 473316, 655360),
            (100, 800997, 655360), (102, 12398578, 1671175), (40, 12789976, 1671175),
            (120, 13044839, 1671175), (41, 13419395, 1671175), (61, 13856298, 1671175),
            (26, 14548064, 747109), (48, 15148809, 1297119), (105, 16131851, 1297119),
            (102, 16313896, 1297119), (120, 16732599, 1297119), (60, 17289195, 1297119),
            (48, 17980961, 1297119), (49, 15148809, 2083551), (105, 16131851, 2083551),
            (102, 16313896, 2083551), (120, 16732599, 2083551), (21, 17289195, 2083551),
            (48, 17980961, 2083551), (116, 0, 3273174), (97, 254863, 3273174),
            (105, 582544, 3273174),
        ]

    def test_settabs_fields_are_math(self) -> None:
        """: ``$…$`` in ``\\+`` fields sets cmmi glyphs on one line per row."""
        body = "\n".join([
            r"\settabs 2 \columns",
            r"\+$a+b$&$x=y$\cr",
            r"\+$c-d$&$\alpha\beta$\cr",
        ])
        assert _page1(body) == [
            (97, 0, 655360), (43, 492048, 655360), (98, 1147406, 655360),
            (120, 15392931, 655360), (61, 15949527, 655360), (121, 16641293, 655360),
            (99, 0, 1441792), (0, 429243, 1441792), (100, 1084601, 1441792),
            (11, 15392931, 1441792), (12, 15814592, 1441792),
        ]


# ---------------------------------------------------------------------------
# Component 2 — §801 null_flag column widths
# ---------------------------------------------------------------------------


def _cell(width: int, col: int, span: int = 1) -> _CellRecord:
    box = HlistNode(list=[], width=width, height=0, depth=0, shift_amount=0,
                    glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0)
    return _CellRecord(box, col, span, False)


def _state(rows: list, ncols: int) -> _AlignmentState:
    return _AlignmentState(
        templates=[None] * ncols, tabskip=[], rows=rows, column_width=[], vertical=False,
    )


class TestNullFlagColumnWidths:
    """A column starts at null_flag, so negative cell widths survive (§801)."""

    def test_negative_column_keeps_its_width(self) -> None:
        state = _state([[_cell(10, 0), _cell(-300, 1)], [_cell(20, 0), _cell(-200, 1)]], 2)
        _measure_columns(state)
        assert state.column_width == [20, -200]

    def test_column_without_cells_is_zero(self) -> None:
        state = _state([[_cell(-7, 0)]], 3)
        _measure_columns(state)
        assert state.column_width == [-7, 0, 0]

    def test_span_over_negative_column(self) -> None:
        """``\\omit\\span`` over a ``\\kern-5pt`` column: MiKTeX ``\\wd0`` = 1."""
        body = (
            r"\setbox0\vbox{\halign{#&#\cr\kern-5pt&a\cr \omit\span\kern-3pt\cr}}"
            r"\dimen0=\wd0 \message{[\number\dimen0]}"
        )
        assert _messages(body) == ["[1]"]

    def test_leqalignno_number_column(self) -> None:
        """The archived repro: ``(1)``/``(2)`` at h = 0, not -\\displaywidth."""
        body = (
            r"\hsize=6.5in \nopagenumbers \noindent lead "
            r"$$\leqalignno{u &= v + w&(1)\cr p &= q&(2)\cr}$$ tail"
        )
        assert _page1(body) == [
            (108, 0, 655360), (101, 182045, 655360), (97, 473316, 655360),
            (100, 800997, 655360), (117, 13953951, 2228224), (61, 14511157, 2228224),
            (118, 15202923, 2228224), (43, 15689736, 2228224), (119, 16345094, 2228224),
            (40, 0, 2228224), (49, 254863, 2228224), (41, 582544, 2228224),
            (112, 13999389, 3211264), (61, 14511157, 3211264), (113, 15202923, 3211264),
            (40, 0, 3211264), (50, 254863, 3211264), (41, 582544, 3211264),
            (116, 0, 4784128), (97, 254863, 4784128), (105, 582544, 4784128),
        ]

    def test_eqalignno_unchanged(self) -> None:
        body = (
            r"\hsize=6.5in \nopagenumbers \noindent lead "
            r"$$\eqalignno{u &= v + w&(1)\cr p &= q&(2)\cr}$$ tail"
        )
        assert _page1(body) == [
            (108, 0, 655360), (101, 182045, 655360), (97, 473316, 655360),
            (100, 800997, 655360), (117, 13953951, 2228224), (61, 14511157, 2228224),
            (118, 15202923, 2228224), (43, 15689736, 2228224), (119, 16345094, 2228224),
            (40, 29948456, 2228224), (49, 30203319, 2228224), (41, 30531000, 2228224),
            (112, 13999389, 3211264), (61, 14511157, 3211264), (113, 15202923, 3211264),
            (40, 29948456, 3211264), (50, 30203319, 3211264), (41, 30531000, 3211264),
            (116, 0, 4784128), (97, 254863, 4784128), (105, 582544, 4784128),
        ]

    def test_leqalignno_after_paragraph(self) -> None:
        assert _page1(r"x\par$$\leqalignno{a&=b\cr c&=d&(1)\cr}$$ x") == [
            (120, 1310720, 655360), (97, 14612268, 3014656), (61, 15140724, 3014656),
            (98, 15832490, 3014656), (99, 14675073, 3997696), (61, 15140724, 3997696),
            (100, 15832490, 3997696), (40, 1, 3997696), (49, 254864, 3997696),
            (41, 582545, 3997696), (120, 0, 5570560),
        ]


# ---------------------------------------------------------------------------
# Component 3 — \noalign \prevdepth through both passes
# ---------------------------------------------------------------------------


class TestNoalignPrevdepth:
    """A ``\\noalign`` ``\\prevdepth`` sets the alignment list's depth (§785)."""

    @pytest.mark.parametrize(
        ("formula", "miktex"),
        [
            (r"\overbrace{a\,b}", "[1179660,926968,0]"),
            (r"\underbrace{a+b}_{n\,m}", "[1428664,455111,985222]"),
            (r"\overbrace{x+y}^{k}", "[1520370,1369334,127431]"),
        ],
    )
    def test_braces_build(self, formula: str, miktex: str) -> None:
        assert _messages(r"\setbox0\hbox{$" + formula + "$}" + _DIMS) == [miktex]

    @pytest.mark.parametrize(
        ("noalign", "miktex"),
        [
            (r"\prevdepth=-1000pt", "[737279,0]"),
            (r"\nointerlineskip", "[737279,0]"),
            (r"\prevdepth=5pt", "[740920,0]"),
            # a rule after the assignment resets it; one before is overridden
            (r"\prevdepth=5pt\hrule", "[763493,0]"),
            (r"\hrule\prevdepth=5pt", "[767134,0]"),
            # a kern leaves it in force
            (r"\prevdepth=5pt\kern2pt", "[871992,0]"),
        ],
    )
    def test_internal_vbox(self, noalign: str, miktex: str) -> None:
        body = (
            r"\setbox0\vbox{\halign{#\cr a\cr\noalign{" + noalign + r"}b\cr}}"
            r"\dimen0=\ht0 \dimen1=\dp0 \message{[\number\dimen0,\number\dimen1]}"
        )
        assert _messages(body) == [miktex]

    def test_survives_a_later_noalign(self) -> None:
        body = (
            r"\setbox0\vbox{\halign{#\cr a\cr\noalign{\prevdepth=5pt}\noalign{\kern0pt}b\cr}}"
            r"\dimen0=\ht0 \message{[\number\dimen0]}"
        )
        assert _messages(body) == ["[740920]"]

    def test_handed_to_the_enclosing_list(self) -> None:
        """§812: the alignment's final ``\\prevdepth`` is the enclosing list's."""
        body = (
            r"\setbox0\vbox{\hbox{q}\halign{#\cr a\cr\noalign{\prevdepth=5pt}}"
            r"\message{[\the\prevdepth]}\hbox{b}}\dimen0=\ht0 \message{[\number\dimen0]}"
        )
        assert _messages(body) == ["[5.0pt]", "[1527352]"]

    def test_does_not_leak_out_of_a_nested_alignment(self) -> None:
        body = (
            r"\setbox0\vbox{\halign{#\cr\vbox{\halign{#\cr a\cr\noalign{\prevdepth=5pt}b\cr}}"
            r"\cr c\cr}}\dimen0=\ht0 \message{[\number\dimen0]}"
        )
        assert _messages(body) == ["[1527352]"]

    def test_does_not_leak_into_a_nested_alignment(self) -> None:
        body = (
            r"\setbox0\vbox{\halign{#\cr g\cr\noalign{\prevdepth=9pt}\vbox{\halign{#\cr a\cr}}"
            r"\cr}}\dimen0=\ht0 \message{[\number\dimen0]}"
        )
        assert _messages(body) == ["[757303]"]

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (
                r"x\par\halign{#\cr a\cr\noalign{\nointerlineskip}b\cr}x",
                [(120, 1310720, 655360), (97, 0, 1441792), (98, 0, 1896903),
                 (120, 1310720, 2683335)],
            ),
            (
                r"x\par\halign{#\cr a\cr\noalign{\prevdepth=5pt}b\cr}x",
                [(120, 1310720, 655360), (97, 0, 1441792), (98, 0, 1900544),
                 (120, 1310720, 2686976)],
            ),
            (
                r"x\par\halign{#\cr a\cr\noalign{\prevdepth=5pt}}x",
                [(120, 1310720, 655360), (97, 0, 1441792), (120, 1310720, 1900544)],
            ),
            (
                r"x\par $$\halign{#\cr a\cr\noalign{\prevdepth=5pt}b\cr}$$ x",
                [(120, 1310720, 655360), (97, 0, 3014656), (98, 0, 3473408),
                 (120, 0, 5046272)],
            ),
            (
                r"x\par $$\halign{#\cr a\cr\noalign{\nointerlineskip}b\cr}$$ x",
                [(120, 1310720, 655360), (97, 0, 3014656), (98, 0, 3469767),
                 (120, 0, 5042631)],
            ),
            (
                r"x\par $$\halign{#\cr a\cr\noalign{\prevdepth=5pt}}$$ x",
                [(120, 1310720, 655360), (97, 0, 3014656), (120, 0, 4259840)],
            ),
            (
                r"x\par $$\displaylines{a\cr\noalign{\nointerlineskip}b\cr}$$ x",
                [(120, 1310720, 655360), (97, 15219724, 3014656), (98, 15252302, 3469767),
                 (120, 0, 5042631)],
            ),
            (
                r"\noindent $\overbrace{a\,b}$ and $\underbrace{a+b}_{n\,m}$ x",
                [(122, 0, 275249), (125, 294915, 275249), (124, 589830, 275249),
                 (123, 884745, 275249), (97, 221381, 926968), (98, 677021, 926968),
                 (97, 1398113, 926968), (110, 1725794, 926968), (100, 2089884, 926968),
                 (97, 2672427, 926968), (43, 3164475, 926968), (98, 3819833, 926968),
                 (124, 2672427, 1256830), (123, 3091844, 1256830), (122, 3386759, 1256830),
                 (125, 3806176, 1256830), (110, 2947498, 1846654), (109, 3360969, 1846654),
                 (120, 4319544, 926968)],
            ),
            (
                r"x\par $$\overbrace{a+b+c}^{3}$$ x",
                [(120, 1310720, 655360), (51, 15262314, 1868504), (122, 14136299, 2274824),
                 (125, 15098017, 2274824), (124, 15392932, 2274824), (123, 16354649, 2274824),
                 (97, 14136299, 2926543), (43, 14628347, 2926543), (98, 15283705, 2926543),
                 (43, 15710595, 2926543), (99, 16365953, 2926543), (120, 0, 4171727)],
            ),
        ],
    )
    def test_page_positions(self, body: str, miktex: list) -> None:
        """Outer vertical list, display splice and inline formulas."""
        #: brace leaders now paint real set_rule events. The old
        # walker hid their advancement. now sets every glue exactly.
        data = _compile(body, DviDevice())
        assert walk_chars_with_positions(data, _tfm_width(), advance_rules=True)[0][:-1] == miktex


# ---------------------------------------------------------------------------
# Component 4 — §1202-§1203 display skips and displacement
# ---------------------------------------------------------------------------

_LEQNO_AFTER_TEXT = [
    (120, 1310720, 655360), (40, 0, 2228224), (49, 254863, 2228224),
    (41, 582544, 2228224), (121, 15220519, 2228224), (120, 0, 3801088),
]


class TestDisplaySkipSelection:
    """§1203: long iff ``d+s <= \\predisplaysize`` or the number is a ``\\leqno``."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # \leqno always takes the long skips
            (
                r"x\par $$y\leqno(1)$$ x",
                [(120, 1310720, 655360), (40, 0, 3014656), (49, 254863, 3014656),
                 (41, 582544, 3014656), (121, 15220519, 3014656), (120, 0, 4587520)],
            ),
            (r"x $$y\leqno(1)$$ x", _LEQNO_AFTER_TEXT),
            (r"x\par\noindent$$y\leqno(1)$$ x", _LEQNO_AFTER_TEXT),
            (
                r"\noindent x $$\eqalign{a&=b\cr}\leqno(1)$$ x",
                [(120, 0, 655360), (40, 0, 2228224), (49, 254863, 2228224),
                 (41, 582544, 2228224), (97, 14642191, 2228224), (61, 15170647, 2228224),
                 (98, 15862413, 2228224), (120, 0, 3801088)],
            ),
            # §1146 quad(cur_font): a 20pt text font, not the family-2 quad
            (
                r"\font\big=cmr10 at 20pt \big\noindent\hskip190pt x $$y$$ x",
                [(120, 12451840, 655360), (121, 15220520, 2228224), (120, 0, 3801088)],
            ),
        ],
    )
    def test_long_skips(self, body: str, miktex: list) -> None:
        assert _page1(body) == miktex

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # §1202 d<2e: the formula moves to half(z-w-e) and takes long skips
            (
                r"\noindent\hbox{}$$\hbox to 425pt{a\hfil}\eqno(1)$$ x",
                [(97, 1047828, 2228224), (40, 29948456, 2228224), (49, 30203319, 2228224),
                 (41, 30531000, 2228224), (120, 0, 3801088)],
            ),
            # ... and to d = 0 when it starts with glue
            (
                r"\noindent\hbox{}$$\hskip0pt\hbox to 425pt{a\hfil}\eqno(1)$$ x",
                [(97, 0, 2228224), (40, 29948456, 2228224), (49, 30203319, 2228224),
                 (41, 30531000, 2228224), (120, 0, 3801088)],
            ),
            (
                r"\noindent\hbox{}$$\hbox to 425pt{a\hfil}\leqno(1)$$ x",
                [(40, 0, 2228224), (49, 254863, 2228224), (41, 582544, 2228224),
                 (97, 1885235, 2228224), (120, 0, 3801088)],
            ),
            (
                r"\noindent\hbox{}$$\hskip0pt\hbox to 425pt{a\hfil}\leqno(1)$$ x",
                [(40, 0, 2228224), (49, 254863, 2228224), (41, 582544, 2228224),
                 (97, 2933063, 2228224), (120, 0, 3801088)],
            ),
        ],
    )
    def test_numbered_displacement(self, body: str, miktex: list) -> None:
        assert _page1(body) == miktex

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (
                r"\noindent\hskip 213.6pt x $$y\eqno(1)$$ x",
                [(120, 13998490, 655360), (121, 15220520, 2228224), (40, 29948456, 2228224),
                 (49, 30203319, 2228224), (41, 30531000, 2228224), (120, 0, 3801088)],
            ),
            (
                r"\noindent\hskip 214.5pt x $$y$$ x",
                [(120, 14057472, 655360), (121, 15220520, 2228224), (120, 0, 3801088)],
            ),
            (
                r"\noindent x $$\hskip0pt y$$ x",
                [(120, 0, 655360), (121, 15220520, 1441792), (120, 0, 2686976)],
            ),
            (
                r"\everydisplay{\predisplaysize=-5pt}\noindent x $$y$$ x",
                [(120, 0, 655360), (121, 15220520, 1441792), (120, 0, 2686976)],
            ),
            (
                r"x\par $$y\eqno(1)$$ x",
                [(120, 1310720, 655360), (121, 15220520, 2228224), (40, 29948456, 2228224),
                 (49, 30203319, 2228224), (41, 30531000, 2228224), (120, 0, 3473408)],
            ),
            (
                r"x\par $$\halign{#\cr y\cr}$$ x",
                [(120, 1310720, 655360), (121, 0, 3014656), (120, 0, 4587520)],
            ),
            (
                r"x\par\noindent$$\halign{#\cr y\cr}$$ x",
                [(120, 1310720, 655360), (121, 0, 2228224), (120, 0, 3801088)],
            ),
            (
                r"x $$\halign{#\cr y\cr}$$ x",
                [(120, 1310720, 655360), (121, 0, 2228224), (120, 0, 3801088)],
            ),
            # reviewer rows
            (
                r"x\par\noindent$$\displaylines{a\cr b\cr}$$ x",
                [(120, 1310720, 655360), (97, 15219724, 2228224), (98, 15252302, 3211264),
                 (120, 0, 4784128)],
            ),
        ],
    )
    def test_unchanged(self, body: str, miktex: list) -> None:
        """Displays that were already exact stay exact."""
        assert _page1(body) == miktex

    def test_noindent_eqalignno_vertical(self) -> None:
        """ reviewer vertical row; complete positions are covered by the corpus guard."""
        glyphs = _page1(r"x\par\noindent$$\eqalignno{a&=b&(1)\cr}$$ x")
        assert [(c, v) for c, _h, v in glyphs] == [
            (120, 655360), (97, 2228224), (61, 2228224), (98, 2228224),
            (40, 2228224), (49, 2228224), (41, 2228224), (120, 3801088),
        ]
