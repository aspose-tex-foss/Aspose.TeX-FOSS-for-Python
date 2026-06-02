from __future__ import annotations

from pathlib import Path

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

_NO_FORMAT = TeXOptions(load_format=False)


def _plain_lines(start: int, end: int) -> str:
 lines = Path("src/aspose_tex/data/format/plain.tex").read_text(encoding="utf-8").splitlines()
 return "\n".join(lines[start - 1:end])


def _run(tex: str) -> TeXJob:
 job = TeXJob(StringInputSource(tex), DviDevice(), options=_NO_FORMAT)
 job.run()
 return job


class TestPlainTexMathSymbolBlock:
 def test_mathchardef_block_loads(self) -> None:
 source = _plain_lines(744, 911) + r" \bye"
 interp = TeXInterpreter()
 interp.run_with_device(StringInputSource(source), DviDevice())

 assert interp._register_set.resolve_constant("alpha") == ("mathchardef", 0x010B)

 def test_math_accent_definitions_load(self) -> None:
 source = _plain_lines(939, 950) + r" $\acute{a}\widehat{x}$\bye"

 _run(source)

 def test_textfont_assignments_load(self) -> None:
 source = (
 r"\font\sevenrm=cmr7 \font\fiverm=cmr5 "
 r"\textfont0=\tenrm \scriptfont0=\sevenrm \scriptscriptfont0=\fiverm "
 r"\bye"
 )

 interp = TeXInterpreter()
 interp.run_with_device(StringInputSource(source), DviDevice())

 registry = interp._math_family_registry
 assert registry.get_text(0) == "tenrm"
 assert registry.get_script(0) == "sevenrm"
 assert registry.get_scriptscript(0) == "fiverm"

 def test_dollar_alpha_dollar_consumes(self) -> None:
 _run(r'\mathchardef\alpha="010B $\alpha$\bye')

 def test_dollar_acute_a_dollar_consumes(self) -> None:
 _run(r'\def\acute{\mathaccent"7013 } $\acute{a}$\bye')

 def test_math_symbol_after_math_block_load(self) -> None:
 source = _plain_lines(744, 911) + r" $\alpha$\bye"

 _run(source)
