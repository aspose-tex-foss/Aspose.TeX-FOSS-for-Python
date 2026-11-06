"""Measured binary32 glue arithmetic (, MiKTeX §109)."""
import json
from pathlib import Path

import pytest

from aspose_tex._engine.nodes import GlueSign, HlistNode
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._engine.tex_arith import glue_ratio, tex_round, to_binary32
from aspose_tex._output.glue_setter import GlueSetter


def _glue(width=0, stretch=0, stretch_order=GlueOrder.NORMAL, shrink=0, shrink_order=GlueOrder.NORMAL):
    return Glue(width, stretch, stretch_order, shrink, shrink_order)


@pytest.mark.parametrize("value,expected", [
    (0.1, 0.10000000149011612), (16777217, 16777216.0), (39666195, 39666196.0),
])
def test_binary32(value, expected):
    assert to_binary32(value) == expected
    assert to_binary32(expected) == expected


def test_ratio_operand_precision():
    assert glue_ratio(21465135, 91573472) == 0.23440343141555786
    assert to_binary32(21465135 / 91573472) == 0.23440341651439667
    assert glue_ratio(39666195, 65536) == 605.2581176757812
    assert glue_ratio(39666195, -65536) == -605.2581176757812


@pytest.mark.parametrize("value,expected", [(2.5, 3), (-2.5, -3), (3.5, 4), (0.49999997, 0), (-1.5, -2)])
def test_pascal_round(value, expected):
    assert tex_round(value) == expected


@pytest.mark.parametrize("need,total,count,expected", [
    (160196, 196608, 3, [53399, 53398, 53399]),
    (4408605, 131072, 2, [2204303, 2204302]),
])
def test_cumulative_stretch(need, total, count, expected):
    setter = GlueSetter(GlueSign.STRETCHING, GlueOrder.FIL, glue_ratio(need, total))
    assert [setter.set_size(_glue(stretch=65536, stretch_order=GlueOrder.FIL)) for _ in range(count)] == expected


def test_shrink_and_order_state():
    setter = GlueSetter(GlueSign.SHRINKING, GlueOrder.FIL, glue_ratio(3, 131072))
    glue = _glue(shrink=65536, shrink_order=GlueOrder.FIL)
    assert setter.set_size(glue) == -2
    assert setter.set_size(_glue(width=17, shrink=123, shrink_order=GlueOrder.FILL)) == 17
    assert setter.set_size(glue) == -1


@pytest.mark.parametrize("sign,direction", [(GlueSign.STRETCHING, 1), (GlueSign.SHRINKING, -1)])
def test_clamp(sign, direction):
    setter = GlueSetter(sign, GlueOrder.NORMAL, 1e9)
    assert setter.set_size(_glue(width=17, stretch=2, shrink=2)) == 17 + direction * 1000000000
    assert setter.set_size(_glue(width=17, stretch=2, shrink=2)) == 17


def test_normal_and_for_box():
    assert GlueSetter(GlueSign.NORMAL, GlueOrder.NORMAL, 3).set_size(_glue(width=17, stretch=5)) == 17
    box = HlistNode(list=[], width=0, height=0, depth=0, shift_amount=0,
                    glue_sign=GlueSign.STRETCHING, glue_order=GlueOrder.FIL, glue_set=0.5)
    assert GlueSetter.for_box(box).set_size(_glue(stretch=3, stretch_order=GlueOrder.FIL)) == 2


def test_matches_miktex_glue_model_reference():
    path = Path(__file__).parents[1] / "testdata/reference/glue_model/glue_model_reference.json"
    reference = json.loads(path.read_text())
    for run, row in reference.items():
        for case, measured in zip(row["cases"], row["measured"], strict=True):
            setter = GlueSetter(GlueSign.SHRINKING if case["shrink"] else GlueSign.STRETCHING,
                                GlueOrder.NORMAL, glue_ratio(abs(case["need"]), sum(case["flex"])))
            positions, cursor = [0], 0
            for width, flex in zip(case["width"], case["flex"], strict=True):
                glue = _glue(width=width, shrink=flex) if case["shrink"] else _glue(stretch=flex)
                cursor += 1 + setter.set_size(glue)
                positions.append(cursor)
            assert positions == measured, (run, case)
