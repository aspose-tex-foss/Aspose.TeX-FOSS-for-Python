"""Unit tests for page_primitives module.

Tests follow test plan.
"""
from __future__ import annotations

from aspose_tex._engine.nodes import (
 GlueNode,
 GlueSign,
 HlistNode,
 VlistNode,
)
from aspose_tex._engine.page_builder import (
 OutputRoutineBase,
 PageBuilder,
 PageBuilderConfig,
)
from aspose_tex._engine.page_primitives import (
 exec_nointerlineskip,
 exec_offinterlineskip,
 exec_shipout,
 make_vfil_glue,
 make_vfill_glue,
 make_vfilneg_glue,
 make_vss_glue,
)
from aspose_tex._engine.registers import Glue, GlueOrder

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hbox(height: int, depth: int = 0, width: int = 1000) -> HlistNode:
 return HlistNode(
 list=[],
 width=width,
 height=height,
 depth=depth,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )


def _default_config(**overrides) -> PageBuilderConfig:
 cfg = PageBuilderConfig(
 vsize=42152952,
 topskip=Glue(655360, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 max_depth=262144,
 baselineskip=Glue(786432, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 lineskip=Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 lineskiplimit=0,
 max_dead_cycles=25,
 )
 for k, v in overrides.items():
 setattr(cfg, k, v)
 return cfg


class _NullBackend:
 def __init__(self):
 self.calls: list[tuple[int, VlistNode]] = []

 def shipout(self, pn: int, box: VlistNode) -> None:
 self.calls.append((pn, box))


class _ShippingRoutine(OutputRoutineBase):
 def execute(self, body_box, page_number, backend):
 backend.shipout(page_number, body_box)


# ---------------------------------------------------------------------------
# Glue factory tests
# ---------------------------------------------------------------------------

def test_make_vfil_glue_properties():
 node = make_vfil_glue()
 assert isinstance(node, GlueNode)
 assert node.glue.width == 0
 assert node.glue.stretch == 65536
 assert node.glue.stretch_order == GlueOrder.FIL
 assert node.glue.shrink == 0
 assert node.glue.shrink_order == GlueOrder.NORMAL


def test_make_vfill_glue_properties():
 node = make_vfill_glue()
 assert isinstance(node, GlueNode)
 assert node.glue.stretch_order == GlueOrder.FILL
 assert node.glue.stretch == 65536
 assert node.glue.width == 0
 assert node.glue.shrink == 0


def test_make_vfilneg_glue_properties():
 node = make_vfilneg_glue()
 assert isinstance(node, GlueNode)
 assert node.glue.width == 0
 assert node.glue.stretch == 0
 assert node.glue.stretch_order == GlueOrder.NORMAL
 assert node.glue.shrink == 65536
 assert node.glue.shrink_order == GlueOrder.FIL


def test_make_vss_glue_properties():
 node = make_vss_glue()
 assert isinstance(node, GlueNode)
 assert node.glue.stretch_order == GlueOrder.FIL
 assert node.glue.shrink_order == GlueOrder.FIL
 assert node.glue.stretch == 65536
 assert node.glue.shrink == 65536


# ---------------------------------------------------------------------------
# exec_nointerlineskip
# ---------------------------------------------------------------------------

def test_exec_nointerlineskip_skips_one():
 """exec_nointerlineskip → next box has no interline glue, subsequent one does."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 box = _make_hbox(height=400000, depth=100000)
 builder.contribute(box)
 exec_nointerlineskip(builder)
 builder.contribute(box) # no interline
 builder.contribute(box) # interline before this one
 # MVL: [topskip, box1, box2, interline_glue, box3]
 assert len(builder._mvl) == 5
 assert isinstance(builder._mvl[2], HlistNode) # box2 directly after box1
 assert isinstance(builder._mvl[3], GlueNode) # interline before box3


# ---------------------------------------------------------------------------
# exec_offinterlineskip
# ---------------------------------------------------------------------------

def test_exec_offinterlineskip_disables_all():
 """exec_offinterlineskip → no interline glue at all (only topskip)."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 exec_offinterlineskip(builder)
 box = _make_hbox(height=400000)
 builder.contribute(box)
 builder.contribute(box)
 builder.contribute(box)
 # MVL: [topskip, box1, box2, box3]
 assert len(builder._mvl) == 4


# ---------------------------------------------------------------------------
# exec_shipout
# ---------------------------------------------------------------------------

def test_exec_shipout_resets_dead_cycles():
 """Manually increment dead_cycles, exec_shipout → dead_cycles == 0."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())

 # Manually set dead_cycles to simulate a previous output call without shipout
 builder._dead_cycles = 3

 page_box = VlistNode(
 list=[],
 width=0,
 height=100000,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 exec_shipout(page_box, page_number=1, backend=backend, page_builder=builder)
 assert builder.dead_cycles == 0
 assert len(backend.calls) == 1
 assert backend.calls[0][0] == 1
