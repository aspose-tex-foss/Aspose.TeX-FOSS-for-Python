"""Tests for cascade #2 ``\\insert`` support."""
from __future__ import annotations

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import (
    CharNode,
    HlistNode,
    InsertNode,
    VlistNode,
)
from aspose_tex._input.reader import StringInputSource


class _CapturingBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[int, VlistNode]] = []

    def shipout(self, page_number: int, box: VlistNode) -> None:
        self.calls.append((page_number, box))


class _CapturingDevice:
    def __init__(self) -> None:
        self.backend = _CapturingBackend()

    def _create_backend(self, font_manager, *, mag: int = 1000):
        return self.backend

    def finalize(self) -> None:
        pass


def _run(tex: str) -> tuple[TeXInterpreter, _CapturingDevice]:
    interp = TeXInterpreter()
    device = _CapturingDevice()
    interp.run_with_device(StringInputSource(tex), device)
    return interp, device


def _chars(node) -> str:
    if isinstance(node, CharNode):
        return chr(node.char)
    if isinstance(node, (HlistNode, VlistNode)):
        return "".join(_chars(child) for child in node.list)
    return ""


def _find_inserts(node) -> list[InsertNode]:
    if isinstance(node, InsertNode):
        return [node]
    if isinstance(node, (HlistNode, VlistNode)):
        return [found for child in node.list for found in _find_inserts(child)]
    return []


def test_insert_primitive_in_vmode_moves_into_its_box() -> None:
    # \end flushes the insertion-only page (§1054) and fire_up moves
    # the insertion into \box254 (§1018-§1021).
    interp, _device = _run(r"\insert254{\hbox{N}}\end")

    box = interp._box_regs.peekbox(254)
    assert isinstance(box, VlistNode)
    assert _chars(box) == "N"


def test_insert_primitive_snapshots_named_parameters() -> None:
    _interp, device = _run(
        r"\holdinginserts=1 \floatingpenalty=9999 \splittopskip=5pt \splitmaxdepth=4pt "
        r"\insert254{\hbox{N}}X\end"
    )

    [node] = _find_inserts(device.backend.calls[0][1])
    assert node.floating_penalty == 9999
    assert node.split_top_skip.width == 5 * 65_536
    assert node.split_max_depth == 4 * 65_536


def test_insert_primitive_in_adjusted_hbox_migrates() -> None:
    interp, _device = _run(r"\hbox{\insert254{\hbox{x}}}\end")
    assert _chars(interp._box_regs.peekbox(254)) == "x"


def test_insert_primitive_in_stored_hbox_stays_inside() -> None:
    interp, _device = _run(r"\setbox0=\hbox{\insert254{\hbox{x}}}\end")
    [node] = _find_inserts(interp._box_regs.peekbox(0))
    assert "".join(_chars(child) for child in node.vlist) == "x"
    assert interp._box_regs.peekbox(254) is None


def test_insert_flushes_to_box_register_before_output_body() -> None:
    _interp, device = _run(
        r"\output={\shipout\vbox{\unvbox254\unvbox255}}"
        r"\insert254{\hbox{N}}X\eject"
    )

    assert len(device.backend.calls) == 1
    assert "NX" in _chars(device.backend.calls[0][1])


def test_holdinginserts_leaves_insert_in_body_and_box_register_void() -> None:
    interp, device = _run(
        r"\holdinginserts=1 \output={\shipout\box255}"
        r"\insert254{\hbox{N}}X\eject"
    )

    assert len(device.backend.calls) == 1
    assert "X" in _chars(device.backend.calls[0][1])
    assert "N" not in _chars(device.backend.calls[0][1])
    assert interp._box_regs.peekbox(254) is None


def test_insertpenalties_is_zero_after_the_output_routine() -> None:
    interp, _device = _run(
        r"\output={\shipout\box255}\insert254{\hbox{N}}X\eject"
    )
    # \insertpenalties is now owned by InternalQuantityRegistry — the
    # Appendix A placeholder was retired since InternalQuantityRegistry
    # supersedes it in both _dispatch_cs and \the dispatch.
    entry = interp._internal_quantities.lookup("insertpenalties")

    assert entry is not None
    assert entry.getter() == 0
