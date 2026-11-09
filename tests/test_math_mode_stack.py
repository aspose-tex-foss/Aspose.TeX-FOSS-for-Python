from __future__ import annotations

import pytest

from aspose_tex._engine.interpreter import ModeKind, TeXInterpreter
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.reader import StringInputSource
from aspose_tex._input.token import CharToken
from aspose_tex.exceptions import EngineError


def _run(source: str) -> TeXInterpreter:
    interp = TeXInterpreter()
    interp.run(StringInputSource(source))
    return interp


class TestMathModePush:
    def test_dollar_in_horizontal_pushes_math_and_closes(self) -> None:
        interp = _run(r"$ $\bye")

        assert interp._mode_stack.current == ModeKind.OUTER_VERTICAL

    def test_double_dollar_in_horizontal_pushes_display_and_closes(self) -> None:
        interp = _run(r"$$ $$\bye")

        assert interp._mode_stack.current == ModeKind.OUTER_VERTICAL

    def test_dollar_in_restricted_horizontal_pushes_math(self) -> None:
        interp = _run("")
        interp._mode_stack.push(ModeKind.RESTRICTED_HORIZONTAL)

        interp._handle_math_shift(CharToken("$", Catcode.MATH_SHIFT))

        assert interp._mode_stack.current == ModeKind.MATH

    def test_double_dollar_in_restricted_horizontal_raises(self) -> None:
        interp = _run("")
        interp._mode_stack.push(ModeKind.RESTRICTED_HORIZONTAL)
        interp._expander.push_tokens([CharToken("$", Catcode.MATH_SHIFT)])

        with pytest.raises(EngineError, match="display math is not allowed"):
            interp._handle_math_shift(CharToken("$", Catcode.MATH_SHIFT))


class TestMathModePop:
    def test_inline_math_pops_on_single_dollar(self) -> None:
        interp = _run(r"$ $\bye")

        assert interp._mode_stack.current == ModeKind.OUTER_VERTICAL

    def test_display_math_pops_on_double_dollar(self) -> None:
        interp = _run(r"$$ $$\bye")

        assert interp._mode_stack.current == ModeKind.OUTER_VERTICAL

    def test_second_adjacent_inline_formula_requires_its_closing_dollar(self) -> None:
        # the first dollar closes inline math without inspecting the
        # following dollar. That opens another inline formula, which is unclosed.
        with pytest.raises(EngineError, match=r"missing \$ inserted"):
            _run(r"$ $$\bye")

    def test_single_dollar_in_display_math_raises(self) -> None:
        with pytest.raises(EngineError, match=r"\$\$ display-math close expected"):
            _run(r"$$ $\bye")


class TestEverymathInjection:
    def test_everymath_tokens_injected_at_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[int] = []
        original = TeXInterpreter._push_toks_if_any

        def record(interp: TeXInterpreter, slot: int) -> None:
            seen.append(slot)
            original(interp, slot)

        monkeypatch.setattr(TeXInterpreter, "_push_toks_if_any", record)

        _run(r"\everymath={\relax}$ $\bye")

        # The $ first starts a paragraph, which inserts \everypar (§1091).
        assert seen == [257, 258]

    def test_everydisplay_tokens_injected_at_display_open(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[int] = []
        original = TeXInterpreter._push_toks_if_any

        def record(interp: TeXInterpreter, slot: int) -> None:
            seen.append(slot)
            original(interp, slot)

        monkeypatch.setattr(TeXInterpreter, "_push_toks_if_any", record)

        _run(r"\everydisplay={\relax}$$ $$\bye")

        # The $$ first starts a paragraph, which inserts \everypar (§1091).
        assert seen == [257, 259]

    def test_empty_everymath_and_everydisplay_are_noops(self) -> None:
        _run(r"$ $\bye")
        _run(r"$$ $$\bye")


class TestIfmodeIntegration:
    def test_ifmmode_true_in_inline_math(self) -> None:
        _run(r"$\ifmmode\relax\else\relax\fi$\bye")

    def test_ifmmode_true_in_display_math(self) -> None:
        _run(r"$$\ifmmode\relax\else\relax\fi$$\bye")

    def test_ifmmode_false_outside_math(self) -> None:
        _run(r"\ifmmode\undefined\else\relax\fi\bye")

    def test_ifinner_true_in_inline_math(self) -> None:
        _run(r"$\ifinner\relax\else\relax\fi$\bye")

    def test_ifinner_false_in_display_math(self) -> None:
        _run(r"$$\ifinner\undefined\else\relax\fi$$\bye")


class TestMathBodyConsumed:
    def test_space_in_inline_math_is_dropped(self) -> None:
        _run(r"$   $\bye")

    def test_space_in_display_math_is_dropped(self) -> None:
        _run(r"$$   $$\bye")

    @pytest.mark.parametrize("source", [r"$x$", r"$1$", r"$^x$", r"$_x$"])
    def test_math_body_non_space_tokens_are_consumed(self, source: str) -> None:
        _run(source + r"\bye")


class TestModeLeakOnError:
    def test_unclosed_inline_math_pops_before_raising(self) -> None:
        interp = TeXInterpreter()

        with pytest.raises(EngineError, match=r"missing \$ inserted"):
            interp.run(StringInputSource("$"))

        assert interp._mode_stack.current not in (ModeKind.MATH, ModeKind.MATH_DISPLAY)

    def test_unclosed_display_math_pops_before_raising(self) -> None:
        interp = TeXInterpreter()

        with pytest.raises(EngineError, match=r"missing \$\$ inserted"):
            interp.run(StringInputSource("$$"))

        assert interp._mode_stack.current not in (ModeKind.MATH, ModeKind.MATH_DISPLAY)


def _run_plain(body: str) -> None:
    import warnings

    from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

    job = TeXJob(StringInputSource(body + r"\end"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job.run()


class TestParInMathMode:
    r"""TeX §1046/§1047: ``mmode+par_end`` is "! Missing $ inserted".

    MiKTeX 24.4 reports the error for each ``_raises`` body; the ``_allowed``
    bodies run without one, because the inner box is the mode barrier.
    """

    @pytest.mark.parametrize(
        "body",
        [
            r"$a\par b$",
            r"\setbox0\hbox{$a\par b$}",
            r"$$a\par b$$",
            r"\let\endgraf\par $a\endgraf b$",
            "$a\n\nb$",  # a blank line inside the formula
        ],
    )
    def test_par_in_math_raises_missing_dollar(self, body: str) -> None:
        with pytest.raises(EngineError, match=r"Missing \$ inserted"):
            _run_plain(body)

    @pytest.mark.parametrize(
        "body",
        [
            r"\setbox0\hbox{$a\vbox{x\par y}b$}",
            r"\setbox0\hbox{$a\hbox{x\par y}b$}",
            r"\setbox0\hbox{$\vcenter{x\par y}$}",
            "$a$\n\nb",
        ],
    )
    def test_par_inside_a_box_in_math_is_allowed(self, body: str) -> None:
        _run_plain(body)
