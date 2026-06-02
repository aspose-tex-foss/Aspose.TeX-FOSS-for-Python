"""Handlers for page-mode TeX primitives.

Implements: \\vfil, \\vfill, \\vfilneg, \\vss,
\\nointerlineskip, \\offinterlineskip, \\shipout. \\eject (FR-13) moved to
interpreter.py per .

Follows the same pattern as par_primitives.py: stateless factory functions
and exec functions that take PageBuilder as an explicit argument.

See the project documentation for design rationale.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aspose_tex._engine.nodes import GlueNode, VlistNode
from aspose_tex._engine.registers import Glue, GlueOrder

if TYPE_CHECKING:
 from aspose_tex._engine.page_builder import PageBuilder, ShipoutBackend


def make_vfil_glue() -> GlueNode:
 r"""\vfil — 0pt plus 1fil.

 Returns:
 GlueNode(Glue(width=0, stretch=65536, stretch_order=FIL,
 shrink=0, shrink_order=NORMAL))
 """
 return GlueNode(Glue(
 width=0,
 stretch=65536,
 stretch_order=GlueOrder.FIL,
 shrink=0,
 shrink_order=GlueOrder.NORMAL,
 ))


def make_vfill_glue() -> GlueNode:
 r"""\vfill — 0pt plus 1fill.

 Returns:
 GlueNode(Glue(width=0, stretch=65536, stretch_order=FILL,
 shrink=0, shrink_order=NORMAL))
 """
 return GlueNode(Glue(
 width=0,
 stretch=65536,
 stretch_order=GlueOrder.FILL,
 shrink=0,
 shrink_order=GlueOrder.NORMAL,
 ))


def make_vfilneg_glue() -> GlueNode:
 r"""\vfilneg — 0pt minus 1fil.

 Returns:
 GlueNode(Glue(width=0, stretch=0, stretch_order=NORMAL,
 shrink=65536, shrink_order=FIL))
 """
 return GlueNode(Glue(
 width=0,
 stretch=0,
 stretch_order=GlueOrder.NORMAL,
 shrink=65536,
 shrink_order=GlueOrder.FIL,
 ))


def make_vss_glue() -> GlueNode:
 r"""\vss — 0pt plus 1fil minus 1fil.

 Returns:
 GlueNode(Glue(width=0, stretch=65536, stretch_order=FIL,
 shrink=65536, shrink_order=FIL))
 """
 return GlueNode(Glue(
 width=0,
 stretch=65536,
 stretch_order=GlueOrder.FIL,
 shrink=65536,
 shrink_order=GlueOrder.FIL,
 ))


def exec_nointerlineskip(page_builder: PageBuilder) -> None:
 r"""\nointerlineskip — suppress interline glue for the next box only.

 Args:
 page_builder: The active PageBuilder instance.
 """
 page_builder.skip_next_interline()


def exec_offinterlineskip(page_builder: PageBuilder) -> None:
 r"""\offinterlineskip — disable all subsequent interline glue.

 Args:
 page_builder: The active PageBuilder instance.
 """
 page_builder.off_interline()


def exec_shipout(
 box: VlistNode,
 page_number: int,
 backend: ShipoutBackend,
 page_builder: PageBuilder,
) -> None:
 r"""\shipout — send a completed box directly to the output backend.

 Bypasses the output routine. Called within an output routine to
 actually send the page.

 Args:
 box: The finalized page VlistNode to ship.
 page_number: Current value of \\pageno.
 backend: Shipout target.
 page_builder: The active PageBuilder (for dead_cycles reset).
 """
 backend.shipout(page_number, box)
 page_builder._record_shipout()
