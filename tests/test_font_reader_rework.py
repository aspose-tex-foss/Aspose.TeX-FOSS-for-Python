""" B1/B2: measured live reader precedence and frozen selector printing."""
import json
from pathlib import Path

import pytest

from aspose_tex._fonts.font_manager import FontManager, resolve_font_cs
from tests.test_plain_tie import _run

_DIR = Path(__file__).parents[1] / 'testdata/reference/font_reader'
_REVIEW = json.loads((_DIR / 'reference.json').read_text())


@pytest.mark.parametrize('name', list(_REVIEW))
def test_exact_independent_review_witnesses(name):
    row = _REVIEW[name]
    assert [m for m in _run(row['source']).messages if m.startswith('R[')] == row['miktex']


@pytest.mark.parametrize('name', ['font', 'textfont', 'scriptfont', 'scriptscriptfont', 'nullfont'])
def test_string_resolver_preserves_live_binding_identity(name):
    fonts = FontManager()
    fonts.load_font('selected', 'cmr10')
    fonts.select_font('selected')
    fonts.load_font(name, 'cmr17')
    assert resolve_font_cs(fonts, name) == fonts.font_id(name)


def test_empty_font_identifier_is_printable_without_changing_binding_name():
    fonts = FontManager()
    fonts.load_font('', 'cmr10')
    assert fonts.font_id_text(fonts.font_id('')) == 'FONT'
    assert not fonts.is_font('FONT')
_REWORK = json.loads((_DIR / 'extended_reference.json').read_text())


@pytest.mark.parametrize('name', [n for n in _REWORK if n not in _REVIEW])
def test_adversarial_reader_and_printer_matrix(name):
    row = _REWORK[name]
    assert row['match'] and not row['errors']
    assert [m for m in _run(row['source']).messages if m.startswith('R[')] == row['miktex']
