r""" — plain's tie ``~`` and the control space ``\ `` ( amendment).

plain.tex defines the tie ``\def~{\penalty\@M \ }`` (line 555) and later the
accent ``\def\~#1{{\accent"7E #1}}`` (line 703).  Both used to share the macro
key ``"~"``, so every ``~`` ran the accent and crashed on its ``#1``.  Active
characters now have their own key and are expanded by the expander, so a tie
also works inside a box.  The tie ends in ``\ ``, which only became the real
control-space primitive once ``\^^I`` stopped being tokenized as ``\ ``
: it is the font's normal interword glue and ignores the space factor
(TeX §1045).

Every expected list is MiKTeX 24.4 ``tex`` + the DVI walker over its DVI:
``(char code, h)`` of each glyph on page 1, the folio excluded.
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


def _run(body: str) -> TeXJob:
    job = TeXJob(StringInputSource(body + r"\bye"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job._dvi = job.run()  # type: ignore[attr-defined]
    return job


def _glyph_h(body: str) -> list[tuple[int, int]]:
    """``(code, h)`` of every page-1 glyph but the folio for plain ``<body>\bye``."""
    dvi = _run(body)._dvi  # type: ignore[attr-defined]
    assert dvi is not None
    return [(c, h) for c, h, _v in walk_chars_with_positions(dvi, _tfm_width())[0]][:-1]


def _messages(body: str) -> list[str]:
    return [m for m in _run(body).messages if m.startswith("[")]


_O = ord("o")


class TestPlainTie:
    """ tests 1-7: the tie in paragraphs and boxes, next to the accent."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\noindent o ~ o", [(_O, 0), (_O, 983040)]),
            (r"\noindent o~o", [(_O, 0), (_O, 546134)]),
            # the tie's \ is a normal space even after a period (§1045)
            (
                r"\noindent Fig.~1",
                [(70, 0), (105, 427806), (103, 609851), (46, 937532), (49, 1338030)],
            ),
            # accent and tie side by side: \~ is the accent, ~ the tie
            (r"\noindent o \~o~o", [(_O, 0), (126, 546134), (_O, 546134), (_O, 1092268)]),
            (r"\noindent \~o o", [(126, 0), (_O, 0), (_O, 546134)]),
            # a tie inside a box
            (r"\noindent\hbox{o~o} o", [(_O, 0), (_O, 546134), (_O, 1092268)]),
            # the active space defined by \let\space
            (r"{\obeyspaces\noindent o  o}", [(_O, 218453), (_O, 983040)]),
        ],
    )
    def test_glyphs_at_miktex_positions(self, body: str, miktex: list[tuple[int, int]]) -> None:
        assert _glyph_h(body) == miktex

    def test_math_active_prime_still_typesets(self) -> None:
        # Guard: plain's ' is math-active, defined as an active character.
        # MiKTeX 24.4 width, including f's italic correction before the
        # prime superscript.
        assert _messages(r"\setbox0\hbox{$f'$}\dimen0=\wd0 \message{[\the\dimen0]}") == ["[8.77782pt]"]


class TestControlSpace:
    r"""``\ `` is the primitive, a normal space ( Component 4/5)."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\noindent o \kern1pt\ o", [(_O, 0), (_O, 830123)]),
            (r"\noindent o\kern1pt\ o", [(_O, 0), (_O, 611670)]),
            (r"\noindent o \penalty0\ o", [(_O, 0), (_O, 764587)]),
            (r"\noindent o \hskip0pt\ o", [(_O, 0), (_O, 764587)]),
            (r"\noindent o \vrule width 1pt\ o", [(_O, 0), (_O, 764587)]),
            (r"\noindent o\ \ o", [(_O, 0), (_O, 764587)]),
            # no sentence space after a period
            (r"\noindent x.\ o", [(120, 0), (46, 345886), (_O, 746384)]),
            # inside a box, after a number
            (r"\noindent o\hbox{o\penalty10000\ o} o", [(_O, 0), (_O, 327681), (_O, 873815), (_O, 1419949)]),
        ],
    )
    def test_glyphs_at_miktex_positions(self, body: str, miktex: list[tuple[int, int]]) -> None:
        assert _glyph_h(body) == miktex

    def test_control_space_is_not_a_macro_after_plain(self) -> None:
        # plain's \def\^^I{\ } and \def\^^M{\ } no longer land on \  itself
        # (MiKTeX 24.4 prints the same line)
        assert _messages(r"\message{[\meaning\ |\meaning\^^I|\meaning\^^M]}") == [
            r"[\ |macro:->\ |macro:->\ ]"
        ]

    def test_backquote_control_return_still_reads_13(self) -> None:
        assert _messages(r"\count1=`\^^M \message{[\the\count1]}") == ["[13]"]


def _glyph_h_or_hang(body: str, seconds: float = 20.0) -> list[tuple[int, int]]:
    """``_glyph_h`` in a daemon thread; fail instead of hanging the suite."""
    import threading

    result: dict[str, object] = {}

    def run() -> None:
        try:
            result["glyphs"] = _glyph_h(body)
        except BaseException as exc:  # re-raised in the test thread below
            result["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    assert not worker.is_alive(), f"job did not finish in {seconds}s: {body}"
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result["glyphs"]  # type: ignore[return-value]


class TestControlSpaceInVerticalLists:
    r"""``\ `` and ``~`` inside ``\vbox``/``\footnote`` ( review blockers 1-3).

    The vbox text-line scanner used to re-dispatch ``\ `` forever, and the
    vbox's vertical loop rejected a ``\ `` that a ``\penalty`` left behind.
    """

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\vbox{\noindent o\ o}", [(_O, 0), (_O, 546134)]),
            (r"\vtop{\noindent o\ o}", [(_O, 0), (_O, 546134)]),
            (
                r"\noindent o\footnote{*}{e.g.\ this} o",
                [
                    (_O, 0), (42, 327681), (_O, 873815), (42, 655359),
                    (101, 1310720), (46, 1601991), (103, 1784036), (46, 2111717),
                    (116, 2512215), (104, 2767078), (105, 3131168), (115, 3313213),
                ],
            ),
        ],
    )
    def test_glyphs_at_miktex_positions(self, body: str, miktex: list[tuple[int, int]]) -> None:
        assert _glyph_h_or_hang(body) == miktex

    def test_tie_in_a_footnote_typesets(self) -> None:
        # MiKTeX keeps "1" on the line (h 3813835); our vbox text line still
        # breaks at the tie's \penalty, so only the run up to the
        # tie and the glyph sequence are pinned here.
        glyphs = _glyph_h_or_hang(r"\noindent o\footnote{*}{See Fig.~1} o")
        assert [c for c, _h in glyphs] == [_O, 42, _O, 42, 83, 101, 101, 70, 105, 103, 46, 49]
        assert glyphs[:11] == [
            (_O, 0), (42, 327681), (_O, 873815), (42, 655359), (83, 1310720), (101, 1674810),
            (101, 1966081), (70, 2475805), (105, 2903611), (103, 3085656), (46, 3413337),
        ]

    @pytest.mark.parametrize(
        ("body", "glyphs"),
        [
            (r"\setbox0\vbox{\hsize=100pt \noindent o\penalty0\ o}\box0", 2),
            (r"\setbox0\vbox{\hsize=100pt \ o}\box0", 1),
            (r"\vbox{\noindent o~o}", 2),
        ],
    )
    def test_control_space_left_in_vertical_mode_starts_text(self, body: str, glyphs: int) -> None:
        # §1090: \  in vertical mode starts a paragraph.  Positions differ
        # from MiKTeX only by the vbox text-line model.
        assert [c for c, _h in _glyph_h_or_hang(body)] == [_O] * glyphs
