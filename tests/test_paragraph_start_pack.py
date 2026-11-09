r""" paragraph start (``new_graf``) pack — MiKTeX-measured glyph positions.

Every expected value is a MiKTeX 24.4 plain measurement of the same input:
per page, the glyphs ``(code, h, v)`` from the DVI via
``tests/_verification/dvi_walker`` with the folio dropped.
"""

from __future__ import annotations

import warnings

import pytest

from aspose_tex import DviDevice, TeXJob, TeXOptions
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
# §1090: horizontal commands in vertical mode start an indented
# paragraph (back_input; new_graf(true)); plain's \leavevmode is \unhbox
# ---------------------------------------------------------------------------


class TestNewGrafFromVerticalMode:
    r"""``\leavevmode``, ``\unhbox``, ``\hfil``, ``\vrule`` … begin a paragraph."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\leavevmode y", [(121, 1310720, 655360)]),
            (r"x\par\leavevmode y", [(120, 1310720, 655360), (121, 1310720, 1441792)]),
            (r"x\par\leavevmode\hskip3pt y",
             [(120, 1310720, 655360), (121, 1507328, 1441792)]),
            # An indent-only paragraph still sets a line.
            (r"x\par\leavevmode\hskip3pt\par x",
             [(120, 1310720, 655360), (120, 1310720, 2228224)]),
            (r"\parindent=0pt x\par\leavevmode y", [(120, 0, 655360), (121, 0, 1441792)]),
            (r"\setbox1\hbox{ab}x\par\unhbox1 y",
             [(120, 1310720, 655360), (97, 1310720, 1441792), (98, 1638401, 1441792),
              (121, 2002491, 1441792)]),
            (r"\setbox1\hbox{ab}x\par\unhcopy1 y\par\unhcopy1",
             [(120, 1310720, 655360), (97, 1310720, 1441792), (98, 1638401, 1441792),
              (121, 2002491, 1441792), (97, 1310720, 2228224), (98, 1638401, 2228224)]),
            (r"x\par\leavevmode$$y$$ z",
             [(120, 1310720, 655360), (121, 15220520, 2228224), (122, 0, 3473408)]),
            (r"\hfil x", [(120, 15875348, 655360)]),
            (r"x\par\hfil y", [(120, 1310720, 655360), (121, 15875348, 1441792)]),
            # \vrule is a paragraph's first item, not a rule on the page.
            (r"\vrule height 2pt x", [(120, 1310720, 655360)]),
            (r"x\par\vrule width 2pt\par y",
             [(120, 1310720, 655360), (121, 1310720, 2228224)]),
        ],
    )
    def test_glyph_positions_match_miktex(self, body, miktex) -> None:
        assert _page1(body) == miktex


# ---------------------------------------------------------------------------
# §1091: new_graf inserts \everypar after the indent box (not on the
# resume after a display)
# ---------------------------------------------------------------------------


class TestEverypar:
    r"""``\everypar`` runs at every new paragraph, ahead of the token that started it."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # The \noindent paragraph is no longer void: it sets an A.
            (r"\everypar{A}x\par\noindent\par y",
             [(65, 1310720, 655360), (120, 1802241, 655360), (65, 0, 1441792),
              (65, 1310720, 2228224), (121, 1802241, 2228224)]),
            (r"\everypar{A}x\par y",
             [(65, 1310720, 655360), (120, 1802241, 655360), (65, 1310720, 1441792),
              (121, 1802241, 1441792)]),
            (r"\everypar{A}\noindent x", [(65, 0, 655360), (120, 491521, 655360)]),
            (r"\everypar{A}\indent x", [(65, 1310720, 655360), (120, 1802241, 655360)]),
            (r"\everypar{A}\noindent\hbox{x}", [(65, 0, 655360), (120, 491521, 655360)]),
            # The paragraph resumed after a display gets none (§1200).
            (r"\everypar{A}x$$y$$ z\par w",
             [(65, 1310720, 655360), (120, 1802241, 655360), (121, 15220520, 1441792),
              (122, 0, 2686976), (65, 1310720, 3473408), (119, 1802241, 3473408)]),
            # An \hbox in vertical mode starts no paragraph.
            (r"\everypar{A}\hbox{x}y",
             [(120, 0, 655360), (65, 1310720, 1441792), (121, 1802241, 1441792)]),
            # Inserted before the token that started the paragraph (§1090).
            (r"\everypar{A}\leavevmode y", [(65, 1310720, 655360), (121, 1802241, 655360)]),
            (r"\everypar{A}\hskip3pt x", [(65, 1310720, 655360), (120, 1998849, 655360)]),
            (r"\everypar{A}\hfil x", [(65, 1310720, 655360), (120, 16121109, 655360)]),
            (r"\everypar{A}\char`y", [(65, 1310720, 655360), (121, 1802241, 655360)]),
            (r"\everypar{A}\chardef\cc=`y \cc", [(65, 1310720, 655360), (121, 1802241, 655360)]),
            (r"\everypar{A}\ x", [(65, 1310720, 655360), (120, 2020694, 655360)]),
            (r"\everypar{A}\discretionary{}{}{} x",
             [(65, 1310720, 655360), (120, 2020694, 655360)]),
            (r"\everypar{A}$y$", [(65, 1310720, 655360), (121, 1802241, 655360)]),
            # The toks are read when the paragraph starts; emptying them inside
            # the first paragraph spares the second.
            (r"\everypar{A\everypar{}}x\par y",
             [(65, 1310720, 655360), (120, 1802241, 655360), (121, 1310720, 1441792)]),
            # Alignment cells are not paragraphs.
            (r"\everypar{A}\halign{#\cr x\cr}", [(120, 0, 655360)]),
        ],
    )
    def test_glyph_positions_match_miktex(self, body, miktex) -> None:
        assert _page1(body) == miktex

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\everypar{\message{[ep]}}x\par y\par", ["[ep]", "[ep]"]),
            (r"\everypar{\message{[ep]}}x$$y$$ z\par", ["[ep]"]),
            (r"\everypar{\message{[ep]}}\hbox{x}\par", []),
            (r"\everypar{\message{[ep]}}\noindent\par\indent\par", ["[ep]", "[ep]"]),
            (r"\everypar{\count200=5 }x\par\message{[c=\the\count200]}", ["[c=5]"]),
        ],
    )
    def test_messages_match_miktex(self, body, miktex) -> None:
        assert _messages(body) == miktex


# ---------------------------------------------------------------------------
# §1091: new_graf resets \prevgraf; §1200: a display adds 3
# ---------------------------------------------------------------------------


class TestPrevgraf:
    r"""``\the\prevgraf`` counts the lines of the last paragraph, plus 3 per display."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\message{[pg=\the\prevgraf]}", ["[pg=0]"]),
            (r"x\par y\par\message{[pg=\the\prevgraf]}", ["[pg=1]"]),
            (r"\parskip=5pt plus 1pt x\par y\par\indent\par\message{[pg=\the\prevgraf]}",
             ["[pg=1]"]),
            (r"\hsize=25pt\noindent aa\hfil\break b\par\message{[lines=\the\prevgraf]}",
             ["[lines=2]"]),
            (r"x$$y$$\par\message{[pg=\the\prevgraf]}", ["[pg=4]"]),
            (r"x$$y$$ z\par\message{[pg=\the\prevgraf]}", ["[pg=5]"]),
            (r"\noindent$$y$$\par\message{[pg=\the\prevgraf]}", ["[pg=3]"]),
            (r"\hsize=25pt\noindent aa\hfil\break b$$y$$ c\par\message{[pg=\the\prevgraf]}",
             ["[pg=6]"]),
            # Readable in horizontal mode: the enclosing vertical list's value.
            (r"x$$y$$\message{[pg=\the\prevgraf]}", ["[pg=4]"]),
            # An \hbox in vertical mode starts no paragraph.
            (r"x\par\hbox{y}\message{[pg=\the\prevgraf]}", ["[pg=1]"]),
        ],
    )
    def test_messages_match_miktex(self, body, miktex) -> None:
        assert _messages(body) == miktex

    def test_readme_group_completion_example(self) -> None:
        body = (
            r"\def\later{\message{[after=\the\count200]}}\count200=2"
            r"{\count200=7\aftergroup\later}"
            r"{\count200=1\global\count200=9\count200=4}"
            r"\message{[global=\the\count200]}"
            r"\hsize=25pt\noindent aa\hfil\break\break\par"
            r"\message{[lines=\the\prevgraf]}"
        )
        assert _messages(body) == ["[after=2]", "[global=9]", "[lines=3]"]
