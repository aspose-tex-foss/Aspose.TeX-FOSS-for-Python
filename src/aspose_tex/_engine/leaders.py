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
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken, PrimitiveRefToken
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
    from aspose_tex._engine.box_registers import BoxRegisterSet
    from aspose_tex._engine.expansion import Expander
    from aspose_tex._engine.group import GroupStack
    from aspose_tex._engine.interpreter import TeXInterpreter
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
    *,
    vertical: bool = False,
    interp: TeXInterpreter | None = None,
) -> LeadersNode:
    r"""Parse ``\leaders <box-or-rule> <skip>`` and return a node."""
    payload = _parse_payload(expander, font_manager, group_stack, box_regs, interp)
    glue = _parse_skip(expander, vertical=vertical)
    return make_leaders(kind, payload, glue)


def _parse_payload(
    expander: Expander,
    font_manager: FontManager,
    group_stack: GroupStack,
    box_regs: BoxRegisterSet,
    interp: TeXInterpreter | None,
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
    raise EngineError(f"\\leaders: expected box or rule, got \\{expander._diagnostic_cs_name(tok)}")


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


def _parse_skip(expander: Expander, *, vertical: bool) -> Glue:
    tok = _next_non_space(expander)
    if not isinstance(tok, ControlSequenceToken):
        raise EngineError(f"\\leaders: expected skip, got {tok!r}")
    axis = "v" if vertical else "h"
    if tok.name == axis + "fil":
        return make_hfil_glue().glue
    if tok.name == axis + "fill":
        return make_hfill_glue().glue
    if tok.name == axis + "ss":
        return make_hss_glue().glue
    if tok.name == axis + "filneg":
        return Glue(0, -65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)
    if tok.name == axis + "skip":
        return parse_glue(expander)
    raise EngineError(f"\\leaders: expected skip, got \\{expander._diagnostic_cs_name(tok)}")


def _next_non_space(expander: Expander):
    tok = _next_meaning(expander)
    while ((isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE)
           or (isinstance(tok, ControlSequenceToken) and tok.name == "relax")):
        tok = _next_meaning(expander)
    return tok


def _next_meaning(expander: Expander):
    tok = expander._next_unexpandable()
    while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
        tok = expander._next_unexpandable()
    seen = set()
    # A PrimitiveRefToken is already the primitive ( D3).
    while (isinstance(tok, ControlSequenceToken) and not isinstance(tok, PrimitiveRefToken)
           and tok.name not in seen):
        seen.add(tok.name)
        meaning = expander.macros.get(tok.name)
        if not isinstance(meaning, (ControlSequenceToken, CharToken)):
            break
        tok = meaning
    return tok


def leader_positions(
    kind: LeadersKind, *, start: int, span: int, extent: int, origin: int,
) -> tuple[int, ...]:
    """Return TeX's integer leader leading edges in scaled points.

    Args:
        kind: Grid, centred or expanded distribution.
        start: Leading edge of the glue.
        span: Set glue extent.
        extent: Payload width or height plus depth.
        origin: Containing list's leading edge.

    Returns:
        Payload leading edges; the caller advances by span, not the allowance.
    """
    if span <= 0 or extent <= 0:
        return ()
    allowed = span + 10
    edge = start + allowed
    q, r = divmod(allowed, extent)
    stride = extent
    if kind == LeadersKind.NORMAL:
        delta = start - origin
        grid = abs(delta) // extent * (-1 if delta < 0 else 1)
        position = origin + grid * extent
        if position < start:
            position += extent
    elif kind == LeadersKind.C:
        position = start + r // 2
    else:
        gap = r // (q + 1)
        position = start + (r - (q - 1) * gap) // 2
        stride += gap
    positions = []
    while position + extent <= edge:
        positions.append(position)
        position += stride
    return tuple(positions)
