"""Alignment-subsystem registration stub tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from aspose_tex._engine.alignment import (
 STUB_ERROR_HALIGN,
 STUB_ERROR_VALIGN,
 build_stub_handlers,
)
from aspose_tex._engine.interpreter import ModeKind, TeXInterpreter
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.reader import FileInputSource, StringInputSource
from aspose_tex._input.token import CharToken
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

_NO_FORMAT = TeXOptions(load_format=False)
_FIXTURE = Path("testdata/fixtures/alignment_define_only.tex")


def _run(tex: str) -> None:
 TeXInterpreter().run_with_device(StringInputSource(tex), DviDevice())


def _run_job(tex: str, options: TeXOptions = _NO_FORMAT) -> TeXJob:
 job = TeXJob(StringInputSource(tex), DviDevice(), options=options)
 job.run()
 return job


class TestBuildStubHandlers:
 def test_seven_handlers_registered(self) -> None:
 handlers = build_stub_handlers()

 assert set(handlers) == {
 "halign",
 "valign",
 "cr",
 "crcr",
 "noalign",
 "span",
 "omit",
 }

 def test_handlers_are_zero_arg_callables(self) -> None:
 for handler in build_stub_handlers().values():
 assert callable(handler)


class TestStubExecRaises:
 def test_halign_raises_not_implemented_text(self) -> None:
 with pytest.raises(NotImplementedError) as exc:
 build_stub_handlers()["halign"]()

 assert str(exc.value) == STUB_ERROR_HALIGN
 assert "not yet implemented" in str(exc.value)

 def test_valign_raises_not_implemented_text(self) -> None:
 with pytest.raises(NotImplementedError) as exc:
 build_stub_handlers()["valign"]()

 assert str(exc.value) == STUB_ERROR_VALIGN
 assert "not yet implemented" in str(exc.value)

 @pytest.mark.parametrize(
 ("name", "message"),
 [
 ("cr", r"\cr outside \halign/\valign"),
 ("crcr", r"\crcr outside \halign/\valign"),
 ("noalign", r"\noalign outside \halign/\valign"),
 ("span", r"\span outside \halign/\valign"),
 ("omit", r"\omit outside \halign/\valign"),
 ],
 )
 def test_outside_alignment_raises_engine_error(
 self,
 name: str,
 message: str,
 ) -> None:
 with pytest.raises(EngineError) as exc:
 build_stub_handlers()[name]()

 assert str(exc.value) == message


class TestAmpersandOutsideAlignment:
 def test_amp_in_outer_vertical_mode_raises(self) -> None:
 with pytest.raises(EngineError, match=r"alignment tab outside \\halign/\\valign"):
 _run(r"&\bye")

 def test_amp_in_horizontal_mode_raises(self) -> None:
 with pytest.raises(EngineError, match=r"alignment tab outside \\halign/\\valign"):
 _run(r"a&b\bye")

 def test_amp_in_restricted_horizontal_mode_raises(self) -> None:
 interp = TeXInterpreter()
 interp.run_with_device(StringInputSource(""), DviDevice())
 interp._mode_stack.push(ModeKind.RESTRICTED_HORIZONTAL)

 with pytest.raises(EngineError, match=r"alignment tab outside \\halign/\\valign"):
 interp._dispatch_char(CharToken("&", Catcode.ALIGNMENT))

 def test_amp_inside_macro_body_does_not_raise_at_definition(self) -> None:
 _run(r"\def\foo{a&b}\bye")

 def test_amp_inside_macro_body_raises_at_invocation(self) -> None:
 with pytest.raises(EngineError, match=r"alignment tab outside \\halign/\\valign"):
 _run(r"\def\foo{a&b}\foo\bye")


class TestDefinitionTimeParse:
 def test_def_matrix_with_halign_body_does_not_raise(self) -> None:
 _run(r"\def\matrix#1{\halign{##\cr#1}}\bye")

 def test_def_with_amp_in_body_does_not_raise(self) -> None:
 _run(r"\def\foo{a&b\cr}\bye")

 def test_def_with_span_omit_noalign_in_body_does_not_raise(self) -> None:
 _run(r"\def\bar{\span\omit\noalign{x}}\bye")

 def test_nested_def_inside_def_body_parses(self) -> None:
 _run(r"\def\outermacro#1{\def\cr{\crcr\noalign{\let\cr\relax}}#1}\bye")

 def test_define_then_invoke_then_raises(self) -> None:
 with pytest.raises(NotImplementedError) as exc:
 _run(r"\def\matrix#1{\halign{##\cr#1}}\matrix{a}\bye")

 assert str(exc.value) == STUB_ERROR_HALIGN


class TestPlainTexMacroInvocation:
 def test_matrix_shape_invocation_raises_not_implemented(self) -> None:
 with pytest.raises(NotImplementedError) as exc:
 _run(r"\def\matrix#1{\halign{##\cr#1}}\matrix{1&2\cr 3&4\cr}\bye")

 assert str(exc.value) == STUB_ERROR_HALIGN

 def test_settabs_shape_invocation_raises_not_implemented(self) -> None:
 with pytest.raises(NotImplementedError) as exc:
 _run(
 r"\def\settabs#1\columns{\halign{##\cr}}"
 r"\settabs 4\columns \+ a&b&c&d\cr\bye"
 )

 assert str(exc.value) == STUB_ERROR_HALIGN

 def test_eqalign_in_math_mode_raises_not_implemented(self) -> None:
 with pytest.raises(NotImplementedError) as exc:
 _run(r"\def\eqalign#1{\halign{##\cr#1}} $\eqalign{x &= y\cr}$\bye")

 assert str(exc.value) == STUB_ERROR_HALIGN


class TestDefineButNeverUse:
 def test_document_with_unused_alignment_macro_succeeds(self) -> None:
 job = TeXJob(FileInputSource(_FIXTURE), DviDevice(), options=_NO_FORMAT)
 result = job.run()

 assert result is not None
 assert result[0] == 247


class TestPlainTexAlignmentNamesRegistered:
 @pytest.mark.parametrize("name", ["halign", "valign"])
 def test_alignment_head_dispatches_through_primitives(self, name: str) -> None:
 with pytest.raises(NotImplementedError, match="not yet implemented"):
 _run(rf"\{name}\bye")

 @pytest.mark.parametrize("name", ["cr", "crcr", "noalign", "span", "omit"])
 def test_alignment_body_name_dispatches_through_primitives(self, name: str) -> None:
 with pytest.raises(EngineError, match=r"outside \\halign/\\valign") as exc:
 _run(rf"\{name}\bye")

 assert "Undefined control sequence" not in str(exc.value)

 @pytest.mark.parametrize("name", ["halign", "valign"])
 def test_plain_format_alignment_head_name_is_registered(self, name: str) -> None:
 with pytest.raises(NotImplementedError, match="not yet implemented"):
 _run_job(rf"\{name}\bye", options=TeXOptions(load_format="plain"))

 @pytest.mark.parametrize("name", ["cr", "crcr", "noalign", "span", "omit"])
 def test_plain_format_alignment_body_name_is_registered(self, name: str) -> None:
 with pytest.raises(EngineError, match=r"outside \\halign/\\valign") as exc:
 _run_job(rf"\{name}\bye", options=TeXOptions(load_format="plain"))

 assert "Undefined control sequence" not in str(exc.value)


class TestMacroLetCr:
 def test_let_par_eq_cr_succeeds_but_calling_par_raises(self) -> None:
 with pytest.raises(EngineError, match=r"\\cr outside \\halign/\\valign"):
 _run(r"\let\par=\cr\par")

 def test_let_par_eq_cr_without_call_succeeds(self) -> None:
 _run_job(r"\let\par=\cr\end")
