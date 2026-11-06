r""" — interpreter \raise / \lower accept the full <box> operand grammar.

`TeXInterpreter._exec_raise_cmd` / `_exec_lower_cmd` previously called
`exec_hbox` directly, so they only accepted the `\raise<dimen>{…}` brace form
and failed on the full TeX `<box>` operand (`\raise2pt\hbox{x}`,
`\raise2pt\box0`, `\vbox{…}`, `\vtop{…}`).  This was surfaced by the
open-group box path (content inside `\hbox\bgroup…\egroup` routes through the
interpreter dispatch).  The handlers now read the operand via the shared
`box_primitives._scan_next_box`, mirroring the eager `dispatch_hbox_token` arms,
and apply the shift with the same sign convention (`\raise` -> +, `\lower` -> -).
"""
from __future__ import annotations

import warnings

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import HlistNode, VlistNode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice

# \let\bgroup={ for the open-group cases; a font for character measurement.
_PRE = r"\let\bgroup={ \let\egroup=} \font\tenrm=cmr10 \tenrm "


def _box0(source: str):
    interp = TeXInterpreter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(StringInputSource(_PRE + source), DviDevice())
    return interp._box_regs.peekbox(0)


class TestRaiseLowerHbox:
    def test_raise_hbox_box_form(self) -> None:
        # \raise2pt\hbox{x} (box-form operand) shifts the inner hbox up by +2pt.
        box = _box0(r"\setbox0=\hbox{\raise2pt\hbox{x}}")
        inner = box.list[0]
        assert isinstance(inner, HlistNode)
        assert inner.shift_amount == 2 * 65536

    def test_lower_hbox_box_form(self) -> None:
        box = _box0(r"\setbox0=\hbox{\lower2pt\hbox{x}}")
        inner = box.list[0]
        assert isinstance(inner, HlistNode)
        assert inner.shift_amount == -2 * 65536


class TestRaiseLowerOperands:
    def test_raise_box_register(self) -> None:
        # \raise<dimen>\box<n> uses the register's box as the operand.
        box = _box0(r"\setbox1=\hbox{y}\setbox0=\hbox{\raise1pt\box1}")
        inner = box.list[0]
        assert isinstance(inner, HlistNode)
        assert inner.shift_amount == 65536

    def test_raise_copy_register(self) -> None:
        box = _box0(r"\setbox1=\hbox{y}\setbox0=\hbox{\raise1pt\copy1}")
        inner = box.list[0]
        assert isinstance(inner, HlistNode)
        assert inner.shift_amount == 65536

    def test_raise_vbox_operand(self) -> None:
        box = _box0(r"\setbox0=\hbox{\raise1pt\vbox{\hbox{z}}}")
        inner = box.list[0]
        assert isinstance(inner, VlistNode)
        assert inner.shift_amount == 65536

    def test_lower_vtop_operand(self) -> None:
        box = _box0(r"\setbox0=\hbox{\lower1pt\vtop{\hbox{z}}}")
        inner = box.list[0]
        assert isinstance(inner, VlistNode)
        assert inner.shift_amount == -65536


class TestRaiseLowerInOpenGroup:
    def test_raise_inside_open_group_hbox(self) -> None:
        # The same mover works inside an open-group \hbox\bgroup…\egroup
        # (content routes through the interpreter dispatch — the path).
        box = _box0(r"\setbox0=\hbox\bgroup\raise2pt\hbox{x}\egroup")
        inner = box.list[0]
        assert isinstance(inner, HlistNode)
        assert inner.shift_amount == 2 * 65536
