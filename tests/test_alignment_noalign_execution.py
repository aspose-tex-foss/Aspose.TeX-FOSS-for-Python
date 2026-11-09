"""Ordinary noalign execution against fresh MiKTeX measurements."""
import json
import warnings
from pathlib import Path

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob
from aspose_tex.exceptions import EngineError
from tests._verification.dvi_walker import walk_chars_with_positions, walk_rules
from tests.test_plain_tie import _tfm_width

ROOT = Path(__file__).resolve().parents[1]
BASE_CASES = json.loads((ROOT / 'testdata/reference/noalign_execution/results.json').read_text())
EXTRA = json.loads((ROOT / 'testdata/reference/noalign_execution/measurements.json').read_text())
OWNERS = json.loads((ROOT / 'testdata/reference/noalign_execution/document_measurements.json').read_text())


def assert_reference(case):
    """Compare complete glyph coordinates and every measured diagnostic."""
    job = TeXJob(StringInputSource(case['source']), DviDevice())
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        data = job.run()
    assert [m for m in job.messages if m.startswith('[')] == case['ref']['messages']
    actual = walk_chars_with_positions(data, _tfm_width()) if data else []
    assert [[list(g) for g in page] for page in actual] == case['ref'].get('glyphs', [])
    if 'rules' in case['ref']:
        rules = walk_rules(data) if data else []
        assert [[list(r) for r in page] for page in rules] == case['ref']['rules']


@pytest.mark.parametrize('name', [n for n in BASE_CASES if not n.startswith('span_') and n != 'valign_wrong_prevdepth'])
def test_base_context(name):
    assert_reference(BASE_CASES[name])


@pytest.mark.parametrize('name', [n for n in EXTRA if not n.startswith('span_')])
def test_additional_measured_context(name):
    assert_reference(EXTRA[name])


@pytest.mark.parametrize('name', OWNERS)
def test_ordinary_list_ownership_context(name):
    assert_reference(OWNERS[name])


def test_valign_rejects_vertical_prevdepth():
    with pytest.raises(EngineError, match=r'prevdepth.*vertical'):
        TeXJob(StringInputSource(BASE_CASES['valign_wrong_prevdepth']['source']), DviDevice()).run()


@pytest.mark.parametrize('body', [r'\begingroup}', r'$x}', r'\endgroup}', r'\hbox{M', r'{\aftergroup\relax'])
def test_malformed_body_rejected(body):
    with pytest.raises(EngineError):
        TeXJob(StringInputSource(r'\halign{#\cr a\cr\noalign{' + body), DviDevice()).run()


@pytest.mark.parametrize('vertical', [False, True])
@pytest.mark.parametrize('body', [r'\begingroup}', r'\endgroup}', r'\hbox{M', r'{\aftergroup\relax'])
def test_failed_scan_restores_enclosing_owners(monkeypatch, vertical, body):
    import aspose_tex._engine.alignment as alignment

    original = alignment._scan_noalign
    checked = []

    def scan(interpreter, **kwargs):
        names = ('_par_list', '_math_builder', '_prev_depth', '_spacefactor', '_prev_graf', '_last_paragraph_line')
        before = {name: getattr(interpreter, name) for name in names}
        depths = (interpreter._mode_stack.depth, interpreter._group_stack.depth,
                  len(interpreter._box_construction_stack), len(interpreter._tail_providers))
        with pytest.raises(EngineError):
            original(interpreter, **kwargs)
        assert {name: getattr(interpreter, name) for name in names} == before
        assert (interpreter._mode_stack.depth, interpreter._group_stack.depth,
                len(interpreter._box_construction_stack), len(interpreter._tail_providers)) == depths
        checked.append(True)
        raise EngineError('checked cleanup')

    monkeypatch.setattr(alignment, '_scan_noalign', scan)
    prefix = r'\valign{#\cr\hbox{A}\cr' if vertical else r'\halign{#\cr a\cr'
    with pytest.raises(EngineError, match='checked cleanup'):
        TeXJob(StringInputSource(prefix + r'\noalign{' + body), DviDevice()).run()
    assert checked == [True]


def test_collection_preserves_carriers_without_page_writes(monkeypatch):
    import aspose_tex._engine.alignment as alignment
    from aspose_tex._engine.nodes import InsertNode, MarkNode

    original = alignment._scan_noalign
    records = []

    def scan(interpreter, **kwargs):
        page = interpreter._page_builder
        before = (page._prev_depth, list(page._contrib))
        record = original(interpreter, **kwargs)
        assert (page._prev_depth, list(page._contrib)) == before
        records.append(record)
        return record

    monkeypatch.setattr(alignment, '_scan_noalign', scan)
    assert_reference(BASE_CASES['mark_insert'])
    assert any(isinstance(node, MarkNode) for node in records[0].nodes)
    assert any(isinstance(node, InsertNode) for node in records[0].nodes)


@pytest.mark.parametrize('failed', [False, True])
def test_unset_row_barrier_never_leaks(monkeypatch, failed):
    import aspose_tex._engine.alignment as alignment
    from aspose_tex._engine.nodes import NODE_TYPES

    original = alignment._scan_noalign
    records = []

    def scan(interpreter, **kwargs):
        record = kwargs['previous']
        records.append(record)
        try:
            return original(interpreter, **kwargs)
        finally:
            assert all(isinstance(node, NODE_TYPES) for node in record.nodes)

    monkeypatch.setattr(alignment, '_scan_noalign', scan)
    source = (r'\halign{#\cr a\cr\noalign{\begingroup}' if failed else
              r'\halign{#\cr a\cr\noalign{\parskip=3pt\noindent middle}b\cr}\bye')
    if failed:
        with pytest.raises(EngineError):
            TeXJob(StringInputSource(source), DviDevice()).run()
    else:
        TeXJob(StringInputSource(source), DviDevice()).run()
    assert records
    assert all(isinstance(node, NODE_TYPES) for record in records for node in record.nodes)
