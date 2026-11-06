r"""``\ifx`` compares meanings, not tokens (TeX §507) —.

Every expected line is MiKTeX 24.4 plain ``\message`` output of the same input.
"""
from __future__ import annotations

import warnings

import pytest

from aspose_tex import TeXJob, TeXOptions
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.registers import RegisterSet
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice
from tests.test_expansion import chars, expand

_IFX = r"\message{[\ifx a\next T\else F\fi]}"
_WIDTH = r"\dimen0=\wd0 \message{[\the\dimen0]}"


def _plain_messages(body: str) -> list[str]:
    job = TeXJob(StringInputSource(body + r"\bye"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job.run()
    return [m for m in job.messages if m.startswith("[")]


class TestIfxCharAgainstLetChar:
    """A character and a control sequence ``\\let`` to it have one meaning."""

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            (r"\let\next=a " + _IFX, "[T]"),
            (r"\let\next=a \message{[\ifx\next a T\else F\fi]}", "[ T]"),
            (r"\let\next=a \message{[\ifx b\next T\else F\fi]}", "[F]"),
            # \string a is the same character with catcode 12: a different meaning
            (r"\let\next=a \message{[\expandafter\ifx\string a\next T\else F\fi]}", "[F]"),
            (r"\let\x=a \let\y=a \message{[\ifx\x\y T\else F\fi]}", "[T]"),
            (r"\def\t{" + _IFX + r"}\futurelet\next\t a", "[T]"),
        ],
        ids=["let", "let-reversed", "other-char", "other-catcode", "two-aliases", "futurelet"],
    )
    def test_paragraph(self, body: str, expected: str) -> None:
        assert _plain_messages(body) == [expected]

    @pytest.mark.parametrize(
        "body",
        [
            r"\setbox0\hbox{\let\next=a " + _IFX + "}",
            r"\setbox0\vbox{\let\next=a " + _IFX + "}",
            r"\let\next=a \edef\r{\ifx a\next T\else F\fi}\message{[\r]}",
            r"$\let\next=a " + _IFX + "$",
        ],
        ids=["hbox", "vbox", "edef", "math"],
    )
    def test_other_contexts(self, body: str) -> None:
        assert _plain_messages(body) == ["[T]"]

    def test_bare_expander(self) -> None:
        tokens = expand(r"\let\next=a\ifx a\next yes\else no\fi")
        letters = [t for t in tokens if t.catcode == Catcode.LETTER]
        assert chars(letters) == "yes"


class TestIfxAliasChains:
    def test_let_to_a_primitive_equals_the_primitive(self) -> None:
        assert _plain_messages(r"\let\x=\relax \message{[\ifx\x\relax T\else F\fi]}") == ["[T]"]

    def test_two_primitives_differ(self) -> None:
        assert _plain_messages(r"\message{[\ifx\relax\par T\else F\fi]}") == ["[F]"]

    def test_undefined_names_are_equal(self) -> None:
        assert _plain_messages(r"\message{[\ifx\zzqa\zzqb T\else F\fi]}") == ["[T]"]

    def test_undefined_differs_from_relax(self) -> None:
        assert _plain_messages(r"\message{[\ifx\zzqa\relax T\else F\fi]}") == ["[F]"]


class TestCsHasMeaning:
    r"""The interpreter's ``undefined_cs`` answer, asked without executing."""

    @pytest.fixture(scope="class")
    def interp(self) -> TeXInterpreter:
        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(r"\countdef\mycount=5 \chardef\mychar=65 \font\myfont=cmr10 "),
            DviDevice(),
        )
        return interp

    @pytest.mark.parametrize(
        "name",
        ["relax", "par", "hbox", "over", "mathchoice", "count", "advance", "mychar",
         "mycount", "myfont", "hsize", "pagegoal"],
    )
    def test_known_names(self, interp: TeXInterpreter, name: str) -> None:
        assert interp.cs_has_meaning(name)

    def test_unknown_name(self, interp: TeXInterpreter) -> None:
        assert not interp.cs_has_meaning("zzqa")

    def test_register_has_command_does_not_execute(self) -> None:
        regs = RegisterSet()
        regs.define_alias("pageno", "count", 0)
        assert regs.has_command("count")
        assert regs.has_command("mathchardef")
        assert regs.has_command("pageno")
        assert not regs.has_command("zzqa")


class TestPlainPrimes:
    r"""plain's ``\pr@m@s`` tests ``\ifx'\next`` after ``\futurelet\next``."""

    @pytest.mark.parametrize(
        ("formula", "width"),
        [
            ("f''", "[11.08337pt]"),
            ("f''_{a\\,b}", "[14.6159pt]"),
            ("f'''", "[13.38893pt]"),
            ("f'^2", "[12.76395pt]"),
        ],
    )
    def test_width_matches_miktex(self, formula: str, width: str) -> None:
        assert _plain_messages(r"\setbox0\hbox{$" + formula + "$}" + _WIDTH) == [width]
