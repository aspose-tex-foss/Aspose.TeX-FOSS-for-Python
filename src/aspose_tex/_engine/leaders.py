r"""Helpers for ``\leaders`` / ``\cleaders`` / ``\xleaders`` nodes."""
from __future__ import annotations

from typing import TYPE_CHECKING

from aspose_tex._engine.dimparser import _scan_keyword, parse_dimen, parse_glue, parse_integer
from aspose_tex._engine.nodes import (
 RUNNING_DIMEN,
 HlistNode,
 LeadersKind,
 LeadersNode,
 RuleNode,
 VlistNode,
)
from aspose_tex._engine.par_primitives import make_hfil_glue, make_hfill_glue, make_hss_glue
from aspose_tex._engine.registers import Glue
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
 from aspose_tex._engine.box_registers import BoxRegisterSet
 from aspose_tex._engine.expansion import Expander
 from aspose_tex._engine.group import GroupStack
 from aspose_tex._fonts.font_manager import FontManager


def make_leaders(
 kind: LeadersKind,
 payload: HlistNode | VlistNode | RuleNode,
 glue: Glue,
) -> LeadersNode:
 """Build a leaders node from a payload box/rule and skip glue."""
 return LeadersNode(kind=kind, payload=payload, glue=glue)


def parse_leaders(
 expander: Expander,
 font_manager: FontManager,
 group_stack: GroupStack,
 box_regs: BoxRegisterSet,
 kind: LeadersKind,
) -> LeadersNode:
 r"""Parse ``\leaders <box-or-rule> <skip>`` and return a node."""
 payload = _parse_payload(expander, font_manager, group_stack, box_regs)
 glue = _parse_skip(expander)
 return make_leaders(kind, payload, glue)


def _parse_payload(
 expander: Expander,
 font_manager: FontManager,
 group_stack: GroupStack,
 box_regs: BoxRegisterSet,
) -> HlistNode | VlistNode | RuleNode:
 tok = _next_non_space(expander)
 if not isinstance(tok, ControlSequenceToken):
 raise EngineError(f"\\leaders: expected box or rule, got {tok!r}")

 from aspose_tex._engine.box_primitives import (
 _scan_box_keyword,
 exec_hbox,
 exec_vbox,
 exec_vtop,
 )

 if tok.name == "hrule":
 return _parse_rule(expander, horizontal=True)
 if tok.name == "vrule":
 return _parse_rule(expander, horizontal=False)
 if tok.name == "hbox":
 tw, sp = _scan_box_keyword(expander)
 return exec_hbox(expander, font_manager, group_stack, box_regs, target_width=tw, spread=sp)
 if tok.name == "vbox":
 th, sp = _scan_box_keyword(expander)
 return exec_vbox(expander, font_manager, group_stack, box_regs, target_height=th, spread=sp)
 if tok.name == "vtop":
 th, sp = _scan_box_keyword(expander)
 return exec_vtop(expander, font_manager, group_stack, box_regs, target_height=th, spread=sp)
 if tok.name == "copy":
 box = box_regs.copybox(parse_integer(expander))
 if box is None:
 raise EngineError("\\leaders: \\copy register is void")
 return box
 if tok.name == "box":
 box = box_regs.getbox(parse_integer(expander))
 if box is None:
 raise EngineError("\\leaders: \\box register is void")
 return box
 raise EngineError(f"\\leaders: expected box or rule, got \\{tok.name}")


def _parse_rule(expander: Expander, *, horizontal: bool) -> RuleNode:
 width = RUNNING_DIMEN if horizontal else 26_214
 height = 26_214 if horizontal else RUNNING_DIMEN
 depth = 0 if horizontal else RUNNING_DIMEN
 while True:
 if _scan_keyword(expander, "width"):
 width = parse_dimen(expander)
 elif _scan_keyword(expander, "height"):
 height = parse_dimen(expander)
 elif _scan_keyword(expander, "depth"):
 depth = parse_dimen(expander)
 else:
 break
 return RuleNode(width=width, height=height, depth=depth)


def _parse_skip(expander: Expander) -> Glue:
 tok = _next_non_space(expander)
 if not isinstance(tok, ControlSequenceToken):
 raise EngineError(f"\\leaders: expected skip, got {tok!r}")
 if tok.name == "hfil":
 return make_hfil_glue().glue
 if tok.name == "hfill":
 return make_hfill_glue().glue
 if tok.name == "hss":
 return make_hss_glue().glue
 if tok.name == "hskip":
 return parse_glue(expander)
 raise EngineError(f"\\leaders: expected skip, got \\{tok.name}")


def _next_non_space(expander: Expander):
 tok = expander._next_unexpandable()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = expander._next_unexpandable()
 return tok
