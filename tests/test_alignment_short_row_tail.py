r"""Short alignment rows and row-sized cells (amendments).

Every expected value is the MiKTeX 24.4 ``ref`` record of
``testdata/reference/alignment_short_rows/results.json`` (probe.py); none is computed.
"""
import json
import re
from pathlib import Path

import pytest

from aspose_tex import DviDevice
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import GlueNode, HlistNode, VlistNode
from aspose_tex._input.reader import StringInputSource
from tests.test_alignment_halign import _FONT_PREAMBLE
from tests.test_alignment_noalign_execution import assert_reference

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads(
    (ROOT / 'testdata/reference/alignment_short_rows/results.json').read_text(encoding='utf-8')
)

BORDERMATRIX = [name for name in CASES if name.startswith('bm_')]
ROWS = [name for name in CASES if name.startswith('row_')]
RULES = [name for name in CASES if name.startswith('rule_')]
COLUMNS = [name for name in CASES if name.startswith('col_')]


def test_context_inventory():
    assert len(BORDERMATRIX) == 12
    assert len(ROWS) == 11
    assert len(RULES) == 6
    assert len(COLUMNS) == 5


@pytest.mark.parametrize('name', BORDERMATRIX)
def test_bordermatrix_context(name):
    assert_reference(CASES[name])


def test_bordermatrix_uses_the_small_delimiter():
    # The defect's visible symptom: cmex size-variant parentheses (0x12/0x13),
    # not the extensible pieces that wrapped the border row and column.
    codes = [code for code, _h, _v in CASES['bm_display']['ref']['glyphs'][0]]
    assert (codes[0], codes[-1]) == (0x12, 0x13)
    assert_reference(CASES['bm_display'])


@pytest.mark.parametrize('name', ROWS)
def test_short_row_tail(name):
    assert_reference(CASES[name])


@pytest.mark.parametrize('name', RULES)
def test_cell_takes_the_row_or_column_extent(name):
    assert_reference(CASES[name])


def _measured(case, key):
    """Return the value of the ``[key=...]`` message of a MiKTeX record."""
    prefix = f'[{key}='
    (value,) = [m[len(prefix):-1] for m in case['ref']['messages'] if m.startswith(prefix)]
    return value


def _last_column(box):
    """Return the last column of a ``\\valign`` box.

    The alignment arrives wrapped in one hbox until splices it into the
    enclosing list, so the descent accepts both shapes.
    """
    while isinstance(box, HlistNode):
        box = box.list[-1]
    assert isinstance(box, VlistNode)
    return box


@pytest.mark.parametrize('name', COLUMNS)
def test_short_column_tail(name):
    # \lastbox cannot reach the column before: read it from the register.
    case = CASES[name]
    source = re.sub(r'\\setbox1\\lastbox.*\}\\bye$', r'}\\bye', case['source'])
    source = source.replace(r'\nopagenumbers ', _FONT_PREAMBLE)
    interp = TeXInterpreter()
    interp.run_with_device(StringInputSource(source), DviDevice())
    column = _last_column(interp._box_regs.getbox(0))

    width, height, depth = (int(v) for v in _measured(case, 'col').split(','))
    assert (column.width, column.height, column.depth) == (width, height, depth)

    tail, cell = column.list[-1], column.list[-2]
    assert isinstance(tail, GlueNode)
    assert tail.glue.width == int(_measured(case, 'skipsp'))
    cell_width, cell_height, cell_depth = (int(v) for v in _measured(case, 'cell').split(','))
    assert (cell.width, cell.height, cell.depth) == (cell_width, cell_height, cell_depth)
