r""" horizontal token boundaries pack — MiKTeX-measured glyph positions.

Every expected value is a MiKTeX 24.4 plain measurement of the same input:
per page, the glyphs ``(code, h, v)`` from the DVI via
``tests/_verification/dvi_walker`` with the folio dropped, and the
``\message`` output that starts with ``[``.
"""

from __future__ import annotations

import warnings

import pytest

from aspose_tex import DviDevice, TeXJob, TeXOptions
from aspose_tex._engine.box_builder import HBoxBuilder
from aspose_tex._engine.nodes import CharNode, KernNode
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._input.reader import StringInputSource
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _messages, _tfm_width


def _page1(body: str) -> list[tuple[int, int, int]]:
    """``(code, h, v)`` of every page-1 glyph but the folio."""
    job = TeXJob(StringInputSource(body + "\n\\bye\n"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = job.run()
    return [tuple(g) for g in walk_chars_with_positions(dvi, _tfm_width())[0][:-1]]


# ---------------------------------------------------------------------------
# — §1038: a non-character command ends the lig/kern run; a character,
# \char and a \chardef constant continue it
# ---------------------------------------------------------------------------


class TestLigKernRunBoundary:
    r"""``o\relax o`` gets no font kern, ``o\char`o`` and ``o\oo`` do."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # The archived repro: the eager \hbox kerned across \relax.
            (r"\noindent\hbox{o\relax o}", [(111, 0, 655360), (111, 327681, 655360)]),
            (r"\noindent o\relax o", [(111, 0, 655360), (111, 327681, 655360)]),
            (r"\vbox{\noindent o\relax o}", [(111, 0, 655360), (111, 327681, 655360)]),
            (r"\setbox1\vbox{\hbox{o\relax o}}\box1",
             [(111, 0, 655360), (111, 327681, 655360)]),
            (r"\noindent\hbox{f\relax i}", [(102, 0, 655360), (105, 200250, 655360)]),
            (r"\noindent\hbox{ff\relax i}", [(11, 0, 655360), (105, 382295, 655360)]),
            (r"\noindent\hbox{A\relax V}", [(65, 0, 655360), (86, 491521, 655360)]),
            # Braces, assignments, \message and boxes are commands too.
            (r"\noindent\hbox{o{}o}", [(111, 0, 655360), (111, 327681, 655360)]),
            (r"\noindent\hbox{{o}o}", [(111, 0, 655360), (111, 327681, 655360)]),
            (r"\noindent\hbox{o\count1=1 o}", [(111, 0, 655360), (111, 327681, 655360)]),
            (r"\noindent\hbox{o\hbox{}o}", [(111, 0, 655360), (111, 327681, 655360)]),
            # Characters spliced by \unhcopy start no run with the next one.
            (r"\setbox1\hbox{oo}\noindent\hbox{\unhcopy1 o}",
             [(111, 0, 655360), (111, 345886, 655360), (111, 673567, 655360)]),
            (r"\halign{#\cr o{}o\cr o\relax o\cr oo\cr}",
             [(111, 0, 655360), (111, 327681, 655360), (111, 0, 1441792),
              (111, 327681, 1441792), (111, 0, 2228224), (111, 345886, 2228224)]),
            # Adjacent characters keep their ligatures and kerns.
            (r"\noindent\hbox{fi}", [(12, 0, 655360)]),
            (r"\noindent\hbox{oo}", [(111, 0, 655360), (111, 345886, 655360)]),
            (r"\noindent\hbox{o\char`o}", [(111, 0, 655360), (111, 345886, 655360)]),
            (r"\noindent\hbox{$o\relax o$}", [(111, 0, 655360), (111, 317668, 655360)]),
        ],
    )
    def test_glyph_positions_match_miktex(self, body, miktex) -> None:
        assert _page1(body) == miktex

    def test_message_ends_the_run_and_still_runs(self) -> None:
        body = r"\noindent\hbox{o\message{[m]}o}"
        assert _page1(body) == [(111, 0, 655360), (111, 327681, 655360)]
        assert _messages(body) == ["[m]"]

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # plain's \% is \chardef\%=`\%: it used to raise inside \hbox.
            (r"\noindent\hbox{50\%}", [(53, 0, 655360), (48, 327681, 655360), (37, 655362, 655360)]),
            (r"\chardef\oo=`o \noindent\hbox{o\oo}", [(111, 0, 655360), (111, 345886, 655360)]),
            (r"\chardef\oo=`o \noindent o\oo", [(111, 0, 655360), (111, 345886, 655360)]),
            (r"\chardef\ff=`f \noindent\hbox{\ff i}", [(12, 0, 655360)]),
            (r"\chardef\ii=`i \noindent f\ii", [(12, 0, 655360)]),
        ],
    )
    def test_chardef_constant_continues_the_run(self, body, miktex) -> None:
        assert _page1(body) == miktex


class TestHBoxBuilderRun:
    """``HBoxBuilder.end_run`` and spliced characters (unit level)."""

    @staticmethod
    def _builder() -> HBoxBuilder:
        mgr = FontManager()
        mgr.load_font("tenrm", "cmr10")
        return HBoxBuilder(mgr)

    def test_adjacent_characters_kern(self) -> None:
        b = self._builder()
        b.add_char(ord("o"), "tenrm")
        b.add_char(ord("o"), "tenrm")
        assert [type(n) for n in b._nodes] == [CharNode, KernNode, CharNode]

    def test_end_run_drops_the_kern(self) -> None:
        b = self._builder()
        b.add_char(ord("o"), "tenrm")
        b.end_run()
        b.add_char(ord("o"), "tenrm")
        assert [type(n) for n in b._nodes] == [CharNode, CharNode]

    def test_end_run_drops_the_ligature(self) -> None:
        b = self._builder()
        b.add_char(ord("f"), "tenrm")
        b.end_run()
        b.add_char(ord("i"), "tenrm")
        assert [n.char for n in b._nodes] == [ord("f"), ord("i")]

    def test_spliced_character_starts_no_run(self) -> None:
        b = self._builder()
        b._nodes.append(CharNode(char=ord("f"), font_name="tenrm"))
        b.add_char(ord("i"), "tenrm")
        assert [n.char for n in b._nodes] == [ord("f"), ord("i")]


# ---------------------------------------------------------------------------
# — §1041: a space in an open-group \hbox\bgroup list is interword
# glue; the list starts at \spacefactor 1000 and restores its parent's
# ---------------------------------------------------------------------------


class TestOpenGroupHBoxSpaces:
    r"""``\hbox\bgroup o o\egroup`` keeps its space, as ``\hbox{o o}`` does."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # The archived repro.
            (r"\noindent x.\hbox\bgroup o o\egroup o",
             [(120, 0, 655360), (46, 345886, 655360), (111, 527931, 655360),
              (111, 1074065, 655360), (111, 1401746, 655360)]),
            (r"x.\hbox\bgroup o o\egroup o",
             [(120, 1310720, 655360), (46, 1656606, 655360), (111, 1838651, 655360),
              (111, 2384785, 655360), (111, 2712466, 655360)]),
            (r"\noindent\hbox\bgroup o o\egroup", [(111, 0, 655360), (111, 546134, 655360)]),
            (r"\noindent\hbox\bgroup o\hbox\bgroup o o\egroup o\egroup o",
             [(111, 0, 655360), (111, 327681, 655360), (111, 873815, 655360),
              (111, 1201496, 655360), (111, 1529177, 655360)]),
            (r"\noindent\hbox{\hbox\bgroup o o\egroup o}",
             [(111, 0, 655360), (111, 546134, 655360), (111, 873815, 655360)]),
            (r"\noindent\vbox{\hbox\bgroup o o\egroup}", [(111, 0, 655360), (111, 546134, 655360)]),
            (r"\noindent\hbox to 50pt\bgroup o o\egroup o",
             [(111, 0, 655360), (111, 2949119, 655360), (111, 3276800, 655360)]),
            (r"\noindent\hbox\bgroup o{} o{ }o\egroup",
             [(111, 0, 655360), (111, 546134, 655360), (111, 1092268, 655360)]),
            (r"\noindent\hbox\bgroup o~o\egroup", [(111, 0, 655360), (111, 546134, 655360)]),
            # Delegated \setbox / \box / \copy.
            (r"\setbox1\hbox\bgroup o o\egroup\noindent\box1 o",
             [(111, 0, 655360), (111, 546134, 655360), (111, 873815, 655360)]),
            (r"\setbox1\hbox\bgroup o o\egroup\noindent\copy1\box1",
             [(111, 0, 655360), (111, 546134, 655360), (111, 873815, 655360),
              (111, 1419949, 655360)]),
            # The new list starts at 1000: no sentence space after the outer "x.".
            (r"\noindent x.\hbox\bgroup\relax{} o\egroup",
             [(120, 0, 655360), (46, 345886, 655360), (111, 746384, 655360)]),
            (r"\noindent x.\hbox\bgroup x.{} o\egroup",
             [(120, 0, 655360), (46, 345886, 655360), (120, 527931, 655360),
              (46, 873817, 655360), (111, 1347133, 655360)]),
            # Literal-brace boxes are unchanged.
            (r"\noindent x.\hbox{o o} o",
             [(120, 0, 655360), (46, 345886, 655360), (111, 527931, 655360),
              (111, 1074065, 655360), (111, 1620199, 655360)]),
        ],
    )
    def test_glyph_positions_match_miktex(self, body, miktex) -> None:
        assert _page1(body) == miktex

    def test_setbox_restores_the_parent_spacefactor(self) -> None:
        body = (r"\noindent x.\setbox1\hbox\bgroup x.\message{[\the\spacefactor]}\egroup"
                r"\message{[\the\spacefactor]} o\box1")
        assert _page1(body) == [(120, 0, 655360), (46, 345886, 655360), (111, 819202, 655360),
                                (120, 1146883, 655360), (46, 1492769, 655360)]
        assert _messages(body) == ["[3000]", "[3000]"]

    def test_box_end_sets_1000(self) -> None:
        body = r"\noindent\hbox\bgroup o o\egroup\message{[\the\spacefactor]} o"
        assert _page1(body) == [(111, 0, 655360), (111, 546134, 655360), (111, 1092268, 655360)]
        assert _messages(body) == ["[1000]"]


# ---------------------------------------------------------------------------
# — §1034 adjust_space_factor: sfcode 0 leaves the factor alone,
# 1..999 sets it outright
# ---------------------------------------------------------------------------


class TestSpaceFactorCodes:
    r"""``x.) o`` keeps the sentence space: plain's ``)`` has sfcode 0."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # The archived repro.
            (r"\noindent\hbox{x.) o}",
             [(120, 0, 655360), (46, 345886, 655360), (41, 527931, 655360), (111, 1074065, 655360)]),
            (r"\noindent x.) o",
             [(120, 0, 655360), (46, 345886, 655360), (41, 527931, 655360), (111, 1074065, 655360)]),
            (r"\vbox{\noindent x.) o}",
             [(120, 0, 655360), (46, 345886, 655360), (41, 527931, 655360), (111, 1074065, 655360)]),
            (r"\setbox1\vbox{\noindent x.) o}\box1",
             [(120, 0, 655360), (46, 345886, 655360), (41, 527931, 655360), (111, 1074065, 655360)]),
            (r"\noindent\hbox{x.'' o}",
             [(120, 0, 655360), (46, 345886, 655360), (34, 527931, 655360), (111, 1146883, 655360)]),
            (r"\noindent\hbox{x.)) o}",
             [(120, 0, 655360), (46, 345886, 655360), (41, 527931, 655360), (41, 782794, 655360),
              (111, 1328928, 655360)]),
            (r"\noindent\hbox{x?) o}",
             [(120, 0, 655360), (63, 345886, 655360), (41, 655362, 655360), (111, 1201496, 655360)]),
            (r"\noindent\hbox{x;) o}",
             [(120, 0, 655360), (59, 345886, 655360), (41, 527931, 655360), (111, 1001247, 655360)]),
            # Custom zero and positive codes.
            (r"\sfcode`a=0 \noindent\hbox{x.a o}",
             [(120, 0, 655360), (46, 345886, 655360), (97, 527931, 655360), (111, 1146883, 655360)]),
            (r"\sfcode`a=0 \noindent\hbox{xa o}",
             [(120, 0, 655360), (97, 345886, 655360), (111, 892020, 655360)]),
            (r"\sfcode`)=500 \noindent\hbox{x.) o}",
             [(120, 0, 655360), (46, 345886, 655360), (41, 527931, 655360), (111, 1001247, 655360)]),
            (r"\frenchspacing\noindent\hbox{x.) o}",
             [(120, 0, 655360), (46, 345886, 655360), (41, 527931, 655360), (111, 1001247, 655360)]),
            (r"\noindent\hbox{x, o}", [(120, 0, 655360), (44, 345886, 655360), (111, 746384, 655360)]),
            (r"\noindent\hbox{A. o}", [(65, 0, 655360), (46, 491521, 655360), (111, 892019, 655360)]),
            (r"\noindent\hbox{x.A o}",
             [(120, 0, 655360), (46, 345886, 655360), (65, 527931, 655360), (111, 1237905, 655360)]),
        ],
    )
    def test_glyph_positions_match_miktex(self, body, miktex) -> None:
        assert _page1(body) == miktex

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\noindent x.)\message{[\the\spacefactor]}", "[3000]"),
            (r"\noindent\hbox{x.)\message{[\the\spacefactor]}}", "[3000]"),
            (r"\noindent x.\char`)\message{[\the\spacefactor]}", "[3000]"),
            (r"\chardef\rp=`) \noindent x.\rp\message{[\the\spacefactor]}", "[3000]"),
            (r"\noindent\hbox{)\message{[\the\spacefactor]}}", "[1000]"),
            (r"\sfcode`a=0 \noindent x,a\message{[\the\spacefactor]}", "[1250]"),
            # 1..999 sets the factor outright, also after a sentence end.
            (r"\noindent x.A\message{[\the\spacefactor]}", "[999]"),
            (r"\noindent\hbox{x.A\message{[\the\spacefactor]}}", "[999]"),
            (r"\sfcode`a=500 \noindent x.a\message{[\the\spacefactor]}", "[500]"),
            (r"\noindent A\message{[\the\spacefactor]}", "[999]"),
            # Above 1000: kept below 1000 at 1000, otherwise set.
            (r"\sfcode`a=2000 \noindent x,a\message{[\the\spacefactor]}", "[2000]"),
            (r"\sfcode`a=2000 \noindent Aa\message{[\the\spacefactor]}", "[1000]"),
        ],
    )
    def test_spacefactor_matches_miktex(self, body, miktex) -> None:
        assert _messages(body) == [miktex]


# ---------------------------------------------------------------------------
# — §1123-1124: without a base character the accent stands alone and
# the following token is read again; spaces and \relax are skipped first
# ---------------------------------------------------------------------------


class TestAccentWithoutBase:
    r"""``\accent19\relax\message{…}`` sets glyph 19 alone and runs ``\message``."""

    def test_archived_repro(self) -> None:
        body = r"\noindent\hbox{x.\accent19\relax\message{[sf\the\spacefactor]}}"
        assert _page1(body) == [(120, 0, 655360), (46, 345886, 655360), (19, 527931, 655360)]
        assert _messages(body) == ["[sf1000]"]

    def test_paragraph_repro(self) -> None:
        body = r"\noindent x.\accent19\relax\message{[sf\the\spacefactor]} y"
        assert _page1(body) == [(120, 0, 655360), (46, 345886, 655360), (19, 527931, 655360),
                                (121, 1074065, 655360)]
        assert _messages(body) == ["[sf1000]"]

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\noindent\hbox{\accent19\hbox{o}}", [(19, 0, 655360), (111, 327681, 655360)]),
            (r"\noindent\accent19\hbox{o}", [(19, 0, 655360), (111, 327681, 655360)]),
            (r"\noindent\hbox{\accent19 \kern1pt o}", [(19, 0, 655360), (111, 393217, 655360)]),
            (r"\noindent\hbox{\accent19{o}}", [(19, 0, 655360), (111, 327681, 655360)]),
            (r"\noindent\hbox{x\accent19}", [(120, 0, 655360), (19, 345886, 655360)]),
            (r"\noindent\hbox{\accent19$x$}", [(19, 0, 655360), (120, 327681, 655360)]),
            (r"\noindent\accent19\ o", [(19, 0, 655360), (111, 546134, 655360)]),
            (r"\noindent\hbox{\accent19 \par o}", [(19, 0, 655360), (111, 327681, 655360)]),
            (r"\noindent o\accent19\relax{}o",
             [(111, 0, 655360), (19, 327681, 655360), (111, 655362, 655360)]),
            # The space after the accent is a normal one: the factor is 1000.
            (r"\noindent x.\accent19\relax{} y",
             [(120, 0, 655360), (46, 345886, 655360), (19, 527931, 655360), (121, 1074065, 655360)]),
            (r"\noindent\hbox{x.\accent19\relax{} y}",
             [(120, 0, 655360), (46, 345886, 655360), (19, 527931, 655360), (121, 1074065, 655360)]),
            (r"\setbox1\hbox{\accent19\relax}\noindent\box1 x", [(19, 0, 655360), (120, 327681, 655360)]),
            (r"\noindent\hbox\bgroup\accent19\hbox{o}\egroup", [(19, 0, 655360), (111, 327681, 655360)]),
            (r"\halign{#\cr\accent19\hbox{o}\cr}", [(19, 0, 655360), (111, 327681, 655360)]),
        ],
    )
    def test_glyph_positions_match_miktex(self, body, miktex) -> None:
        assert _page1(body) == miktex

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # \relax and spaces are skipped before the base (§1123 do_assignments);
            # a \chardef constant is a base. The accent's line height is,
            # so only (code, h) is compared here.
            (r"\noindent\hbox{\accent19\relax o}", [(19, 0), (111, 0)]),
            (r"\noindent\hbox{\accent19 \relax\relax o}", [(19, 0), (111, 0)]),
            (r"\chardef\oo=`o \noindent\hbox{\accent19\oo}", [(19, 0), (111, 0)]),
            (r"\chardef\oo=`o \noindent\accent19\oo", [(19, 0), (111, 0)]),
            (r"\noindent\hbox{o\accent19\relax o}", [(111, 0), (19, 327681), (111, 327681)]),
            (r"\noindent\hbox{\accent19 \accent18 o}", [(19, 0), (18, 327681), (111, 327681)]),
        ],
    )
    def test_base_after_relax_is_accented(self, body, miktex) -> None:
        assert [(c, h) for c, h, _v in _page1(body)] == miktex


# ---------------------------------------------------------------------------
# — \noboundary: starts a paragraph in vertical mode (§1090), ends
# the lig/kern run in horizontal mode (§1038), is ignored in math (§1045)
# ---------------------------------------------------------------------------


class TestNoBoundary:
    r"""``\noboundary`` is a primitive; CM fonts have no boundary character."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\noboundary x", [(120, 1310720, 655360)]),
            (r"x\noboundary y", [(120, 1310720, 655360), (121, 1656606, 655360)]),
            (r"x\par\noboundary y", [(120, 1310720, 655360), (121, 1310720, 1441792)]),
            (r"\noindent\noboundary\par x", [(120, 1310720, 655360)]),
            # Inside a word it ends the run: no fi ligature, no o-o kern.
            (r"\noindent f\noboundary i", [(102, 0, 655360), (105, 200250, 655360)]),
            (r"\noindent o\noboundary o", [(111, 0, 655360), (111, 327681, 655360)]),
            (r"\noindent\hbox{f\noboundary i}", [(102, 0, 655360), (105, 200250, 655360)]),
            (r"\noindent\hbox{o\noboundary o}", [(111, 0, 655360), (111, 327681, 655360)]),
            (r"\noindent\hbox\bgroup f\noboundary i\egroup", [(102, 0, 655360), (105, 200250, 655360)]),
            (r"\vbox{\noindent f\noboundary i}", [(102, 0, 655360), (105, 200250, 655360)]),
            (r"\halign{#\cr f\noboundary i\cr}", [(102, 0, 655360), (105, 200250, 655360)]),
            # Before or after a whole word it changes nothing.
            (r"\noindent\hbox{\noboundary fi}", [(12, 0, 655360)]),
            (r"\noindent fi\noboundary", [(12, 0, 655360)]),
            (r"\noindent\hbox{\noboundary x}", [(120, 0, 655360)]),
            (r"\noindent\hbox{x\noboundary\ y}", [(120, 0, 655360), (121, 564339, 655360)]),
            (r"$\noboundary x$", [(120, 1310720, 655360)]),
            (r"$x\noboundary y$", [(120, 1310720, 655360), (121, 1685276, 655360)]),
        ],
    )
    def test_glyph_positions_match_miktex(self, body, miktex) -> None:
        assert _page1(body) == miktex

    def test_spacefactor_is_untouched(self) -> None:
        body = r"\noindent x.\noboundary\message{[\the\spacefactor]} y"
        assert _page1(body) == [(120, 0, 655360), (46, 345886, 655360), (121, 819202, 655360)]
        assert _messages(body) == ["[3000]"]
