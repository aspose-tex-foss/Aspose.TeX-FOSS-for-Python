from __future__ import annotations

import pytest

from aspose_tex._engine.interpreter import ModeKind, TeXInterpreter
from aspose_tex._engine.math_shell import (
 _MATH_PRIMITIVES,
 MathOperandKind,
 MathShellRegistry,
)
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError


def _run(source: str) -> TeXInterpreter:
 interp = TeXInterpreter()
 interp.run(StringInputSource(source))
 return interp


class TestMathOperandKind:
 def test_arity_table_covers_required_primitives(self) -> None:
 names = {prim.name for prim in _MATH_PRIMITIVES}

 assert len(names) >= 25
 assert {
 "over",
 "above",
 "left",
 "right",
 "mathchoice",
 "mathaccent",
 "radical",
 "delimiter",
 "mathchar",
 } <= names

 def test_each_kind_has_table_entry(self) -> None:
 kinds = {prim.arity for prim in _MATH_PRIMITIVES}

 assert set(MathOperandKind) == kinds


class TestMathShellDispatch:
 def test_over_consumes_zero_operands(self) -> None:
 _run(r"$\over$\bye")

 def test_above_consumes_dimen(self) -> None:
 _run(r"$\above1pt$\bye")

 def test_overwithdelims_consumes_two_delims(self) -> None:
 _run(r"$\overwithdelims()$\bye")

 def test_abovewithdelims_consumes_two_delims_and_dimen(self) -> None:
 _run(r"$\abovewithdelims()1pt$\bye")

 def test_left_increments_and_right_decrements_depth(self) -> None:
 _run(r"$\left(x\right)$\bye")

 def test_right_underflow_raises(self) -> None:
 with pytest.raises(EngineError, match=r"\\right without \\left"):
 _run(r"$\right)$\bye")

 def test_left_without_right_raises_at_math_close(self) -> None:
 with pytest.raises(EngineError, match=r"missing \\right"):
 _run(r"$\left(x$\bye")

 def test_mathopen_consumes_math_field(self) -> None:
 _run(r"$\mathopen{x}$\bye")

 def test_mathaccent_consumes_int_then_field(self) -> None:
 _run(r'$\mathaccent"7013 {a}$\bye')

 def test_radical_consumes_int_then_field(self) -> None:
 _run(r'$\radical"270370 {x}$\bye')

 def test_mathchoice_consumes_four_balanced_groups(self) -> None:
 _run(r"$\mathchoice{d}{t}{s}{ss}$\bye")

 def test_mskip_consumes_muglue(self) -> None:
 _run(r"$\mskip3mu$\bye")

 def test_mkern_consumes_mudimen(self) -> None:
 _run(r"$\mkern-2mu$\bye")

 @pytest.mark.parametrize(
 "name",
 [
 "displaystyle",
 "textstyle",
 "scriptstyle",
 "scriptscriptstyle",
 "nonscript",
 "limits",
 "nolimits",
 "displaylimits",
 ],
 )
 def test_zero_arity_style_and_limit_primitives(self, name: str) -> None:
 _run(rf"$\{name}$\bye")

 def test_overline_underline_consume_field(self) -> None:
 _run(r"$\overline{x}\underline y$\bye")

 def test_delimiter_consumes_integer(self) -> None:
 _run(r'$\delimiter"028300 $\bye')

 def test_mathchar_and_char_consume_integer(self) -> None:
 _run(r'$\mathchar"010B \char65 $\bye')

 def test_unknown_math_cs_still_raises_undefined(self) -> None:
 with pytest.raises(EngineError, match=r"Undefined control sequence \\missing"):
 _run(r"$\missing$\bye")


class TestMathFieldConsumer:
 def test_subscript_consumes_single_cs_field(self) -> None:
 _run(r'\mathchardef\alpha="010B $x_\alpha$\bye')

 def test_superscript_consumes_balanced_group(self) -> None:
 _run(r"$x^{ab}$\bye")

 def test_subscript_at_eof_raises(self) -> None:
 with pytest.raises(EngineError, match="math field expected"):
 _run(r"$x_")


class TestEqnoLeqno:
 def test_eqno_in_display_math_consumes_field(self) -> None:
 _run(r"$$x\eqno{1}$$\bye")

 def test_eqno_outside_display_math_raises(self) -> None:
 with pytest.raises(EngineError, match="valid only in display math"):
 _run(r"\eqno{1}\bye")

 def test_leqno_outside_display_math_raises(self) -> None:
 with pytest.raises(EngineError, match="valid only in display math"):
 _run(r"\leqno{1}\bye")


class TestMathActiveChar:
 def test_apostrophe_with_macro_dispatches(self) -> None:
 _run(r'{\catcode`\~=13 \gdef~{^{\relax}}}\mathcode`\~="8000 $x~$\bye')

 def test_math_active_without_macro_raises(self) -> None:
 with pytest.raises(EngineError, match="math-active char without macro"):
 _run(r'\mathcode`\~="8000 $~$\bye')


def test_registry_export_type_is_constructible() -> None:
 interp = _run("")

 assert isinstance(interp._math_shell, MathShellRegistry)
 assert interp._mode_stack.current == ModeKind.OUTER_VERTICAL
