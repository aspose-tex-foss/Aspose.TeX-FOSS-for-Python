r""" — an interword space after a box, a group or a control space.

``_handle_space`` used to drop a space token whenever the previous space token
had set an ``_after_space`` flag that only typeset characters (and, since
, inline math) cleared.  A box, ``{}``, ``\relax`` or a second control
space left the flag set, so in ``o \hbox{o} o`` the space after the box was
taken for a repeated space and discarded.  TeX has no such flag: runs of input
spaces are collapsed by the tokenizer's state S (§347), and every space token
that reaches horizontal mode is appended (§1041), so ``\ \ `` and a macro that
expands to a space each give a glue.

Every expected list is MiKTeX 24.4 ``tex`` + the DVI walker over its DVI:
``(char code, h)`` of each glyph on page 1, the folio excluded.  cmr10 ``o`` is
327681 sp wide and its interword space 218453 sp.
"""

from __future__ import annotations

import warnings

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob, TeXOptions
from aspose_tex._fonts.font_manager import FontManager
from tests._verification.dvi_walker import walk_chars_with_positions


def _tfm_width():
    """``char_width`` for the walker: TFM widths at design size, as dvitype."""
    mgr = FontManager()

    def width(font: str, code: int) -> int:
        if mgr.get_metrics(font) is None:
            mgr.load_font(font, font)
        return mgr.get_metrics(font).char_metrics(code).width

    return width


def _glyph_h(body: str) -> list[tuple[int, int]]:
    """``(code, h)`` of every page-1 glyph but the folio for plain ``<body>\bye``."""
    job = TeXJob(StringInputSource(body + r"\bye"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = job.run()
    assert dvi is not None
    return [(c, h) for c, h, _v in walk_chars_with_positions(dvi, _tfm_width())[0]][:-1]


_O = ord("o")


class TestSpaceAfterBox:
    """A box between two spaces keeps both interword glues (AC #1)."""

    @pytest.mark.parametrize(
        "body",
        [
            r"\noindent o \hbox{o} o",
            r"\noindent o \kern0pt\hbox{o} o",
            r"\noindent o \hbox{o}\ o",
            r"\noindent o \vbox{\hbox{o}} o",
            r"\noindent o \vtop{\hbox{o}} o",
        ],
    )
    def test_box_between_spaces(self, body: str) -> None:
        assert _glyph_h(body) == [(_O, 0), (_O, 546134), (_O, 1092268)]

    def test_plain_b_accent_between_spaces(self) -> None:
        # plain \b builds a \vtop via \oalign; char 22 is its macron bar
        assert _glyph_h(r"\noindent o \b o o") == [(_O, 0), (_O, 546134), (22, 546134), (_O, 1092268)]

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # no space before the box, and explicit glue after it
            (r"\noindent\hbox{o} o", [(_O, 0), (_O, 546134)]),
            (r"\noindent o \hbox{o}\hskip3.33333pt o", [(_O, 0), (_O, 546134), (_O, 1092268)]),
        ],
    )
    def test_shapes_that_were_already_right(self, body: str, miktex: list[tuple[int, int]]) -> None:
        assert _glyph_h(body) == miktex


class TestEverySpaceTokenIsAppended:
    """Two space tokens in a row give two glues — TeX collapses spaces only in the tokenizer."""

    @pytest.mark.parametrize(
        "body",
        [
            r"\noindent o {} o",
            r"\noindent o \relax\ o",
            r"\noindent o \ o",
            r"\noindent o\ \ o",
            r"\def\sp{ }\noindent o \sp o",
            r"\def\sp{ }\noindent o\sp\sp o",
        ],
    )
    def test_two_spaces(self, body: str) -> None:
        assert _glyph_h(body) == [(_O, 0), (_O, 764587)]

    def test_input_space_run_is_still_one_glue(self) -> None:
        # state S (§347) collapses the run before the interpreter sees it
        assert _glyph_h(r"\noindent o     o") == [(_O, 0), (_O, 546134)]

    def test_space_around_inline_math(self) -> None:
        #'s shape keeps working without a math-close flag reset
        assert _glyph_h(r"\noindent o $x$ o") == [(_O, 0), (ord("x"), 546134), (_O, 1139143)]
