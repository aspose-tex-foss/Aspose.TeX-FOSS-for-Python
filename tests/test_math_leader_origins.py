"""Fresh whole-nucleus ownership oracle."""
import json
from pathlib import Path

import pytest

from aspose_tex import DviDevice, SvgDevice
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_leaders_shipout import _compile
from tests.test_plain_tie import _tfm_width

REFERENCE = json.loads(
    (Path(__file__).parents[1] / "testdata/reference/math_brace_leaders/origin_reference.json").read_text())


@pytest.mark.parametrize("name", REFERENCE)
@pytest.mark.parametrize("backend", ["dvi", "svg"])
def test_whole_nucleus_leader_grid_and_running_rules(name, backend):
    row = REFERENCE[name]
    device = DviDevice() if backend == "dvi" else SvgDevice()
    data = _compile(r"\nopagenumbers " + row["tex"], device)
    expected_glyphs = [tuple(g) for page in row["glyphs"] for g in page]
    expected_rules = [tuple(r) for r in row["rules"]]
    if backend == "dvi":
        rules = []
        glyphs = walk_chars_with_positions(data, _tfm_width(), advance_rules=True, rule_events=rules)
        assert [g for page in glyphs for g in page] == expected_glyphs
        assert rules == expected_rules
    else:
        writer = device._backend
        assert [(c, h, v) for _, c, h, v in writer._char_placements] == expected_glyphs
        assert writer._rule_placements == [(h, v-height, width, height) for h, v, height, width in expected_rules]
