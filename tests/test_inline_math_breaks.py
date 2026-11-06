r""": live tolerance and the measured fourteen inline-math widths.

Ground truth: MiKTeX 24.4, ``tex -interaction=nonstopmode`` and the DVI
walker; measured 2026-10-14. The baseline excludes plain's page number.
"""
import json
import warnings
from pathlib import Path

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob, TeXOptions
from aspose_tex._engine.linebreak import _is_legal_breakpoint
from aspose_tex._engine.nodes import DiscretionaryNode, PenaltyNode
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_linebreak_math_and_hyphen import (
    _paragraph_items,
    _penalties_after_chars,
    _run,
)
from tests.test_plain_tie import _tfm_width

_BASELINES = json.loads(
    (Path(__file__).parents[1] / "testdata/baselines/inline-breaks.json").read_text()
)


@pytest.mark.parametrize("row", _BASELINES, ids=[
    row.get("context", row["body"].split()[0]) for row in _BASELINES
])
def test_measured_inline_math_breaks(row):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = TeXJob(StringInputSource(row["body"] + r"\bye"), DviDevice(),
                     options=TeXOptions()).run()
    ours = walk_chars_with_positions(dvi, _tfm_width())[0][:-1]
    reference = row["glyphs"]
    assert len(ours) == len(reference)
    for (code, h, v), (ref_code, ref_h, ref_v) in zip(ours, reference, strict=True):
        assert code == ref_code
        assert abs(h - ref_h) <= 6554
        assert abs(v - ref_v) <= 32768


def test_tolerance_restores_after_local_assignment():
    interp = _run(r"\tolerance=10000 {\tolerance=200}\relax")
    assert interp._linebreak_params().tolerance == 10000


def test_tolerance_default_remains_plain_value():
    assert _run(r"\relax")._linebreak_params().tolerance == 200


@pytest.mark.parametrize(("source", "expected"), [
    (r"\binoppenalty=10001 A $a+b=c$ end.", [("=", 500)]),
    (r"\relpenalty=10000 A $a+b=c$ end.", [("+", 700)]),
    (r"\relpenalty=10001 A $a+b=c$ end.", [("+", 700)]),
    (r"\binoppenalty=23\relpenalty=17 A $a+b=c$ end.", [("+", 23), ("=", 17)]),
    ("A $a+,b$ end.", []),
    ("A $a=,b$ end.", [("=", 500)]),
    ("A $a+b=$ end.", [("+", 700)]),
    ("A $a+)b$ end.", []),
])
def test_miktex_measured_penalty_controls(source, expected):
    # MiKTeX showbox of a single-line vbox, 2026-10-14. Punct/Close retype
    # a preceding Bin to Ord; a Rel before Punct still gets its penalty.
    assert _penalties_after_chars(_paragraph_items(source)) == expected


def test_penalty_and_discretionary_remain_legal_inside_math():
    nodes = [PenaltyNode(500), DiscretionaryNode(pre=(), post=(), nobreak=())]
    assert _is_legal_breakpoint(nodes, 0, in_math=True)
    assert _is_legal_breakpoint(nodes, 1, in_math=True)
