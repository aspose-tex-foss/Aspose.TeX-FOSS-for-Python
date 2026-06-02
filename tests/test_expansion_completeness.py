from __future__ import annotations

import pytest

from aspose_tex._engine.code_arrays import CodeArrays
from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.group import GroupStack
from aspose_tex._engine.named_parameters import NamedParameterRegistry, ParamKind
from aspose_tex._engine.registers import RegisterSet
from aspose_tex._input import (
 CatcodeTable,
 CharToken,
 ControlSequenceToken,
 InputReader,
 StringInputSource,
 Tokenizer,
)
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions


def _make_expander(
 text: str,
 *,
 regs: RegisterSet | None = None,
 codes: CodeArrays | None = None,
 job_name: str = "texput",
) -> Expander:
 reader = InputReader(StringInputSource(text))
 catcodes = CatcodeTable()
 tokenizer = Tokenizer(reader, catcodes)
 expander = Expander(
 reader,
 tokenizer,
 catcodes,
 register_provider=regs,
 job_name_provider=lambda: job_name,
 code_arrays_provider=lambda: codes or CodeArrays(),
 )
 if regs is not None:
 expander._register_set = regs
 return expander


def _expand(text: str, **kwargs) -> list:
 return list(_make_expander(text, **kwargs))


def _chars(tokens: list) -> str:
 return "".join(t.char for t in tokens if isinstance(t, CharToken))


def test_futurelet_assigns_second_lookahead_meaning_and_reemits_tokens() -> None:
 expander = _make_expander(r"\futurelet\next ab\next")
 tokens = list(expander)

 assert _chars(tokens) == "abb"
 meaning = expander.macros["next"]
 assert isinstance(meaning, CharToken)
 assert meaning.char == "b"


def test_afterassignment_fires_after_count_assignment_once() -> None:
 regs = RegisterSet()
 expander = _make_expander(r"\afterassignment X\count0=42", regs=regs)
 out = []
 for token in expander:
 if isinstance(token, ControlSequenceToken) and regs.execute(token.name, expander):
 continue
 out.append(token)

 assert regs.get_count(0) == 42
 assert _chars(out) == "X"


def test_afterassignment_overwrites_prior_token() -> None:
 regs = RegisterSet()
 expander = _make_expander(r"\afterassignment X\afterassignment Y\count0=42", regs=regs)
 out = []
 for token in expander:
 if isinstance(token, ControlSequenceToken) and regs.execute(token.name, expander):
 continue
 out.append(token)

 assert _chars(out) == "Y"


def test_afterassignment_fires_after_def_and_let() -> None:
 assert _chars(_expand(r"\afterassignment X\def\a{}")).strip() == "X"
 assert _chars(_expand(r"\afterassignment X\let\a=Y")).strip() == "X"


def test_afterassignment_fires_after_named_parameter_assignment() -> None:
 group_stack = GroupStack()
 regs = RegisterSet(group_stack=group_stack)
 named = NamedParameterRegistry(regs, group_stack)
 named.register("foo", ParamKind.INT, 256, default=0)
 expander = _make_expander(r"\afterassignment X\foo=7", regs=regs)

 out = []
 for token in expander:
 if isinstance(token, ControlSequenceToken):
 entry = named.lookup(token.name)
 if entry is not None:
 named.dispatch_assignment(entry, expander)
 continue
 out.append(token)

 assert regs.get_count(256, _internal=True) == 7
 assert _chars(out) == "X"


def test_afterassignment_fires_after_code_array_assignment() -> None:
 job = TeXJob(
 StringInputSource(r"\afterassignment\message \uccode`a=`A{done}\bye"),
 DviDevice(),
 options=TeXOptions(load_format=False),
 )

 job.run()

 assert job.messages == ["done"]


def test_afterassignment_fires_after_font_definition() -> None:
 job = TeXJob(
 StringInputSource(r"\afterassignment\message \font\foo=cmr10{done}\bye"),
 DviDevice(),
 options=TeXOptions(load_format=False),
 )

 job.run()

 assert job.messages == ["done"]


def test_romannumeral_jobname_and_meaning() -> None:
 tokens = _expand(
 r"\romannumeral 2026 \jobname \meaning\undefined",
 job_name="sample",
 )
 text = _chars(tokens)
 assert "mmxxvi" in text
 assert "sample" in text
 assert r"\undefined" in text


def test_romannumeral_accepts_count_alias() -> None:
 regs = RegisterSet()
 regs.define_alias("pageno", "count", 0)
 regs.set_count(0, 12)

 assert "xii" in _chars(_expand(r"\romannumeral\pageno", regs=regs))


def test_romannumeral_non_positive_is_empty() -> None:
 assert _chars(_expand(r"\romannumeral 0 X")).strip() == "X"
 assert _chars(_expand(r"\romannumeral -5 X")).strip() == "X"


def test_uppercase_lowercase_preserve_control_sequences_and_catcodes() -> None:
 codes = CodeArrays()
 tokens = _expand(r"\uppercase{ab\foo}", codes=codes)
 assert _chars(tokens).strip() == "AB"
 assert any(isinstance(t, ControlSequenceToken) and t.name == "foo" for t in tokens)

 lower = _expand(r"\lowercase{AB}", codes=codes)
 assert _chars(lower).strip() == "ab"


def test_uppercase_zero_uccode_passes_through() -> None:
 codes = CodeArrays()
 codes.set_uccode(ord("a"), 0)
 assert _chars(_expand(r"\uppercase{a}", codes=codes)).strip() == "a"


def test_uppercase_missing_group_raises() -> None:
 with pytest.raises(EngineError, match=r"\\uppercase expects"):
 _expand(r"\uppercase A")


def test_patterns_and_hyphenation_consume_balanced_text() -> None:
 assert _chars(_expand(r"\patterns{a1b {nested}}\hyphenation{foo-bar}Z")).strip() == "Z"


def test_jobname_flows_from_tex_options() -> None:
 job = TeXJob(
 StringInputSource(r"\message{\jobname}\bye"),
 DviDevice(),
 options=TeXOptions(load_format=False, job_name="from-options"),
 )

 job.run()

 assert job.messages == ["from-options"]
