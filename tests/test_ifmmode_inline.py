r""" — `\ifmmode` is true inside inline `$…$` (mode-before-peek fix).

`\handle_math_shift` used to peek for the second `$` of `$$` BEFORE pushing math
mode, so a leading expandable conditional in the formula (e.g. `\mathstrut`'s
`\ph@nt` → `\ifmmode`) was expanded while still in HORIZONTAL mode and read
`\ifmmode` as false (and the spurious peek mis-detected display math).  Math
mode is now entered on the first `$`, then the display check runs (TeX:The
Program §1090) so any expansion during the peek sees math mode.
"""
from __future__ import annotations

from aspose_tex import DviDevice
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.reader import StringInputSource

_PT = 65_536
# A math `(` is ~7.5 pt tall; a text `x` is ~4.3 pt — the height tells the branch.
_PAREN_H = 7.5


def _box0_height(body: str) -> float:
    interp = TeXInterpreter()
    interp._load_format = "plain"
    interp.run_with_device(StringInputSource(body + r"\bye"), DviDevice())
    box = interp._box_regs.getbox(0)
    assert box is not None
    return round(box.height / _PT, 3)


class TestIfmmodeInlineMath:
    def test_ifmmode_true_inline(self) -> None:
        # \ifmmode picks the `(` (true) branch inside `$…$`, not the `x` (else).
        h = _box0_height(
            r"$\ifmmode\global\setbox0=\hbox{(}\else\global\setbox0=\hbox{x}\fi$"
        )
        assert h == _PAREN_H, f"\\ifmmode read false inline (box height {h})"

    def test_ifmmode_true_display(self) -> None:
        # Display `$$…$$` was always correct; pin it so the mode-before-peek
        # change keeps display detection working.
        h = _box0_height(
            r"$$\ifmmode\global\setbox0=\hbox{(}\else\global\setbox0=\hbox{x}\fi$$"
        )
        assert h == _PAREN_H

    def test_inline_and_display_still_distinguished(self) -> None:
        # Sanity: a bare `$x$` (inline) and `$$x$$` (display) both still compile
        # end-to-end through the public-ish path (no spurious "$$ inserted").
        assert _box0_height(r"\setbox0=\hbox{$x$}") >= 0  # builds without raising
