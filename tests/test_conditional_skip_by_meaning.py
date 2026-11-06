r""" — conditional branches are skipped by meaning (TeX §494).

``pass_text`` classifies the tokens of a skipped branch by ``cur_cmd``: a
``\let`` or ``\newif`` alias of a conditional nests, ``\let\myfi=\fi`` ends
the branch, and a macro whose name starts with ``if`` is not a conditional.
Plain's ``\endinsert`` depends on it: with ``\@midtrue`` its ``\else`` branch
holds ``\ifp@ge … \fi}`` and the skip used to stop at that inner ``\fi``,
letting ``}`` close the ``\begingroup`` of ``\@ins``.

The regression pins cover the deferred ``\vbox\bgroup`` layers that
delivered and the implicit-``\par`` witness.

Every expected list is the MiKTeX 24.4 page-1 glyph ``(code, h, v)`` in sp
without the folio (probe a reference probe, 2026-10-14).
"""

from __future__ import annotations

import pytest

from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _run, _tfm_width


def _glyphs(body: str) -> list[tuple[int, int, int]]:
    """``(code, h, v)`` of every page-1 glyph but the folio for plain ``<body>\\bye``."""
    dvi = _run(body)._dvi  # type: ignore[attr-defined]
    assert dvi is not None
    return [tuple(g) for g in walk_chars_with_positions(dvi, _tfm_width())[0]][:-1]


_X, _Y, _Z = ord("x"), ord("y"), ord("z")
_A, _B, _C = ord("a"), ord("b"), ord("c")


class TestSkipByMeaning:
    """ Testing 1: the skip loops read the meaning, not the name."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            pytest.param(
                r"\let\ifa=\iffalse \noindent\iftrue x\else\ifa\else\fi}\fi z",
                [(_X, 0, 655360), (_Z, 345886, 655360)],
                id="let-alias-nested-in-skipped-else",
            ),
            pytest.param(
                r"\newif\ifa \noindent\iftrue x\else\ifa q\fi}\fi z",
                [(_X, 0, 655360), (_Z, 345886, 655360)],
                id="newif-alias-nested-in-skipped-else",
            ),
            pytest.param(
                r"\newif\ifa \noindent\iffalse x\ifa q\else r\fi}\else y\fi z",
                [(_Y, 0, 655360), (_Z, 345886, 655360)],
                id="newif-alias-nested-in-false-branch",
            ),
            pytest.param(
                r"\let\b=\iffalse \let\a=\b \noindent\iftrue x\else\a\fi}\fi z",
                [(_X, 0, 655360), (_Z, 345886, 655360)],
                id="alias-chain",
            ),
            pytest.param(
                r"\let\myfi=\fi \noindent\iffalse x\myfi z",
                [(_Z, 0, 655360)],
                id="let-fi-ends-false-branch",
            ),
            pytest.param(
                r"\let\myelse=\else \noindent\iffalse x\myelse y\fi z",
                [(_Y, 0, 655360), (_Z, 345886, 655360)],
                id="let-else-selects-false-branch",
            ),
            pytest.param(
                r"\def\iffoo{}\noindent\iffalse \iffoo\fi z",
                [(_Z, 0, 655360)],
                id="macro-named-if-not-counted",
            ),
            pytest.param(
                r"\let\ifa=\iffalse \noindent\ifcase1 \ifa\or}\fi x\or y\fi z",
                [(_Y, 0, 655360), (_Z, 345886, 655360)],
                id="alias-in-skipped-ifcase-branch",
            ),
        ],
    )
    def test_matches_miktex(self, body: str, miktex: list[tuple[int, int, int]]) -> None:
        assert _glyphs(body) == miktex


class TestPlainInserts:
    r""" Testing 2: plain ``\midinsert``/``\topinsert`` after the fix."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            pytest.param(
                r"\parskip=5pt x\par\midinsert a\endinsert y\par z",
                [(_X, 1310720, 655360), (_A, 1310720, 2228224),
                 (_Y, 1310720, 4128768), (_Z, 1310720, 5242880)],
                id="midinsert-after-par",
            ),
            pytest.param(
                r"x \midinsert a\endinsert y\par z",
                [(_X, 1310720, 655360), (_A, 1310720, 2228224),
                 (_Y, 1310720, 3801088), (_Z, 1310720, 4587520)],
                id="midinsert-in-paragraph",
            ),
            pytest.param(
                r"\parskip=5pt x\par\topinsert a\endinsert y\par z",
                [(_A, 1310720, 282168), (_X, 1310720, 1723960),
                 (_Y, 1310720, 2838072), (_Z, 1310720, 3952184)],
                id="topinsert",
            ),
        ],
    )
    def test_matches_miktex(self, body: str, miktex: list[tuple[int, int, int]]) -> None:
        assert _glyphs(body) == miktex


class TestDeferredVboxRegressionPins:
    r""" Testing 3:'s reported layers, delivered by."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            pytest.param(
                r"\vbox\bgroup\hbox{a}\hbox{b}\egroup",
                [(_A, 0, 282168), (_B, 0, 1068600)],
                id="vbox-bgroup-interline-glue",
            ),
            pytest.param(
                r"\vbox\bgroup\hbox{a}\vskip3pt\hbox{b}\egroup",
                [(_A, 0, 282168), (_B, 0, 1265208)],
                id="vbox-bgroup-vskip",
            ),
            pytest.param(
                r"\vtop\bgroup\hbox{a}\hbox{b}\egroup",
                [(_A, 0, 655360), (_B, 0, 1441792)],
                id="vtop-bgroup",
            ),
            pytest.param(
                r"\setbox0\vbox\bgroup\hbox{a}\hbox{b}\egroup\box0",
                [(_A, 0, 282168), (_B, 0, 1068600)],
                id="setbox-vbox-bgroup",
            ),
            pytest.param(
                r"\vbox\bgroup\baselineskip=20pt\hbox{a}\hbox{b}\egroup",
                [(_A, 0, 282168), (_B, 0, 1592888)],
                id="vbox-bgroup-local-baselineskip",
            ),
            pytest.param(
                r"\vbox\bgroup\vbox\bgroup\hbox{a}\hbox{b}\egroup\hbox{c}\egroup",
                [(_A, 0, 282168), (_B, 0, 1068600), (_C, 0, 1855032)],
                id="nested-deferred",
            ),
            pytest.param(
                r"\vbox\bgroup a\vskip3pt b\egroup",
                [(_A, 1310720, 282168), (_B, 1310720, 1265208)],
                id="vbox-bgroup-text",
            ),
            pytest.param(
                r"\parskip=5pt x \vbox\bgroup a\vskip3pt b\egroup\ y\par z",
                [(_X, 1310720, 1592888), (_A, 3112961, 282168), (_B, 3112961, 1592888),
                 (_Y, 0, 2379320), (_Z, 1310720, 3493432)],
                id="vbox-bgroup-text-in-paragraph",
            ),
            pytest.param(
                r"$x\vcenter\bgroup\hbox{a}\hbox{b}\egroup y$",
                [(_X, 1310720, 698140), (_A, 1685276, 282168), (_B, 1685276, 1068600),
                 (_Y, 2049366, 698140)],
                id="vcenter-bgroup",
            ),
            pytest.param(
                r"\noindent x\setbox0\vbox\bgroup\noindent\begingroup y\endgroup\egroup\box0 z",
                [(_X, 0, 655360), (_Y, 345886, 655360), (_Z, 31131749, 655360)],
                id="tex352-implicit-par-vbox",
            ),
            pytest.param(
                r"\noindent x\setbox0\vtop\bgroup\noindent\begingroup y\endgroup\egroup\box0 z",
                [(_X, 0, 655360), (_Y, 345886, 655360), (_Z, 31131749, 655360)],
                id="tex352-implicit-par-vtop",
            ),
            pytest.param(
                r"\noindent x\setbox0\vbox{\noindent\begingroup y\endgroup}\box0 z",
                [(_X, 0, 655360), (_Y, 345886, 655360), (_Z, 31131749, 655360)],
                id="tex352-implicit-par-eager",
            ),
        ],
    )
    def test_matches_miktex(self, body: str, miktex: list[tuple[int, int, int]]) -> None:
        assert _glyphs(body) == miktex
