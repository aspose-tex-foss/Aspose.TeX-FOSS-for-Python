""" public-job regressions pinned to architecture MiKTeX measurements."""
import json
from pathlib import Path

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob, TeXOptions
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _tfm_width

DATA = Path(__file__).resolve().parents[1] / 'testdata/reference/output_cycle_timing'
BASELINE = json.loads((DATA / 'baseline.json').read_text())
POSITIONS = json.loads((DATA / 'miktex_positions.json').read_text())


def counters(dvi: bytes) -> list[int]:
    """Read count0 via the DVI postamble and bop back-pointer chain."""
    import struct
    end = len(dvi) - 1
    while dvi[end] == 223:
        end -= 1
    post = struct.unpack('>i', dvi[end - 4:end])[0]
    bop = struct.unpack('>i', dvi[post + 1:post + 5])[0]
    pages = []
    while bop >= 0:
        pages.append(struct.unpack('>i', dvi[bop + 1:bop + 5])[0])
        bop = struct.unpack('>i', dvi[bop + 41:bop + 45])[0]
    return pages[::-1]


def run(source, load_format='plain'):
    job = TeXJob(StringInputSource(source), DviDevice(), options=TeXOptions(load_format=load_format))
    dvi = job.run()
    return job, dvi


PAGE_CASES = [name for name in BASELINE if not name.startswith(('mark_', 'ctx_'))
              and name != 'user_local_advance']


@pytest.mark.parametrize('name', PAGE_CASES)
def test_pageno_reference(name):
    assert_reference(name)


def assert_reference(name):
    row = BASELINE[name]
    job, dvi = run(row['source'])
    assert [m for m in job.messages if m.startswith('R[')] == row['miktex']
    assert counters(dvi) == row['miktex_count0']
    pages = walk_chars_with_positions(dvi, _tfm_width())
    assert [''.join(chr(c) for c, _, _ in page) for page in pages] == row['miktex_text']
    if name in POSITIONS:
        assert pages == [[tuple(g) for g in page] for page in POSITIONS[name]]


# An open residual.
@pytest.mark.xfail(strict=True, reason='Separate output-group residual')
def test_output_residual_reference():
    assert_reference('user_local_advance')


@pytest.mark.parametrize('source,expected,messages', [
    (r'{A\vfill\eject B\vfill\eject}\message{R[\the\pageno]}C\end', [1, 2, 3], ['R[3]']),
    (r'\pageno=-1 A\vfill\eject B\vfill\eject C\end', [-1, -2, -3], []),
])
def test_builtin_pageno(source, expected, messages):
    job, dvi = run(source, load_format=False)
    assert counters(dvi) == expected
    assert [m for m in job.messages if m.startswith('R[')] == messages


@pytest.mark.parametrize('name', [name for name in BASELINE if name.startswith(('mark_', 'ctx_'))])
def test_mark_reference(name):
    assert_reference(name)


def test_builtin_marks_retained_after_output():
    job, _ = run(r'\hbox{}\mark{A}\vfill\eject\message{R[\topmark:\firstmark:\botmark]}\end', load_format=False)
    assert [m for m in job.messages if m.startswith('R[')] == ['R[:A:A]']
