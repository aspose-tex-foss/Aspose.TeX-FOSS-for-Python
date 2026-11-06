"""Horizontal span keeps one live list per logical cell.

Every expected value is the MiKTeX 24.4 ``ref`` record of
``testdata/reference/alignment_span_list/results.json`` (probe.py); none is computed.
"""
import json
import warnings
from pathlib import Path

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_alignment_noalign_execution import assert_reference
from tests.test_plain_tie import _tfm_width

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads(
    (ROOT / 'testdata/reference/alignment_span_list/results.json').read_text(encoding='utf-8')
)

SHIFT = (
    'shifted', 'shift_hbox_no_align', 'shift_vbox_no_align',
    'shift_contribution_unvbox', 'shift_reinsert_hbox',
)
MATH_GLYPHS_ONLY = ('math_template_second', 'math_cells')
# Recoverable diagnostics owned by follow-ups.
OUT_OF_SCOPE = (
    *MATH_GLYPHS_ONLY, 'math_lastbox_no_align', 'diag_current_page',
    'deferred_straddle',
)
SPAN = [name for name in CASES if name not in SHIFT and name not in OUT_OF_SCOPE]


def test_span_context_inventory():
    assert len(SPAN) == 30
    assert 'witness' in SPAN


@pytest.mark.parametrize('name', SPAN)
def test_span_list_owner_context(name):
    assert_reference(CASES[name])


@pytest.mark.parametrize('name', SHIFT)
def test_lastbox_resets_shift(name):
    assert_reference(CASES[name])


@pytest.mark.parametrize('name', MATH_GLYPHS_ONLY)
def test_math_cell_lastbox_glyphs(name):
    case = CASES[name]
    job = TeXJob(StringInputSource(case['source']), DviDevice())
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        data = job.run()
    actual = walk_chars_with_positions(data, _tfm_width()) if data else []
    assert [[list(g) for g in page] for page in actual] == case['ref']['glyphs']
