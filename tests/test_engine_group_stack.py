"""Unit tests for GroupStack in isolation.

Tests the save/restore, global flag, aftergroup, and error handling
of GroupStack without involving Expander or RegisterSet.

See the project documentation for design rationale.
"""
import pytest

from aspose_tex._engine.group import GroupKind, GroupStack
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken
from aspose_tex.exceptions import EngineError


def test_initial_depth() -> None:
 gs = GroupStack()
 assert gs.depth == 0


def test_global_at_depth_0() -> None:
 gs = GroupStack()
 # At global level, is_global_pending is always True (depth 0)
 assert gs.is_global_pending is True


def test_global_flag_at_depth_1() -> None:
 gs = GroupStack()
 gs.open_group(GroupKind.BRACE)
 assert gs.is_global_pending is False
 gs.set_global()
 assert gs.is_global_pending is True
 gs.consume_global()
 assert gs.is_global_pending is False


def test_open_close_brace() -> None:
 gs = GroupStack()
 gs.open_group(GroupKind.BRACE)
 assert gs.depth == 1
 aftergroup, kind = gs.close_group()
 assert aftergroup == []
 assert kind == GroupKind.BRACE
 assert gs.depth == 0


def test_open_close_semi_simple() -> None:
 gs = GroupStack()
 gs.open_group(GroupKind.SEMI_SIMPLE)
 _aftergroup, kind = gs.close_group()
 assert kind == GroupKind.SEMI_SIMPLE


def test_close_empty_stack_raises() -> None:
 gs = GroupStack()
 with pytest.raises(EngineError, match="Too many"):
 gs.close_group()


def test_save_restores_value() -> None:
 gs = GroupStack()
 gs.open_group(GroupKind.BRACE)

 container = [10]
 old = container[0]
 gs.save(("test", 0), lambda: container.__setitem__(0, old))
 container[0] = 99

 assert container[0] == 99
 gs.close_group()
 assert container[0] == 10


def test_save_dedup_same_key() -> None:
 """Saving same key twice in one group → restore called only once."""
 gs = GroupStack()
 gs.open_group(GroupKind.BRACE)

 call_count = [0]
 gs.save(("x", 0), lambda: call_count.__setitem__(0, call_count[0] + 1))
 # Second save with same key — should be ignored
 gs.save(("x", 0), lambda: call_count.__setitem__(0, call_count[0] + 100))

 gs.close_group()
 assert call_count[0] == 1


def test_save_noops_at_depth_0() -> None:
 """save() at global level (depth 0) is a no-op."""
 gs = GroupStack()
 container = [42]
 old = container[0]
 gs.save(("count", 0), lambda: container.__setitem__(0, old))
 container[0] = 99
 # No group to close — value stays changed
 assert container[0] == 99


def test_aftergroup_queued_and_returned() -> None:
 gs = GroupStack()
 gs.open_group(GroupKind.BRACE)

 tok_a = CharToken("A", Catcode.LETTER)
 tok_b = CharToken("B", Catcode.LETTER)
 gs.push_aftergroup(tok_a)
 gs.push_aftergroup(tok_b)

 aftergroup, _ = gs.close_group()
 assert aftergroup == [tok_a, tok_b]


def test_aftergroup_outside_group_raises() -> None:
 gs = GroupStack()
 tok = CharToken("X", Catcode.LETTER)
 with pytest.raises(EngineError, match="aftergroup"):
 gs.push_aftergroup(tok)


def test_nested_frames_isolated() -> None:
 """Saves in inner frame don't bleed into outer frame records."""
 gs = GroupStack()
 outer = [1]
 inner = [10]

 gs.open_group(GroupKind.BRACE)
 old_outer = outer[0]
 gs.save(("outer", 0), lambda: outer.__setitem__(0, old_outer))
 outer[0] = 100

 gs.open_group(GroupKind.BRACE)
 old_inner = inner[0]
 gs.save(("inner", 0), lambda: inner.__setitem__(0, old_inner))
 inner[0] = 999

 # Close inner group — inner restored, outer untouched
 gs.close_group()
 assert inner[0] == 10
 assert outer[0] == 100

 # Close outer group — outer restored
 gs.close_group()
 assert outer[0] == 1


def test_nested_depth_tracking() -> None:
 gs = GroupStack()
 assert gs.depth == 0
 gs.open_group(GroupKind.BRACE)
 assert gs.depth == 1
 gs.open_group(GroupKind.SEMI_SIMPLE)
 assert gs.depth == 2
 gs.close_group()
 assert gs.depth == 1
 gs.close_group()
 assert gs.depth == 0


def test_restore_lifo_order() -> None:
 """Multiple saves in one group restore in LIFO order."""
 gs = GroupStack()
 gs.open_group(GroupKind.BRACE)

 order: list[int] = []
 gs.save(("a", 0), lambda: order.append(1))
 gs.save(("b", 0), lambda: order.append(2))
 gs.save(("c", 0), lambda: order.append(3))

 gs.close_group()
 assert order == [3, 2, 1]
