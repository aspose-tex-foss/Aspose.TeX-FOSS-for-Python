"""missing glyph admission preserves text runs and math owners."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from aspose_tex import DviDevice, PdfDevice, StringInputSource, SvgDevice, TeXJob
from aspose_tex._engine.box_builder import HBoxBuilder
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex.exceptions import FontError
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _tfm_width

EVIDENCE = Path(__file__).resolve().parents[1] / "testdata" / "reference" / "input_bytes"
REFERENCES = json.loads((EVIDENCE / "results.json").read_text())


def _run(body, device=None):
    if isinstance(body, str):
        body = body.encode()
    job = TeXJob(StringInputSource(b"\\nopagenumbers\\parindent=0pt " + body + b"\\bye"),
                 device or DviDevice())
    return job, job.run()


def _missing(job):
    return [m for m in job.messages if m.startswith("Missing character:")]


@pytest.mark.parametrize("case", [
    "paragraph", "hbox", "vbox", "math", "caret_bytes", "ligkern_gap", "hbox_ligkern_gap",
    "spacefactor", "nullfont", "byte_85", "byte_ff", "lostchars_off",
])
def test_measured_contexts(case):
    data = REFERENCES[case]
    source = bytes.fromhex(data["bytes_hex"])
    job = TeXJob(StringInputSource(source), DviDevice())
    payload = job.run()
    actual = walk_chars_with_positions(payload, _tfm_width())
    expected = data["reference"]["glyphs"]
    assert actual == [[tuple(g) for g in page] for page in expected]
    assert len(_missing(job)) == len(data["reference"]["missing"])
    if case == "spacefactor":
        assert "[sf=999]" in job.messages


@pytest.mark.parametrize("device", [DviDevice, PdfDevice, SvgDevice])
@pytest.mark.parametrize("body", ["A“B”C", "\\hbox{A“B”C}", "$A“B”C$", "\\vbox{A“B”C\\par}"])
def test_every_output_backend(device, body):
    job, output = _run(body, device())
    assert output
    assert len(_missing(job)) == 6


def test_live_gate_group_restoration_and_logger(caplog):
    with caplog.at_level(logging.WARNING, logger="aspose_tex"):
        job, _ = _run(r"\char226 {\tracinglostchars=0\char226} \char226")
    assert len(_missing(job)) == 2
    assert [r.message for r in caplog.records if "Missing character:" in r.message] == _missing(job)
    assert all(r.levelno == logging.WARNING for r in caplog.records if "Missing character:" in r.message)


def test_char_chardef_and_box_reuse_report_once():
    job, _ = _run(r"\chardef\missing=226\setbox0\hbox{A\char226\missing B}\copy0\copy0\box0")
    assert len(_missing(job)) == 2


def test_nullfont_alias_and_zero_size_real_font():
    job, payload = _run(r"\let\nothing=\nullfont {\nothing ABC}\font\zero=cmr10 at 0pt {\zero ABC}X")
    assert _missing(job) == [f"Missing character: There is no {c} in font nullfont!" for c in "ABC"]
    assert [c for c, _, _ in walk_chars_with_positions(payload)[0]] == list(map(ord, "ABCX"))


def test_font_manager_tfm_admission_and_strict_metric_access():
    manager = FontManager()
    manager.load_font("rm", "cmr10")
    manager.load_font("zero", "cmr10", at_sp=0)
    manager.alias_font("nil", "nullfont")
    attempts = []
    manager.set_missing_character_sink(lambda name, code: attempts.append((name, code)))
    assert manager.check_character("rm", 65)
    assert manager.check_character("zero", 65)
    assert not manager.check_character("rm", 226)
    assert not manager.check_character("nil", 65)
    assert attempts == [("rm", 226), ("nil", 65)]
    with pytest.raises(FontError):
        manager.get_metrics("rm").char_metrics(226)
    with pytest.raises(FontError):
        manager.check_character("unknown", 65)
    with pytest.raises(FontError):
        manager.load_font("missing", "nonexistent_font")
    manager.set_missing_character_sink(None)
    assert not manager.check_character("rm", 226)
    assert len(attempts) == 2


def test_builder_missing_breaks_run_without_ghost_nodes():
    manager = FontManager()
    manager.load_font("rm", "cmr10")
    builder = HBoxBuilder(manager)
    for code in [102, 226, 105, 65, 226, 86]:
        builder.add_char(code, "rm")
    assert [n.char for n in builder.build().list] == [102, 105, 65, 86]


@pytest.mark.parametrize("body", [r"$\mathchar226_a^b$", r"$\mathchar" + '"10E2' + r"_a^b$",
                                  r"$$\mathchar" + '"10E2' + r"_a^b$$"])
def test_missing_math_nucleus_keeps_scripts(body):
    job, payload = _run(body)
    assert len(_missing(job)) == 1
    assert [c for c, _, _ in walk_chars_with_positions(payload)[0]] == [98, 97]


EXTRA = json.loads((EVIDENCE.parent / "missing_characters" / "results.json").read_text())


@pytest.mark.parametrize("case", EXTRA)
def test_fresh_owner_contexts(case):
    data = EXTRA[case]
    assert data["exit"] == 0
    job = TeXJob(StringInputSource(bytes.fromhex(data["source_hex"])), DviDevice())
    payload = job.run()
    assert walk_chars_with_positions(payload, _tfm_width()) == [
        [tuple(g) for g in page] for page in data["glyphs"]
    ]
    assert len(_missing(job)) == len(data["missing"])
    for message in data["messages"]:
        assert message in job.messages


REVIEW = json.loads((EVIDENCE.parent / "missing_characters" / "extended_results.json").read_text())


def _review_missing(reference):
    # The MiKTeX log stores raw high bytes; spells them as ^^xx.
    return ["".join(f"^^{ord(c):02x}" if ord(c) >= 127 else c for c in message)
            for message in reference["missing"]]


@pytest.mark.parametrize("case", REVIEW)
def test_reviewed_construction_boundaries(case, caplog):
    data = REVIEW[case]
    reference = data["reference"]
    assert reference["exit"] == 0
    job = TeXJob(StringInputSource(bytes.fromhex(data["source_hex"])), DviDevice())
    with caplog.at_level(logging.WARNING, logger="aspose_tex"):
        payload = job.run()
    assert walk_chars_with_positions(payload, _tfm_width()) == [
        [tuple(g) for g in page] for page in reference["glyphs"]
    ]
    assert _missing(job) == _review_missing(reference)
    assert [r.message for r in caplog.records if "Missing character:" in r.message] == _missing(job)


@pytest.mark.parametrize("case", [case for case in REVIEW if case.startswith("accent_")])
@pytest.mark.parametrize("device", [DviDevice, PdfDevice, SvgDevice])
def test_accent_missing_attempts_all_outputs(case, device):
    data = REVIEW[case]
    job = TeXJob(StringInputSource(bytes.fromhex(data["source_hex"])), device())
    assert job.run()
    assert _missing(job) == _review_missing(data["reference"])
