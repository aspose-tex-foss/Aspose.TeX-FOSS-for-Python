"""Box register set: 256 group-scoped box registers.

Implements FR-14 and FR-15: ``\\setbox``, ``\\box``, ``\\copy``,
``\\wd``, ``\\ht``, ``\\dp``.

Register indices are 0-255. Group scoping uses the same save-on-first-write
pattern as ``RegisterSet`` in (via ``GroupStack.save()``).

See the project documentation for design rationale.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aspose_tex._engine.nodes import HlistNode, VlistNode, deep_copy_node

if TYPE_CHECKING:
 from aspose_tex._engine.group import GroupStack

_BoxSlot = HlistNode | VlistNode | None


class BoxRegisterSet:
 """256 box registers with group-scoped save/restore.

 Box registers store ``HlistNode | VlistNode | None``.
 ``None`` represents a void box (the initial state of every register).

 Args:
 group_stack: If provided, assignments are automatically saved on
 first-write per group level (same pattern as ``RegisterSet``).
 Pass ``None`` to disable group scoping.

 Example::

 from aspose_tex._engine.group import GroupStack, GroupKind
 gs = GroupStack()
 regs = BoxRegisterSet(group_stack=gs)
 regs.setbox(0, my_hbox)
 assert regs.getbox(0) is my_hbox # consumes
 assert regs.getbox(0) is None # void after consumption
 """

 def __init__(self, group_stack: GroupStack | None = None) -> None:
 """Initialise all 256 registers to ``None`` (void)."""
 self._slots: list[_BoxSlot] = [None] * 256
 self._group_stack = group_stack

 # ------------------------------------------------------------------
 # Public interface
 # ------------------------------------------------------------------

 def setbox(
 self,
 reg: int,
 box: _BoxSlot,
 *,
 global_: bool = False,
 ) -> None:
 """Store *box* in register *reg*.

 If ``group_stack`` is set and ``global_`` is False, saves the current
 value on first write at this group level for restore on group close.
 If ``global_`` is True, bypasses save/restore.

 Raises:
 ValueError: if ``reg`` is outside [0, 255].
 """
 self._validate(reg)
 gs = self._group_stack
 if gs is not None and not global_:
 old = self._slots[reg]
 gs.save(("box", reg), lambda _old=old, _r=reg: self._restore(_r, _old))
 self._slots[reg] = box

 def getbox(self, reg: int) -> _BoxSlot:
 """Retrieve box from register *reg* and void the register (``\\box`` semantics).

 Returns ``None`` if the register is already void.

 Raises:
 ValueError: if ``reg`` is outside [0, 255].
 """
 self._validate(reg)
 box = self._slots[reg]
 # Void the register — bypass group-save (consuming is not a local assignment)
 self._slots[reg] = None
 return box

 def copybox(self, reg: int) -> _BoxSlot:
 """Retrieve a deep copy of the box without clearing the register (``\\copy`` semantics).

 Returns ``None`` if the register is void.

 Raises:
 ValueError: if ``reg`` is outside [0, 255].
 """
 self._validate(reg)
 box = self._slots[reg]
 if box is None:
 return None
 return deep_copy_node(box) # type: ignore[return-value]

 def peekbox(self, reg: int) -> _BoxSlot:
 """Return the stored box without clearing it.

 Used by conditional readers such as ``\\ifvoid``/``\\ifhbox``/``\\ifvbox``.
 """
 self._validate(reg)
 return self._slots[reg]

 def get_wd(self, reg: int) -> int:
 """Return the width of box *reg* in sp; 0 if void."""
 self._validate(reg)
 box = self._slots[reg]
 return box.width if box is not None else 0

 def get_ht(self, reg: int) -> int:
 """Return the height of box *reg* in sp; 0 if void."""
 self._validate(reg)
 box = self._slots[reg]
 return box.height if box is not None else 0

 def get_dp(self, reg: int) -> int:
 """Return the depth of box *reg* in sp; 0 if void."""
 self._validate(reg)
 box = self._slots[reg]
 return box.depth if box is not None else 0

 def set_wd(self, reg: int, value: int, *, global_: bool = False) -> None:
 """Set width of box *reg* in sp. No-op if register is void."""
 self._validate(reg)
 box = self._slots[reg]
 if box is None:
 return
 gs = self._group_stack
 if gs is not None and not global_:
 old = box.width
 gs.save(("box_wd", reg), lambda _old=old, _b=box: setattr(_b, "width", _old))
 box.width = value

 def set_ht(self, reg: int, value: int, *, global_: bool = False) -> None:
 """Set height of box *reg* in sp. No-op if register is void."""
 self._validate(reg)
 box = self._slots[reg]
 if box is None:
 return
 gs = self._group_stack
 if gs is not None and not global_:
 old = box.height
 gs.save(("box_ht", reg), lambda _old=old, _b=box: setattr(_b, "height", _old))
 box.height = value

 def set_dp(self, reg: int, value: int, *, global_: bool = False) -> None:
 """Set depth of box *reg* in sp. No-op if register is void."""
 self._validate(reg)
 box = self._slots[reg]
 if box is None:
 return
 gs = self._group_stack
 if gs is not None and not global_:
 old = box.depth
 gs.save(("box_dp", reg), lambda _old=old, _b=box: setattr(_b, "depth", _old))
 box.depth = value

 # ------------------------------------------------------------------
 # Internal
 # ------------------------------------------------------------------

 def _validate(self, reg: int) -> None:
 """Raise ValueError if reg not in [0, 255]."""
 if reg < 0 or reg > 255:
 raise ValueError(f"Box register {reg} out of range [0, 255]")

 def _restore(self, reg: int, old_value: _BoxSlot) -> None:
 """Write old_value directly into _slots[reg], bypassing save logic."""
 self._slots[reg] = old_value
