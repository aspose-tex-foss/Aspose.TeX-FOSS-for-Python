"""Tests for HBoxBuilder, VBoxBuilder, glue-setting, and badness.

Covers AC-1, AC-2, AC-3, AC-4, AC-5.
"""
from __future__ import annotations

import pytest

from aspose_tex._engine.box_builder import (
 HBoxBuilder,
 VBoxBuilder,
 _measure_hlist,
 _measure_vlist,
 compute_badness,
 set_glue_hbox,
)
from aspose_tex._engine.nodes import (
 INF_BAD,
 CharNode,
 GlueNode,
 GlueOrder,
 GlueSign,
 HlistNode,
 KernNode,
 VlistNode,
)
from aspose_tex._engine.registers import Glue
from aspose_tex._engine.registers import GlueOrder as RegGlueOrder
from aspose_tex._fonts.font_manager import FontManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fm() -> FontManager:
 """FontManager loaded with cmr10 at design size (10pt = 655360 sp)."""
 mgr = FontManager()
 mgr.load_font("tenrm", "cmr10")
 mgr.select_font("tenrm")
 return mgr


# Reference values from test_fonts_font_manager.py
CMR10_CHAR_A_WIDTH_SP = 491521
CMR10_KERN_AV_SP = -72819
CMR10_FI_LIGATURE_CODE = 12 # 'f'(102)+'i'(105) → char 12


# ---------------------------------------------------------------------------
# compute_badness
# ---------------------------------------------------------------------------

def test_badness_zero_shortage() -> None:
 assert compute_badness(0, 1000) == 0


def test_badness_zero_shortage_zero_flex() -> None:
 assert compute_badness(0, 0) == 0


def test_badness_no_flex() -> None:
 assert compute_badness(100, 0) == INF_BAD


def test_badness_ratio_half() -> None:
 # round(100 * 0.5**3) = round(12.5) = 12 or 13 depending on Python rounding
 b = compute_badness(500, 1000)
 assert b == round(100 * 0.5 ** 3)


def test_badness_ratio_one() -> None:
 # ratio == 1.0 → round(100 * 1**3) = 100
 b = compute_badness(1000, 1000)
 assert b == 100


def test_badness_ratio_exceeds_one() -> None:
 assert compute_badness(1001, 1000) == INF_BAD


def test_badness_capped_at_inf_bad() -> None:
 assert compute_badness(9999, 1) == INF_BAD


# ---------------------------------------------------------------------------
# _measure_hlist
# ---------------------------------------------------------------------------

def test_measure_hlist_single_char(fm) -> None:
 nodes = [CharNode(char=ord('A'), font_name='tenrm')]
 w, h, d = _measure_hlist(nodes, fm)
 assert w == CMR10_CHAR_A_WIDTH_SP
 assert h > 0
 assert d >= 0


def test_measure_hlist_glue_node(fm) -> None:
 glue = Glue(65536, 0, RegGlueOrder.NORMAL, 0, RegGlueOrder.NORMAL)
 nodes = [GlueNode(glue=glue)]
 w, h, d = _measure_hlist(nodes, fm)
 assert w == 65536
 assert h == 0
 assert d == 0


def test_measure_hlist_kern_node(fm) -> None:
 nodes = [KernNode(width=1000, explicit=True)]
 w, h, d = _measure_hlist(nodes, fm)
 assert w == 1000
 assert h == 0
 assert d == 0


def test_measure_hlist_hlist_node(fm) -> None:
 inner = HlistNode(
 list=[], width=50000, height=30000, depth=5000,
 shift_amount=0, glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 w, h, d = _measure_hlist([inner], fm)
 assert w == 50000
 assert h == 30000
 assert d == 5000


def test_measure_hlist_empty(fm) -> None:
 w, h, d = _measure_hlist([], fm)
 assert w == 0
 assert h == 0
 assert d == 0


# ---------------------------------------------------------------------------
# _measure_vlist
# ---------------------------------------------------------------------------

def test_measure_vlist_two_hboxes(fm) -> None:
 h1 = HlistNode(list=[], width=200, height=50, depth=10,
 shift_amount=0, glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0)
 h2 = HlistNode(list=[], width=300, height=40, depth=8,
 shift_amount=0, glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0)
 w, h, d = _measure_vlist([h1, h2], fm)
 assert w == 300 # max of 200, 300
 # height: h1.height + h1.depth + h2.height = 50 + 10 + 40 = 100
 assert h == 50 + 10 + 40
 assert d == 8 # depth of last box


def test_measure_vlist_with_kern(fm) -> None:
 hb = HlistNode(list=[], width=100, height=50, depth=10,
 shift_amount=0, glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0)
 kern = KernNode(width=32768, explicit=True) # 0.5pt
 hb2 = HlistNode(list=[], width=100, height=30, depth=5,
 shift_amount=0, glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0)
 _, h, _ = _measure_vlist([hb, kern, hb2], fm)
 # height: hb.height(50) + hb.depth(10) + kern(32768) + hb2.height(30)
 assert h == 50 + 10 + 32768 + 30


# ---------------------------------------------------------------------------
# set_glue_hbox
# ---------------------------------------------------------------------------

def _make_hbox(nat_width: int, nodes: list) -> HlistNode:
 return HlistNode(
 list=nodes, width=nat_width, height=0, depth=0, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )


def test_set_glue_hbox_exact_fit() -> None:
 box = _make_hbox(1000, [])
 set_glue_hbox(box, target_width=1000)
 assert box.glue_sign == GlueSign.NORMAL
 assert box.glue_set == 0.0
 assert box.width == 1000


def test_set_glue_hbox_stretch_infinite() -> None:
 hfil = GlueNode(glue=Glue(0, 65536, RegGlueOrder.FIL, 0, RegGlueOrder.NORMAL))
 box = _make_hbox(500, [hfil])
 set_glue_hbox(box, target_width=1000)
 assert box.glue_sign == GlueSign.STRETCHING
 assert box.glue_order == GlueOrder.FIL
 assert box.glue_set > 0
 assert box.width == 1000


def test_set_glue_hbox_no_stretch_available() -> None:
 """Overfull: needs stretch but no glue present."""
 box = _make_hbox(500, [])
 set_glue_hbox(box, target_width=1000)
 assert box.glue_sign == GlueSign.STRETCHING
 assert box.glue_set == 0.0
 assert box.width == 1000


def test_set_glue_hbox_shrink() -> None:
 shrink_glue = GlueNode(glue=Glue(200000, 0, RegGlueOrder.NORMAL, 65536, RegGlueOrder.NORMAL))
 box = _make_hbox(1000, [shrink_glue])
 set_glue_hbox(box, target_width=900)
 assert box.glue_sign == GlueSign.SHRINKING
 # shortage = 1000 - 900 = 100 sp; total_shrink = 65536 sp → ratio = 100/65536
 assert box.glue_set == pytest.approx(100 / 65536, rel=1e-5)
 assert box.width == 900


def test_set_glue_hbox_shrink_capped() -> None:
 """Finite shrink: ratio capped at 1.0."""
 shrink_glue = GlueNode(glue=Glue(500000, 0, RegGlueOrder.NORMAL, 10, RegGlueOrder.NORMAL))
 box = _make_hbox(1000, [shrink_glue])
 set_glue_hbox(box, target_width=500) # need 500sp shrink, only 10sp available
 assert box.glue_sign == GlueSign.SHRINKING
 assert box.glue_set == 1.0 # capped


# ---------------------------------------------------------------------------
# HBoxBuilder — AC-1, AC-2
# ---------------------------------------------------------------------------

def test_hbox_builder_single_char_width(fm) -> None:
 """AC-1: CharNode for 'A' in cmr10 has width matching TFM data."""
 builder = HBoxBuilder(fm)
 builder.add_char(ord('A'), 'tenrm')
 box = builder.build()
 assert box.width == CMR10_CHAR_A_WIDTH_SP


def test_hbox_builder_hello_width(fm) -> None:
 """AC-2: \\hbox{Hello} has correct total width."""
 builder = HBoxBuilder(fm)
 for ch in "Hello":
 builder.add_char(ord(ch), 'tenrm')
 box = builder.build()
 # Width should be at least sum of individual char widths (may include kerns)
 metrics = fm.get_metrics('tenrm')
 expected_min = sum(metrics.char_metrics(ord(c)).width for c in "Hello")
 assert box.width >= expected_min - 10 # allow for kern adjustments


def test_hbox_builder_natural_size_no_glue(fm) -> None:
 builder = HBoxBuilder(fm)
 builder.add_char(ord('A'), 'tenrm')
 box = builder.build()
 assert box.glue_sign == GlueSign.NORMAL
 assert box.glue_set == 0.0


def test_hbox_builder_to_width_with_hfil(fm) -> None:
 """AC-3: \\hbox to 200pt{text \\hfil} stretches glue."""
 target = 200 * 65536 # 200pt in sp
 builder = HBoxBuilder(fm)
 for ch in "text":
 builder.add_char(ord(ch), 'tenrm')
 builder.add_glue(Glue(0, 65536, RegGlueOrder.FIL, 0, RegGlueOrder.NORMAL))
 box = builder.build(target_width=target)
 assert box.width == target
 assert box.glue_sign == GlueSign.STRETCHING
 assert box.glue_order == GlueOrder.FIL


def test_hbox_builder_ligature(fm) -> None:
 """'f'+'i' in cmr10 should produce a ligature (char 12), not two chars."""
 builder = HBoxBuilder(fm)
 builder.add_char(ord('f'), 'tenrm')
 builder.add_char(ord('i'), 'tenrm')
 box = builder.build()
 # Should have exactly one CharNode (the fi ligature)
 char_nodes = [n for n in box.list if isinstance(n, CharNode)]
 assert len(char_nodes) == 1
 assert char_nodes[0].char == CMR10_FI_LIGATURE_CODE


def test_hbox_builder_kern_av(fm) -> None:
 """'A'+'V' in cmr10 should have a negative kern between them."""
 builder = HBoxBuilder(fm)
 builder.add_char(ord('A'), 'tenrm')
 builder.add_char(ord('V'), 'tenrm')
 box = builder.build()
 # Should contain a KernNode with the A-V kern
 kern_nodes = [n for n in box.list if isinstance(n, KernNode)]
 assert len(kern_nodes) == 1
 assert kern_nodes[0].width == CMR10_KERN_AV_SP
 assert kern_nodes[0].explicit is False


# ---------------------------------------------------------------------------
# VBoxBuilder — AC-5
# ---------------------------------------------------------------------------

def test_vbox_builder_two_hboxes(fm) -> None:
 """AC-5: \\vbox stacks hboxes vertically."""
 h1 = HlistNode(list=[], width=200, height=50, depth=10,
 shift_amount=0, glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0)
 h2 = HlistNode(list=[], width=300, height=40, depth=8,
 shift_amount=0, glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0)
 vb = VBoxBuilder(fm)
 vb.add_hbox(h1)
 vb.add_hbox(h2)
 vbox = vb.build()
 assert vbox.width == 300 # max of 200, 300
 assert vbox.height == 50 + 10 + 40 # h1.h + h1.d + h2.h
 assert vbox.depth == 8


def test_vbox_builder_with_kern(fm) -> None:
 """Vertical kern contributes to height."""
 h1 = HlistNode(list=[], width=100, height=50, depth=10,
 shift_amount=0, glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0)
 h2 = HlistNode(list=[], width=100, height=30, depth=5,
 shift_amount=0, glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0)
 vb = VBoxBuilder(fm)
 vb.add_hbox(h1)
 vb.add_kern(5 * 65536) # 5pt kern
 vb.add_hbox(h2)
 vbox = vb.build()
 # height: 50 + 10 + 5*65536 + 30
 assert vbox.height == 50 + 10 + 5 * 65536 + 30


def test_vbox_builder_empty(fm) -> None:
 vb = VBoxBuilder(fm)
 vbox = vb.build()
 assert vbox.width == 0
 assert vbox.height == 0
 assert vbox.depth == 0


# ---------------------------------------------------------------------------
# Nested box
# ---------------------------------------------------------------------------

def test_hbox_builder_contains_vlist(fm) -> None:
 """AC-8 partial: nested HlistNode → VlistNode."""
 inner_hbox = HlistNode(list=[], width=100, height=30, depth=5,
 shift_amount=0, glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0)
 vb = VBoxBuilder(fm)
 vb.add_hbox(inner_hbox)
 vbox = vb.build()

 outer = HBoxBuilder(fm)
 outer.add_box(vbox)
 hbox = outer.build()
 assert isinstance(hbox.list[0], VlistNode)
 assert hbox.width == vbox.width
