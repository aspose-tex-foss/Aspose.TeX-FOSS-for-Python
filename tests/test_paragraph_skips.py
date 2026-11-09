"""live paragraph side glue, measured against fresh MiKTeX."""
import json
import warnings
from pathlib import Path

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob
from aspose_tex._engine.linebreak import LinebreakParams
from aspose_tex._engine.nodes import CharNode, GlueNode, HlistNode, PenaltyNode
from aspose_tex._engine.par_primitives import ParagraphList, exec_par, make_hfilneg_glue
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._fonts.font_manager import FontManager
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_linebreak_math_and_hyphen import _run
from tests.test_plain_tie import _tfm_width

ROWS = json.loads(
    (Path(__file__).parents[1] / "testdata/reference/paragraph_skips/reference.json").read_text(encoding="utf-8"))
CONTROL_ROWS = json.loads(
    (Path(__file__).parents[1] / "testdata/reference/paragraph_skips/control_reference.json")
    .read_text(encoding="utf-8"))
EXTENDED_ROWS = json.loads(
    (Path(__file__).parents[1] / "testdata/reference/paragraph_skips/extended_reference.json")
    .read_text(encoding="utf-8"))


@pytest.mark.parametrize("row", ROWS + CONTROL_ROWS + EXTENDED_ROWS, ids=lambda row: row["name"])
def test_live_skips_match_fresh_miktex(row):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job = TeXJob(StringInputSource(row["source"]), DviDevice())
        ours = walk_chars_with_positions(job.run(), _tfm_width())
    assert len(ours) == len(row["glyphs"])
    for page, expected in zip(ours, row["glyphs"], strict=True):
        assert len(page) == len(expected)
        for (c, h, v), (rc, rh, rv) in zip(page, expected, strict=True):
            assert c == rc
            assert v == rv
            assert abs(h - rh) <= 2  # Existing binary32 packing/rounding boundary.
    if row["name"] == "simple_skips":
        assert ours == [[(65, 131072, 655360), (66, 131072, 1441792)]]
    if row["name"] == "read":
        assert "[SKIP=2.0pt plus 3.0pt minus 1.0pt;4.0pt plus 1.0fil]" in job.messages


def test_snapshot_preserves_all_glue_components_and_group_restore():
    interp = _run(r"\leftskip2pt plus3fill minus1pt\rightskip-4pt plus5fil minus6pt"
                  r"{\leftskip9pt\rightskip10pt}")
    snapshot = interp._linebreak_params()
    assert snapshot.leftskip == Glue(131072, 196608, GlueOrder.FILL, 65536, GlueOrder.NORMAL)
    assert snapshot.rightskip == Glue(-262144, 327680, GlueOrder.FIL, 393216, GlueOrder.NORMAL)


def test_paragraph_end_uses_late_glue_and_preserves_line_box_width():
    interp = _run(r"\setbox0\vbox{\hsize100pt\parindent0pt\noindent A\hfil\break B"
                  r"\leftskip2pt\rightskip3pt\par}")
    lines = [n for n in interp._box_regs.getbox(0).list if isinstance(n, HlistNode)]
    assert len(lines) == 2
    for line in lines:
        assert line.width == 6553600
        assert line.shift_amount == 0
        assert isinstance(line.list[0], GlueNode)
        assert line.list[0].glue.width == 131072
        assert isinstance(line.list[-1], GlueNode)
        assert line.list[-1].glue.width == 196608


@pytest.mark.parametrize("cancel", [False, True])
def test_direct_params_keep_measured_wraps_and_empty_lines(cancel):
    zero = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
    fil = Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)
    params = LinebreakParams((120 if cancel else 40) * 65536, 200, 100, 10, 10000,
                            fil if cancel else zero, fil, fil)
    fm = FontManager()
    fm.load_font("tenrm", "cmr10")
    fm.select_font("tenrm")
    paragraph = ParagraphList()
    if cancel:
        nodes = [CharNode(65, "tenrm"), make_hfilneg_glue(), make_hfilneg_glue(),
                 PenaltyNode(-10000), CharNode(66, "tenrm")]
    else:
        nodes = []
        for c in "ABCDEF":
            if nodes:
                nodes.append(GlueNode(Glue(655360, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
            nodes.append(CharNode(ord(c), "tenrm"))
    for node in nodes:
        paragraph.append(node)
    lines = exec_par(paragraph, params, fm)
    actual = [[n.char for n in line.list if isinstance(n, CharNode)] for line in lines]
    if cancel:
        assert actual == [[65], [], [66]]  # Measured cancellation witness.
    else:
        row = next(r for r in EXTENDED_ROWS if r["name"] == "direct_side_stretch")
        expected = {}
        for c, _h, v in row["glyphs"][0]:
            expected.setdefault(v, []).append(c)
        assert actual == list(expected.values())
