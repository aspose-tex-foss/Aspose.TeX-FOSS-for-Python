r"""source sfcodes precede expanded lig/kern lookahead.

Every expected message and complete glyph stream was measured with MiKTeX
24.4 tex; testdata/reference/footnote_spacefactor/miktex.json retains the exact source for replay.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _tfm_width

_CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "testdata/reference/footnote_spacefactor/miktex.json")
    .read_text(encoding="utf-8")
)


@pytest.mark.parametrize("name", _CASES)
def test_character_spacefactor_matches_miktex(name: str) -> None:
    case = _CASES[name]
    job = TeXJob(StringInputSource(case["source"]), DviDevice())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        payload = job.run()
    assert [message for message in job.messages if message.startswith("[")] == case["messages"]
    glyphs = walk_chars_with_positions(payload, _tfm_width())
    assert [[list(glyph) for glyph in page] for page in glyphs] == case["glyphs"]
