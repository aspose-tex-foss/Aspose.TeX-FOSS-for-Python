"""Tests for internal quantities."""
from __future__ import annotations

import warnings

import pytest

from aspose_tex._input import StringInputSource
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions


def _run_messages(source: str) -> list[str]:
 job = TeXJob(
 StringInputSource(source),
 DviDevice(),
 options=TeXOptions(load_format=False),
 )
 with warnings.catch_warnings():
 warnings.simplefilter("ignore")
 job.run()
 return job.messages


def test_spacefactor_reads_and_writes_in_horizontal_mode() -> None:
 messages = _run_messages(
 r"Hi\message{sf=\the\spacefactor}"
 r"\spacefactor=1200\message{sf2=\the\spacefactor}\bye"
 )

 assert messages == ["sf=1000", "sf2=1200"]


def test_spacefactor_read_outside_horizontal_mode_raises() -> None:
 with pytest.raises(EngineError, match=r"\\spacefactor only valid in horizontal mode"):
 _run_messages(r"\message{sf=\the\spacefactor}\bye")


def test_prevdepth_and_prevgraf_are_vertical_mode_quantities() -> None:
 messages = _run_messages(
 r"\prevdepth=5pt\message{pd=\the\prevdepth pg=\the\prevgraf}"
 r"\noindent A\par\message{pg2=\the\prevgraf}\bye"
 )

 assert messages[0] == "pd=327680sppg=0"
 assert messages[1] == "pg2=1"


def test_prevdepth_assignment_outside_vertical_mode_raises() -> None:
 with pytest.raises(EngineError, match=r"\\prevdepth only valid in vertical mode"):
 _run_messages(r"A\prevdepth=5pt\bye")


def test_read_only_quantities_reject_assignment() -> None:
 with pytest.raises(EngineError, match=r"\\pagetotal is read-only"):
 _run_messages(r"\pagetotal=1pt\bye")


def test_page_builder_readers_return_live_values() -> None:
 messages = _run_messages(
 r"\vsize=20pt"
 r"\vskip 5pt"
 r"\vskip 0pt plus 2pt minus 1pt"
 r"\message{total=\the\pagetotal goal=\the\pagegoal "
 r"stretch=\the\pagestretch shrink=\the\pageshrink depth=\the\pagedepth}"
 r"\bye"
 )

 assert messages == [
 "total=327680spgoal=1310720spstretch=131072spshrink=65536spdepth=0sp"
 ]


def test_page_builder_fill_order_readers_and_counters_are_registered() -> None:
 messages = _run_messages(
 r"\vskip 0pt plus 1fil"
 r"\vskip 0pt plus 2fill"
 r"\vskip 0pt plus 3filll"
 r"\message{fil=\the\pagefilstretch fill=\the\pagefillstretch "
 r"filll=\the\pagefilllstretch dead=\the\deadcycles ins=\the\insertpenalties}"
 r"\bye"
 )

 assert messages == ["fil=1spfill=2spfilll=3spdead=0ins=0"]


def test_inputlineno_reports_current_reader_location() -> None:
 messages = _run_messages("first\n\\message{line=\\the\\inputlineno}\\bye")

 assert messages == ["line=2"]


def test_lastskip_lastpenalty_lastkern_update_and_reset() -> None:
 messages = _run_messages(
 r"\vskip 5pt\message{skip=\the\lastskip}"
 r"\kern 3pt\message{kern=\the\lastkern skip2=\the\lastskip}"
 r"\penalty 7\message{pen=\the\lastpenalty kern2=\the\lastkern}"
 r"\vskip 1pt\hbox{}\message{reset=\the\lastskip/\the\lastpenalty/\the\lastkern}"
 r"\bye"
 )

 assert messages == [
 "skip=327680sp",
 "kern=196608spskip2=0sp",
 "pen=7kern2=0sp",
 "reset=0sp/0/0sp",
 ]


def test_badness_reflects_last_box_glue_setting() -> None:
 messages = _run_messages(
 r"\setbox0=\hbox to 100pt{A}\message{bad=\the\badness}\bye"
 )

 assert messages == ["bad=10000"]


def test_afterassignment_fires_after_internal_quantity_write() -> None:
 messages = _run_messages(
 r"Hi\afterassignment\message\spacefactor=1200{internal}\bye"
 )

 assert messages == ["internal"]


def test_endinsert_style_page_comparison_uses_internal_readers() -> None:
 messages = _run_messages(
 r"\vsize=20pt\vskip 5pt"
 r"\ifdim\pagetotal<\pagegoal \message{fits}\else\message{overflow}\fi"
 r"\message{shrink=\the\pageshrink}\bye"
 )

 assert messages == ["fits", "shrink=0sp"]
