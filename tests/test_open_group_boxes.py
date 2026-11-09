r"""open-group box construction (\hbox\bgroup…\egroup).

Real TeX builds every box "open-group": ``\hbox{`` opens a box whose matching
``}`` arrives later in the token stream.  Before this engine built boxes
only eagerly (``exec_hbox``/``exec_vbox`` scan to their own close in one pass),
so ``\setbox0=\hbox\bgroup … \egroup`` — where the ``\egroup`` arrives after a
macro or alignment-cell boundary — could not run.  adds a main-loop
box-build stack: a box keyword followed by a ``\bgroup`` alias opens a deferred-
close frame; the matching ``\egroup`` finalises and delivers the box.

The eager literal-brace path (``\hbox{…}``) stays byte-identical (the
5-MD5 gate); these tests drive only the ``\bgroup`` open-group path plus the
pre-existing eager-nested ``\setbox`` case that AC-2 requires.
"""
from __future__ import annotations

import warnings

import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode, HlistNode, VlistNode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice

# \let\bgroup={ \let\egroup=} mirrors plain.tex line 517; a font is selected so
# characters can be measured.
_PRE = r"\let\bgroup={ \let\egroup=} \font\tenrm=cmr10 \tenrm "


def _run(source: str) -> TeXInterpreter:
    interp = TeXInterpreter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(StringInputSource(_PRE + source), DviDevice())
    return interp


def _box(source: str, reg: int = 0):
    return _run(source)._box_regs.peekbox(reg)


class TestOpenGroupHbox:
    def test_setbox_hbox_bgroup_collects_content(self) -> None:
        # \setbox0=\hbox\bgroup xy\egroup builds the two-char hbox in register 0.
        box = _box(r"\setbox0=\hbox\bgroup xy\egroup")
        assert isinstance(box, HlistNode)
        chars = [n.char for n in box.list if isinstance(n, CharNode)]
        assert chars == [ord("x"), ord("y")]
        assert box.width > 0

    def test_box_value_round_trips(self) -> None:
        # The built box is usable by \box afterwards (contributes to a list).
        interp = _run(r"\setbox0=\hbox\bgroup x\egroup")
        assert isinstance(interp._box_regs.peekbox(0), HlistNode)

    def test_bare_hbox_bgroup_in_horizontal_mode(self) -> None:
        # A bare \hbox\bgroup…\egroup in horizontal mode contributes in place
        # without raising (no \setbox).
        _run(r"\hbox\bgroup a\egroup")  # must not raise

    def test_hbox_to_dimen_bgroup_sets_target_width(self) -> None:
        # \hbox to 20pt\bgroup x\egroup honours the open-group target width.
        box = _box(r"\setbox0=\hbox to 20pt\bgroup x\egroup")
        assert isinstance(box, HlistNode)
        assert box.width == 20 * 65536


class TestOpenGroupNested:
    def test_nested_open_group_hbox(self) -> None:
        # \setbox0=\hbox\bgroup\setbox1=\hbox\bgroup y\egroup\box1\egroup —
        # the inner open-group box (register 1) is placed inside the outer one.
        box = _box(
            r"\setbox0=\hbox\bgroup\setbox1=\hbox\bgroup y\egroup\box1\egroup"
        )
        assert isinstance(box, HlistNode)
        inner = [n for n in box.list if isinstance(n, HlistNode)]
        assert len(inner) == 1
        assert [n.char for n in inner[0].list if isinstance(n, CharNode)] == [ord("y")]

    def test_eager_nested_setbox_in_literal_brace_hbox(self) -> None:
        # the pre-existing \setbox0=\hbox{\setbox1=\hbox{x}\box1}
        # (literal braces, eager path) now places the inner box.
        box = _box(r"\setbox0=\hbox{\setbox1=\hbox{x}\box1}")
        assert isinstance(box, HlistNode)
        inner = [n for n in box.list if isinstance(n, HlistNode)]
        assert len(inner) == 1
        assert [n.char for n in inner[0].list if isinstance(n, CharNode)] == [ord("x")]


class TestOpenGroupVbox:
    def test_setbox_vbox_bgroup_collects_boxes(self) -> None:
        # \setbox0=\vbox\bgroup\hbox{a}\egroup builds a vbox of one line.
        box = _box(r"\setbox0=\vbox\bgroup\hbox{a}\egroup")
        assert isinstance(box, VlistNode)
        lines = [n for n in box.list if isinstance(n, HlistNode)]
        assert len(lines) == 1

    def test_setbox_vbox_bgroup_two_lines_stack(self) -> None:
        box = _box(r"\setbox0=\vbox\bgroup\hbox{a}\hbox{b}\egroup")
        assert isinstance(box, VlistNode)
        lines = [n for n in box.list if isinstance(n, HlistNode)]
        assert len(lines) == 2


class TestOpenGroupGlobal:
    def test_global_setbox_bgroup_survives_group(self) -> None:
        # \global\setbox inside a brace group writes the register globally, so it
        # is still set after the group closes.
        interp = _run(r"{\global\setbox0=\hbox\bgroup z\egroup}")
        box = interp._box_regs.peekbox(0)
        assert isinstance(box, HlistNode)
        assert [n.char for n in box.list if isinstance(n, CharNode)] == [ord("z")]

    def test_local_setbox_bgroup_restored_on_group_close(self) -> None:
        # A local \setbox inside a group is restored (voided) on group close.
        interp = _run(r"{\setbox0=\hbox\bgroup z\egroup}")
        assert interp._box_regs.peekbox(0) is None


class TestOpenGroupErrors:
    def test_missing_egroup_raises_at_eof(self) -> None:
        # §Error Handling: an open-group \hbox\bgroup whose \egroup never
        # arrives must raise at EOF, not silently leave a dangling frame.
        with pytest.raises(EngineError, match=r"missing \\egroup"):
            _run(r"\setbox0=\hbox\bgroup x")

    def test_missing_egroup_vbox_raises_at_eof(self) -> None:
        with pytest.raises(EngineError, match=r"missing \\egroup"):
            _run(r"\setbox0=\vbox\bgroup\hbox{x}")
