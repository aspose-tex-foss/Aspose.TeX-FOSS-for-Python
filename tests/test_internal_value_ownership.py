r"""readers consult the live owner of every internal value.

Every expected value is a MiKTeX 24.4 measurement recorded by
a reference probe (``probe_baseline.json``); none is computed by hand.
"""
from __future__ import annotations

import datetime
import struct
import warnings

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob, TeXOptions
from aspose_tex._engine.group import GroupStack
from aspose_tex._engine.named_parameters import (
    NamedParameterRegistry,
    _register_appendix_a,
)
from aspose_tex._engine.registers import RegisterSet
from aspose_tex._input.token import ControlSequenceToken, PrimitiveRefToken
from aspose_tex.exceptions import EngineError
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _tfm_width


def _job(body: str) -> tuple[list[str], bytes]:
    job = TeXJob(StringInputSource(body + "\n\\bye\n"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = job.run()
    return [m for m in job.messages if m.startswith("[")], dvi


def _messages(body: str) -> list[str]:
    return _job(body)[0]


def _glyphs(body: str) -> list[tuple[int, int, int]]:
    """``(code, h, v)`` of every page-1 glyph but the folio."""
    return [tuple(g) for g in walk_chars_with_positions(_job(body)[1], _tfm_width())[0][:-1]]


def _first_bop(dvi: bytes) -> list[int]:
    at = 15 + dvi[14]
    while dvi[at] in (138, 243):  # nop, fnt_def1
        at += 1 if dvi[at] == 138 else 16 + dvi[at + 14] + dvi[at + 15]
    assert dvi[at] == 139
    return list(struct.unpack(">10i", dvi[at + 1: at + 41]))


# ---------------------------------------------------------------------------
# D1: the clock is four integer parameters, \count0..9 are free
# ---------------------------------------------------------------------------


class TestClockParameters:
    """``\\year``/``\\month``/``\\day``/``\\time`` no longer alias ``\\count0..3``."""

    def test_count_registers_after_plain(self) -> None:
        body = r"\message{[\the\count0,\the\count1,\the\count2,\the\count3,\the\count9]}"
        assert _messages(body) == ["[1,0,0,0,0]"]

    def test_clock_survives_plain(self) -> None:
        body = (r"\message{[\ifnum\year>2000 Y\fi\ifnum\month<13 M\fi"
                r"\ifnum\day<32 D\fi\ifnum\time<1441 T\fi]}")
        assert _messages(body) == ["[YMDT]"]

    def test_count1_does_not_change_month(self) -> None:
        body = r"\count9=\month \count1=77 \message{[\ifnum\month=\count9 same\fi,\the\count1]}"
        assert _messages(body) == ["[same,77]"]

    def test_month_does_not_change_count1(self) -> None:
        body = r"\count9=\count1 \month=3 \message{[\the\month,\ifnum\count1=\count9 same\fi]}"
        assert _messages(body) == ["[3,same]"]

    def test_local_month_is_restored(self) -> None:
        body = r"\count9=\month {\month=3 }\message{[\ifnum\month=\count9 restored\fi]}"
        assert _messages(body) == ["[restored]"]

    def test_global_month_survives_group(self) -> None:
        assert _messages(r"{\global\month=3 }\message{[\the\month]}") == ["[3]"]

    def test_count_registers_scope_independently(self) -> None:
        body = r"{\count1=5 \global\count2=3 }\message{[\the\count1,\the\count2]}"
        assert _messages(body) == ["[0,3]"]

    def test_year_arithmetic(self) -> None:
        body = r"\year=1999 \advance\year by 1 \edef\x{\the\year}\message{[\x]}"
        assert _messages(body) == ["[2000]"]

    def test_registry_seeds_from_injected_clock(self) -> None:
        group_stack = GroupStack()
        regs = RegisterSet(group_stack=group_stack)
        named = NamedParameterRegistry(regs, group_stack)
        _register_appendix_a(named, now=datetime.datetime(2026, 10, 13, 17, 32))
        values = {
            name: regs.get_count(named.lookup(name).slot, _internal=True)
            for name in ("year", "month", "day", "time")
        }
        assert values == {"year": 2026, "month": 10, "day": 13, "time": 1052}
        assert [regs.get_count(i) for i in range(4)] == [0, 0, 0, 0]

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            ("x", [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
            (r"\count1=7 \count9=-2 x", [1, 7, 0, 0, 0, 0, 0, 0, 0, -2]),
        ],
    )
    def test_dvi_bop_carries_count_registers(self, body: str, miktex: list[int]) -> None:
        assert _first_bop(_job(body)[1]) == miktex


# ---------------------------------------------------------------------------
# D4: paragraph-shape values are read from their owners
# ---------------------------------------------------------------------------


class TestParagraphShapeReaders:
    r"""``\hangindent``/``\hangafter`` are named parameters, ``\parshape`` reads its owner."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\hangindent=2pt\message{[\the\hangindent]}", ['[2.0pt]']),
            (r"\hangafter=2\message{[\the\hangafter]}", ['[2]']),
            (r"\parshape=2 1pt 10pt 2pt 11pt\message{[\the\parshape]}", ['[2]']),
            (r"{\hangindent=2pt}\message{[\the\hangindent]}", ['[0.0pt]']),
            (r"{\global\hangafter=3}\message{[\the\hangafter]}", ['[3]']),
            (r"{\global\parshape=1 1pt 2pt}\message{[\the\parshape]}", ['[1]']),
            (r"\hangindent=2pt x\par\message{[\the\hangindent]}", ['[0.0pt]']),
            (r"\hangindent=2pt\par\message{[\the\hangindent]}", ['[0.0pt]']),
            (r"\hangafter=3 \parshape=1 1pt 2pt \par\message{[\the\hangafter,\the\parshape]}", ['[1,0]']),
            (r"\hangindent=2pt\setbox0\vbox{\message{[\the\hangindent]}}\message{[\the\hangindent]}",
             ['[0.0pt]', '[2.0pt]']),
            (r"\hangindent=2pt\setbox0\hbox{\message{[\the\hangindent]}}", ['[2.0pt]']),
            (r"\parshape=1 1pt 2pt \count1=\parshape \message{[\the\count1]}", ['[1]']),
            (r"\hangindent=2pt\dimen0=\hangindent\message{[\the\dimen0]}", ['[2.0pt]']),
            (r"\hangindent=3pt\advance\hangindent by 1pt\message{[\the\hangindent]}", ['[4.0pt]']),
            (r"\hangafter=-2 \multiply\hangafter by 3 \message{[\the\hangafter]}", ['[-6]']),
            (r"\hangindent=2pt\edef\x{\the\hangindent}\message{[\x]}", ['[2.0pt]']),
            (r"\hangindent=2pt\vbox{\message{[\the\hangindent]}}\message{[\the\hangindent]}", ['[0.0pt]', '[2.0pt]']),
            (r"\noindent x\hangindent=2pt $\message{[\the\hangindent]}$\par", ['[2.0pt]']),
        ],
    )
    def test_reader_matches_miktex(self, body: str, miktex: list[str]) -> None:
        assert _messages(body) == miktex

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # §1145: a display breaks the lines but keeps the shape for the rest
            (r"\hangindent=2pt x$$y$$\message{[\the\hangindent]}z\par\message{[\the\hangindent]}",
             ["[2.0pt]", "[0.0pt]"]),
            # §785: \noalign of an \halign; §787: a \valign cell
            (r"\hangindent=2pt\halign{#\cr x\cr\noalign{\global\dimen1=\hangindent}y\cr}"
             r"\message{[\the\dimen1,\the\hangindent]}", ["[0.0pt,2.0pt]"]),
            # MiKTeX also reports the overfull cell line (`[][] |`, §8)
            (r"\hangindent=2pt\valign{#\cr \global\dimen1=\hangindent x\cr}"
             r"\message{[\the\dimen1,\the\hangindent]}", ["[0.0pt,2.0pt]", "[][] |"]),
            # §1083 deferred-close box, §1099 \vadjust, §1167 \vcenter
            (r"\hangindent=2pt\setbox0\vbox\bgroup\global\dimen1=\hangindent\egroup"
             r"\message{[\the\dimen1,\the\hangindent]}", ["[0.0pt,2.0pt]"]),
            (r"\hangindent=2pt\noindent x\vadjust{\global\dimen1=\hangindent}\par\message{[\the\dimen1]}",
             ["[0.0pt]"]),
            (r"\hangindent=2pt$\vcenter{\global\dimen1=\hangindent}$\message{[\the\dimen1,\the\hangindent]}",
             ["[0.0pt,2.0pt]"]),
        ],
    )
    def test_normal_paragraph_contexts(self, body: str, miktex: list[str]) -> None:
        assert _messages(body) == miktex


# ---------------------------------------------------------------------------
# D2: one current binding per control-sequence name
# ---------------------------------------------------------------------------


class TestOneMeaningPerName:
    r"""Macro, register alias, constant and font bindings replace each other."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\chardef\c=65 \setbox0\hbox{\c}\message{[\the\wd0]}", ['[7.50002pt]']),
            (r"\chardef\c=65 \message{[\meaning\c]}", ['[\\char"41]']),
            (r"\countdef\k=5 \message{[\meaning\k]}", ['[\\count5]']),
            (r"\message{[\meaning\tenrm]}", ['[select font cmr10]']),
            (r"\font\big=cmr10 at 12pt \message{[\meaning\big]}", ['[select font cmr10 at 12.0pt]']),
            (r'\mathchardef\q="1234 \message{[\meaning\q]}', ['[\\mathchar"1234]']),
            # a released font binding is hidden for the group and comes back
            (r"\font\q=cmr10 {\chardef\q=65 \message{[\meaning\q]}}\message{[\meaning\q]}",
             ['[\\char"41]', "[select font cmr10]"]),
            (r"\font\q=cmr10 \countdef\q=5 \q=3 \message{[\the\count5,\meaning\q]}", ["[3,\\count5]"]),
            (r"\font\q=cmr10 {\global\def\q{m}}\message{[\meaning\q]}", ["[macro:->m]"]),
            (r"\countdef\q=5 {\def\q{m}\q}\q=3 \message{[\the\count5]}", ["[3]"]),
            (r"\chardef\q=65 \setbox0\hbox{$\q$}\message{[\the\wd0]}", ["[7.50002pt]"]),
            (r'\mathchardef\q="141 \setbox0\hbox{$\q$}\message{[\the\wd0]}', ["[7.50002pt]"]),
            (r"\dimendef\q=3 \message{[\meaning\q]}\skipdef\q=4 \message{[\meaning\q]}"
             r"\toksdef\q=5 \message{[\meaning\q]}\muskipdef\q=6 \message{[\meaning\q]}",
             ['[\\dimen3]', '[\\skip4]', '[\\toks5]', '[\\muskip6]']),
            (r"\chardef\qa=5 \chardef\qb=5 \message{[\ifx\qa\qb T\else F\fi]}", ['[T]']),
            (r"\chardef\qa=5 \mathchardef\qb=5 \message{[\ifx\qa\qb T\else F\fi]}", ['[F]']),
            (r"\countdef\qa=10 \countdef\qb=10 \message{[\ifx\qa\qb T\else F\fi]}", ['[T]']),
            (r"\countdef\qa=10 \dimendef\qb=10 \message{[\ifx\qa\qb T\else F\fi]}", ['[F]']),
            (r"\font\fa=cmr10 \font\fb=cmr10 \message{[\ifx\fa\fb T\else F\fi]}", ['[T]']),
            (r"\font\fa=cmr10 \font\fb=cmr10 at 12pt \message{[\ifx\fa\fb T\else F\fi]}", ['[F]']),
            (r"\let\q=\tenrm \message{[\meaning\q,\ifx\q\tenrm T\else F\fi]}", ['[select font cmr10,T]']),
            (r"\def\q{m}{\chardef\q=65 \message{[\meaning\q]}}\message{[\meaning\q]}",
             ['[\\char"41]', '[macro:->m]']),
            (r"\def\q{m}{\global\chardef\q=66 }\message{[\meaning\q]}", ['[\\char"42]']),
            (r"\countdef\q=7 \def\q{m}\message{[\meaning\q]}", ['[macro:->m]']),
            (r"\def\q{m}\countdef\q=7 \q=4 \message{[\the\count7,\meaning\q]}", ['[4,\\count7]']),
            (r"\def\q{m}{\countdef\q=7 }\message{[\meaning\q]}", ['[macro:->m]']),
            (r"\def\q{m}\font\q=cmr10 \message{[\meaning\q]}", ['[select font cmr10]']),
            (r"\def\q{m}{\font\q=cmr10 }\message{[\meaning\q]}", ['[macro:->m]']),
            (r"\font\q=cmr10 \def\q{m}\message{[\meaning\q]}", ['[macro:->m]']),
            (r"\countdef\a=5 \let\b=\a \countdef\a=6 \b=9 \message{[\the\count5,\the\count6,\meaning\b]}",
             ['[9,0,\\count5]']),
            (r"\chardef\a=65 \let\b=\a \chardef\a=66 \message{[\meaning\b]}", ['[\\char"41]']),
            (r"\chardef\c=65 \count1=\c \message{[\the\count1]}", ['[65]']),
            (r"\countdef\c=5 \count5=3 \let\c=\relax \message{[\meaning\c]}", ['[\\relax]']),
        ],
    )
    def test_meaning_matches_miktex(self, body: str, miktex: list[str]) -> None:
        assert _messages(body) == miktex

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\chardef\c=65 \noindent\c", [(65, 0, 655360)]),
            (r"\def\q{m}\chardef\q=65 \noindent\q", [(65, 0, 655360)]),
            (r"\chardef\q=65 \def\q{m}\noindent\q", [(109, 0, 655360)]),
        ],
    )
    def test_glyphs_match_miktex(self, body: str, miktex: list[tuple[int, int, int]]) -> None:
        assert _glyphs(body) == miktex


# ---------------------------------------------------------------------------
# D3: a \let of a primitive holds it; implicit paragraph ends run \par
# ---------------------------------------------------------------------------


class TestPrimitiveMeanings:
    r"""``\let\endgraf=\par`` survives ``\def\par``; ``\vskip`` & co. insert ``\par``."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\def\par{\endgraf}x\par y", [(120, 1310720, 655360), (121, 1310720, 1441792)]),
            (r"\def\par{\endgraf\kern7pt}x\par y", [(120, 1310720, 655360), (121, 1310720, 1900544)]),
            (r"\let\mypar=\par \def\par{\mypar}x\par y", [(120, 1310720, 655360), (121, 1310720, 1441792)]),
            (r"\let\mypar=\par \def\par{\mypar\kern7pt}x\vskip3pt y",
             [(120, 1310720, 655360), (121, 1310720, 2097152)]),
            (r"\let\mypar=\par \def\par{\mypar\kern7pt}x\hrule y", [(120, 1310720, 655360), (121, 1310720, 1422494)]),
            (r"\parskip=5pt \def\par{\endgraf\kern7pt}x\vskip3pt y",
             [(120, 1310720, 655360), (121, 1310720, 2424832)]),
            (r"\def\par{\endgraf\kern7pt}x\vfil y", [(120, 1310720, 655360), (121, 1310720, 1900544)]),
            (r"\setbox0\vbox{z}\def\par{\endgraf\kern7pt}x\unvbox0 y",
             [(120, 1310720, 655360), (122, 1310720, 1396280), (121, 1310720, 2182712)]),
            (r"\def\par{\endgraf\kern7pt}x\halign{#\cr a\cr}y",
             [(120, 1310720, 655360), (97, 0, 1900544), (121, 1310720, 2686976)]),
            (r"\def\par{\endgraf\kern7pt}x\end", [(120, 1310720, 655360)]),
            (r"\def\par{\endgraf\kern7pt}\setbox0\vbox{x\vskip1pt y}\box0",
             [(120, 1310720, 282168), (121, 1310720, 1592888)]),
        ],
    )
    def test_glyphs_match_miktex(self, body: str, miktex: list[tuple[int, int, int]]) -> None:
        assert _glyphs(body) == miktex

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\let\a=\par \message{[\meaning\a]}", ['[\\par]']),
            (r"\let\a=\par {\def\par{z}\message{[\meaning\a,\ifx\a\endgraf T\else F\fi,\ifx\a\par T\else F\fi]}}",
             ['[\\par,T,F]']),
            (r"\let\a=\cr \def\cr{z}\message{[\meaning\a,\meaning\endline]}", ['[\\cr,\\cr]']),
            (r"\let\a=\relax \def\relax{x}\message{[\meaning\a]}", ['[\\relax]']),
            (r"\let\a=\hbox \def\hbox{}\setbox0\a{xx}\message{[\the\wd0]}", ['[10.5556pt]']),
            (r"\let\t=\the \def\the{}\count1=3 \message{[\t\count1]}", ['[3]']),
            (r"\let\a=\ifx \def\ifx{}\message{[\a\a\a T\else F\fi]}", ['[T]']),
            (r"\let\a=\par \let\b=\par \message{[\ifx\a\b T\else F\fi,\ifx\a\par T\else F\fi]}", ['[T,T]']),
            (r"{\let\a=\par \def\par{}}\message{[\meaning\a]}", ['[undefined]']),
        ],
    )
    def test_meaning_matches_miktex(self, body: str, miktex: list[str]) -> None:
        assert _messages(body) == miktex

    def test_expandable_alias_still_expands(self) -> None:
        # MiKTeX prints [x] twice: \a is \expandafter after \def\expandafter{}.
        body = r"\let\a=\expandafter \def\expandafter{}\def\x{[x]}\def\y{\x}\message{\a\x\y}"
        assert _messages(body) == ["[x][x]"]

    def test_par_that_never_ends_the_paragraph_raises(self) -> None:
        # TeX loops forever here; the engine stops with a diagnostic (the
        # expansion-depth limit or the head_for_vmode guard, whichever is first).
        with pytest.raises(EngineError, match=r"\\par"):
            _messages(r"\def\par{}x\vskip1pt y")
        with pytest.raises(EngineError, match="did not end the paragraph"):
            _messages(r"\let\par=\relax x\vskip1pt y")

    def test_primitive_ref_token_is_not_the_plain_token(self) -> None:
        assert PrimitiveRefToken("par") != ControlSequenceToken("par")
        assert isinstance(PrimitiveRefToken("par"), ControlSequenceToken)


# ---------------------------------------------------------------------------
# D5: math nodes frame an inline formula
# ---------------------------------------------------------------------------


class TestClosingMathBoundary:
    r"""After ``$…$`` the list tail is the math-off node, not the formula's glue."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\noindent $\mskip2mu$\message{[\the\lastskip]}", ['[0.0pt]']),
            (r"\noindent $\kern2pt$\message{[\the\lastkern]}", ['[0.0pt]']),
            (r"\noindent $\penalty7$\message{[\the\lastpenalty]}", ['[0]']),
            (r"\noindent x\kern3pt$ $\message{[\the\lastkern]}", ['[0.0pt]']),
            (r"\noindent x\kern3pt$$ $$\message{[\the\lastkern]}", ['[0.0pt]']),
            (r"\setbox0\hbox{$\kern2pt$\message{[\the\lastkern]}}", ['[0.0pt]']),
            (r"\setbox0\hbox{$\kern2pt$\unkern}\message{[\the\wd0]}", ['[2.0pt]']),
            (r"\setbox0\hbox{$\hskip2pt$\unskip}\message{[\the\wd0]}", ['[2.0pt]']),
            (r"\setbox0\hbox{\mathsurround=1pt $\kern2pt$}\message{[\the\wd0]}", ['[4.0pt]']),
            (r"\setbox0\hbox{\mathsurround=1pt $\kern2pt$\unkern}\message{[\the\wd0]}", ['[4.0pt]']),
            (r"\setbox0\hbox{\mathsurround=1pt $ $\message{[\the\lastkern]}}\message{[\the\wd0]}",
             ['[0.0pt]', '[2.0pt]']),
            (r"\setbox0\hbox{x\hskip3pt$ $\unskip}\message{[\the\wd0]}", ['[8.2778pt]']),
            (r"\setbox0\hbox{$x$\message{[\the\lastskip,\the\lastkern,\the\lastpenalty]}}", ['[0.0pt,0.0pt,0]']),
            (r"\setbox0\vbox{\noindent $\mskip2mu$\message{[\the\lastskip]}}", ['[0.0pt]']),
            (r"\setbox0\hbox{$\hbox{$\mskip2mu$\message{[\the\lastskip]}}$}", ['[0.0pt]']),
        ],
    )
    def test_tail_matches_miktex(self, body: str, miktex: list[str]) -> None:
        assert _messages(body) == miktex

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            (r"\noindent\mathsurround=2pt a$x$b", [(97, 0, 655360), (120, 458753, 655360), (98, 964381, 655360)]),
            (r"\hsize=60pt \mathsurround=3pt \noindent aaa bbb $x$ ccc ddd eee fff ggg",
             [
                 (97, 0, 655360), (97, 327681, 655360), (97, 655362, 655360),
                 (98, 1128678, 655360), (98, 1492768, 655360),
                 (98, 1856858, 655360), (120, 2563191, 655360), (99, 3279990, 655360), (99, 3571261, 655360),
                 (99, 3862532, 655360), (100, 0, 1441792), (100, 364090, 1441792), (100, 728180, 1441792),
                 (101, 1237905, 1441792),
                 (101, 1529176, 1441792), (101, 1820447, 1441792), (11, 2257353, 1441792), (102, 2639648, 1441792),
                 (103, 2985533, 1441792), (103, 3313214, 1441792), (103, 3640895, 1441792),
             ]),
        ],
    )
    def test_glyphs_match_miktex(self, body: str, miktex: list[tuple[int, int, int]]) -> None:
        assert _glyphs(body) == miktex


class TestMathNodeUnits:
    """MathNode in packing and line breaking (§866, §879)."""

    def test_math_off_before_glue_is_a_breakpoint(self) -> None:
        from aspose_tex._engine.linebreak import _is_legal_breakpoint
        from aspose_tex._engine.nodes import CharNode, GlueNode, MathNode
        from aspose_tex._engine.registers import Glue, GlueOrder

        glue = GlueNode(Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
        nodes = [MathNode(0, False), CharNode(120, "tenrm"), MathNode(0, True), glue, CharNode(98, "tenrm")]
        assert _is_legal_breakpoint(nodes, 2)
        assert not _is_legal_breakpoint(nodes, 3)  # glue right after a math node (§868)
        assert not _is_legal_breakpoint(nodes, 0)  # math-on

    def test_math_nodes_are_discarded_at_a_line_start(self) -> None:
        from aspose_tex._engine.linebreak import _line_starts
        from aspose_tex._engine.nodes import CharNode, MathNode

        nodes = [CharNode(97, "tenrm"), MathNode(0, True), MathNode(0, False), CharNode(120, "tenrm")]
        assert _line_starts(nodes)[1] == 3

    def test_hpack_counts_mathsurround(self) -> None:
        from aspose_tex._engine.box_builder import _measure_hlist
        from aspose_tex._engine.nodes import MathNode
        from aspose_tex._fonts.font_manager import FontManager

        width, _h, _d = _measure_hlist([MathNode(65536, False), MathNode(65536, True)], FontManager())
        assert width == 131072
