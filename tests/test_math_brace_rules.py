"""Brace leader painting plus the explicit cumulative-rounding boundary."""
import copy
import json
from pathlib import Path

import pytest

from tests._verification.shipout_events import compile_events

REFERENCE = json.loads(
    (Path(__file__).parents[1] / "testdata/reference/math_brace_leaders/brace_reference.json").read_text())


def _events(name, backend, monkeypatch):
    return compile_events(r"\nopagenumbers " + REFERENCE[name]["tex"] + "\n\\bye\n", backend, monkeypatch)


@pytest.mark.parametrize("name", REFERENCE)
@pytest.mark.parametrize("backend", ["dvi", "svg", "pdf"])
def test_brace_paint_and_exact_miktex(name, backend, monkeypatch):
    expected = {key: copy.deepcopy(REFERENCE[name][key]) for key in ("glyphs", "rules", "fonts")}
    assert _events(name, backend, monkeypatch) == expected


@pytest.mark.parametrize("backend", ["dvi", "svg", "pdf"])
def test_display_brace_strict_miktex_oracle(backend, monkeypatch):
    expected = {key: REFERENCE["display"][key] for key in ("glyphs", "rules", "fonts")}
    assert _events("display", backend, monkeypatch) == expected
