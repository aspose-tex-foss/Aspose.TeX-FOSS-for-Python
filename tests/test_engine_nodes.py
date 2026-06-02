"""Tests for TeX node types.

Covers FR-1: node type definitions.
"""
from __future__ import annotations

import dataclasses

import pytest

from aspose_tex._engine.nodes import (
 INF_BAD,
 INF_PENALTY,
 NEG_INF_PENALTY,
 NODE_TYPES,
 RUNNING_DIMEN,
 CharNode,
 GlueNode,
 GlueOrder,
 GlueSign,
 HlistNode,
 InsertNode,
 KernNode,
 LeadersKind,
 LeadersNode,
 MarkNode,
 PenaltyNode,
 RuleNode,
 VlistNode,
 WhatsitNode,
 deep_copy_node,
)
from aspose_tex._engine.registers import Glue
from aspose_tex._engine.registers import GlueOrder as RegGlueOrder

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_running_dimen_value() -> None:
 assert RUNNING_DIMEN == -(1 << 30)


def test_inf_penalty_value() -> None:
 assert INF_PENALTY == 10_000


def test_neg_inf_penalty_value() -> None:
 assert NEG_INF_PENALTY == -10_000


def test_inf_bad_value() -> None:
 assert INF_BAD == 10_000


# ---------------------------------------------------------------------------
# CharNode
# ---------------------------------------------------------------------------

def test_char_node_fields() -> None:
 node = CharNode(char=ord('A'), font_name='tenrm')
 assert node.char == 65
 assert node.font_name == 'tenrm'


def test_char_node_frozen() -> None:
 node = CharNode(char=65, font_name='tenrm')
 with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
 node.char = 66 # type: ignore[misc]


# ---------------------------------------------------------------------------
# KernNode
# ---------------------------------------------------------------------------

def test_kern_node_fields() -> None:
 node = KernNode(width=1000, explicit=True)
 assert node.width == 1000
 assert node.explicit is True


def test_kern_node_frozen() -> None:
 node = KernNode(width=500, explicit=False)
 with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
 node.width = 0 # type: ignore[misc]


# ---------------------------------------------------------------------------
# GlueNode
# ---------------------------------------------------------------------------

def test_glue_node_fields() -> None:
 g = Glue(0, 65536, RegGlueOrder.FIL, 0, RegGlueOrder.NORMAL)
 node = GlueNode(glue=g)
 assert node.glue is g


def test_glue_node_frozen() -> None:
 g = Glue(0, 0, RegGlueOrder.NORMAL, 0, RegGlueOrder.NORMAL)
 node = GlueNode(glue=g)
 with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
 node.glue = g # type: ignore[misc]


# ---------------------------------------------------------------------------
# PenaltyNode
# ---------------------------------------------------------------------------

def test_penalty_node_fields() -> None:
 node = PenaltyNode(penalty=INF_PENALTY)
 assert node.penalty == INF_PENALTY


def test_penalty_node_neg_inf() -> None:
 node = PenaltyNode(penalty=NEG_INF_PENALTY)
 assert node.penalty == -10_000


def test_penalty_node_frozen() -> None:
 node = PenaltyNode(penalty=0)
 with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
 node.penalty = 1 # type: ignore[misc]


# ---------------------------------------------------------------------------
# RuleNode
# ---------------------------------------------------------------------------

def test_rule_node_fields() -> None:
 node = RuleNode(width=65536 * 100, height=26214, depth=0)
 assert node.width == 65536 * 100
 assert node.height == 26214
 assert node.depth == 0


def test_rule_node_running_dimen() -> None:
 node = RuleNode(width=RUNNING_DIMEN, height=RUNNING_DIMEN, depth=RUNNING_DIMEN)
 assert node.width == RUNNING_DIMEN


def test_rule_node_frozen() -> None:
 node = RuleNode(width=0, height=0, depth=0)
 with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
 node.width = 1 # type: ignore[misc]


# ---------------------------------------------------------------------------
# WhatsitNode
# ---------------------------------------------------------------------------

def test_whatsit_node_fields() -> None:
 payload = object()
 node = WhatsitNode(data=payload)
 assert node.data is payload


def test_leaders_node_fields() -> None:
 payload = RuleNode(width=1, height=2, depth=3)
 glue = Glue(4, 5, RegGlueOrder.FIL, 0, RegGlueOrder.NORMAL)
 node = LeadersNode(kind=LeadersKind.X, payload=payload, glue=glue)

 assert node.kind == LeadersKind.X
 assert node.payload is payload
 assert node.glue is glue


def test_mark_node_fields() -> None:
 node = MarkNode(tokens=("a",))

 assert node.tokens == ("a",)


def test_insert_node_fields() -> None:
 glue = Glue(0, 1, RegGlueOrder.FIL, 0, RegGlueOrder.NORMAL)
 node = InsertNode(
 class_=254,
 vlist=(PenaltyNode(0),),
 height=10,
 depth=2,
 floating_penalty=9999,
 split_top_skip=glue,
 split_max_depth=4,
 )

 assert node.class_ == 254
 assert node.vlist == (PenaltyNode(0),)
 assert node.floating_penalty == 9999
 assert node.split_top_skip is glue
 assert node.split_max_depth == 4


# ---------------------------------------------------------------------------
# HlistNode — mutable
# ---------------------------------------------------------------------------

def test_hlist_node_fields() -> None:
 box = HlistNode(
 list=[],
 width=100,
 height=50,
 depth=10,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 assert box.width == 100
 assert box.height == 50
 assert box.depth == 10
 assert box.shift_amount == 0
 assert box.glue_sign == GlueSign.NORMAL


def test_hlist_node_mutable() -> None:
 box = HlistNode(
 list=[],
 width=100,
 height=50,
 depth=10,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 box.shift_amount = 65536
 assert box.shift_amount == 65536


def test_hlist_node_glue_fields_settable() -> None:
 box = HlistNode(
 list=[],
 width=0,
 height=0,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 box.glue_sign = GlueSign.STRETCHING
 box.glue_order = GlueOrder.FIL
 box.glue_set = 1.5
 assert box.glue_sign == GlueSign.STRETCHING
 assert box.glue_order == GlueOrder.FIL
 assert box.glue_set == 1.5


# ---------------------------------------------------------------------------
# VlistNode — mutable
# ---------------------------------------------------------------------------

def test_vlist_node_fields() -> None:
 box = VlistNode(
 list=[],
 width=200,
 height=100,
 depth=20,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 assert box.width == 200
 assert box.height == 100


def test_vlist_node_mutable() -> None:
 box = VlistNode(
 list=[],
 width=0,
 height=0,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 box.shift_amount = -65536
 assert box.shift_amount == -65536


# ---------------------------------------------------------------------------
# deep_copy_node
# ---------------------------------------------------------------------------

def test_deep_copy_hlist_node_is_new_object() -> None:
 child = CharNode(65, 'tenrm')
 original = HlistNode(
 list=[child],
 width=100,
 height=50,
 depth=10,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 clone = deep_copy_node(original)
 assert clone is not original
 assert isinstance(clone, HlistNode)
 assert clone.list is not original.list
 assert clone.width == original.width


def test_deep_copy_hlist_node_children_are_new() -> None:
 child = CharNode(65, 'tenrm')
 original = HlistNode(
 list=[child],
 width=100,
 height=50,
 depth=10,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 clone = deep_copy_node(original)
 # The list is a new list object
 assert clone.list is not original.list
 # CharNode is frozen — deepcopy creates new but equal object
 assert clone.list[0] == original.list[0]


def test_deep_copy_char_node_returns_same_object() -> None:
 """Frozen nodes are safe to share — deep_copy_node returns the original."""
 node = CharNode(65, 'tenrm')
 result = deep_copy_node(node)
 assert result is node


def test_deep_copy_kern_node_returns_same_object() -> None:
 node = KernNode(1000, True)
 assert deep_copy_node(node) is node


def test_deep_copy_glue_node_returns_same_object() -> None:
 node = GlueNode(glue=Glue(0, 0, RegGlueOrder.NORMAL, 0, RegGlueOrder.NORMAL))
 assert deep_copy_node(node) is node


def test_deep_copy_penalty_node_returns_same_object() -> None:
 node = PenaltyNode(penalty=0)
 assert deep_copy_node(node) is node


def test_deep_copy_rule_node_returns_same_object() -> None:
 node = RuleNode(width=0, height=0, depth=0)
 assert deep_copy_node(node) is node


def test_deep_copy_leaders_node_returns_same_object() -> None:
 node = LeadersNode(
 kind=LeadersKind.NORMAL,
 payload=RuleNode(width=0, height=0, depth=0),
 glue=Glue(0, 0, RegGlueOrder.NORMAL, 0, RegGlueOrder.NORMAL),
 )
 assert deep_copy_node(node) is node


def test_deep_copy_mark_node_returns_same_object() -> None:
 node = MarkNode(tokens=())
 assert deep_copy_node(node) is node


def test_deep_copy_insert_node_returns_same_object() -> None:
 node = InsertNode(
 class_=254,
 vlist=(),
 height=0,
 depth=0,
 floating_penalty=0,
 split_top_skip=Glue(0, 0, RegGlueOrder.NORMAL, 0, RegGlueOrder.NORMAL),
 split_max_depth=0,
 )
 assert deep_copy_node(node) is node


# ---------------------------------------------------------------------------
# NODE_TYPES tuple
# ---------------------------------------------------------------------------

def test_node_types_contains_all() -> None:
 assert CharNode in NODE_TYPES
 assert HlistNode in NODE_TYPES
 assert VlistNode in NODE_TYPES
 assert GlueNode in NODE_TYPES
 assert KernNode in NODE_TYPES
 assert PenaltyNode in NODE_TYPES
 assert RuleNode in NODE_TYPES
 assert LeadersNode in NODE_TYPES
 assert MarkNode in NODE_TYPES
 assert InsertNode in NODE_TYPES
 assert WhatsitNode in NODE_TYPES


def test_isinstance_with_node_types() -> None:
 assert isinstance(CharNode(65, 'f'), NODE_TYPES)
 assert isinstance(HlistNode([], 0, 0, 0, 0, GlueSign.NORMAL, GlueOrder.NORMAL, 0.0), NODE_TYPES)


# ---------------------------------------------------------------------------
# GlueSign enum
# ---------------------------------------------------------------------------

def test_glue_sign_values() -> None:
 assert GlueSign.NORMAL == 0
 assert GlueSign.STRETCHING == 1
 assert GlueSign.SHRINKING == 2


def test_leaders_kind_values() -> None:
 assert LeadersKind.NORMAL == 0
 assert LeadersKind.C == 1
 assert LeadersKind.X == 2
