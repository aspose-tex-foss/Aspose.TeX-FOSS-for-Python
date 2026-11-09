r"""scanner operands use existing meanings and binding owners."""
import json
from pathlib import Path

import pytest

from aspose_tex.exceptions import EngineError
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _run, _tfm_width

_EVIDENCE = Path(__file__).resolve().parents[1] / "testdata/reference/meaning_aware_scanners"


def _assert_measured(row):
    job = _run(row["body"])
    pages = walk_chars_with_positions(job._dvi, _tfm_width()) if job._dvi else []
    assert pages == [[tuple(g) for g in page] for page in row["miktex_pages"]]
    messages = row["miktex_messages"][:-len(pages)] if pages else row["miktex_messages"]
    assert [m for m in job.messages if m.startswith("[")] == messages


@pytest.mark.parametrize("row", json.loads(
    (_EVIDENCE / "protected-controls.json").read_text())["rows"], ids=lambda r: r["name"])
def test_protected_active_binding_precedence_and_ligature_barriers(row):
    _assert_measured(row)


@pytest.mark.parametrize("row", json.loads(
    (_EVIDENCE / "shorthand-targets.json").read_text())["rows"], ids=lambda r: r["name"])
def test_active_shorthand_targets_use_existing_scoped_owner(row):
    _assert_measured(row)


@pytest.mark.parametrize("row", json.loads(
    (_EVIDENCE / "arithmetic-operands.json").read_text())["rows"], ids=lambda r: r["name"])
def test_arithmetic_operand_meaning_and_scope(row):
    if row["miktex_exit"]:
        with pytest.raises(EngineError):
            _run(row["body"])
    else:
        _assert_measured(row)


@pytest.mark.parametrize("row", [r for r in json.loads(
    (_EVIDENCE / "context-final.json").read_text())["rows"]
    if r["miktex_exit"] == 0 and r["name"] != "protected_space_alignment"], ids=lambda r: r["name"])
def test_scanners_across_measured_contexts(row):
    # Initial implicit-space suppression in alignment is separately.
    _assert_measured(row)
