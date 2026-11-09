"""Persistent font regressions; expected values measured by a reference probe"""
from __future__ import annotations

import importlib.resources
import json
from pathlib import Path

import pytest

from aspose_tex._engine.group import GroupKind, GroupStack
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex.exceptions import FontError
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _run, _tfm_width

_REFERENCE = json.loads((Path(__file__).parents[1] / 'testdata/reference/assignment_scope/baseline.json').read_text())
_CASES = [k for k in _REFERENCE if k.startswith('font_')]
_READER_REFERENCE = json.loads(
    (Path(__file__).parents[1] / 'testdata/reference/assignment_scope/reference.json').read_text()
)


@pytest.mark.parametrize('name', _CASES)
def test_measured_font_context(name):
    row = _REFERENCE[name]
    job = _run(row['source'])
    assert [m for m in job.messages if m.startswith('R[')] == row['miktex']
    if 'miktex_glyphs' in row:
        actual = walk_chars_with_positions(job._dvi, _tfm_width())
        assert json.loads(json.dumps(actual)) == row['miktex_glyphs']


@pytest.mark.parametrize('name', [k for k in _READER_REFERENCE if not k.startswith(('scope_', 'inline_'))])
def test_frozen_readers_and_composed_glyphs(name):
    row = _READER_REFERENCE[name]
    job = _run(row['source'])
    assert [m for m in job.messages if m.startswith('R[')] == row['miktex']
    if 'miktex_glyphs' in row:
        assert json.loads(json.dumps(walk_chars_with_positions(job._dvi, _tfm_width()))) == row['miktex_glyphs']


def test_distinct_resolved_sources_and_normalized_paths(tmp_path):
    raw = (importlib.resources.files('aspose_tex') / 'data/fonts/cmr10.tfm').read_bytes()
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.mkdir()
    b.mkdir()
    for directory in (a, b):
        (directory / 'same.tfm').write_bytes(raw)
    fonts = FontManager()
    fonts.load_font('a', str(a / 'same'))
    fonts.load_font('alias', str(a / '.' / 'same'))
    fonts.load_font('b', str(b / 'same'))
    assert fonts.font_id('a') == fonts.font_id('alias')
    assert fonts.font_id('a') != fonts.font_id('b')
    fonts.set_fontdimen('a', 2, 123)
    assert fonts.fontdimen('b', 2) != 123


@pytest.mark.parametrize('backend', ['pdf', 'svg'])
def test_lazy_resources_survive_two_pages_of_name_reuse(backend):
    import re
    import xml.etree.ElementTree as ET

    from aspose_tex import PdfDevice, StringInputSource, SvgDevice, TeXJob, TeXOptions
    from tests.test_output_pdf_writer import _find_page_objects, _parse_pdf_objects, _read_content_stream
    row = _READER_REFERENCE['glyph_boxes_pages']
    device = PdfDevice() if backend == 'pdf' else SvgDevice()
    data = TeXJob(StringInputSource(row['source']), device, options=TeXOptions()).run()
    if backend == 'pdf':
        # Both original cmr10 and rebound cmr17 are embedded once, across pages.
        assert b'/BaseFont /CMR10' in data and b'/BaseFont /CMR17' in data
        pages = _find_page_objects(_parse_pdf_objects(data))
        assert len(pages) == 2
        streams = [_read_content_stream(data, int(re.search(rb'/Contents (\d+) 0 R', page).group(1)))
                   for _, page in pages]
        assert any(b'/F1 ' in stream for stream in streams)
        assert any(b'/F2 ' in stream for stream in streams)
        assert b'\x00font:' not in data
    else:
        pages = device.get_all_pages()
        assert len(pages) == 2
        for page in pages:
            root = ET.fromstring(page)
            uses = root.findall('.//{http://www.w3.org/2000/svg}use')
            refs = [u.attrib['{http://www.w3.org/1999/xlink}href'] for u in uses]
            assert any('cmr10' in ref for ref in refs)
            assert any('cmr17' in ref for ref in refs)
            assert b'\x00font:' not in page
            assert all(re.fullmatch(r'#[A-Za-z0-9_-]+', ref) for ref in refs)


def test_bindings_restore_without_destroying_loaded_font():
    gs = GroupStack()
    fonts = FontManager(group_stack=gs)
    fonts.load_font('old', 'cmr10')
    key = fonts.font_id('old')
    gs.open_group(GroupKind.BRACE)
    fonts.load_font('local', 'cmr10')
    fonts.alias_font('copy', 'local')
    fonts.select_font('local')
    gs.close_group()
    assert not fonts.is_font('local') and not fonts.is_font('copy')
    assert fonts.get_metrics(key) is fonts.get_metrics('old')
    assert fonts.font_id_text(key) == 'local'


def test_interning_size_and_zero_are_distinct():
    fonts = FontManager()
    fonts.load_font('a', 'cmr10')
    fonts.load_font('b', 'cmr10.tfm', scaled=1000)
    fonts.load_font('c', 'cmr10', at_sp=655360)
    fonts.load_font('d', 'cmr10', scaled=1200)
    fonts.load_font('zero', 'cmr10', at_sp=0)
    assert fonts.font_id('a') == fonts.font_id('b') == fonts.font_id('c')
    assert fonts.font_id('a') != fonts.font_id('d')
    assert fonts.font_id('zero') != fonts.font_id('nullfont')
    assert fonts.check_character(fonts.font_id('zero'), 65)
    assert not fonts.check_character(fonts.font_id('nullfont'), 65)


def test_unselected_units_use_font_zero_after_nullfont_binding_is_replaced():
    from types import SimpleNamespace

    from aspose_tex._engine.dimparser import _current_font_dimen
    fonts = FontManager()
    zero = fonts._nullfont_id
    fonts.load_font('nullfont', 'cmr17')
    assert fonts.font_id('nullfont') != zero
    expander = SimpleNamespace(_interpreter=SimpleNamespace(_font_manager=fonts))
    assert _current_font_dimen(expander, 6) == 0
    assert fonts.font_name_text(zero) == 'nullfont'


def test_failed_load_and_unknown_key_do_not_replace_font():
    fonts = FontManager()
    fonts.load_font('a', 'cmr10')
    old = fonts.font_id('a')
    with pytest.raises(FontError):
        fonts.load_font('a', 'missing401')
    assert fonts.font_id('a') == old
    assert fonts.get_metrics('\x00font:9999') is None
    with pytest.raises(FontError):
        fonts.bind_font('a', '\x00font:9999', is_global=True)


@pytest.mark.parametrize('method,args', [('fontdimen', (2,)), ('hyphenchar', ()),
                                         ('font_id_text', ()), ('font_name_text', ())])
def test_unknown_key_diagnostics_do_not_disclose_key(method, args):
    with pytest.raises(FontError) as error:
        getattr(FontManager(), method)('\x00font:9999', *args)
    assert 'font:' not in str(error.value)


@pytest.mark.parametrize('command', [r'\csname\saved\endcsname', r'\raise1pt\saved',
                                      r'\leaders\saved\hskip1pt', r'\immediate\saved'])
def test_frozen_selector_in_wrong_operand_does_not_disclose_key(command):
    from aspose_tex.exceptions import EngineError
    with pytest.raises(EngineError) as error:
        _run(r'\edef\saved{\the\font}' + command)
    assert '\x00' not in str(error.value)
    assert 'font:' not in str(error.value)


def test_failed_assignment_retains_previous_binding_and_clears_prefix():
    from aspose_tex import DviDevice, StringInputSource
    from aspose_tex._engine.interpreter import TeXInterpreter
    interp = TeXInterpreter()
    with pytest.raises(FontError):
        interp.run_with_device(StringInputSource(r'\global\font\tenrm=missing401'), DviDevice())
    assert interp._font_manager.get_metrics('tenrm').tfm_name == 'cmr10'
    assert not interp._group_stack._global_pending


def test_expanded_font_scanner_accepts_primitive_aliases():
    job = _run(r'\let\cur=\font\let\family=\textfont'
               r'\message{R[\fontname\cur/\fontname\family0/\the\fontdimen2\cur]}')
    assert [m for m in job.messages if m.startswith('R[')] == ['R[cmr10/cmr10/3.33333pt]']
