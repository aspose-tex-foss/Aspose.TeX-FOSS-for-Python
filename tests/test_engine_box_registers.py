"""Tests for BoxRegisterSet ( / / FR-14, FR-15).

Covers AC-6, AC-7.
"""
from __future__ import annotations

import pytest

from aspose_tex._engine.box_registers import BoxRegisterSet
from aspose_tex._engine.group import GroupKind, GroupStack
from aspose_tex._engine.nodes import GlueOrder, GlueSign, HlistNode, VlistNode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hbox(width: int = 100, height: int = 50, depth: int = 10) -> HlistNode:
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


def _vbox(width: int = 100, height: int = 80, depth: int = 5) -> VlistNode:
 return VlistNode(
 list=[],
 width=width,
 height=height,
 depth=depth,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

def test_initial_all_void() -> None:
 regs = BoxRegisterSet()
 for i in range(256):
 assert regs.getbox(i) is None


# ---------------------------------------------------------------------------
# setbox / getbox — AC-6
# ---------------------------------------------------------------------------

def test_setbox_getbox_returns_box() -> None:
 """AC-6: \\setbox0=\\hbox{...} stores box, \\box0 retrieves it."""
 regs = BoxRegisterSet()
 box = _hbox()
 regs.setbox(0, box)
 result = regs.getbox(0)
 assert result is box


def test_getbox_voids_register() -> None:
 """AC-6: \\box0 retrieves and empties the register."""
 regs = BoxRegisterSet()
 regs.setbox(0, _hbox())
 regs.getbox(0)
 assert regs.getbox(0) is None


def test_setbox_none_voids_register() -> None:
 regs = BoxRegisterSet()
 regs.setbox(0, _hbox())
 regs.setbox(0, None)
 assert regs.getbox(0) is None


# ---------------------------------------------------------------------------
# copybox — AC-6
# ---------------------------------------------------------------------------

def test_copybox_returns_deep_copy() -> None:
 """AC-6: \\copy0 retrieves without emptying."""
 regs = BoxRegisterSet()
 original = _hbox()
 regs.setbox(0, original)
 copy = regs.copybox(0)
 assert copy is not original
 assert isinstance(copy, HlistNode)
 assert copy.width == original.width


def test_copybox_does_not_clear_register() -> None:
 """AC-6: \\copy0 keeps the register."""
 regs = BoxRegisterSet()
 regs.setbox(0, _hbox())
 regs.copybox(0)
 assert regs.getbox(0) is not None


def test_copybox_void_returns_none() -> None:
 regs = BoxRegisterSet()
 assert regs.copybox(5) is None


# ---------------------------------------------------------------------------
# get_wd / get_ht / get_dp — AC-7
# ---------------------------------------------------------------------------

def test_get_wd_returns_width() -> None:
 """AC-7: \\wd0 returns correct width."""
 regs = BoxRegisterSet()
 regs.setbox(0, _hbox(width=123456))
 assert regs.get_wd(0) == 123456


def test_get_ht_returns_height() -> None:
 """AC-7: \\ht0 returns correct height."""
 regs = BoxRegisterSet()
 regs.setbox(0, _hbox(height=654321))
 assert regs.get_ht(0) == 654321


def test_get_dp_returns_depth() -> None:
 """AC-7: \\dp0 returns correct depth."""
 regs = BoxRegisterSet()
 regs.setbox(0, _hbox(depth=11111))
 assert regs.get_dp(0) == 11111


def test_get_wd_void_returns_zero() -> None:
 regs = BoxRegisterSet()
 assert regs.get_wd(0) == 0


def test_get_ht_void_returns_zero() -> None:
 regs = BoxRegisterSet()
 assert regs.get_ht(0) == 0


def test_get_dp_void_returns_zero() -> None:
 regs = BoxRegisterSet()
 assert regs.get_dp(0) == 0


# ---------------------------------------------------------------------------
# set_wd / set_ht / set_dp
# ---------------------------------------------------------------------------

def test_set_wd_updates_width() -> None:
 regs = BoxRegisterSet()
 regs.setbox(0, _hbox(width=100))
 regs.set_wd(0, 999)
 assert regs.get_wd(0) == 999


def test_set_ht_updates_height() -> None:
 regs = BoxRegisterSet()
 regs.setbox(0, _hbox(height=100))
 regs.set_ht(0, 888)
 assert regs.get_ht(0) == 888


def test_set_dp_updates_depth() -> None:
 regs = BoxRegisterSet()
 regs.setbox(0, _hbox(depth=100))
 regs.set_dp(0, 777)
 assert regs.get_dp(0) == 777


def test_set_wd_void_noop() -> None:
 regs = BoxRegisterSet()
 regs.set_wd(0, 999) # no-op on void
 assert regs.get_wd(0) == 0


# ---------------------------------------------------------------------------
# Boundary validation
# ---------------------------------------------------------------------------

def test_setbox_negative_raises() -> None:
 regs = BoxRegisterSet()
 with pytest.raises(ValueError):
 regs.setbox(-1, _hbox())


def test_setbox_256_raises() -> None:
 regs = BoxRegisterSet()
 with pytest.raises(ValueError):
 regs.setbox(256, _hbox())


def test_getbox_negative_raises() -> None:
 regs = BoxRegisterSet()
 with pytest.raises(ValueError):
 regs.getbox(-1)


def test_copybox_256_raises() -> None:
 regs = BoxRegisterSet()
 with pytest.raises(ValueError):
 regs.copybox(256)


def test_get_wd_255_valid() -> None:
 regs = BoxRegisterSet()
 regs.setbox(255, _hbox(width=42))
 assert regs.get_wd(255) == 42


# ---------------------------------------------------------------------------
# Group scoping
# ---------------------------------------------------------------------------

def test_setbox_restored_on_group_close() -> None:
 """setbox inside a group is undone when the group closes."""
 gs = GroupStack()
 regs = BoxRegisterSet(group_stack=gs)

 old_box = _hbox(width=100)
 regs.setbox(0, old_box)

 gs.open_group(GroupKind.BRACE)
 new_box = _hbox(width=200)
 regs.setbox(0, new_box)
 assert regs._slots[0] is new_box

 gs.close_group()
 # Restored to old_box
 assert regs._slots[0] is old_box


def test_global_setbox_not_restored() -> None:
 """global_ setbox is NOT restored on group close."""
 gs = GroupStack()
 regs = BoxRegisterSet(group_stack=gs)

 regs.setbox(0, _hbox(width=100))

 gs.open_group(GroupKind.BRACE)
 new_box = _hbox(width=200)
 regs.setbox(0, new_box, global_=True)
 gs.close_group()

 assert regs._slots[0] is new_box


def test_setbox_no_group_stack_no_error() -> None:
 """Without group_stack, setbox works normally with no save/restore."""
 regs = BoxRegisterSet()
 box = _hbox()
 regs.setbox(0, box)
 assert regs.getbox(0) is box


# ---------------------------------------------------------------------------
# vbox registers
# ---------------------------------------------------------------------------

def test_setbox_vbox() -> None:
 regs = BoxRegisterSet()
 vbox = _vbox()
 regs.setbox(1, vbox)
 assert regs.getbox(1) is vbox


def test_get_wd_vbox() -> None:
 regs = BoxRegisterSet()
 regs.setbox(2, _vbox(width=555))
 assert regs.get_wd(2) == 555
