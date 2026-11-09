"""paragraph geometry and true display-entry boundary.

All numeric output expectations are MiKTeX measurements.
"""

import dataclasses
import json
import re
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from aspose_tex import DviDevice, PdfDevice, StringInputSource, SvgDevice, TeXJob
from aspose_tex._engine.linebreak import LinebreakParams, _line_geometry, break_paragraph
from aspose_tex._engine.nodes import GlueNode, HlistNode, PenaltyNode
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._fonts.font_manager import FontManager
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_linebreak import _word_box
from tests.test_linebreak_math_and_hyphen import _run
from tests.test_plain_tie import _tfm_width

ROWS = json.loads((Path(__file__).parents[1] / "testdata/baselines/paragraph-shapes.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["name"])
def test_fresh_miktex_shapes_and_display_entry(row):
    job = TeXJob(StringInputSource(row["source"]), DviDevice())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = job.run()
    pages = walk_chars_with_positions(dvi, _tfm_width()) if dvi else []
    assert len(pages) == len(row["glyphs"])
    for ours, reference in zip(pages, row["glyphs"], strict=True):
        assert len(ours) == len(reference)
        for (c, h, v), (rc, rh, rv) in zip(ours, reference, strict=True):
            assert c == rc
            assert abs(h - rh) <= 6554
            if row["name"] in ("display_overflow", "overflow_rectangular"):
                assert h == rh  # never relaxes the changed horizontal geometry.
            if row["name"] in ("display_overflow", "overflow_rectangular"):
                assert v == rv  # resolves's vertical ownership.
            else:
                assert abs(v - rv) <= 32768
    for msg in row["messages"]:
        assert msg in job.messages


def test_overflow_vertical_spacing_matches_miktex():
    row = next(r for r in ROWS if r["name"] == "display_overflow")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = TeXJob(StringInputSource(row["source"]), DviDevice()).run()
    ours = walk_chars_with_positions(dvi, _tfm_width())[0]
    assert [v for _c, _h, v in ours] == [v for _c, _h, v in row["glyphs"][0]]


def params(**kw):
    g = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
    return LinebreakParams(100 * 65536, 10000, 10000, 10, 10000, g, g, g, **kw)


@pytest.mark.parametrize(
    "indent,after,expected",
    [
        (20, 1, [(0, 100), (20, 80), (20, 80), (20, 80)]),
        (-20, 1, [(0, 100), (0, 80), (0, 80), (0, 80)]),
        (20, -2, [(20, 80), (20, 80), (0, 100), (0, 100)]),
        (-20, -2, [(0, 80), (0, 80), (0, 100), (0, 100)]),
        (20, 0, [(20, 80)] * 4),
        (0, -2, [(0, 100)] * 4),
    ],
)
def test_hanging_line_boxes(indent, after, expected):
    # Width/shift values measured with \showbox, not glyph offsets.
    interp = _run(
        r"\setbox0\vbox{\hsize100pt\parindent0pt"
        + rf"\hangindent{indent}pt\hangafter{after}"
        + r"\noindent A\hfil\break B\hfil\break C\hfil\break D\par}"
    )
    lines = [n for n in interp._box_regs.getbox(0).list if isinstance(n, HlistNode)]
    assert [(n.shift_amount, n.width) for n in lines] == [(i * 65536, w * 65536) for i, w in expected]


def test_geometry_snapshot_and_repeated_tail():
    p = params(hangindent=40 * 65536, parshape=((-5 * 65536, 90 * 65536), (15 * 65536, 70 * 65536)))
    assert [_line_geometry(p, i) for i in (1, 2, 3, 7)] == [p.parshape[0], p.parshape[1], p.parshape[1], p.parshape[1]]
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.hangindent = 1
    with pytest.raises(ValueError):
        _line_geometry(p, 0)
    assert _line_geometry(params(parshape=((-7, -10),)), 3) == (-7, -10)


def test_live_snapshot_has_no_mutable_shape_alias():
    interp = _run(r"\hangindent20pt\hangafter-2\parshape1 7pt 83pt")
    snapshot = interp._linebreak_params()
    interp._parshape[0] = (0, 0)
    assert snapshot.parshape == ((7 * 65536, 83 * 65536),)
    assert snapshot.hangindent == 20 * 65536
    assert snapshot.hangafter == -2


@pytest.mark.parametrize(
    "widths,shape,counts",
    [
        ([24, 24, 20, 9, 18, 17, 21, 16, 20, 22, 24, 11], [73, 57, 40, 37], [2, 3, 2, 2, 1, 2]),
        ([24, 14, 10, 18, 25, 25, 17, 26, 18], [60], [3, 2, 2, 2]),
    ],
)
def test_dp_retains_geometry_and_fitness_histories(widths, shape, counts):
    # Fresh MiKTeX dp_geometry / dp_fitness: the position-only implementation
    # chooses ABC / DE instead of AB / CDE in the first witness, and AB / CDE
    # instead of ABC / DE in the second. Both finish at the same breakpoint.
    nodes = []
    for width in widths:
        nodes.extend(
            [
                _word_box(width * 65536),
                GlueNode(Glue(3 * 65536, 3 * 65536, GlueOrder.NORMAL, 2 * 65536, GlueOrder.NORMAL)),
            ]
        )
    nodes[-1] = GlueNode(Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL))
    nodes.append(PenaltyNode(-10000))
    p = params(parshape=tuple((0, w * 65536) for w in shape))
    lines = break_paragraph(nodes, p, FontManager())
    assert [sum(isinstance(n, HlistNode) for n in line.list) for line in lines] == counts


def test_resumed_absolute_geometry_and_skip_inside_width():
    # A display after a void \parshape resumes at absolute line four.
    p = dataclasses.replace(
        params(
            parshape=((65536, 91 * 65536), (2 * 65536, 82 * 65536), (3 * 65536, 73 * 65536), (4 * 65536, 64 * 65536))
        ),
        prevgraf=3,
        leftskip=Glue(2 * 65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
    )
    nodes = [_word_box(7 * 65536), GlueNode(Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)), PenaltyNode(-10000)]
    line = break_paragraph(nodes, p, FontManager())[0]
    assert (line.shift_amount, line.width) == (4 * 65536, 64 * 65536)
    assert line.list[0].glue.width == 2 * 65536


def test_shaped_discretionary_history_keeps_final_hyphen_charge():
    from aspose_tex._engine.nodes import DiscretionaryNode
    from tests.test_linebreak_math_and_hyphen import _box, _demerits, _params

    nodes = [
        _box(100),
        DiscretionaryNode(pre=(), post=(), nobreak=()),
        _box(60),
        GlueNode(Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)),
        _box(40),
        PenaltyNode(10000),
        GlueNode(Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
        PenaltyNode(-10000),
    ]
    p = _params(parshape=((7, 100), (9, 100)))
    assert _demerits(nodes, dataclasses.replace(p, finalhyphendemerits=5000)) - _demerits(nodes, p) == 5000


# PDF/SVG write big points; a TeX pt is 72.27/72 bp smaller.
_SP_PER_BP = 65536 * 72.27 / 72


@pytest.mark.parametrize("name", ["shape_repeat", "display_multiple", "display_negative_shift"])
def test_composed_geometry_in_pdf_and_svg(name):
    row = next(r for r in ROWS if r["name"] == name)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pdf = TeXJob(StringInputSource(row["source"]), PdfDevice()).run()
        svg = TeXJob(StringInputSource(row["source"]), SvgDevice()).run()
    uses = ET.fromstring(svg).findall(".//{http://www.w3.org/2000/svg}use")
    runs = re.findall(rb"([\d.-]+) ([\d.-]+) Td\n\(([A-Za-z])\) Tj", pdf)
    reference = row["glyphs"][0]
    assert len(uses) == len(runs) == len(reference)
    for use, (x, y, code), (c, h, v) in zip(uses, runs, reference, strict=True):
        assert code[0] == c
        assert abs(float(use.get("x")) - (72 + h / _SP_PER_BP)) <= 0.1
        assert abs(float(use.get("y")) - (72 + v / _SP_PER_BP)) <= 0.5
        assert abs(float(x) - (72 + h / _SP_PER_BP)) <= 0.1
        assert abs(float(y) - (720 - v / _SP_PER_BP)) <= 0.5
