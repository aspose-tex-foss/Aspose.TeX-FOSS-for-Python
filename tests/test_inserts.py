"""Tests for cascade #2 ``\\insert`` support."""
from __future__ import annotations

import pytest

from aspose_tex._engine.box_registers import BoxRegisterSet
from aspose_tex._engine.group import GroupKind, GroupStack
from aspose_tex._engine.inserts import InsertAccumulator
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import (
 CharNode,
 GlueSign,
 HlistNode,
 InsertNode,
 PenaltyNode,
 VlistNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError


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


def _insert_node(class_: int, *nodes) -> InsertNode:
 return InsertNode(
 class_=class_,
 vlist=tuple(nodes),
 height=10,
 depth=2,
 floating_penalty=0,
 split_top_skip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 split_max_depth=0,
 )


def _hbox(chars: str) -> HlistNode:
 return HlistNode(
 list=[CharNode(ord(ch), "tenrm") for ch in chars],
 width=10,
 height=7,
 depth=3,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )


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


def test_insert_accumulator_append_single_class() -> None:
 node = _insert_node(254, PenaltyNode(1))
 acc = InsertAccumulator()

 acc.append(node)

 assert acc.get_class(254) == [PenaltyNode(1)]


def test_insert_accumulator_two_classes_isolated() -> None:
 acc = InsertAccumulator()

 acc.append(_insert_node(253, PenaltyNode(1)))
 acc.append(_insert_node(254, PenaltyNode(2)))

 assert acc.get_class(253) == [PenaltyNode(1)]
 assert acc.get_class(254) == [PenaltyNode(2)]


def test_insert_accumulator_flush_writes_to_box_registers() -> None:
 regs = BoxRegisterSet()
 acc = InsertAccumulator()
 hbox = _hbox("N")

 acc.append(_insert_node(254, hbox))
 acc.flush_to_box_registers(regs, None)

 box = regs.peekbox(254)
 assert isinstance(box, VlistNode)
 assert box.list == [hbox]


def test_insert_accumulator_flush_clears_state() -> None:
 acc = InsertAccumulator()
 acc.append(_insert_node(254, PenaltyNode(1)))

 acc.flush_to_box_registers(BoxRegisterSet(), None)

 assert acc.get_class(254) == []


def test_insert_accumulator_group_rollback() -> None:
 group_stack = GroupStack()
 acc = InsertAccumulator(group_stack)

 group_stack.open_group(GroupKind.BRACE)
 acc.append(_insert_node(254, PenaltyNode(1)))
 group_stack.close_group()

 assert acc.get_class(254) == []


def test_insert_primitive_in_vmode_contributes_insert_node() -> None:
 interp, _device = _run(r"\insert254{\hbox{N}}\end")

 inserts = [n for n in interp._page_builder._mvl if isinstance(n, InsertNode)]
 assert len(inserts) == 1
 assert inserts[0].class_ == 254
 assert _chars(VlistNode(list=list(inserts[0].vlist), width=0, height=0, depth=0,
 shift_amount=0, glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0)) == "N"


def test_insert_primitive_snapshots_named_parameters() -> None:
 interp, _device = _run(
 r"\floatingpenalty=9999 \splittopskip=5pt \splitmaxdepth=4pt "
 r"\insert254{\hbox{N}}\end"
 )

 [node] = [n for n in interp._page_builder._mvl if isinstance(n, InsertNode)]
 assert node.floating_penalty == 9999
 assert node.split_top_skip.width == 5 * 65_536
 assert node.split_max_depth == 4 * 65_536


def test_insert_primitive_in_restricted_horizontal_raises() -> None:
 with pytest.raises(EngineError, match=r"\\insert is not allowed inside an hbox"):
 _run(r"\hbox{\insert254{\hbox{x}}}\end")


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


def test_insertpenalties_remains_zero_in_m3() -> None:
 interp, _device = _run(
 r"\output={\shipout\box255}\insert254{\hbox{N}}X\eject"
 )
 # : \insertpenalties is now owned by InternalQuantityRegistry — the
 # Appendix A placeholder was retired since InternalQuantityRegistry
 # supersedes it in both _dispatch_cs and \the dispatch.
 entry = interp._internal_quantities.lookup("insertpenalties")

 assert entry is not None
 assert entry.getter() == 0
