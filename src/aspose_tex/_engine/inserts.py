"""Insert-class accumulator for the page builder."""
from __future__ import annotations

from typing import TYPE_CHECKING

from aspose_tex._engine.box_builder import _measure_vlist
from aspose_tex._engine.nodes import GlueSign, InsertNode, VlistNode
from aspose_tex._engine.registers import GlueOrder

if TYPE_CHECKING:
 from aspose_tex._engine.box_registers import BoxRegisterSet
 from aspose_tex._engine.group import GroupStack
 from aspose_tex._fonts.font_manager import FontManager


class InsertAccumulator:
 """Per-class accumulator of ``\\insert<n>{<vlist>}`` payloads."""

 def __init__(self, group_stack: GroupStack | None = None) -> None:
 """Create an empty accumulator.

 Args:
 group_stack: Optional save/restore stack for group-scoped inserts.
 """
 self._group_stack = group_stack
 self._classes: dict[int, list] = {}
 self._dirty_in_group: set[tuple[int, int]] = set()

 def append(self, node: InsertNode) -> None:
 """Append *node*'s vlist to its class accumulator."""
 self._save_class_once(node.class_)
 self._classes.setdefault(node.class_, []).extend(node.vlist)

 def get_class(self, class_: int) -> list:
 """Return a copy of the accumulated nodes for *class_*."""
 return list(self._classes.get(class_, []))

 def flush_to_box_registers(
 self,
 box_regs: BoxRegisterSet,
 font_manager: FontManager | None,
 ) -> None:
 """Write each accumulated insert class into ``\\box<class>``."""
 for class_, nodes in list(self._classes.items()):
 if not nodes:
 continue
 width, height, depth = _measure_vlist(nodes, font_manager) # type: ignore[arg-type]
 box_regs.setbox(
 class_,
 VlistNode(
 list=list(nodes),
 width=width,
 height=height,
 depth=depth,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 ),
 global_=True,
 )
 self.clear()

 def clear(self) -> None:
 """Reset all class accumulators to empty."""
 self._classes.clear()

 def _save_class_once(self, class_: int) -> None:
 """Save one class snapshot once per group level before mutation."""
 if self._group_stack is None or self._group_stack.depth == 0:
 return
 depth = self._group_stack.depth
 dirty_key = (depth, class_)
 if dirty_key in self._dirty_in_group:
 return
 old = list(self._classes.get(class_, []))

 def _restore() -> None:
 if old:
 self._classes[class_] = list(old)
 else:
 self._classes.pop(class_, None)
 self._dirty_in_group.discard(dirty_key)

 self._dirty_in_group.add(dirty_key)
 self._group_stack.save(("insert_class", class_), _restore)
