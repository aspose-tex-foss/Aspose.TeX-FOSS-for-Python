from __future__ import annotations

from pathlib import Path

import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_load_format_false_skips_format_load_and_messages_are_empty() -> None:
 job = TeXJob(
 StringInputSource(""),
 DviDevice(),
 options=TeXOptions(load_format=False),
 )

 job.run()

 assert job.messages == []


def test_unsupported_format_raises_during_run() -> None:
 job = TeXJob(
 StringInputSource(""),
 DviDevice(),
 options=TeXOptions(load_format="latex"),
 )

 with pytest.raises(EngineError, match="unsupported format: latex"):
 job.run()


def test_fake_format_loads_through_dump_then_user_input_runs() -> None:
 job = TeXJob(
 StringInputSource(r"A\bye"),
 DviDevice(),
 options=TeXOptions(
 load_format="fake_format_for_io_test",
 extra_format_paths=[_FIXTURES],
 ),
 )

 result = job.run()

 assert result is not None
 assert job.messages == ["Preloading the plain format: codes,"]


def test_input_uses_extra_format_paths(tmp_path: Path) -> None:
 (tmp_path / "foo.tex").write_text(r"\def\foo{Z}", encoding="utf-8")
 job = TeXJob(
 StringInputSource(r"\input foo \foo\bye"),
 DviDevice(),
 options=TeXOptions(load_format=False, extra_format_paths=[tmp_path]),
 )

 result = job.run()

 assert result is not None


def test_bundled_format_directory_wins_over_extra_paths(tmp_path: Path) -> None:
 (tmp_path / "plain.tex").write_text(r"\dump", encoding="utf-8")
 interp = TeXInterpreter(extra_format_paths=[tmp_path])

 path = interp._resolve_input_path("plain")

 assert path.name == "plain.tex"
 assert path.parent.name == "format"
 assert path.parent.parent.name == "data"


def test_dump_outside_format_load_raises() -> None:
 job = TeXJob(
 StringInputSource(r"\dump"),
 DviDevice(),
 options=TeXOptions(load_format=False),
 )

 with pytest.raises(
 EngineError, match=r"\\dump only allowed during format load"
 ):
 job.run()


def test_everyjob_tokens_fire_before_user_input(tmp_path: Path) -> None:
 fmt = tmp_path / "jobfmt.tex"
 fmt.write_text(
 r"\def\testtoken{\def\marker{X}}\everyjob{\testtoken}\dump",
 encoding="utf-8",
 )
 job = TeXJob(
 StringInputSource(r"\marker\bye"),
 DviDevice(),
 options=TeXOptions(load_format="jobfmt", extra_format_paths=[tmp_path]),
 )

 result = job.run()

 assert result is not None
