"""measured MiKTeX adjusted/stored hbox ownership regressions."""
import json
from pathlib import Path

import pytest

from aspose_tex._fonts.font_manager import FontManager
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_e2e_dvi_baseline import _font_defs
from tests.test_plain_tie import _run, _tfm_width

REFERENCE = json.loads((Path(__file__).parents[1] / 'testdata/reference/adjusted_hbox/reference.json').read_text())


@pytest.mark.parametrize('name', REFERENCE)
def test_adjusted_hbox_matches_miktex(name):
    reference = REFERENCE[name]
    assert reference['exit'] == 0
    job = _run(reference['source'])
    actual = walk_chars_with_positions(job._dvi, _tfm_width())
    assert [[list(glyph) for glyph in page] for page in actual] == reference['glyphs']
    assert [m for m in job.messages if m.startswith('[')] == reference['messages']


def test_original_document_scaled_fonts_and_complete_positions():
    root = Path(__file__).parents[1]
    source = (root / 'testdata/e2e/tex-what-is-what.tex').read_text()
    baseline = (root / 'testdata/baselines/tex-what-is-what.miktex.dvi').read_bytes()
    job = _run(source)
    manager = FontManager()

    def width(name, code, size):
        key = f'{name}:{size}'
        if manager.get_metrics(key) is None:
            manager.load_font(key, name, at_sp=size)
        return manager.get_metrics(key).char_metrics(code).width

    actual = walk_chars_with_positions(job._dvi, scaled_char_width=width, advance_rules=True)
    expected = walk_chars_with_positions(baseline, scaled_char_width=width, advance_rules=True)
    assert len(actual) == len(expected) == 2
    assert sum(map(len, actual)) == 3649
    assert sorted(row[1:] for row in _font_defs(job._dvi)) == sorted(row[1:] for row in _font_defs(baseline))
    for page, reference in zip(actual, expected, strict=True):
        assert len(page) == len(reference)
        for (code, h, v), (rc, rh, rv) in zip(page, reference, strict=True):
            assert code == rc and abs(h - rh) <= 8 and v == rv
