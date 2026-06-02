from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_NO_FORMAT = TeXOptions(load_format=False)


def _run(tex: str, caplog: pytest.LogCaptureFixture) -> TeXJob:
 caplog.set_level(logging.INFO, logger="aspose_tex")
 job = TeXJob(StringInputSource(tex), DviDevice(), options=_NO_FORMAT)
 job.run()
 return job


def _raises(tex: str) -> Iterator[BaseException]:
 job = TeXJob(StringInputSource(tex), DviDevice(), options=_NO_FORMAT)
 with pytest.raises((EngineError, NotImplementedError)) as exc_info:
 job.run()
 yield exc_info.value


def test_message_logs_appends_and_never_writes_stdout(
 caplog: pytest.LogCaptureFixture,
 capsys: pytest.CaptureFixture[str],
) -> None:
 job = _run(r"\message{hello}\bye", caplog)

 assert job.messages == ["hello"]
 assert [r.message for r in caplog.records if r.levelno == logging.INFO] == [
 "hello"
 ]
 assert capsys.readouterr().out == ""


def test_wlog_write_minus_one_logs_without_messages(
 caplog: pytest.LogCaptureFixture,
) -> None:
 tex = (
 r"\catcode`\@=11 "
 r"\countdef\m@ne=22 \m@ne=-1 "
 r"\def\wlog{\immediate\write\m@ne}"
 r"\wlog{hello}\bye"
 )

 job = _run(tex, caplog)

 assert job.messages == []
 assert [r.message for r in caplog.records if r.levelno == logging.INFO] == [
 "hello"
 ]


def test_write_16_matches_message(caplog: pytest.LogCaptureFixture) -> None:
 job = _run(r"\write 16{hello}\bye", caplog)

 assert job.messages == ["hello"]
 assert [r.message for r in caplog.records if r.levelno == logging.INFO] == [
 "hello"
 ]


def test_immediate_write_16_matches_write_16(
 caplog: pytest.LogCaptureFixture,
) -> None:
 job = _run(r"\immediate\write 16{hi}\bye", caplog)

 assert job.messages == ["hi"]
 assert [r.message for r in caplog.records if r.levelno == logging.INFO] == [
 "hi"
 ]


def test_write_numbered_stream_is_deferred_to_m5() -> None:
 job = TeXJob(
 StringInputSource(r"\write 5{x}"),
 DviDevice(),
 options=_NO_FORMAT,
 )

 with pytest.raises(NotImplementedError, match=r"\\openout.*M5"):
 job.run()


def test_write_stream_number_out_of_range_raises_engine_error_first() -> None:
 job = TeXJob(
 StringInputSource(r"\write 99{x}"),
 DviDevice(),
 options=_NO_FORMAT,
 )

 with pytest.raises(EngineError, match="stream number out of range: 99"):
 job.run()


def test_errmessage_logs_appends_and_continues(
 caplog: pytest.LogCaptureFixture,
) -> None:
 job = _run(r"\errmessage{boom}\message{after}\bye", caplog)

 assert job.messages == ["! boom", "after"]
 assert any(
 record.levelno == logging.WARNING and record.message == "! boom"
 for record in caplog.records
 )


def test_errhelp_surfaces_in_warning_line(
 caplog: pytest.LogCaptureFixture,
) -> None:
 job = _run(r"\errhelp{help text}\errmessage{boom}\bye", caplog)

 assert job.messages == ["! boom"]
 warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
 assert warnings == ["! boom\nhelp: help text"]


@pytest.mark.parametrize(
 ("tex", "primitive"),
 [
 (r"\openin 0=foo", "openin"),
 (r"\openout 0=foo", "openout"),
 (r"\closeout 0", "closeout"),
 (r"\closein 0", "closein"),
 (r"\read 0 to \line", "read"),
 ],
)
def test_file_stream_primitives_parse_then_defer_to_m5(
 tex: str, primitive: str
) -> None:
 job = TeXJob(StringInputSource(tex), DviDevice(), options=_NO_FORMAT)

 with pytest.raises(NotImplementedError) as exc_info:
 job.run()

 message = str(exc_info.value)
 assert f"\\{primitive}" in message
 assert "M5" in message


def test_openin_stream_out_of_range_raises_engine_error_first() -> None:
 job = TeXJob(
 StringInputSource(r"\openin 99=foo"),
 DviDevice(),
 options=_NO_FORMAT,
 )

 with pytest.raises(EngineError, match="stream number out of range: 99"):
 job.run()


def test_ifeof_always_takes_false_branch(
 caplog: pytest.LogCaptureFixture,
) -> None:
 job = _run(
 r"\def\foo{\message{foo}}\def\bar{\message{bar}}"
 r"\ifeof 0\foo\else\bar\fi\bye",
 caplog,
 )

 assert job.messages == ["bar"]


def test_fake_format_message_is_collected() -> None:
 job = TeXJob(
 StringInputSource(""),
 DviDevice(),
 options=TeXOptions(
 load_format="fake_format_for_io_test",
 extra_format_paths=[_FIXTURES],
 ),
 )

 job.run()

 assert job.messages == ["Preloading the plain format: codes,"]
