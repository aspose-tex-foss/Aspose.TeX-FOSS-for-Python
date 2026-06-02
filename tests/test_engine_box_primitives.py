"""Tests for box primitives: exec_hbox, exec_vbox, apply_shift.

Covers AC-3, AC-4, AC-8 and testing section.
"""
from __future__ import annotations

import pytest

from aspose_tex._engine.box_primitives import (
 OverfullBoxWarning,
 apply_shift,
 exec_hbox,
 exec_vbox,
)
from aspose_tex._engine.box_registers import BoxRegisterSet
from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.group import GroupStack
from aspose_tex._engine.nodes import (
 CharNode,
 GlueNode,
 GlueOrder,
 GlueSign,
 HlistNode,
 VlistNode,
)
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._input import (
 CatcodeTable,
 InputReader,
 StringInputSource,
 Tokenizer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_expander(text: str) -> Expander:
 src = StringInputSource(text)
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 return Expander(reader, tok, catcodes)


def make_setup(text: str) -> tuple[Expander, FontManager, GroupStack, BoxRegisterSet]:
 exp = make_expander(text)
 fm = FontManager()
 fm.load_font("tenrm", "cmr10")
 fm.select_font("tenrm")
 gs = GroupStack()
 regs = BoxRegisterSet(group_stack=gs)
 return exp, fm, gs, regs


# Reference values
CMR10_CHAR_A_WIDTH_SP = 491521


# ---------------------------------------------------------------------------
# apply_shift
# ---------------------------------------------------------------------------

def test_apply_shift_raise() -> None:
 box = HlistNode(
 list=[], width=100, height=50, depth=10, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 raised = apply_shift(box, 65536, vertical=True)
 assert raised.shift_amount == 65536
 assert raised is not box
 assert box.shift_amount == 0 # original unchanged


def test_apply_shift_lower() -> None:
 box = HlistNode(
 list=[], width=100, height=50, depth=10, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 lowered = apply_shift(box, -65536, vertical=True)
 assert lowered.shift_amount == -65536


def test_apply_shift_moveleft() -> None:
 vbox = VlistNode(
 list=[], width=100, height=50, depth=10, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 shifted = apply_shift(vbox, 32768, vertical=False)
 assert shifted.shift_amount == 32768
 assert shifted is not vbox


def test_apply_shift_returns_same_type_hlist() -> None:
 box = HlistNode(
 list=[], width=0, height=0, depth=0, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 result = apply_shift(box, 1000, vertical=True)
 assert isinstance(result, HlistNode)


def test_apply_shift_returns_same_type_vlist() -> None:
 box = VlistNode(
 list=[], width=0, height=0, depth=0, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
 )
 result = apply_shift(box, 1000, vertical=False)
 assert isinstance(result, VlistNode)


# ---------------------------------------------------------------------------
# exec_hbox — basic
# ---------------------------------------------------------------------------

def test_exec_hbox_simple_chars() -> None:
 """AC-2 / exec: \\hbox{A} produces HlistNode with correct width."""
 exp, fm, gs, regs = make_setup("{A}")
 box = exec_hbox(exp, fm, gs, regs)
 assert isinstance(box, HlistNode)
 char_nodes = [n for n in box.list if isinstance(n, CharNode)]
 assert len(char_nodes) >= 1
 assert char_nodes[0].char == ord('A')
 assert box.width == CMR10_CHAR_A_WIDTH_SP


def test_exec_hbox_empty() -> None:
 exp, fm, gs, regs = make_setup("{}")
 box = exec_hbox(exp, fm, gs, regs)
 assert isinstance(box, HlistNode)
 assert box.width == 0
 assert box.list == []


def test_exec_hbox_multiple_chars_width() -> None:
 exp, fm, gs, regs = make_setup("{Hi}")
 box = exec_hbox(exp, fm, gs, regs)
 assert isinstance(box, HlistNode)
 assert box.width > 0


def test_exec_hbox_returns_hlist_node() -> None:
 exp, fm, gs, regs = make_setup("{x}")
 result = exec_hbox(exp, fm, gs, regs)
 assert isinstance(result, HlistNode)


# ---------------------------------------------------------------------------
# exec_hbox — to / spread — AC-3
# ---------------------------------------------------------------------------

def test_exec_hbox_to_width() -> None:
 """AC-3: \\hbox to 200pt{text \\hfil} stretches glue."""
 target = 200 * 65536
 exp, fm, gs, regs = make_setup(r"{text\hfil}")
 box = exec_hbox(exp, fm, gs, regs, target_width=target)
 assert box.width == target
 assert box.glue_sign == GlueSign.STRETCHING
 assert box.glue_order == GlueOrder.FIL


def test_exec_hbox_glue_nodes_in_list() -> None:
 """\\hfil inserts a GlueNode."""
 exp, fm, gs, regs = make_setup(r"{\hfil}")
 box = exec_hbox(exp, fm, gs, regs)
 glue_nodes = [n for n in box.list if isinstance(n, GlueNode)]
 assert len(glue_nodes) == 1
 assert glue_nodes[0].glue.stretch_order == GlueOrder.FIL


def test_exec_hbox_hfill() -> None:
 exp, fm, gs, regs = make_setup(r"{\hfill}")
 box = exec_hbox(exp, fm, gs, regs, target_width=100 * 65536)
 assert box.glue_order == GlueOrder.FILL


def test_exec_hbox_hss() -> None:
 exp, fm, gs, regs = make_setup(r"{\hss}")
 box = exec_hbox(exp, fm, gs, regs)
 glue_nodes = [n for n in box.list if isinstance(n, GlueNode)]
 assert glue_nodes[0].glue.stretch_order == GlueOrder.FIL
 assert glue_nodes[0].glue.shrink_order == GlueOrder.FIL


# ---------------------------------------------------------------------------
# exec_hbox — overfull warning — AC-4
# ---------------------------------------------------------------------------

def test_exec_hbox_overfull_warning() -> None:
 """AC-4: Overfull hbox detected and reported."""
 exp, fm, gs, regs = make_setup("{A}")
 # A is ~491521 sp wide; request only 1sp
 with pytest.warns(OverfullBoxWarning):
 exec_hbox(exp, fm, gs, regs, target_width=1)


# ---------------------------------------------------------------------------
# exec_vbox — AC-5
# ---------------------------------------------------------------------------

def test_exec_vbox_two_hboxes() -> None:
 """AC-5: \\vbox{\\hbox{A}\\hbox{B}} stacks two hboxes."""
 exp, fm, gs, regs = make_setup(r"{\hbox{A}\hbox{B}}")
 vbox = exec_vbox(exp, fm, gs, regs)
 assert isinstance(vbox, VlistNode)
 hboxes = [n for n in vbox.list if isinstance(n, HlistNode)]
 assert len(hboxes) == 2


def test_exec_vbox_returns_vlist() -> None:
 exp, fm, gs, regs = make_setup(r"{\hbox{x}}")
 result = exec_vbox(exp, fm, gs, regs)
 assert isinstance(result, VlistNode)


def test_exec_vbox_empty() -> None:
 exp, fm, gs, regs = make_setup("{}")
 vbox = exec_vbox(exp, fm, gs, regs)
 assert isinstance(vbox, VlistNode)
 assert vbox.list == []


def test_exec_vbox_height_is_stacked() -> None:
 exp, fm, gs, regs = make_setup(r"{\hbox{A}\hbox{A}}")
 vbox = exec_vbox(exp, fm, gs, regs)
 # height should be > one hbox height
 single_exp, single_fm, single_gs, single_regs = make_setup("{A}")
 single_box = exec_hbox(single_exp, single_fm, single_gs, single_regs)
 assert vbox.height > single_box.height


# ---------------------------------------------------------------------------
# Nested boxes — AC-8
# ---------------------------------------------------------------------------

def test_exec_hbox_nested_vbox() -> None:
 """AC-8: \\hbox{\\vbox{\\hbox{text}}} builds correctly."""
 exp, fm, gs, regs = make_setup(r"{\vbox{\hbox{AB}}}")
 outer = exec_hbox(exp, fm, gs, regs)
 assert isinstance(outer, HlistNode)
 assert len(outer.list) == 1
 assert isinstance(outer.list[0], VlistNode)
 inner_vbox = outer.list[0]
 assert len(inner_vbox.list) == 1
 assert isinstance(inner_vbox.list[0], HlistNode)


def test_exec_vbox_nested_hbox_in_hbox() -> None:
 exp, fm, gs, regs = make_setup(r"{\hbox{\hbox{A}}}")
 vbox = exec_vbox(exp, fm, gs, regs)
 outer_hbox = vbox.list[0]
 assert isinstance(outer_hbox, HlistNode)
 inner_hbox = outer_hbox.list[0]
 assert isinstance(inner_hbox, HlistNode)


# ---------------------------------------------------------------------------
# _scan_box_keyword (via exec_hbox with to/spread)
# ---------------------------------------------------------------------------

def test_scan_keyword_to_via_exec() -> None:
 """Keyword 'to' is parsed: exec_hbox called directly with result."""
 exp, _, _, _ = make_setup(r"to 100pt{\hfil}")
 from aspose_tex._engine.box_primitives import _scan_box_keyword
 tw, sp = _scan_box_keyword(exp)
 assert tw == 100 * 65536
 assert sp is None


# ---------------------------------------------------------------------------
# _warn_badness_vbox — zero-flex overfull special case
# ---------------------------------------------------------------------------

def test_vbox_zero_flex_overfull_warning() -> None:
 """_warn_badness_vbox emits OverfullBoxWarning when vbox has no flex glue."""
 # A rigid vbox requested taller than its natural height triggers the case:
 # glue_sign != NORMAL, glue_order == NORMAL, but total flex == 0.
 exp, fm, gs, regs = make_setup(r"{\hbox{A}}")
 with pytest.warns(OverfullBoxWarning, match=r"no flex available"):
 exec_vbox(exp, fm, gs, regs, target_height=1)


def test_scan_keyword_spread_via_exec() -> None:
 exp, _, _, _ = make_setup(r"spread 5pt{\hfil}")
 from aspose_tex._engine.box_primitives import _scan_box_keyword
 tw, sp = _scan_box_keyword(exp)
 assert tw is None
 assert sp == 5 * 65536


def test_scan_keyword_none() -> None:
 exp, _, _, _ = make_setup("{A}")
 from aspose_tex._engine.box_primitives import _scan_box_keyword
 tw, sp = _scan_box_keyword(exp)
 assert tw is None
 assert sp is None
