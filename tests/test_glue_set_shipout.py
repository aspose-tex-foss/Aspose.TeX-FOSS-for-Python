""" full-event MiKTeX oracles for all four pack members and controls."""
import json
from pathlib import Path

import pytest

from tests._verification.shipout_events import compile_events

REFERENCE = json.loads((Path(__file__).parents[1] / "testdata/reference/glue_model/witness_reference.json").read_text())


@pytest.mark.parametrize("name", REFERENCE)
@pytest.mark.parametrize("backend", ["dvi", "svg", "pdf"])
def test_glue_set_exact_miktex(name, backend, monkeypatch):
    row = REFERENCE[name]
    assert compile_events(row["source"], backend, monkeypatch) == {
        key: row[key] for key in ("glyphs", "rules", "fonts")
    }
