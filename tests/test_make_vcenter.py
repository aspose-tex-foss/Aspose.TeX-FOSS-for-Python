r""" / §C2 — `\vcenter` §735 axis-centring (`_make_vcenter`).

`mlist_to_hlist._translate_nucleus` now has a `MathClass.VCENTER` branch that
centres a `\vcenter` box on the math axis (TeX:The Program §735 `make_vcenter`):
`delta = height + depth`; `height := axis_height + delta//2`; `depth := delta -
height`, set directly on the box (no `shift_amount`).
"""
from __future__ import annotations

from types import SimpleNamespace

from aspose_tex._engine import mlist_to_hlist as mlist_mod
from aspose_tex._engine.math_list import MathClass, Noad, NoadKind
from aspose_tex._engine.math_style import TeXStyle
from aspose_tex._engine.nodes import GlueOrder, GlueSign, VlistNode

_PT = 65_536
_AXIS = round(2.5 * _PT)  # cmsy10 axis_height ≈ 2.5 pt at text size


def _ctx() -> SimpleNamespace:
    """A minimal stand-in for ``_Ctx`` — `_make_vcenter` only reads
    ``style`` and ``math_params.axis_height(size_of(style))``."""
    return SimpleNamespace(
        style=TeXStyle.TEXT,
        math_params=SimpleNamespace(axis_height=lambda _size: _AXIS),
    )


def _box(total_height_pt: float) -> VlistNode:
    return VlistNode(
        list=[], width=0, height=round(total_height_pt * _PT), depth=0,
        shift_amount=0, glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL,
        glue_set=0.0,
    )


class TestMakeVcenter:
    def test_centres_box_on_axis(self) -> None:
        box = _box(20.0)
        delta = box.height + box.depth
        out = mlist_mod._make_vcenter(
            Noad(NoadKind.ATOM, MathClass.VCENTER, nucleus=box), _ctx()
        )
        assert out == [box]
        assert box.height == _AXIS + delta // 2
        assert box.depth == delta - box.height
        # The vertical CENTRE of the box sits on the axis.
        assert box.height - (box.height + box.depth) // 2 == _AXIS

    def test_symmetric_when_axis_zero(self) -> None:
        ctx = _ctx()
        ctx.math_params.axis_height = lambda _s: 0
        box = _box(10.0)
        mlist_mod._make_vcenter(Noad(NoadKind.ATOM, MathClass.VCENTER, nucleus=box), ctx)
        # axis 0 → height == depth == half the total.
        assert box.height == box.depth == round(10.0 * _PT) // 2

    def test_no_shift_amount_set(self) -> None:
        # §735 sets height/depth directly (a vlist is positioned by its height);
        # unlike axis_center it must NOT set shift_amount.
        box = _box(12.0)
        mlist_mod._make_vcenter(Noad(NoadKind.ATOM, MathClass.VCENTER, nucleus=box), _ctx())
        assert getattr(box, "shift_amount", 0) == 0
