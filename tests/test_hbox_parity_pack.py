""": box construction, measured against MiKTeX."""
import json
import warnings
from pathlib import Path

import pytest

from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _run, _tfm_width

REFERENCE = json.loads((Path(__file__).parents[1] / 'testdata/reference/hbox_parity/reference.json').read_text())


@pytest.mark.parametrize('name', [n for n in REFERENCE if n.startswith('hfilneg')])
def test_hfilneg_matches_miktex(name):
    reference = REFERENCE[name]
    job = _run(reference['source'][:-4])
    actual = walk_chars_with_positions(job._dvi, _tfm_width())
    assert [[list(g) for g in page] for page in actual] == reference['glyphs']


@pytest.mark.parametrize('name', [n for n in REFERENCE if n.startswith('every_')])
def test_everyhbox_matches_miktex(name):
    reference = REFERENCE[name]
    job = _run(reference['source'][:-4])
    actual = walk_chars_with_positions(job._dvi, _tfm_width())
    assert [[list(g) for g in page] for page in actual] == reference['glyphs']
    assert [m for m in job.messages if m.startswith(('[marks=', '[saved]'))] == reference['messages']


def test_negative_shrink_matches_miktex():
    from aspose_tex import DviDevice, StringInputSource, TeXJob

    reference = REFERENCE['negative_shrink']
    job = TeXJob(StringInputSource(reference['source']), DviDevice())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        data = job.run()
    actual = walk_chars_with_positions(data, _tfm_width())
    assert [[list(g) for g in page] for page in actual] == reference['glyphs']
    assert [str(w.message) for w in caught] == ['Overfull \\hbox (12.3334pt too wide)']


@pytest.mark.parametrize('name', ['display_report', 'alignment_report', 'deferred_report'])
@pytest.mark.parametrize('suppression', ['', r'\hfuzz=1000pt', r'\hbadness=10000'])
def test_box_reports_match_miktex_without_changing_dvi(name, suppression):
    from aspose_tex import DviDevice, StringInputSource, TeXJob

    reference = REFERENCE[name]
    job = TeXJob(StringInputSource(suppression + reference['source']), DviDevice())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        data = job.run()
    actual = walk_chars_with_positions(data, _tfm_width())
    assert [[list(g) for g in page] for page in actual] == reference['glyphs']
    reports = [str(w.message) for w in caught if 'Overfull \\hbox' in str(w.message)]
    expected = reference['reports'][0].split(' at line')[0].split(' detected')[0]
    assert reports == ([] if suppression.startswith(r'\hfuzz') else [expected])


@pytest.mark.parametrize('name', [n for n in REFERENCE if n.startswith('split_')])
def test_vsplit_geometry_and_marks_match_miktex(name):
    reference = REFERENCE[name]
    job = _run(reference['source'][:-4])
    actual = walk_chars_with_positions(job._dvi, _tfm_width())
    assert [[list(g) for g in page] for page in actual] == reference['glyphs']
    assert [m for m in job.messages if m.startswith(('[split=', '[marks='))] == reference['messages']


@pytest.mark.parametrize('name', [
    'negative_shrink_deferred', 'shrink_zero_sum', 'shrink_infinite_negative',
    'negative_shrink_vbox', 'display_fuzz', 'alignment_fuzz', 'deferred_fuzz',
])
def test_glue_and_report_controls_match_miktex(name):
    from aspose_tex import DviDevice, StringInputSource, TeXJob

    reference = REFERENCE[name]
    assert reference['exit'] == 0
    job = TeXJob(StringInputSource(reference['source']), DviDevice())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        data = job.run()
    actual = walk_chars_with_positions(data, _tfm_width())
    assert [[list(g) for g in page] for page in actual] == reference['glyphs']
    expected = [r.split(' at line')[0].split(' detected')[0] for r in reference['reports']]
    assert [str(w.message) for w in caught if 'Overfull \\hbox' in str(w.message)] == expected
