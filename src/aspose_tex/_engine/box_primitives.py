"""Execution handlers for TeX box primitives.

Implements FR-4 through FR-7, FR-12 through FR-15:
``\\hbox``, ``\\vbox``, ``\\setbox``, ``\\box``, ``\\copy``,
``\\wd``, ``\\ht``, ``\\dp``, ``\\raise``, ``\\lower``,
``\\moveleft``, ``\\moveright``.

Each function is a pure transformation or scanning operation; none
maintains its own state.

See the project documentation for design rationale.
"""
from __future__ import annotations

import dataclasses
import warnings
from typing import TYPE_CHECKING

from aspose_tex._engine.box_builder import (
 HBoxBuilder,
 VBoxBuilder,
 compute_badness,
 vsplit_at_height,
)
from aspose_tex._engine.box_registers import BoxRegisterSet
from aspose_tex._engine.dimparser import (
 _scan_keyword,
 parse_dimen,
 parse_glue,
 parse_integer,
)
from aspose_tex._engine.group import GroupKind
from aspose_tex._engine.nodes import (
 INF_BAD,
 RUNNING_DIMEN,
 CharNode,
 DiscretionaryNode,
 GlueNode,
 GlueOrder,
 GlueSign,
 HlistNode,
 KernNode,
 LeadersKind,
 PenaltyNode,
 RuleNode,
 VlistNode,
)
from aspose_tex._engine.page_primitives import (
 make_vfil_glue,
 make_vfill_glue,
 make_vfilneg_glue,
 make_vss_glue,
)
from aspose_tex._engine.registers import Glue
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken

if TYPE_CHECKING:
 from aspose_tex._engine.expansion import Expander
 from aspose_tex._engine.group import GroupStack
 from aspose_tex._fonts.font_manager import FontManager

from aspose_tex.exceptions import EngineError

# ---------------------------------------------------------------------------
# Warning types
# ---------------------------------------------------------------------------

class OverfullBoxWarning(UserWarning):
 """Issued when an hbox or vbox is overfull (badness == INF_BAD, box too wide)."""


class UnderfullBoxWarning(UserWarning):
 """Issued when an hbox or vbox is underfull (badness > 100 with only finite glue)."""


# ---------------------------------------------------------------------------
# Keyword scanning
# ---------------------------------------------------------------------------

def _scan_box_keyword(expander: Expander) -> tuple[int | None, int | None]:
 """Scan optional ``to <dimen>`` or ``spread <dimen>`` after ``\\hbox`` / ``\\vbox``.

 Returns:
 ``(target_width, spread)`` — at most one is non-None.
 Both None if neither keyword is present.

 Uses ``_scan_keyword`` from dimparser (same low-level interface).
 """
 if _scan_keyword(expander, "to"):
 return parse_dimen(expander), None
 if _scan_keyword(expander, "spread"):
 return None, parse_dimen(expander)
 return None, None


# ---------------------------------------------------------------------------
# Shift helper
# ---------------------------------------------------------------------------

def apply_shift(
 box: HlistNode | VlistNode,
 amount: int,
 *,
 vertical: bool,
) -> HlistNode | VlistNode:
 """Return *box* with ``shift_amount`` set to *amount*.

 For ``\\raise`` / ``\\lower`` (vertical=True):
 - ``\\raise <d>`` passes ``+d``.
 - ``\\lower <d>`` passes ``-d``.

 For ``\\moveleft`` / ``\\moveright`` (vertical=False):
 - ``\\moveleft <d>`` passes ``+d``.
 - ``\\moveright <d>`` passes ``-d``.

 Returns a new dataclass instance (via ``dataclasses.replace``) so the
 original box is not mutated.

 Args:
 box: Source box node.
 amount: Displacement in sp.
 vertical: True for horizontal-mode shift (raise/lower);
 False for vertical-mode shift (moveleft/moveright).

 Example::

 raised = apply_shift(my_hbox, 65536, vertical=True) # \\raise 1pt
 assert raised.shift_amount == 65536
 """
 return dataclasses.replace(box, shift_amount=amount)


# ---------------------------------------------------------------------------
# Internal: next box from stream (for \\raise, \\lower, \\moveleft, \\moveright)
# ---------------------------------------------------------------------------

def _scan_next_box(
 expander: Expander,
 font_manager: FontManager,
 group_stack: GroupStack,
 box_regs: BoxRegisterSet,
) -> HlistNode | VlistNode:
 """Consume the next box-producing token from expander.

 Handles ``\\hbox[to/spread]{...}``, ``\\vbox[to/spread]{...}``,
 ``\\vtop[to/spread]{...}``, ``\\box<n>``, and ``\\copy<n>``.

 Raises:
 EngineError: if the next token is not ``\\hbox`` or ``\\vbox``.
 """
 # Skip optional spaces
 tok = expander._next_unexpandable()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = expander._next_unexpandable()

 if not isinstance(tok, ControlSequenceToken):
 raise EngineError(f"Box expected after \\raise/\\lower/\\moveleft/\\moveright, got {tok!r}")
 if tok.name == "hbox":
 tw, sp = _scan_box_keyword(expander)
 return exec_hbox(expander, font_manager, group_stack, box_regs,
 target_width=tw, spread=sp)
 if tok.name == "vbox":
 tw, sp = _scan_box_keyword(expander)
 return exec_vbox(expander, font_manager, group_stack, box_regs,
 target_height=tw, spread=sp)
 if tok.name == "vtop":
 tw, sp = _scan_box_keyword(expander)
 return exec_vtop(expander, font_manager, group_stack, box_regs,
 target_height=tw, spread=sp)
 if tok.name == "box":
 idx = parse_integer(expander)
 box = box_regs.getbox(idx)
 if box is None:
 raise EngineError("\\box register is void")
 return box
 if tok.name == "copy":
 idx = parse_integer(expander)
 box = box_regs.copybox(idx)
 if box is None:
 raise EngineError("\\copy register is void")
 return box
 raise EngineError(f"\\hbox or \\vbox expected, got \\{tok.name}")


def _first_baseline_height(nodes: list, fallback: int) -> int:
 """Return the height of the first box/rule node in a vertical list."""
 for node in nodes:
 if isinstance(node, (HlistNode, VlistNode)):
 return node.height
 if isinstance(node, RuleNode):
 return 0 if node.height == RUNNING_DIMEN else node.height
 return fallback


def exec_vtop(
 expander: Expander,
 font_manager: FontManager,
 group_stack: GroupStack,
 box_regs: BoxRegisterSet,
 *,
 target_height: int | None = None,
 spread: int | None = None,
) -> VlistNode:
 """Build ``\\vtop`` with its baseline at the first item."""
 box = exec_vbox(
 expander,
 font_manager,
 group_stack,
 box_regs,
 target_height=target_height,
 spread=spread,
 )
 total = box.height + box.depth
 first_height = _first_baseline_height(box.list, box.height)
 box.height = first_height
 box.depth = max(0, total - first_height)
 return box


def exec_unbox(
 expander: Expander,
 box_regs: BoxRegisterSet,
 *,
 copy: bool,
 vertical: bool,
) -> list:
 """Return nodes spliced by ``\\unhbox`` / ``\\unvbox`` families."""
 idx = parse_integer(expander)
 box = box_regs.copybox(idx) if copy else box_regs.getbox(idx)
 if box is None:
 return []
 if vertical and not isinstance(box, VlistNode):
 raise EngineError("\\unvbox expected a vbox register")
 if not vertical and not isinstance(box, HlistNode):
 raise EngineError("\\unhbox expected an hbox register")
 return list(box.list)


def exec_unskip(target) -> None:
 """Remove a trailing ``GlueNode`` from a node list target if present."""
 nodes = _target_nodes(target)
 if nodes and isinstance(nodes[-1], GlueNode):
 nodes.pop()


def exec_unkern(target) -> None:
 """Remove a trailing ``KernNode`` from a node list target if present."""
 nodes = _target_nodes(target)
 if nodes and isinstance(nodes[-1], KernNode):
 nodes.pop()


def exec_unpenalty(target) -> None:
 """Remove a trailing ``PenaltyNode`` from a node list target if present."""
 nodes = _target_nodes(target)
 if nodes and isinstance(nodes[-1], PenaltyNode):
 nodes.pop()


def exec_lastbox(target, mode) -> HlistNode | VlistNode | None:
 """Remove and return the trailing box node from a list target."""
 if getattr(mode, "name", None) == "OUTER_VERTICAL":
 raise EngineError("\\lastbox in outer vertical mode")
 nodes = _target_nodes(target)
 if nodes and isinstance(nodes[-1], (HlistNode, VlistNode)):
 return nodes.pop()
 return None


def _dispatch_internal_quantity_assignment(expander: Expander, name: str) -> bool:
 """Execute an InternalQuantityRegistry assignment in restricted box scanners.

 Mirrors the dispatch precedence in ``TeXInterpreter._dispatch_cs`` and
 ``RegisterSet.get_tokens_for_the``: InternalQuantityRegistry is consulted
 before the Appendix A registry. Read-only entries raise
 ``EngineError`` inside ``dispatch_assignment``, matching the top-level
 behaviour. added this site so that retiring the shadowed Appendix A
 placeholders (e.g. ``\\prevdepth``) does not break vbox/hbox writes.
 """
 interp = getattr(expander, "_interpreter", None)
 if interp is None:
 return False
 registry = getattr(interp, "_internal_quantities", None)
 if registry is None:
 return False
 entry = registry.lookup(name)
 if entry is None:
 return False
 registry.dispatch_assignment(entry, expander)
 return True


def _dispatch_named_assignment(expander: Expander, name: str) -> bool:
 """Execute a named-parameter assignment in restricted box scanners."""
 named = getattr(expander, "_named_params", None)
 if named is None:
 return False
 entry = named.lookup(name)
 if entry is None:
 return False
 named.dispatch_assignment(entry, expander)
 return True


def _dispatch_register_assignment(expander: Expander, name: str) -> bool:
 """Execute a register-family or register-alias assignment in box scanners."""
 regs = getattr(expander, "_register_set", None)
 if regs is None:
 return False
 return bool(regs.execute(name, expander))


def _scan_vbox_text_line(
 first_tok,
 expander: Expander,
 font_manager: FontManager,
 group_stack: GroupStack,
 box_regs: BoxRegisterSet,
 *,
 initial_indent_sp: int | None = None,
) -> HlistNode:
 """Collect text encountered in a vbox into one restricted hbox line.

 When *initial_indent_sp* is non-None, the builder is seeded with an
 explicit indent kern of that width before the first token is read.
 Used by the cascade #3 ``\\indent`` / ``\\noindent`` paragraph
 bootstrap inside ``exec_vbox`` so that plain.tex's ``\\textindent``
 (``\\indent\\llap{#1\\enspace}\\ignorespaces``) lands a single
 ``\\parindent``-wide indent kern at the start of the resulting hlist
 instead of leaving the indent context at h=0.
 """
 builder = HBoxBuilder(font_manager, badness_sink=_badness_sink(expander))
 if initial_indent_sp:
 builder.add_kern(initial_indent_sp, explicit=True)
 tok = first_tok
 while True:
 if tok is None:
 break
 if isinstance(tok, CharToken):
 if tok.catcode == Catcode.END_GROUP:
 expander._stack.append(tok)
 break
 if tok.catcode in (Catcode.LETTER, Catcode.OTHER):
 current_font = font_manager._current
 if current_font is None:
 raise EngineError("No font selected")
 builder.add_char(ord(tok.char), current_font)
 elif tok.catcode == Catcode.SPACE:
 builder.add_glue(_interword_glue(font_manager))
 elif tok.catcode == Catcode.BEGIN_GROUP:
 group_stack.open_group(GroupKind.BRACE)
 else:
 raise EngineError(f"Unexpected character token in vbox text: {tok!r}")
 elif isinstance(tok, ControlSequenceToken):
 name = tok.name
 if name == "par":
 break
 if name in ("relax", "ignorespaces"):
 if name == "ignorespaces":
 nxt = expander.peek()
 while isinstance(nxt, CharToken) and nxt.catcode == Catcode.SPACE:
 expander._next_unexpandable()
 nxt = expander.peek()
 elif name == "kern":
 builder.add_kern(parse_dimen(expander), explicit=True)
 elif name == "hskip":
 builder.add_glue(parse_glue(expander))
 elif name == "unhbox":
 for node in exec_unbox(expander, box_regs, copy=False, vertical=False):
 builder._nodes.append(node)
 elif name == "unhcopy":
 for node in exec_unbox(expander, box_regs, copy=True, vertical=False):
 builder._nodes.append(node)
 elif name == "hbox":
 tw, sp = _scan_box_keyword(expander)
 builder.add_box(exec_hbox(
 expander, font_manager, group_stack, box_regs,
 target_width=tw, spread=sp,
 ))
 elif name == "vbox":
 th, sp = _scan_box_keyword(expander)
 builder.add_box(exec_vbox(
 expander, font_manager, group_stack, box_regs,
 target_height=th, spread=sp,
 ))
 elif name == "vrule":
 builder._nodes.append(_scan_vrule(expander))
 elif name == "char":
 exec_char(expander, font_manager, builder)
 elif font_manager.is_font(name):
 font_manager.select_font(name)
 elif (
 _dispatch_internal_quantity_assignment(expander, name)
 or _dispatch_named_assignment(expander, name)
 or _dispatch_register_assignment(expander, name)
 ):
 pass
 else:
 expander._stack.append(tok)
 break
 else:
 raise EngineError(f"Unexpected token in vbox text: {tok!r}")
 tok = expander._next_unexpandable()
 return builder.build()


def exec_vsplit(
 expander: Expander,
 box_regs: BoxRegisterSet,
 *,
 splittopskip: Glue,
 split_capture_callback=None,
) -> VlistNode | None:
 """Execute simplified ``\\vsplit<n> to <dimen>`` for M3."""
 idx = parse_integer(expander)
 if not _scan_keyword(expander, "to"):
 raise EngineError("\\vsplit: expected 'to'")
 target_height = parse_dimen(expander)
 box = box_regs.getbox(idx)
 if box is None:
 return None
 if not isinstance(box, VlistNode):
 raise EngineError("\\vsplit expected a vbox register")
 top, residue = vsplit_at_height(box, target_height, splittopskip=splittopskip)
 box_regs.setbox(idx, residue)
 if split_capture_callback is not None:
 split_capture_callback(top.list)
 return top


def _target_nodes(target) -> list:
 """Return the mutable node list from a paragraph/list builder target."""
 if hasattr(target, "_nodes"):
 return target._nodes
 if hasattr(target, "_mvl"):
 return target._mvl
 raise EngineError("node list target is not mutable")


# ---------------------------------------------------------------------------
# Interword space glue helper
# ---------------------------------------------------------------------------

def _interword_glue(font_manager: FontManager) -> Glue:
 """Return interword space glue from the current font's fontdimen 2/3/4.

 Falls back to zero glue if no font is selected or font has no params.
 """
 current = font_manager._current
 if current is None:
 return Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
 try:
 space = font_manager.fontdimen(current, 2)
 stretch = font_manager.fontdimen(current, 3)
 shrink = font_manager.fontdimen(current, 4)
 except Exception:
 return Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
 return Glue(space, stretch, GlueOrder.NORMAL, shrink, GlueOrder.NORMAL)


def _current_font_name(font_manager: FontManager) -> str:
 """Return the selected font control-sequence name."""
 current = font_manager._current
 if current is None:
 raise EngineError("No font selected")
 return current


def _append_char_node(
 font_manager: FontManager,
 par_list_or_hbuilder,
 code: int,
) -> None:
 """Append a character code to a paragraph list or hbox builder."""
 font_name = _current_font_name(font_manager)
 if hasattr(par_list_or_hbuilder, "add_char"):
 par_list_or_hbuilder.add_char(code, font_name)
 return
 par_list_or_hbuilder.append(CharNode(char=code, font_name=font_name))


def _scan_char_code(expander: Expander) -> int:
 """Read a text character operand for ``\\accent``."""
 tok = expander._next_unexpandable()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = expander._next_unexpandable()
 if isinstance(tok, CharToken) and tok.catcode in (Catcode.LETTER, Catcode.OTHER):
 return ord(tok.char)
 if isinstance(tok, ControlSequenceToken) and tok.name == "char":
 code = parse_integer(expander)
 _check_char_code(code, "\\char")
 return code
 raise EngineError(f"\\accent: expected character, got {tok!r}")


def _check_char_code(code: int, command: str) -> None:
 """Validate a TeX text character code."""
 if not (0 <= code <= 255):
 raise EngineError(f"{command}: code {code} out of range 0-255")


def exec_char(expander: Expander, font_manager: FontManager, par_list_or_hbuilder) -> None:
 """Execute ``\\char<n>`` and append the character to the current hlist."""
 code = parse_integer(expander)
 _check_char_code(code, "\\char")
 _append_char_node(font_manager, par_list_or_hbuilder, code)


def exec_accent(expander: Expander, font_manager: FontManager, par_list_or_hbuilder) -> None:
 """Execute ``\\accent<n><char>`` as a kerned hbox holding accent and base."""
 accent_code = parse_integer(expander)
 _check_char_code(accent_code, "\\accent")
 base_code = _scan_char_code(expander)
 font_name = _current_font_name(font_manager)
 metrics = font_manager.current_metrics
 if metrics is None:
 raise EngineError("No font selected")
 accent_metrics = metrics.char_metrics(accent_code)
 base_metrics = metrics.char_metrics(base_code)
 kern = max(0, (base_metrics.width - accent_metrics.width) // 2)
 nodes = [
 KernNode(width=kern, explicit=False),
 CharNode(char=accent_code, font_name=font_name),
 KernNode(width=-kern - accent_metrics.width, explicit=False),
 CharNode(char=base_code, font_name=font_name),
 ]
 box = HlistNode(
 list=nodes,
 width=base_metrics.width,
 height=max(base_metrics.height, accent_metrics.height + metrics.fontdimen(5)),
 depth=base_metrics.depth,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 if hasattr(par_list_or_hbuilder, "add_box"):
 par_list_or_hbuilder.add_box(box)
 else:
 par_list_or_hbuilder.append(box)


def _read_discretionary_branch(
 expander: Expander,
 font_manager: FontManager,
 group_stack: GroupStack,
 box_regs: BoxRegisterSet,
) -> tuple:
 """Read one balanced ``\\discretionary`` branch into hlist nodes."""
 open_tok = expander._next_unexpandable()
 if not (isinstance(open_tok, CharToken) and open_tok.catcode == Catcode.BEGIN_GROUP):
 raise EngineError(f"Expected '{{' in \\discretionary, got {open_tok!r}")
 builder = HBoxBuilder(font_manager, badness_sink=_badness_sink(expander))
 depth = 0
 while True:
 tok = expander._next_unexpandable()
 if tok is None:
 raise EngineError("Unexpected end of input inside \\discretionary")
 if isinstance(tok, CharToken) and tok.catcode == Catcode.END_GROUP:
 if depth == 0:
 break
 depth -= 1
 continue
 if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
 depth += 1
 continue
 if isinstance(tok, CharToken):
 if tok.catcode in (Catcode.LETTER, Catcode.OTHER):
 builder.add_char(ord(tok.char), _current_font_name(font_manager))
 elif tok.catcode == Catcode.SPACE:
 builder.add_glue(_interword_glue(font_manager))
 else:
 raise EngineError(f"Unexpected token in \\discretionary: {tok!r}")
 continue
 if isinstance(tok, ControlSequenceToken):
 if tok.name == "char":
 exec_char(expander, font_manager, builder)
 elif tok.name == "hbox":
 tw, sp = _scan_box_keyword(expander)
 builder.add_box(exec_hbox(
 expander, font_manager, group_stack, box_regs,
 target_width=tw, spread=sp,
 ))
 else:
 raise EngineError(f"Unexpected token in \\discretionary: \\{tok.name}")
 return tuple(builder._nodes)


def exec_discretionary(
 expander: Expander,
 font_manager: FontManager,
 group_stack: GroupStack,
 box_regs: BoxRegisterSet,
 par_list_or_hbuilder,
) -> None:
 """Execute ``\\discretionary{pre}{post}{nobreak}``."""
 node = DiscretionaryNode(
 pre=_read_discretionary_branch(expander, font_manager, group_stack, box_regs),
 post=_read_discretionary_branch(expander, font_manager, group_stack, box_regs),
 nobreak=_read_discretionary_branch(expander, font_manager, group_stack, box_regs),
 )
 if hasattr(par_list_or_hbuilder, "add_box"):
 par_list_or_hbuilder._nodes.append(node)
 else:
 par_list_or_hbuilder.append(node)


# ---------------------------------------------------------------------------
# exec_hbox
# ---------------------------------------------------------------------------

def exec_hbox(
 expander: Expander,
 font_manager: FontManager,
 group_stack: GroupStack,
 box_regs: BoxRegisterSet,
 *,
 target_width: int | None = None,
 spread: int | None = None,
) -> HlistNode:
 """Scan ``{...}`` content and build an ``HlistNode``.

 Expects the expander to yield the opening ``{`` (catcode BEGIN_GROUP)
 as the first token. The caller has already consumed ``\\hbox`` and
 any optional ``to <dimen>`` / ``spread <dimen>``.

 Dispatches tokens in horizontal mode. See for the full
 dispatch table.

 Raises:
 EngineError: on unexpected token or no font selected for characters.
 """
 # Consume opening {
 open_tok = expander._next_unexpandable()
 if not (isinstance(open_tok, CharToken) and open_tok.catcode == Catcode.BEGIN_GROUP):
 raise EngineError(
 f"Expected '{{' to open \\hbox, got {open_tok!r}"
 )
 from aspose_tex._engine.group import GroupKind
 group_stack.open_group(GroupKind.BRACE)

 builder = HBoxBuilder(font_manager, badness_sink=_badness_sink(expander))
 inner_depth = 0 # depth of extra nested brace groups inside the hbox

 while True:
 tok = expander._next_unexpandable()
 if tok is None:
 raise EngineError("Unexpected end of input inside \\hbox")

 # --- End group ---
 if isinstance(tok, CharToken) and tok.catcode == Catcode.END_GROUP:
 if inner_depth == 0:
 group_stack.close_group()
 break
 inner_depth -= 1
 group_stack.close_group()
 continue

 # --- Begin group (nested braces in content) ---
 if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
 inner_depth += 1
 group_stack.open_group(GroupKind.BRACE)
 continue

 # --- Character tokens ---
 if isinstance(tok, CharToken):
 if tok.catcode in (Catcode.LETTER, Catcode.OTHER):
 current_font = font_manager._current
 if current_font is None:
 raise EngineError("No font selected")
 builder.add_char(ord(tok.char), current_font)
 continue
 if tok.catcode == Catcode.SPACE:
 builder.add_glue(_interword_glue(font_manager))
 continue
 raise EngineError(f"Unexpected token in hbox: {tok!r}")

 # --- Control sequences ---
 if isinstance(tok, ControlSequenceToken):
 name = tok.name
 if name == "kern":
 sp = parse_dimen(expander)
 builder.add_kern(sp, explicit=True)
 elif name == "hskip":
 g = parse_glue(expander)
 builder.add_glue(g)
 elif name == "unhbox":
 for node in exec_unbox(expander, box_regs, copy=False, vertical=False):
 builder._nodes.append(node)
 elif name == "unhcopy":
 for node in exec_unbox(expander, box_regs, copy=True, vertical=False):
 builder._nodes.append(node)
 elif name == "unskip":
 exec_unskip(builder)
 elif name == "unkern":
 exec_unkern(builder)
 elif name == "unpenalty":
 exec_unpenalty(builder)
 elif name == "lastbox":
 box = exec_lastbox(builder, None)
 if box is not None:
 builder.add_box(box)
 elif name == "hfil":
 builder.add_glue(Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL))
 elif name == "hfill":
 builder.add_glue(Glue(0, 65536, GlueOrder.FILL, 0, GlueOrder.NORMAL))
 elif name == "hss":
 builder.add_glue(Glue(0, 65536, GlueOrder.FIL, 65536, GlueOrder.FIL))
 elif (
 _dispatch_internal_quantity_assignment(expander, name)
 or _dispatch_named_assignment(expander, name)
 or _dispatch_register_assignment(expander, name)
 ):
 pass
 elif name == "penalty":
 n = parse_integer(expander)
 builder.add_penalty(n)
 elif name == "char":
 exec_char(expander, font_manager, builder)
 elif name == "accent":
 exec_accent(expander, font_manager, builder)
 elif name == "discretionary":
 exec_discretionary(expander, font_manager, group_stack, box_regs, builder)
 elif name == "vrule":
 builder._nodes.append(_scan_vrule(expander))
 elif name == "insert":
 raise EngineError("\\insert is not allowed inside an hbox")
 elif font_manager.is_font(name):
 font_manager.select_font(name)
 elif name in ("leaders", "cleaders", "xleaders"):
 from aspose_tex._engine.leaders import parse_leaders
 kind = {
 "leaders": LeadersKind.NORMAL,
 "cleaders": LeadersKind.C,
 "xleaders": LeadersKind.X,
 }[name]
 builder._nodes.append(parse_leaders(
 expander, font_manager, group_stack, box_regs, kind,
 ))
 elif name == "hbox":
 tw, sp = _scan_box_keyword(expander)
 inner = exec_hbox(expander, font_manager, group_stack, box_regs,
 target_width=tw, spread=sp)
 builder.add_box(inner)
 elif name == "vbox":
 tw, sp = _scan_box_keyword(expander)
 inner = exec_vbox(expander, font_manager, group_stack, box_regs,
 target_height=tw, spread=sp)
 builder.add_box(inner)
 elif name == "vtop":
 tw, sp = _scan_box_keyword(expander)
 inner = exec_vtop(expander, font_manager, group_stack, box_regs,
 target_height=tw, spread=sp)
 builder.add_box(inner)
 elif name == "raise":
 amount = parse_dimen(expander)
 inner_box = _scan_next_box(expander, font_manager, group_stack, box_regs)
 builder.add_box(apply_shift(inner_box, amount, vertical=True))
 elif name == "lower":
 amount = parse_dimen(expander)
 inner_box = _scan_next_box(expander, font_manager, group_stack, box_regs)
 builder.add_box(apply_shift(inner_box, -amount, vertical=True))
 else:
 raise EngineError(f"Unexpected token in hbox: \\{name}")
 continue

 raise EngineError(f"Unexpected token in hbox: {tok!r}")

 box = builder.build(target_width=target_width, spread=spread)

 # Warn if overfull or underfull (see error handling)
 _warn_badness(box, mode="h")
 return box


def _scan_vrule(expander: Expander) -> RuleNode:
 r"""Scan ``\vrule`` dimensions for restricted horizontal mode."""
 width = 26_214
 height = RUNNING_DIMEN
 depth = RUNNING_DIMEN
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


def _scan_hrule(expander: Expander) -> RuleNode:
 r"""Scan ``\hrule`` dimensions for internal vertical mode."""
 width = RUNNING_DIMEN
 height = 26_214
 depth = 0
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


# ---------------------------------------------------------------------------
# exec_vbox
# ---------------------------------------------------------------------------

_PREVDEPTH_SENTINEL = -65_536_000 # -1000 pt; TeXbook §253 "ignore" marker


def _read_named_skip(expander: Expander, name: str) -> Glue | None:
 """Return the live ``Glue`` for SKIP named-param *name*, or None."""
 named = getattr(expander, "_named_params", None)
 regs = getattr(expander, "_register_set", None)
 if named is None or regs is None:
 return None
 entry = named.lookup(name)
 if entry is None:
 return None
 return regs.get_skip(entry.slot, _internal=True)


def _read_named_dimen(expander: Expander, name: str) -> int | None:
 """Return the live ``sp`` value for DIMEN named-param *name*, or None."""
 named = getattr(expander, "_named_params", None)
 regs = getattr(expander, "_register_set", None)
 if named is None or regs is None:
 return None
 entry = named.lookup(name)
 if entry is None:
 return None
 return regs.get_dimen(entry.slot, _internal=True)


def _last_box_depth(nodes: list) -> int | None:
 """Return the depth of the last box-like node in *nodes*, or None."""
 for node in reversed(nodes):
 if isinstance(node, (HlistNode, VlistNode)):
 return node.depth
 if isinstance(node, RuleNode):
 return 0 if node.depth == RUNNING_DIMEN else node.depth
 return None


def exec_vbox(
 expander: Expander,
 font_manager: FontManager,
 group_stack: GroupStack,
 box_regs: BoxRegisterSet,
 *,
 target_height: int | None = None,
 spread: int | None = None,
) -> VlistNode:
 """Scan ``{...}`` content and build a ``VlistNode``.

 Expects the opening ``{`` as the first token from expander.
 Dispatches tokens in vertical mode. See for the dispatch table.

 Interline glue between consecutive contributed boxes is inserted live
 using ``\\baselineskip`` / ``\\lineskip`` / ``\\lineskiplimit`` from the
 named-parameter registry (TeXbook §253 / TeX:The Program §679).
 ``\\prevdepth`` is treated as vbox-local: saved on entry, reset to the
 -1000 pt sentinel, restored on exit. This closes cascade #1:
 plain-TeX ``\\makefootline`` writes ``\\baselineskip=24pt`` which is now
 honoured by the outer ``\\vbox{\\makeheadline\\pagebody\\makefootline}``
 of ``\\plainoutput``.
 """
 open_tok = expander._next_unexpandable()
 if not (isinstance(open_tok, CharToken) and open_tok.catcode == Catcode.BEGIN_GROUP):
 raise EngineError(f"Expected '{{' to open \\vbox, got {open_tok!r}")
 from aspose_tex._engine.group import GroupKind
 group_stack.open_group(GroupKind.BRACE)

 vbuilder = VBoxBuilder(font_manager, badness_sink=_badness_sink(expander))
 inner_depth = 0

 interp = getattr(expander, "_interpreter", None)
 page_builder = getattr(interp, "_page_builder", None) if interp is not None else None
 saved_prev_depth = interp._prev_depth if interp is not None else None
 saved_pb_prev_depth = page_builder._prev_depth if page_builder is not None else None
 saved_pb_page_depth = page_builder._page_depth if page_builder is not None else None
 if interp is not None:
 interp._prev_depth = _PREVDEPTH_SENTINEL

 def _emit_interline_glue(next_box_height: int) -> None:
 """Insert interline glue before a non-first box per TeX §679."""
 if interp is None:
 return
 prev = interp._prev_depth
 if prev <= _PREVDEPTH_SENTINEL:
 return
 baselineskip = _read_named_skip(expander, "baselineskip")
 if baselineskip is None:
 return
 lineskiplimit = _read_named_dimen(expander, "lineskiplimit") or 0
 ideal = baselineskip.width - prev - next_box_height
 if ideal < lineskiplimit:
 lineskip = _read_named_skip(expander, "lineskip")
 if lineskip is None:
 return
 vbuilder.add_glue(lineskip)
 else:
 vbuilder.add_glue(Glue(
 ideal,
 baselineskip.stretch, baselineskip.stretch_order,
 baselineskip.shrink, baselineskip.shrink_order,
 ))

 def _track_box(box: HlistNode | VlistNode) -> None:
 if interp is not None:
 interp._prev_depth = box.depth

 def _track_rule(rule: RuleNode) -> None:
 """Contribute a rule and reset the interline-glue chain (TeX §679).

 Per TeX:The Program §679, a rule node in vertical mode is a non-box
 discardable: no interline glue is emitted before it, and ``prevdepth``
 is reset to the entry sentinel so any subsequent box contribution
 likewise does not receive interline glue. This allows
 ``\\vbox{a\\hrule b}`` to compose two separate baselines around the
 rule. See .
 """
 vbuilder._nodes.append(rule)
 if interp is not None:
 interp._prev_depth = _PREVDEPTH_SENTINEL

 def _track_splice(spliced: list) -> None:
 """Update ``prevdepth`` after a verbatim ``\\unvbox`` / ``\\unvcopy`` splice.

 Per TeX:The Program §1083, the spliced children already carry their
 own internal interline glue; real TeX does not re-emit glue before
 the first spliced child. After the splice, ``prevdepth`` is set to
 the depth of the last box-like child (``HlistNode`` / ``VlistNode``);
 if the splice ends on a rule (a non-box discardable), ``prevdepth``
 is reset to the entry sentinel so the next outer box contribution
 does not receive spurious interline glue. An empty splice or a
 splice composed only of "transparent" discardables (kern / glue /
 penalty / whatsit) leaves ``prevdepth`` unchanged. See .
 """
 if interp is None or not spliced:
 return
 for node in reversed(spliced):
 if isinstance(node, RuleNode):
 interp._prev_depth = _PREVDEPTH_SENTINEL
 return
 if isinstance(node, (HlistNode, VlistNode)):
 interp._prev_depth = node.depth
 return

 def _add_hbox(box: HlistNode) -> None:
 _emit_interline_glue(box.height)
 vbuilder.add_hbox(box)
 _track_box(box)

 def _add_vbox(box: VlistNode) -> None:
 _emit_interline_glue(box.height)
 vbuilder.add_vbox(box)
 _track_box(box)

 try:
 while True:
 tok = expander._next_unexpandable()
 if tok is None:
 raise EngineError("Unexpected end of input inside \\vbox")

 if isinstance(tok, CharToken) and tok.catcode == Catcode.END_GROUP:
 if inner_depth == 0:
 group_stack.close_group()
 break
 inner_depth -= 1
 group_stack.close_group()
 continue

 if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
 inner_depth += 1
 group_stack.open_group(GroupKind.BRACE)
 continue

 if isinstance(tok, CharToken):
 if tok.catcode in (Catcode.LETTER, Catcode.OTHER, Catcode.SPACE):
 _add_hbox(_scan_vbox_text_line(
 tok, expander, font_manager, group_stack, box_regs,
 ))
 continue
 raise EngineError(f"Unexpected character token in vbox: {tok!r}")

 if isinstance(tok, ControlSequenceToken):
 name = tok.name
 if name == "hbox":
 tw, sp = _scan_box_keyword(expander)
 _add_hbox(exec_hbox(expander, font_manager, group_stack, box_regs,
 target_width=tw, spread=sp))
 elif name == "vbox":
 tw, sp = _scan_box_keyword(expander)
 _add_vbox(exec_vbox(expander, font_manager, group_stack, box_regs,
 target_height=tw, spread=sp))
 elif name == "box":
 idx = parse_integer(expander)
 box = box_regs.getbox(idx)
 if isinstance(box, HlistNode):
 _add_hbox(box)
 elif isinstance(box, VlistNode):
 _add_vbox(box)
 elif name == "copy":
 idx = parse_integer(expander)
 box = box_regs.copybox(idx)
 if isinstance(box, HlistNode):
 _add_hbox(box)
 elif isinstance(box, VlistNode):
 _add_vbox(box)
 elif name == "vskip":
 g = parse_glue(expander)
 vbuilder.add_glue(g)
 elif name == "hrule":
 _track_rule(_scan_hrule(expander))
 elif name == "vfil":
 vbuilder.add_glue(make_vfil_glue().glue)
 elif name == "vfill":
 vbuilder.add_glue(make_vfill_glue().glue)
 elif name == "vfilneg":
 vbuilder.add_glue(make_vfilneg_glue().glue)
 elif name == "vss":
 vbuilder.add_glue(make_vss_glue().glue)
 elif name in ("indent", "noindent"):
 # cascade #3: `\indent` / `\noindent` in internal
 # vertical mode (vbox scanner) start a paragraph. Real TeX
 # auto-switches to horizontal mode here (TeXbook ch. 13);
 # plain.tex's `\textindent` (`\indent\llap{#1\enspace}…`)
 # relies on this to anchor the indent kern + remaining
 # tokens (`\llap`, `\footstrut`, body text) as ONE hlist
 # line. Without this, `\vfootnote` produced three vlist
 # items (`\llap` hbox, `\footstrut` vbox, body hbox) each
 # starting at h=0, so the note text appeared at the raw
 # page-left edge instead of `\parindent` (=20pt) right.
 indent_sp = (
 _read_named_dimen(expander, "parindent") or 0
 ) if name == "indent" else 0
 nxt = expander._next_unexpandable()
 if nxt is None:
 raise EngineError(
 "Unexpected end of input after \\indent in vbox"
 )
 if (
 isinstance(nxt, CharToken)
 and nxt.catcode == Catcode.END_GROUP
 ):
 # Empty paragraph: just emit an indent-kern-only hbox
 # for `\indent`, or skip entirely for `\noindent`.
 if indent_sp:
 builder = HBoxBuilder(
 font_manager, badness_sink=_badness_sink(expander)
 )
 builder.add_kern(indent_sp, explicit=True)
 _add_hbox(builder.build())
 expander._stack.append(nxt)
 else:
 _add_hbox(_scan_vbox_text_line(
 nxt, expander, font_manager, group_stack, box_regs,
 initial_indent_sp=indent_sp or None,
 ))
 elif name == "ignorespaces":
 nxt = expander.peek()
 while isinstance(nxt, CharToken) and nxt.catcode == Catcode.SPACE:
 expander._next_unexpandable()
 nxt = expander.peek()
 elif (
 _dispatch_internal_quantity_assignment(expander, name)
 or _dispatch_named_assignment(expander, name)
 or _dispatch_register_assignment(expander, name)
 ):
 pass
 elif name == "unvbox":
 spliced = exec_unbox(expander, box_regs, copy=False, vertical=True)
 for node in spliced:
 vbuilder._nodes.append(node)
 _track_splice(spliced)
 elif name == "unvcopy":
 spliced = exec_unbox(expander, box_regs, copy=True, vertical=True)
 for node in spliced:
 vbuilder._nodes.append(node)
 _track_splice(spliced)
 elif name == "unskip":
 exec_unskip(vbuilder)
 elif name == "unkern":
 exec_unkern(vbuilder)
 elif name == "unpenalty":
 exec_unpenalty(vbuilder)
 elif name == "lastbox":
 box = exec_lastbox(vbuilder, None)
 if isinstance(box, HlistNode):
 _add_hbox(box)
 elif isinstance(box, VlistNode):
 _add_vbox(box)
 elif name == "setbox":
 idx = parse_integer(expander)
 next_tok = expander.peek()
 while isinstance(next_tok, CharToken) and next_tok.catcode == Catcode.SPACE:
 expander._next_unexpandable()
 next_tok = expander.peek()
 if isinstance(next_tok, CharToken) and next_tok.char == "=" and next_tok.catcode == Catcode.OTHER:
 expander._next_unexpandable()
 next_tok = expander._next_unexpandable()
 while isinstance(next_tok, CharToken) and next_tok.catcode == Catcode.SPACE:
 next_tok = expander._next_unexpandable()
 if isinstance(next_tok, ControlSequenceToken) and next_tok.name == "lastbox":
 box_regs.setbox(idx, exec_lastbox(vbuilder, None))
 elif isinstance(next_tok, ControlSequenceToken) and next_tok.name == "hbox":
 tw, sp = _scan_box_keyword(expander)
 box_regs.setbox(idx, exec_hbox(
 expander, font_manager, group_stack, box_regs,
 target_width=tw, spread=sp,
 ))
 elif isinstance(next_tok, ControlSequenceToken) and next_tok.name == "vbox":
 th, sp = _scan_box_keyword(expander)
 box_regs.setbox(idx, exec_vbox(
 expander, font_manager, group_stack, box_regs,
 target_height=th, spread=sp,
 ))
 else:
 raise EngineError(f"\\setbox: expected box primitive, got {next_tok!r}")
 elif name == "kern":
 sp = parse_dimen(expander)
 vbuilder.add_kern(sp)
 elif name == "penalty":
 n = parse_integer(expander)
 vbuilder.add_penalty(n)
 elif name == "moveleft":
 amount = parse_dimen(expander)
 inner_box = _scan_next_box(expander, font_manager, group_stack, box_regs)
 shifted = apply_shift(inner_box, amount, vertical=False)
 if isinstance(shifted, HlistNode):
 _add_hbox(shifted)
 else:
 _add_vbox(shifted)
 elif name == "moveright":
 amount = parse_dimen(expander)
 inner_box = _scan_next_box(expander, font_manager, group_stack, box_regs)
 shifted = apply_shift(inner_box, -amount, vertical=False)
 if isinstance(shifted, HlistNode):
 _add_hbox(shifted)
 else:
 _add_vbox(shifted)
 else:
 raise EngineError(f"Unexpected token in vbox: \\{name}")
 continue

 raise EngineError(f"Unexpected token in vbox: {tok!r}")
 finally:
 if interp is not None:
 interp._prev_depth = saved_prev_depth
 if page_builder is not None:
 page_builder._prev_depth = saved_pb_prev_depth
 page_builder._page_depth = saved_pb_page_depth

 box = vbuilder.build(target_height=target_height, spread=spread)
 _warn_badness_vbox(box)
 return box


# ---------------------------------------------------------------------------
# Badness warnings (internal)
# ---------------------------------------------------------------------------

def _warn_badness(box: HlistNode, mode: str = "h") -> None:
 """Emit overfull/underfull warning if badness is significant."""
 if box.glue_sign == GlueSign.NORMAL:
 return
 if box.glue_order != GlueOrder.NORMAL:
 # Infinite glue is being used — box cannot be overfull
 return

 # Finite glue: reconstruct shortage from glue_set * total_flex.
 if box.glue_sign == GlueSign.STRETCHING:
 total = sum(
 n.glue.stretch for n in box.list
 if isinstance(n, GlueNode) and n.glue.stretch_order == GlueOrder.NORMAL
 )
 else:
 total = sum(
 n.glue.shrink for n in box.list
 if isinstance(n, GlueNode) and n.glue.shrink_order == GlueOrder.NORMAL
 )

 if total == 0:
 # No flex at all — box cannot be set; always overfull/underfull
 warnings.warn(
 "Overfull \\hbox (no flex available)",
 OverfullBoxWarning,
 stacklevel=3,
 )
 return

 shortage = round(box.glue_set * total)
 bad = compute_badness(shortage, total)
 if bad >= INF_BAD:
 warnings.warn(
 f"Overfull \\hbox (badness {bad})",
 OverfullBoxWarning,
 stacklevel=3,
 )
 elif bad > 100:
 warnings.warn(
 f"Underfull \\hbox (badness {bad})",
 UnderfullBoxWarning,
 stacklevel=3,
 )


def _warn_badness_vbox(box: VlistNode) -> None:
 """Emit overfull/underfull warning for a vbox if badness is significant."""
 if box.glue_sign == GlueSign.NORMAL:
 return
 if box.glue_order != GlueOrder.NORMAL:
 # Infinite glue is being used — box cannot be overfull
 return

 # Finite glue: reconstruct shortage from glue_set * total_flex.
 if box.glue_sign == GlueSign.STRETCHING:
 total = sum(
 n.glue.stretch for n in box.list
 if isinstance(n, GlueNode) and n.glue.stretch_order == GlueOrder.NORMAL
 )
 else:
 total = sum(
 n.glue.shrink for n in box.list
 if isinstance(n, GlueNode) and n.glue.shrink_order == GlueOrder.NORMAL
 )

 if total == 0:
 # No flex at all — box cannot be set; always overfull # See 
 warnings.warn(
 "Overfull \\vbox (no flex available)",
 OverfullBoxWarning,
 stacklevel=3,
 )
 return

 shortage = round(box.glue_set * total)
 bad = compute_badness(shortage, total)
 if bad >= INF_BAD:
 warnings.warn(
 f"Overfull \\vbox (badness {bad})",
 OverfullBoxWarning,
 stacklevel=3,
 )
 elif bad > 100:
 warnings.warn(
 f"Underfull \\vbox (badness {bad})",
 UnderfullBoxWarning,
 stacklevel=3,
 )


def _badness_sink(expander: Expander):
 interp = getattr(expander, "_interpreter", None)
 if interp is None:
 return None
 return getattr(interp, "_set_badness", None)
