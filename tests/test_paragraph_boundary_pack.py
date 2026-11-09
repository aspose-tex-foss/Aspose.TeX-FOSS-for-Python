r""" paragraph start and end pack — MiKTeX-measured glyph positions.

Every expected value is a MiKTeX 24.4 plain measurement of the same input:
per page, the glyphs ``(code, v)`` from the DVI via
``tests/_verification/dvi_walker`` with the folio dropped.  Only vertical
positions are compared here; separately pins exact full glyph events.
"""

from __future__ import annotations

import warnings

import pytest

from aspose_tex import DviDevice, TeXJob, TeXOptions
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode, GlueNode
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._input.reader import StringInputSource
from tests._verification.dvi_walker import walk_chars_with_positions


def _tfm_char_width():
    """``char_width`` for the DVI walker: TFM widths at design size, as dvitype."""
    from aspose_tex._fonts.font_manager import FontManager

    mgr = FontManager()

    def width(font: str, code: int) -> int:
        if mgr.get_metrics(font) is None:
            mgr.load_font(font, font)
        return mgr.get_metrics(font).char_metrics(code).width

    return width


def _pages(body: str) -> list[list[tuple[int, int]]]:
    """``(code, v)`` of every glyph on every page, the folio dropped."""
    job = TeXJob(StringInputSource(body + "\n\\bye\n"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = job.run()
    pages = walk_chars_with_positions(dvi, _tfm_char_width())
    return [[(c, v) for c, _h, v in page[:-1]] for page in pages]


def _page1(body: str) -> list[tuple[int, int]]:
    return _pages(body)[0]


# ---------------------------------------------------------------------------
# \parskip is the register value taken at paragraph start (§1091)
# ---------------------------------------------------------------------------


class TestParskipRegister:
    r"""``\parskip`` reaches the vertical list; not at a page top; not on resume."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\parskip=5pt x\par y", [(120, 655360), (121, 1769472)]),
            # The stretch of \parskip loses to \vfill's fill order.
            (r"\parskip=5pt plus 3pt minus 2pt x\par y\par z\par\vfill",
             [(120, 655360), (121, 1769472), (122, 2883584)]),
            (r"\parskip=5pt x\par y$$z$$ x",
             [(120, 655360), (121, 1769472), (122, 2555904), (120, 3801088)]),
            # A void paragraph keeps its \parskip on the list.
            (r"\parskip=5pt x\par\noindent$$y$$ x",
             [(120, 655360), (121, 1769472), (120, 3014656)]),
            (r"\parskip=5pt x\par\noindent\par x", [(120, 655360), (120, 2097152)]),
            # The value in force when the paragraph starts, not when it ends.
            (r"\parskip=5pt x\par{\parskip=20pt y\par} z",
             [(120, 655360), (121, 2752512), (122, 3866624)]),
            (r"\parskip=5pt x\par y\parskip=20pt\par z",
             [(120, 655360), (121, 1769472), (122, 3866624)]),
            # A paragraph resumed after a display gets no \parskip (§1206).
            (r"\parskip=5pt x$$z$$\par y", [(120, 655360), (122, 1441792), (121, 3014656)]),
            (r"\parskip=5pt x$$z$$ y\par z",
             [(120, 655360), (122, 1441792), (121, 2686976), (122, 3801088)]),
            (r"\parskip=5pt x\par\item{a}b\par y",
             [(120, 655360), (97, 1769472), (98, 1769472), (121, 2883584)]),
            (r"\parskip=5pt x\par\hrule y", [(120, 655360), (121, 1291422)]),
            (r"\parskip=5pt x\par\vskip3pt y", [(120, 655360), (121, 1966080)]),
        ],
    )
    def test_page_positions(self, body: str, miktex: list) -> None:
        assert _page1(body) == miktex

    def test_no_parskip_at_the_top_of_a_page(self) -> None:
        assert _pages(r"\parskip=5pt x\par\eject y\par z") == [
            [(120, 655360)], [(121, 655360), (122, 1769472)],
        ]

    def test_parskip_is_contributed_when_the_paragraph_starts(self) -> None:
        # §1091: the glue goes on the list at new_graf with the value
        # in force then; at the page top build_page discards it (§1000).
        interp = TeXInterpreter()
        interp.run_with_device(StringInputSource(""), DviDevice())
        skip = Glue(5 * 65_536, 2 * 65_536, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
        interp._set_named_skip("parskip", skip)
        interp._begin_paragraph(indent=False)
        assert interp._page_builder.last_contributed_node == GlueNode(skip)
        assert interp._page_builder._mvl == []
        interp._append_to_hlist(CharNode(ord("A"), "tenrm"))
        interp._set_named_skip("parskip", Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
        interp._end_paragraph()
        interp._begin_paragraph(indent=False)
        interp._append_to_hlist(CharNode(ord("B"), "tenrm"))
        interp._end_paragraph()
        glues = [n.glue for n in interp._page_builder._mvl if isinstance(n, GlueNode)]
        assert Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL) in glues
        assert skip not in glues

    def test_resumed_paragraph_has_none(self) -> None:
        interp = TeXInterpreter()
        interp.run_with_device(StringInputSource(""), DviDevice())
        builder = interp._page_builder
        before = (list(builder._contrib), list(builder._mvl))
        interp._begin_paragraph(indent=False, par_skip=False)
        assert (list(builder._contrib), list(builder._mvl)) == before


# ---------------------------------------------------------------------------
# vertical glue in a paragraph ends it first (§1094 head_for_vmode)
# Needed for the \vfill row: the glue went in ahead of the lines.
# ---------------------------------------------------------------------------


class TestHeadForVmode:
    r"""``\vskip``/``\vfil``/``\vfill``/``\vss``/``\unvbox`` end the open paragraph."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"x\par y\vfill", [(120, 655360), (121, 1441792)]),
            # The \vfill row: the parskip must precede the \vfill.
            (r"\parskip=6pt plus 2pt x\par y\vfill", [(120, 655360), (121, 1835008)]),
            (r"\parskip=5pt plus 3pt minus 2pt x\par y\par z\vfill",
             [(120, 655360), (121, 1769472), (122, 2883584)]),
            (r"x\par y\vss", [(120, 655360), (121, 1441792)]),
            (r"x\par y\bigskip z", [(120, 655360), (121, 1441792), (122, 3014656)]),
            (r"\parskip=5pt x\par y\vskip 3pt z",
             [(120, 655360), (121, 1769472), (122, 3080192)]),
            (r"x \hbox{y}\vfil z", [(120, 655360), (121, 655360), (122, 1441792)]),
        ],
    )
    def test_page_positions(self, body: str, miktex: list) -> None:
        assert _page1(body) == miktex

    def test_unvbox_in_a_paragraph_ends_it(self) -> None:
        # Raised "\unvbox in horizontal mode" before.  The unvboxed material
        # itself still gets interline glue it should not (separate follow-up),
        # so this compares with the explicit-\par form, not with MiKTeX.
        box = r"\setbox1\vbox{\hbox{a}}x\par y"
        assert _page1(box + r"\unvbox1 z") == _page1(box + r"\par\unvbox1 z")


# ---------------------------------------------------------------------------
# a non-void paragraph is line-broken even with no content (§1096)
# ---------------------------------------------------------------------------


class TestEmptyLineParagraph:
    r"""``\indent\par`` sets an empty line; ``\noindent\par`` sets nothing."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"x\par\indent\par x", [(120, 655360), (120, 2228224)]),
            (r"\parskip=5pt x\par\indent\par x", [(120, 655360), (120, 2883584)]),
            (r"x\par\indent\par\indent\par x", [(120, 655360), (120, 3014656)]),
            # A paragraph of one interword space is not void either.
            (r"x\par\noindent\ \par x", [(120, 655360), (120, 2228224)]),
            # At the top of the page the empty line takes \topskip.
            (r"\indent\par x", [(120, 1441792)]),
            # Void: nothing is set.
            (r"x\par\noindent\par x", [(120, 655360), (120, 1441792)]),
            # A display after an indent-only paragraph is unchanged.
            (r"x\par\indent$$y$$ x", [(120, 655360), (121, 2228224), (120, 3473408)]),
            (r"x$$y$$\par x", [(120, 655360), (121, 1441792), (120, 2686976)]),
        ],
    )
    def test_page_positions(self, body: str, miktex: list) -> None:
        assert _page1(body) == miktex
