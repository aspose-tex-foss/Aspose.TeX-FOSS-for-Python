""" complete MiKTeX glyph and display-entry regression oracles."""
import json
import warnings
from pathlib import Path

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob
from aspose_tex._engine.nodes import GlueNode, HlistNode, PenaltyNode
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_linebreak_math_and_hyphen import _run
from tests.test_plain_tie import _tfm_width

ROWS = json.loads(
    (Path(__file__).parents[1] / "testdata/reference/display_overflow/reference.json").read_text(encoding="utf-8"))
REVIEW_ROWS = json.loads(
    (Path(__file__).parents[1] / "testdata/reference/display_overflow/extended_reference.json")
    .read_text(encoding="utf-8")
)


@pytest.mark.parametrize("row", ROWS + REVIEW_ROWS, ids=lambda row: row["name"])
def test_measured_display(row):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job = TeXJob(StringInputSource(row["source"]), DviDevice())
        data = job.run()
    pages = walk_chars_with_positions(data, _tfm_width())
    assert [[list(g) for g in page] for page in pages] == row["glyphs"]
    for message in row["messages"]:
        assert message in job.messages


@pytest.mark.parametrize(("line", "pre"), [
    #, §1146: v starts at two quads (20pt) and stops growing at
    # \maxdimen; a later visible node then gives exactly \maxdimen.
    (r"\kern\maxdimen\kern-\maxdimen\hbox{}", "16383.99998pt"),
    (r"\kern16370pt\kern-100pt\hbox{}", "16383.99998pt"),
    (r"\kern16363.99998pt\hbox{}", "16383.99998pt"),
    (r"\kern8191.99998pt\kern8191pt\hbox{}", "16383.99998pt"),
    # The visible node that crosses \maxdimen keeps the full sum: no clamp.
    (r"\hbox to\maxdimen{}\kern-\maxdimen", "16404.00002pt"),
    # ordinary and negative-width controls
    (r"ab", "30.55562pt"),
    (r"\kern-30pt ab", "0.55562pt"),
])
def test_predisplaysize_saturates_like_tex(line, pre):
    # Expected values: MiKTeX 24.4 plain, measured 2026-10-29.
    hsize = "100pt" if line.endswith("ab") else "50pt"
    source = (r"\nopagenumbers\parindent0pt\hsize" + hsize
              + r"\everydisplay{\message{[PRE=\the\predisplaysize]}}\noindent " + line
              + "$$z$$ Q\\par\n\\bye\n")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job = TeXJob(StringInputSource(source), DviDevice())
        job.run()
    assert [m for m in job.messages if m.startswith("[PRE=")] == [f"[PRE={pre}]"]


@pytest.mark.parametrize("side", ["eqno", "leqno"])
@pytest.mark.parametrize("number", ["(1)", r"\hbox to0pt{(1)\hss}"])
def test_direct_number_contributions(side, number):
    source = (r"\setbox0\vbox{\hsize40pt\parindent0pt\predisplaypenalty17"
              r"\postdisplaypenalty23\noindent A$$abcdefgh" + "\\" + side + number + r"$$}")
    nodes = _run(source)._box_regs.getbox(0).list
    start = next(i for i, n in enumerate(nodes) if isinstance(n, PenaltyNode) and n.penalty == 17)
    end = next(i for i, n in enumerate(nodes) if isinstance(n, PenaltyNode) and n.penalty == 23)
    material = nodes[start + 1:end]
    boxes = [n for n in material if isinstance(n, HlistNode)]
    assert len(boxes) == 2
    assert sum(isinstance(n, PenaltyNode) and n.penalty == 10000 for n in material) == 1
    if side == "leqno":
        # Only baseline glue precedes the number; no 12pt display skip.
        assert [n.glue.width for n in material[:material.index(boxes[0])] if isinstance(n, GlueNode)] == [294912]
        assert isinstance(nodes[end + 1], GlueNode)  # below skip retained
    else:
        assert isinstance(material[0], GlueNode)  # above skip retained
        assert end == len(nodes) - 1  # no below skip


@pytest.mark.parametrize("shrink, beside", [
    ("0pt", False), ("5pt", False), ("20pt", True), ("40pt", True),
    ("1fil", True), ("1fill", True), ("1filll", True),
])
def test_squeeze_uses_top_level_shrink(shrink, beside):
    interp = _run(r"\setbox0\vbox{\predisplaypenalty17\noindent A$$\hbox to460pt{a\hfil}"
                  r"\hskip0pt minus" + shrink + r"\eqno(1)$$}")
    nodes = interp._box_regs.getbox(0).list
    # The hfil inside the fixed 460pt hbox is not shrink for the formula.
    assert (not any(isinstance(n, PenaltyNode) and n.penalty == 10000 for n in nodes)) == beside
