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
import math
import warnings
from contextlib import contextmanager
from typing import TYPE_CHECKING

from aspose_tex._engine.box_builder import (
    IGNORE_PREV_DEPTH,
    HBoxBuilder,
    VBoxBuilder,
    _box_badness_message,
    _collect_shrink,
    _measure_hlist,
    _measure_vlist,
    append_overfull_rule,
    compute_interline_glue,
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
from aspose_tex._engine.macro import active_char_key
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
    LeadersNode,
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
from aspose_tex._input.token import CharToken, ControlSequenceToken, PrimitiveRefToken, Token

if TYPE_CHECKING:
    from aspose_tex._engine.expansion import Expander
    from aspose_tex._engine.group import GroupStack
    from aspose_tex._fonts.font_manager import FontManager

from aspose_tex.exceptions import EngineError

# ---------------------------------------------------------------------------
# Warning types
# ---------------------------------------------------------------------------

class OverfullBoxWarning(UserWarning):
    """Issued when an hbox or vbox is overfull (its finite shrink falls short)."""


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
    - ``\\moveleft <d>`` passes ``-d``.
    - ``\\moveright <d>`` passes ``+d``.

    Returns a new dataclass instance (via ``dataclasses.replace``) so the
    original box is not mutated.

    Args:
        box:      Source box node.
        amount:   Displacement in sp.
        vertical: True for horizontal-mode shift (raise/lower);
                  False for vertical-mode shift (moveleft/moveright).

    Example::

        raised = apply_shift(my_hbox, 65536, vertical=True)  # \\raise 1pt
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
    raise EngineError(f"\\hbox or \\vbox expected, got \\{expander._diagnostic_cs_name(tok)}")


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
    if nodes and isinstance(nodes[-1], (GlueNode, LeadersNode)):
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
    """Remove and return the trailing box node from a list target.

    In the main vertical list (``OUTER_VERTICAL``) ``\\lastbox`` is forbidden by
    TeX:The Program §1080 *when the list has no removable last box* — the
    classic "you can't use ``\\lastbox`` in the main vertical list" error.  When
    a box has just been contributed to the contribution list (e.g. plain.tex's
    ``\\m@ketabbox`` does ``\\unvbox\\z@\\lastbox`` to re-extract the ``\\settabs``
    row), the trailing box IS removable and is popped — matching real
    TeX, which only errors at the genuinely-empty main vertical list.  The
    removed box loses any ``\\raise``/``\\moveright`` shift (§1081).
    """
    nodes = _target_nodes(target)
    if nodes and isinstance(nodes[-1], (HlistNode, VlistNode)):
        box = nodes.pop()
        box.shift_amount = 0  # §1081,
        return box
    if getattr(mode, "name", None) == "OUTER_VERTICAL":
        raise EngineError("\\lastbox in outer vertical mode")
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


def _dispatch_register_assignment(expander: Expander, name: str, *, primitive: bool = False) -> bool:
    """Execute a register-family or register-alias assignment in box scanners.

    *primitive* marks a frozen primitive reference, which skips aliases.
    """
    regs = getattr(expander, "_register_set", None)
    if regs is None:
        return False
    return bool(regs.execute(name, expander, primitive=primitive))


# Code-array primitives (§5b).  None of the three registries above owns
# them — the interpreter does — so before every box scanner raised
# "Unexpected token" on e.g. \hbox{\catcode`\@=11 }, and so did an \halign
# cell, which dispatches through the same hbox arm.
_CODE_ARRAY_CS = frozenset({
    "catcode", "mathcode", "delcode", "sfcode", "lccode", "uccode",
})


def _dispatch_code_array_assignment(expander: Expander, name: str) -> bool:
    """Execute a code-array assignment (``\\catcode`` etc.) in box scanners.

    Delegates to the interpreter's own ``_exec_<name>`` handler, so range
    checks, the ``\\global`` prefix and group save/restore are exactly those
    of the top-level path.  The assignment contributes no list material, so
    unlike ``_delegate_hbox_primitive`` no live hlist has to be installed.

    Returns:
        ``True`` if *name* was a code-array primitive and was executed;
        ``False`` otherwise, or when no interpreter is reachable.
    """
    if name not in _CODE_ARRAY_CS:
        return False
    interp = getattr(expander, "_interpreter", None)
    if interp is None:
        return False
    getattr(interp, f"_exec_{name}")()
    return True


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
    with _list_tail_scope(expander, builder):
        tok = first_tok
        while True:
            if tok is None:
                break
            if not _continues_lig_run(tok, expander):
                builder.end_run()
            if isinstance(tok, CharToken):
                if tok.catcode == Catcode.END_GROUP:
                    expander._stack.append(tok)
                    break
                if tok.catcode in (Catcode.LETTER, Catcode.OTHER):
                    _add_eager_char(expander, font_manager, builder, ord(tok.char))
                elif tok.catcode == Catcode.SPACE:
                    builder.add_glue(_interword_glue(font_manager, expander))
                elif tok.catcode == Catcode.BEGIN_GROUP:
                    group_stack.open_group(GroupKind.BRACE)
                elif tok.catcode == Catcode.MATH_SHIFT:
                    # A $…$ formula in a vbox text line (e.g. \matrix inside a
                    # \footnote body).  Mirror the eager-\hbox
                    # math barrier (dispatch_hbox_token / §C): the vbox text
                    # line is already a restricted hbox, so delegate to the
                    # interpreter to open a fresh math builder and splice the
                    # resulting nodes into this line.
                    interp = getattr(expander, "_interpreter", None)
                    if interp is None:
                        raise EngineError("inline math in \\vbox needs the interpreter")
                    for node in interp.run_inline_math_in_box(tok):
                        builder._nodes.append(node)
                    interp._spacefactor = 1000
                else:
                    raise EngineError(f"Unexpected character token in vbox text: {tok!r}")
            elif isinstance(tok, ControlSequenceToken):
                name = tok.name
                if name == "par":
                    break
                if name == " ":
                    # \  is the font's normal interword glue (§1045).
                    # No `continue`: this loop reads the next token at the bottom.
                    builder.add_glue(_interword_glue(font_manager, expander, normal=True))
                elif name in ("relax", "ignorespaces", "noboundary"):
                    if name == "ignorespaces":
                        nxt = expander.peek()
                        while isinstance(nxt, CharToken) and nxt.catcode == Catcode.SPACE:
                            expander._next_unexpandable()
                            nxt = expander.peek()
                elif name == "kern":
                    builder.add_kern(parse_dimen(expander), explicit=True)
                elif name in ("indent", "noindent"):
                    if name == "indent":
                        _append_indent_box(expander, builder)
                elif name == "/":
                    # \/ italic correction (§1112) — a vbox text line is
                    # itself a restricted hbox, so the same rule applies here.
                    builder.add_italic_correction()
                elif name == "hskip":
                    builder.add_glue(parse_glue(expander))
                elif name in ("leaders", "cleaders", "xleaders"):
                    from aspose_tex._engine.leaders import parse_leaders
                    kind = {"leaders": LeadersKind.NORMAL, "cleaders": LeadersKind.C,
                            "xleaders": LeadersKind.X}[name]
                    builder._nodes.append(parse_leaders(
                        expander, font_manager, group_stack, box_regs, kind,
                        interp=getattr(expander, "_interpreter", None),
                    ))
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
                elif name == "-":
                    _append_discretionary_hyphen(font_manager, builder)
                elif name == "unskip":
                    exec_unskip(builder)
                elif name == "unkern":
                    exec_unkern(builder)
                elif name == "unpenalty":
                    exec_unpenalty(builder)
                elif name in ("font", "fontdimen", "message", "errmessage", "write", "immediate", "show", "showthe"):
                    _dispatch_box_command(expander, name)
                elif (font_manager.is_font(name) or name in font_manager._fonts):
                    font_manager.select_font(name)
                elif (
                    _dispatch_internal_quantity_assignment(expander, name)
                    or _dispatch_named_assignment(expander, name)
                    or _dispatch_register_assignment(expander, name, primitive=isinstance(tok, PrimitiveRefToken))
                    or _dispatch_code_array_assignment(expander, name)
                ):
                    pass
                elif (code := _chardef_code(expander, name)) is not None:
                    _add_eager_char(expander, font_manager, builder, code)
                else:
                    expander._stack.append(tok)
                    break
            else:
                raise EngineError(f"Unexpected token in vbox text: {tok!r}")
            if isinstance(tok, ControlSequenceToken) and tok.name in ("hbox", "vbox"):
                interp = getattr(expander, "_interpreter", None)
                if interp is not None:
                    interp._spacefactor = 1000
            tok = expander._next_unexpandable()
    return builder.build()


def exec_vsplit(
    expander: Expander,
    box_regs: BoxRegisterSet,
    *,
    splittopskip: Glue,
    split_capture_callback=None,
) -> VlistNode | None:
    """Execute simplified ``\\vsplit<n> to <dimen>``."""
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


def _append_indent_box(expander: Expander, builder: HBoxBuilder) -> None:
    """Append the live parindent null box to an eager horizontal owner (§1093)."""
    builder.add_box(HlistNode(
        list=[], width=_read_named_dimen(expander, "parindent") or 0,
        height=0, depth=0, shift_amount=0, glue_sign=GlueSign.NORMAL,
        glue_order=GlueOrder.NORMAL, glue_set=0.0,
    ))
    interp = getattr(expander, "_interpreter", None)
    if interp is not None:
        interp._spacefactor = 1000


def _target_nodes(target) -> list:
    """Return the mutable node list from a paragraph/list builder target."""
    if hasattr(target, "_nodes"):
        return target._nodes
    raise EngineError("node list target is not mutable")


# ---------------------------------------------------------------------------
# Interword space glue helper
# ---------------------------------------------------------------------------

def _chardef_code(expander, name: str) -> int | None:
    r"""Return the code of a ``\chardef`` constant *name*, else ``None``."""
    interp = getattr(expander, "_interpreter", None)
    if interp is None:
        return None
    const = interp._register_set.resolve_constant(name)
    if const is None or const[0] != "chardef":
        return None
    return const[1]


def _continues_lig_run(tok, expander) -> bool:
    r"""Whether *tok* continues a lig/kern run (§1038).

    Only a letter, an other character, ``\char`` and a ``\chardef`` constant
    do; any other command ends the run, so ``o\relax o`` gets no font kern.
    """
    if isinstance(tok, CharToken):
        return tok.catcode in (Catcode.LETTER, Catcode.OTHER)
    return isinstance(tok, ControlSequenceToken) and (
        tok.name == "char" or _chardef_code(expander, tok.name) is not None
    )


def _add_eager_char(expander, font_manager: FontManager, builder, code: int) -> None:
    """Append a character to an eager list and update the space factor."""
    current_font = font_manager._current
    if current_font is None:
        raise EngineError("No font selected")
    _update_eager_spacefactor(expander, code)
    builder.add_char(code, current_font)


def _update_eager_spacefactor(expander, char_code: int) -> None:
    """Use the interpreter's current horizontal-list sfcode rules (§1034)."""
    interp = getattr(expander, "_interpreter", None)
    if interp is not None:
        interp._update_spacefactor(char_code)


def _interword_glue(font_manager: FontManager, expander=None, *, normal=False) -> Glue:
    """Use live interword glue rules, or fontdimens for standalone scanners.

    Falls back to zero glue if no font is selected or font has no params.
    """
    interp = getattr(expander, "_interpreter", None)
    if interp is not None:
        return interp._interword_glue(normal=normal) or Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
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


def _accent_meaning_token(expander: Expander, token: Token) -> Token:
    """Resolve active binding references while keeping frozen builtins frozen."""
    tok = expander.primitive_token(token)
    meaning = expander._let_meaning(token)
    if isinstance(meaning, (CharToken, ControlSequenceToken)):
        tok = expander.primitive_token(meaning)
    if isinstance(tok, CharToken) and tok.catcode == Catcode.ACTIVE:
        tok = ControlSequenceToken(active_char_key(tok.char))
    return tok


def _execute_accent_assignment(expander: Expander, token: Token) -> bool:
    """Execute one assignment, with no list-command dispatch."""
    tok = _accent_meaning_token(expander, token)
    if not isinstance(tok, ControlSequenceToken):
        return False
    name = tok.name
    interp = getattr(expander, "_interpreter", None)
    if ((expander._long_pending or expander._outer_pending)
            and name not in ("global", "long", "outer", "def", "gdef", "edef", "xdef")):
        raise EngineError("You can't use a prefix with this command")
    # Bindings outrank a primitive spelling, but never a frozen primitive.
    if interp is not None and not isinstance(tok, PrimitiveRefToken):
        if interp._register_set.resolve_alias(name) is not None:
            return _dispatch_register_assignment(expander, name)
        if interp._font_manager.is_font(name) or name in interp._font_manager._fonts:
            interp._font_manager.select_font(name)
            if interp._group_stack is not None:
                interp._group_stack.consume_global()
            expander.fire_after_assignment()
            return True
        if interp._register_set.resolve_constant(name) is not None:
            return False
    if name == "setbox":
        if expander._group_stack is not None:
            expander._group_stack.consume_global()
        expander._long_pending = expander._outer_pending = False
        raise EngineError("Improper \\setbox in \\accent")
    if name in ("global", "long", "outer"):
        if name == "global":
            expander._exec_global()
        else:
            setattr(expander, f"_{name}_pending", True)
        # A prefix must belong to this assignment, never to a later command.
        following = expander.get_x_token()
        while following is not None:
            resolved = expander.primitive_token(following)
            if not ((isinstance(resolved, CharToken) and resolved.catcode == Catcode.SPACE)
                    or (isinstance(resolved, ControlSequenceToken) and resolved.name == "relax"
                        and (isinstance(resolved, PrimitiveRefToken)
                             or _chardef_code(expander, resolved.name) is None))):
                break
            following = expander.get_x_token()
        try:
            if following is None or not _execute_accent_assignment(expander, following):
                raise EngineError("You can't use a prefix with this command")
        finally:
            expander._long_pending = expander._outer_pending = False
            if expander._group_stack is not None:
                expander._group_stack.consume_global()
        return True
    if name in ("def", "gdef", "edef", "xdef"):
        expander._exec_def(name)
        return True
    if name in ("let", "futurelet"):
        getattr(expander, f"_exec_{name}")()
        return True
    if name in ("patterns", "hyphenation"):
        expander._exec_hyph_data(name)
        return True
    owners = {
        "font": "_exec_font", "fontdimen": "_exec_fontdimen_cmd",
        "hyphenchar": "_exec_hyphenchar_cmd", "skewchar": "_exec_skewchar_cmd",
        "textfont": "_exec_textfont_cmd", "scriptfont": "_exec_scriptfont_cmd",
        "scriptscriptfont": "_exec_scriptscriptfont_cmd", "parshape": "_exec_parshape_cmd",
        "wd": "_exec_wd_cmd", "ht": "_exec_ht_cmd", "dp": "_exec_dp_cmd",
    }
    if interp is not None and name in owners:
        getattr(interp, owners[name])()
        return True
    return (_dispatch_internal_quantity_assignment(expander, name)
            or _dispatch_named_assignment(expander, name)
            or _dispatch_register_assignment(expander, name, primitive=isinstance(tok, PrimitiveRefToken))
            or _dispatch_code_array_assignment(expander, name))


def _scan_accent_base(expander: Expander) -> int | None:
    r"""Read the base character of ``\accent``, or ``None`` when there is none.

    §1123-1124: assignments execute, spaces and ``\relax`` are skipped; a letter, an other
    character, ``\char`` or a ``\chardef`` constant is the base.  Any other
    token is read again after the accent (back_input), so
    ``\accent19\hbox{o}`` sets the accent alone, then the box.
    """
    while True:
        original = expander.get_x_token()
        if original is None:
            return None
        tok = _accent_meaning_token(expander, original)
        if _execute_accent_assignment(expander, tok):
            continue
        if isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
            continue
        if (isinstance(tok, ControlSequenceToken) and tok.name == "relax"
                and (isinstance(tok, PrimitiveRefToken) or _chardef_code(expander, tok.name) is None)):
            continue
        break
    if isinstance(tok, CharToken) and tok.catcode in (Catcode.LETTER, Catcode.OTHER):
        return ord(tok.char)
    if isinstance(tok, ControlSequenceToken):
        if not isinstance(tok, PrimitiveRefToken):
            code = _chardef_code(expander, tok.name)
            if code is not None:
                return code
        if tok.name == "char":
            code = parse_integer(expander)
            _check_char_code(code, "\\char")
            return code
    expander.push_tokens([original])
    return None


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
    """Append TeX's direct, slant-aware accent/base list.

    Without a base character the accent glyph is appended on its own and the
    token that followed is read again (§1123, amendment).
    """
    accent_code = parse_integer(expander)
    _check_char_code(accent_code, "\\accent")
    font_name = _current_font_name(font_manager)
    metrics = font_manager.current_metrics
    if metrics is None:
        raise EngineError("No font selected")
    if not font_manager.check_character(font_name, accent_code):
        return
    accent_metrics = metrics.char_metrics(accent_code)
    a, x, s = accent_metrics.width, metrics.fontdimen(5), metrics.fontdimen(1) / 65536
    accent = CharNode(char=accent_code, font_name=font_name)
    if hasattr(par_list_or_hbuilder, "end_run"):
        par_list_or_hbuilder.end_run()
    base_code = _scan_accent_base(expander)
    base_font = _current_font_name(font_manager)
    base_metrics = font_manager.current_metrics
    nodes = [accent]
    if base_code is not None and font_manager.check_character(base_font, base_code):
        base = base_metrics.char_metrics(base_code)
        real_delta = (base.width - a) / 2 + base.height * (base_metrics.fontdimen(1) / 65536) - x * s
        delta = math.floor(real_delta + .5) if real_delta >= 0 else math.ceil(real_delta - .5)
        accent_node = accent
        if base.height != x:
            builder = HBoxBuilder(font_manager)
            builder._nodes.append(accent)
            # Engine box shifts are positive upwards; TeX stores the opposite.
            accent_node = dataclasses.replace(builder.build(), shift_amount=base.height - x)
        nodes = [KernNode(delta, explicit=False, accent_kern=True), accent_node,
                 KernNode(-a - delta, explicit=False, accent_kern=True),
                 CharNode(char=base_code, font_name=base_font)]
    if isinstance(par_list_or_hbuilder, list):
        par_list_or_hbuilder.extend(nodes)
    else:
        par_list_or_hbuilder._nodes.extend(nodes)
    if hasattr(par_list_or_hbuilder, "end_run"):
        par_list_or_hbuilder.end_run()
    # TeX §1123 resets the live list state after an accent, regardless of
    # the base character's sfcode. Eager and paragraph paths share it.
    interp = getattr(expander, "_interpreter", None)
    if interp is not None:
        interp._spacefactor = 1000


def _read_discretionary_branch(
    expander: Expander,
    font_manager: FontManager,
    group_stack: GroupStack,
    box_regs: BoxRegisterSet,
) -> tuple:
    """Read one balanced ``\\discretionary`` branch into hlist nodes."""
    expander._scan_left_brace("\\discretionary")
    builder = HBoxBuilder(font_manager, badness_sink=_badness_sink(expander))
    depth = 0
    with _list_tail_scope(expander, builder):
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
                elif tok.name == " ":
                    # \  is the font's normal interword glue (§1045).
                    builder.add_glue(_interword_glue(font_manager))
                elif tok.name == "kern":
                    # §1121 allows kerns in a discretionary list; \kern is explicit.
                    builder.add_kern(parse_dimen(expander), explicit=True)
                elif tok.name == "hbox":
                    tw, sp = _scan_box_keyword(expander)
                    builder.add_box(exec_hbox(
                        expander, font_manager, group_stack, box_regs,
                        target_width=tw, spread=sp,
                    ))
                else:
                    raise EngineError(f"Unexpected token in \\discretionary: \\{expander._diagnostic_cs_name(tok)}")
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
# Shared horizontal-mode token dispatch (exec_hbox + alignment cell scanner)
# ---------------------------------------------------------------------------


def _append_discretionary_hyphen(font_manager, target) -> None:
    """Append §1117's pre-break hyphen using the existing node."""
    font = _current_font_name(font_manager)
    code = font_manager.hyphenchar(font)
    pre = (CharNode(char=code, font_name=font),) if 0 <= code <= 255 else ()
    _target_nodes(target).append(DiscretionaryNode(pre=pre, post=(), nobreak=()))


@contextmanager
def _list_tail_scope(expander, builder):
    """Scope an eager list's tail and horizontal state."""
    interp = getattr(expander, "_interpreter", None)
    if interp is None:
        yield
        return
    # A fresh horizontal list starts at sf=1000; brace groups within the
    # list keep it. Nested lists restore their parent (§1083).
    horizontal = isinstance(builder, HBoxBuilder)
    saved_sf = interp._spacefactor
    saved_mode_depth = interp._mode_stack.depth
    if horizontal:
        from aspose_tex._engine.interpreter import ModeKind
        interp._mode_stack.push(ModeKind.RESTRICTED_HORIZONTAL)
        interp._spacefactor = 1000
    try:
        with interp._tail_scope(builder):
            yield
    finally:
        if horizontal:
            interp._spacefactor = saved_sf
            while interp._mode_stack.depth > saved_mode_depth:
                interp._mode_stack.pop()


def _dispatch_box_command(expander, name) -> None:
    """Delegate list-neutral commands to their existing interpreter handlers.

    Keep the allowlist at each scanner: arbitrary primitive dispatch may
    contribute to the interpreter's outer list rather than this eager list.
    """
    interp = getattr(expander, "_interpreter", None)
    if interp is None:
        raise EngineError(f"\\{name} inside a box needs the interpreter")
    interp._primitives[name]()

@dataclasses.dataclass(slots=True)
class _HBoxDispatchContext:
    """Bundle the collaborators a restricted-horizontal token loop needs.

    Shared by :func:`exec_hbox` and the alignment cell scanner
    (``alignment._scan_cell``) so both dispatch character/glue/box/control
    tokens identically. See §Components/2.

    Attributes:
        expander:     Active token stream.
        font_manager: Font lookups for characters and interword glue.
        group_stack:  Brace-group scope tracker.
        box_regs:     Box-register set for ``\\unhbox`` / ``\\lastbox`` etc.
        builder:      The :class:`HBoxBuilder` accumulating the hlist.
    """

    expander: Expander
    font_manager: FontManager
    group_stack: GroupStack
    box_regs: BoxRegisterSet
    builder: HBoxBuilder


def dispatch_hbox_token(tok, ctx: _HBoxDispatchContext) -> None:
    """Dispatch one restricted-horizontal-mode token into ``ctx.builder``.

    Handles exactly the character, space, and control-sequence arms of the
    ``\\hbox`` content loop.  Begin-group / end-group brace tracking is the
    caller's responsibility (it is loop control, not content).

    Args:
        tok: The next unexpandable token (never a begin/end-group char).
        ctx: The shared dispatch context.

    Raises:
        EngineError: on an unexpected token, or a character with no font.
    """
    expander = ctx.expander
    font_manager = ctx.font_manager
    group_stack = ctx.group_stack
    box_regs = ctx.box_regs
    builder = ctx.builder
    if not _continues_lig_run(tok, expander):
        builder.end_run()

    # --- Character tokens ---
    if isinstance(tok, CharToken):
        if tok.catcode in (Catcode.LETTER, Catcode.OTHER):
            _add_eager_char(expander, font_manager, builder, ord(tok.char))
            return
        if tok.catcode == Catcode.SPACE:
            builder.add_glue(_interword_glue(font_manager, expander))
            return
        if tok.catcode == Catcode.MATH_SHIFT:
            # §C: a nested $…$ inside an eager \hbox body (the plain.tex
            # \big-family \hbox{$\left(…\right.$}).  Delegate to the interpreter
            # so the inner formula opens a fresh math builder (the \hbox is the
            # mode barrier) and its nodes splice into this hbox.
            interp = getattr(expander, "_interpreter", None)
            if interp is None:
                raise EngineError("inline math in \\hbox needs the interpreter")
            for node in interp.run_inline_math_in_box(tok):
                builder._nodes.append(node)
            interp._spacefactor = 1000
            return
        raise EngineError(f"Unexpected token in hbox: {tok!r}")

    # --- Control sequences ---
    if isinstance(tok, ControlSequenceToken):
        name = tok.name
        if name == " ":
            # Control space uses spaceskip without sentence scaling (§1045).
            builder.add_glue(_interword_glue(font_manager, expander, normal=True))
            return
        if name in ("relax", "ignorespaces", "noboundary"):
            # No-ops in restricted horizontal mode (mirrors the vbox-text loop).
            # \ignorespaces additionally swallows following spaces. Plain TeX's
            # \multispan / \settabs cell machinery leaves these in cell bodies.
            if name == "ignorespaces":
                nxt = expander.peek()
                while isinstance(nxt, CharToken) and nxt.catcode == Catcode.SPACE:
                    expander._next_unexpandable()
                    nxt = expander.peek()
        elif name == "par":
            # TeX §1094 `hmode+par_end` calls `end_graf`, which acts only when
            # `mode=hmode`: in RESTRICTED horizontal mode \par does nothing
            # This is what makes a blank line legal in an \halign:
            # §785 `align_peek` does NOT skip \par — it starts a new row and
            # becomes the cell's first token, then vanishes here.  MiKTeX 24.4:
            # `\hbox{a\par b}` is `ab`; a blank line before `}` is
            # "Missing \cr inserted", so a row-boundary skip would be wrong.
            pass
        elif name in ("font", "fontdimen", "message", "errmessage", "write", "immediate", "show", "showthe"):
            _dispatch_box_command(expander, name)
        elif name in ("indent", "noindent"):
            if name == "indent":
                _append_indent_box(expander, builder)
        elif name == "kern":
            sp = parse_dimen(expander)
            builder.add_kern(sp, explicit=True)
        elif name == "/":
            # \/ italic correction (§1112) — the eager \hbox scanner
            # is a second horizontal-list path, so it needs the same rule the
            # interpreter applies to the paragraph list.
            builder.add_italic_correction()
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
        elif name == "hfilneg":
            builder.add_glue(Glue(0, -65536, GlueOrder.FIL, 0, GlueOrder.NORMAL))
        elif name == "hss":
            builder.add_glue(Glue(0, 65536, GlueOrder.FIL, 65536, GlueOrder.FIL))
        elif (
            _dispatch_internal_quantity_assignment(expander, name)
            or _dispatch_named_assignment(expander, name)
            or _dispatch_register_assignment(expander, name, primitive=isinstance(tok, PrimitiveRefToken))
            or _dispatch_code_array_assignment(expander, name)
        ):
            pass
        elif name == "penalty":
            n = parse_integer(expander)
            builder.add_penalty(n)
        elif name == "char":
            # Spacefactor belongs to the source byte, even when admission
            # omits it; inspecting the previous emitted node is wrong.
            code = parse_integer(expander)
            _check_char_code(code, "\\char")
            _add_eager_char(expander, font_manager, builder, code)
        elif name == "accent":
            exec_accent(expander, font_manager, builder)
        elif name == "discretionary":
            exec_discretionary(expander, font_manager, group_stack, box_regs, builder)
        elif name == "-":
            _append_discretionary_hyphen(font_manager, builder)
        elif name == "vrule":
            builder._nodes.append(_scan_vrule(expander))
        elif name == "endgroup" and (
            not group_stack._frames or group_stack._frames[-1].kind != GroupKind.SEMI_SIMPLE
        ):
            # A semisimple close cannot consume this scanner's box/brace frame.
            raise EngineError("\\endgroup cannot close an hbox or brace group")
        elif (font_manager.is_font(name) or name in font_manager._fonts):
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
        elif name in _DELEGATED_HBOX_CS and _delegate_hbox_primitive(
            expander, builder, tok,
        ):
            # box-register machinery (\setbox / \box / \copy /
            # \global / \wd / \ht / \dp) inside a literal-brace \hbox{…} is
            # delegated to the interpreter with the builder installed as the
            # live hlist, so \setbox0=\hbox{\setbox1=\hbox{x}\box1} works.
            pass
        elif (code := _chardef_code(expander, name)) is not None:
            # A \chardef constant is a character (§1038 char_given): plain's
            # \% \& \# \$ inside \hbox{…}.
            _add_eager_char(expander, font_manager, builder, code)
        else:
            raise EngineError(f"Unexpected token in hbox: \\{name}")
        if name in ("hbox", "vbox", "vtop", "raise", "lower"):
            interp = getattr(expander, "_interpreter", None)
            if interp is not None:
                interp._spacefactor = 1000  # §1076 box_end.
        return

    raise EngineError(f"Unexpected token in hbox: {tok!r}")


# Box-register / dimension primitives the shared horizontal dispatch delegates
# to the interpreter (mirrors alignment._DELEGATED_CELL_CS).  Handled only when
# an interpreter is reachable through the expander.
_DELEGATED_HBOX_CS = frozenset({
    "setbox", "box", "copy", "global", "wd", "ht", "dp", "aftergroup", "vadjust",
    "begingroup", "endgroup", "valign", "insert", "mark", "setlanguage",
})


def _delegate_hbox_primitive(expander: Expander, builder, tok) -> bool:
    """Run one interpreter box primitive with *builder* as the live hlist.

    Returns ``True`` if the primitive was delegated; ``False`` when no
    interpreter is reachable (the caller then raises the usual error).  The
    installed :class:`ParagraphList` shares *builder*'s live node list, so
    contributions and ``\\lastbox`` extraction act directly on that list.
    Deferred box frames retain the context until their closing group restores
    the enclosing list and mode. See.
    """
    interp = getattr(expander, "_interpreter", None)
    if interp is None:
        return False
    from aspose_tex._engine.interpreter import ModeKind
    from aspose_tex._engine.par_primitives import ParagraphList

    saved_par_list = interp._par_list
    saved_mode_depth = interp._mode_stack.depth
    cell_list = ParagraphList()
    # a delegated box value (notably \lastbox) reads and mutates
    # the list already built by the eager scanner, not an empty scratch list.
    cell_list._nodes = builder._nodes
    interp._par_list = cell_list
    interp._mode_stack.push(ModeKind.RESTRICTED_HORIZONTAL)
    base_box_depth = len(interp._box_construction_stack)
    opened_frame = False
    try:
        interp._dispatch_cs(tok)
        if len(interp._box_construction_stack) > base_box_depth:
            opened_frame = True
            frame = interp._box_construction_stack[base_box_depth]
            frame.restore_mode_depth = saved_mode_depth
            frame.saved_par_list = saved_par_list
    finally:
        if not opened_frame:
            interp._mode_stack.pop()
            interp._par_list = saved_par_list
    return True


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
    as the first token.  The caller has already consumed ``\\hbox`` and
    any optional ``to <dimen>`` / ``spread <dimen>``.

    Dispatches tokens in horizontal mode.  See for the full
    dispatch table.

    Raises:
        EngineError: on unexpected token or no font selected for characters.
    """
    # Consume opening {
    expander._scan_left_brace("\\hbox")
    from aspose_tex._engine.group import GroupKind
    group_stack.open_group(GroupKind.BRACE)

    builder = HBoxBuilder(font_manager, badness_sink=_badness_sink(expander))
    ctx = _HBoxDispatchContext(expander, font_manager, group_stack, box_regs, builder)
    inner_depth = 0  # depth of extra nested brace groups inside the hbox
    interp = getattr(expander, "_interpreter", None)
    base_box_depth = len(interp._box_construction_stack) if interp is not None else 0

    with _list_tail_scope(expander, builder):
        # §1083: the hook belongs to the newly opened group/list, before content.
        if interp is not None:
            interp._push_toks_if_any(260)  # \everyhbox
        while True:
            tok = expander._next_unexpandable()
            if tok is None:
                raise EngineError("Unexpected end of input inside \\hbox")

            # A protected active token still executes its unexpandable meaning
            # (§358). Resolve before brace tracking: its meaning can be a brace.
            if isinstance(tok, CharToken) and tok.catcode == Catcode.ACTIVE:
                from aspose_tex._engine.expansion import _EXPANDABLE_PRIMITIVES, _UNDEFINED
                from aspose_tex._engine.macro import MacroDefinition

                meaning = expander._ifx_meaning(tok)
                if expander._last_noexpand and (
                    meaning == _UNDEFINED or isinstance(meaning, MacroDefinition)
                    or (isinstance(meaning, tuple) and meaning[0] == "prim"
                        and meaning[1] in _EXPANDABLE_PRIMITIVES)
                ):
                    builder.end_run()  # The effective relax is a ligature barrier.
                    continue
                tok = _accent_meaning_token(expander, tok)

            # a delegated \setbox may open a deferred box. Its own
            # closing brace belongs to the interpreter, not this eager scanner.
            if interp is not None and len(interp._box_construction_stack) > base_box_depth:
                kind = group_stack._frames[-1].kind
                if isinstance(tok, CharToken) and tok.catcode == Catcode.END_GROUP and kind != GroupKind.BRACE:
                    raise EngineError("} cannot close a \\begingroup inside a deferred hbox")
                if isinstance(tok, ControlSequenceToken) and tok.name == "endgroup" and kind != GroupKind.SEMI_SIMPLE:
                    raise EngineError("\\endgroup cannot close a deferred box or brace group")
                interp._dispatch(tok)
                continue

            if not _continues_lig_run(tok, expander):
                builder.end_run()

            # --- End group ---
            if isinstance(tok, CharToken) and tok.catcode == Catcode.END_GROUP:
                if group_stack._frames[-1].kind != GroupKind.BRACE:
                    raise EngineError("} cannot close a \\begingroup inside an hbox")
                if inner_depth == 0:
                    tokens, _kind = group_stack.close_group()
                    expander.push_tokens(tokens)
                    break
                inner_depth -= 1
                tokens, _kind = group_stack.close_group()
                expander.push_tokens(tokens)
                continue

            # --- Begin group (nested braces in content) ---
            if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
                inner_depth += 1
                group_stack.open_group(GroupKind.BRACE)
                continue

            # cross-scanner \endv terminator propagation.  The display
            # family (\displaylines/\eqalignno/\leqalignno) wraps its math cell in an
            # \hbox (`\hbox to\displaywidth{$…##…$}`), so when the math pump injects
            # the v-template and returns the row terminator, that terminator surfaces
            # in THIS exec_hbox loop, not the cell scanner.  If we are the live frame
            # of an open math alignment cell and read a top-level alignment terminator
            # (&/\cr/\crcr/\span by meaning), finish the hbox and re-push the
            # terminator so it propagates out to the enclosing cell scanner.  Without
            # this it would reach dispatch_hbox_token and raise "Unexpected token".
            interp = getattr(expander, "_interpreter", None)
            if (interp is not None and interp._alignment_cell_depth > 0
                    and interp._alignment_cell_assembled_close[-1] is not None):
                from aspose_tex._engine.alignment import _terminator_kind
                if (_terminator_kind(tok, interp) is not None
                        and interp._inject_cell_vtemplate(tok)):
                    continue
            if inner_depth == 0:
                interp = getattr(expander, "_interpreter", None)
                if interp is not None and interp._alignment_cell_depth > 0:
                    from aspose_tex._engine.alignment import _terminator_kind
                    if _terminator_kind(tok, interp) is not None:
                        group_stack.close_group()
                        expander.push_tokens([tok])
                        break

            # --- Character / glue / box / control tokens (shared dispatch) ---
            dispatch_hbox_token(tok, ctx)

    box = builder.build(target_width=target_width, spread=spread)

    # Warn if overfull or underfull (error handling)
    _warn_badness(box, builder.last_badness, expander=expander, font_manager=font_manager)
    append_overfull_rule(
        box, builder.last_badness, font_manager,
        hfuzz=_read_named_dimen(expander, "hfuzz") or 0,
        overfull_rule=_read_named_dimen(expander, "overfullrule") or 0,
    )
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

# TeXbook §253 "ignore" marker. Aliases box_builder.IGNORE_PREV_DEPTH so the
# vbox and alignment interline paths share one sentinel value.
_PREVDEPTH_SENTINEL = IGNORE_PREV_DEPTH


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
    Dispatches tokens in vertical mode.  See for the dispatch table.

    Interline glue between consecutive contributed boxes is inserted live
    using ``\\baselineskip`` / ``\\lineskip`` / ``\\lineskiplimit`` from the
    named-parameter registry (TeXbook §253 / TeX:The Program §679).
    ``\\prevdepth`` is treated as vbox-local: saved on entry, reset to the
    -1000 pt sentinel, restored on exit.  This closes cascade #1:
    plain-TeX ``\\makefootline`` writes ``\\baselineskip=24pt`` which is now
    honoured by the outer ``\\vbox{\\makeheadline\\pagebody\\makefootline}``
    of ``\\plainoutput``.
    """
    interp = getattr(expander, "_interpreter", None)
    if interp is not None:
        return interp._execute_vbox(target_height=target_height, spread=spread)
    expander._scan_left_brace("\\vbox")
    from aspose_tex._engine.group import GroupKind
    group_stack.open_group(GroupKind.BRACE)

    vbuilder = VBoxBuilder(font_manager, badness_sink=_badness_sink(expander))
    inner_depth = 0

    interp = getattr(expander, "_interpreter", None)
    page_builder = getattr(interp, "_page_builder", None) if interp is not None else None
    saved_prev_depth = interp._prev_depth if interp is not None else None
    saved_pb_prev_depth = page_builder._prev_depth if page_builder is not None else None
    if interp is not None:
        interp._prev_depth = _PREVDEPTH_SENTINEL

    def _emit_interline_glue(next_box_height: int) -> None:
        """Insert interline glue before a non-first box per TeX §679.

        The §679 computation lives in ``box_builder.compute_interline_glue``
        (shared with the alignment row-stacker); this closure owns the
        live named-param reads + the ``vbuilder.add_glue`` side effect.
        """
        if interp is None:
            return
        prev = interp._prev_depth
        if prev <= _PREVDEPTH_SENTINEL:
            return
        baselineskip = _read_named_skip(expander, "baselineskip")
        if baselineskip is None:
            return
        lineskiplimit = _read_named_dimen(expander, "lineskiplimit") or 0
        # \lineskip is only consulted on the too-close branch; read it lazily so
        # a missing \lineskip never suppresses the baselineskip path (preserves
        # the pre- exec_vbox behaviour — 5-MD5 byte-identical).
        ideal = baselineskip.width - prev - next_box_height
        if ideal < lineskiplimit:
            lineskip = _read_named_skip(expander, "lineskip")
            if lineskip is None:
                return
        else:
            lineskip = baselineskip  # unused on this branch; satisfies the call
        glue = compute_interline_glue(
            prev_depth=prev,
            next_height=next_box_height,
            baselineskip=baselineskip,
            lineskip=lineskip,
            lineskiplimit=lineskiplimit,
        )
        if glue is not None:
            vbuilder.add_glue(glue)

    def _track_box(box: HlistNode | VlistNode) -> None:
        if interp is not None:
            interp._prev_depth = box.depth

    def _track_rule(rule: RuleNode) -> None:
        """Contribute a rule and reset the interline-glue chain (TeX §679).

        Per TeX:The Program §679, a rule node in vertical mode is a non-box
        discardable: no interline glue is emitted before it, and ``prevdepth``
        is reset to the entry sentinel so any subsequent box contribution
        likewise does not receive interline glue.  This allows
        ``\\vbox{a\\hrule b}`` to compose two separate baselines around the
        rule.  See.
        """
        vbuilder._nodes.append(rule)
        if interp is not None:
            interp._prev_depth = _PREVDEPTH_SENTINEL

    def _track_alignment_rows(spliced: list) -> None:
        """Track ordinary alignment rows; raw unpackaging preserves depth.

        Row boxes set depth and rules reset it, unlike raw splices.
        Transparent trailing nodes do not replace the last depth owner.
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

    with _list_tail_scope(expander, vbuilder):
        try:
            while True:
                tok = expander._next_unexpandable()
                if tok is None:
                    raise EngineError("Unexpected end of input inside \\vbox")

                if isinstance(tok, CharToken) and tok.catcode == Catcode.END_GROUP:
                    if inner_depth == 0:
                        tokens, _kind = group_stack.close_group()
                        expander.push_tokens(tokens)
                        break
                    inner_depth -= 1
                    tokens, _kind = group_stack.close_group()
                    expander.push_tokens(tokens)
                    continue

                if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
                    inner_depth += 1
                    group_stack.open_group(GroupKind.BRACE)
                    continue

                if isinstance(tok, CharToken):
                    if tok.catcode in (
                        Catcode.LETTER, Catcode.OTHER, Catcode.SPACE,
                        Catcode.MATH_SHIFT,
                    ):
                        # A vbox line may begin with a $…$ formula (e.g. a \footnote
                        # body whose text is wholly math).  Real TeX
                        # starts a paragraph here; the text-line scanner handles the
                        # MATH_SHIFT token via run_inline_math_in_box.
                        _add_hbox(_scan_vbox_text_line(
                            tok, expander, font_manager, group_stack, box_regs,
                        ))
                        continue
                    raise EngineError(f"Unexpected character token in vbox: {tok!r}")

                if isinstance(tok, ControlSequenceToken):
                    name = tok.name
                    if name == "aftergroup" and interp is not None:
                        interp._exec_aftergroup()
                        continue
                    if name == "relax":
                        continue
                    if name in (" ", "noboundary"):
                        # §1090: \  and \noboundary in vertical mode start a
                        # paragraph, like a character; the text line appends the
                        # glue of \ and ignores \noboundary.
                        _add_hbox(_scan_vbox_text_line(
                            tok, expander, font_manager, group_stack, box_regs,
                        ))
                        continue
                    if name in ("halign", "valign"):
                        # an alignment in internal vertical mode (e.g.
                        # \ialign\bgroup…\crcr inside \settabs's \vbox). \halign
                        # contributes a vlist of row hboxes spliced verbatim; \valign
                        # an hlist of column vboxes added as one box.
                        interp = getattr(expander, "_interpreter", None)
                        from aspose_tex._engine.alignment import _run_nested_alignment
                        result = _run_nested_alignment(interp, vertical=name == "valign")
                        if isinstance(result, VlistNode):
                            for node in result.list:
                                vbuilder._nodes.append(node)
                            _track_alignment_rows(result.list)
                        else:
                            _add_hbox(result)
                    elif name in (
                        "font", "fontdimen", "message", "errmessage", "write", "immediate", "show", "showthe",
                    ):
                        _dispatch_box_command(expander, name)
                    elif (font_manager.is_font(name) or name in font_manager._fonts):
                        font_manager.select_font(name)
                    elif name == "hbox":
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
                    elif name in ("leaders", "cleaders", "xleaders"):
                        from aspose_tex._engine.leaders import parse_leaders
                        kind = {"leaders": LeadersKind.NORMAL, "cleaders": LeadersKind.C,
                                "xleaders": LeadersKind.X}[name]
                        vbuilder._nodes.append(parse_leaders(
                            expander, font_manager, group_stack, box_regs, kind,
                            vertical=True, interp=interp,
                        ))
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
                        # vertical mode (vbox scanner) start a paragraph.  Real TeX
                        # auto-switches to horizontal mode here (TeXbook ch. 13);
                        # plain.tex's `\textindent` (`\indent\llap{#1\enspace}…`)
                        # relies on this to anchor the indent kern + remaining
                        # tokens (`\llap`, `\footstrut`, body text) as ONE hlist
                        # line.  Without this, `\vfootnote` produced three vlist
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
                        or _dispatch_register_assignment(expander, name, primitive=isinstance(tok, PrimitiveRefToken))
                        or _dispatch_code_array_assignment(expander, name)
                    ):
                        pass
                    elif name == "unvbox":
                        spliced = exec_unbox(expander, box_regs, copy=False, vertical=True)
                        for node in spliced:
                            vbuilder._nodes.append(node)
                    elif name == "unvcopy":
                        spliced = exec_unbox(expander, box_regs, copy=True, vertical=True)
                        for node in spliced:
                            vbuilder._nodes.append(node)
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
                        if (isinstance(next_tok, CharToken) and next_tok.char == "="
                                and next_tok.catcode == Catcode.OTHER):
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
                        shifted = apply_shift(inner_box, -amount, vertical=False)
                        if isinstance(shifted, HlistNode):
                            _add_hbox(shifted)
                        else:
                            _add_vbox(shifted)
                    elif name == "moveright":
                        amount = parse_dimen(expander)
                        inner_box = _scan_next_box(expander, font_manager, group_stack, box_regs)
                        shifted = apply_shift(inner_box, amount, vertical=False)
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

    box = vbuilder.build(target_height=target_height, spread=spread)
    _warn_badness(box, vbuilder.last_badness, "vbox", expander=expander, font_manager=font_manager)
    return box


# ---------------------------------------------------------------------------
# Badness warnings (internal)
# ---------------------------------------------------------------------------

def _warn_badness(
    box: HlistNode | VlistNode, badness: int, kind: str = "hbox", *,
    expander: Expander | None = None, font_manager: FontManager | None = None,
    context: str = "",
) -> None:
    """Emit an overfull/underfull warning from the box's TeX ``last_badness``.

    *badness* is what ``set_glue_hbox``/``set_glue_vbox`` returned: TeX
    §660/§664 (and §674/§677 for vboxes) report a box overfull only when its
    finite shrink falls short (``OVERFULL_BAD``), and underfull or tight
    when the badness exceeds the threshold.
    """
    axis = "h" if kind == "hbox" else "v"
    threshold = 100  # legacy standalone primitive callers have no named registry
    fuzz = 0
    if expander is not None:
        named = getattr(expander, "_named_params", None)
        regs = getattr(expander, "_register_set", None)
        entry = named.lookup(axis + "badness") if named is not None else None
        if entry is not None and regs is not None:
            threshold = regs.get_count(entry.slot, _internal=True)
        live_fuzz = _read_named_dimen(expander, axis + "fuzz")
        if live_fuzz is not None:
            fuzz = live_fuzz
    excess = 0
    if badness > INF_BAD and font_manager is not None:
        natural = (_measure_hlist(box.list, font_manager)[0] if axis == "h"
                   else _measure_vlist(box.list, font_manager)[1])
        target = box.width if axis == "h" else box.height
        excess = natural - target - _collect_shrink(box.list)[GlueOrder.NORMAL]
    message = _box_badness_message(box, badness, kind, threshold, fuzz, excess)
    if message is not None:
        if badness > INF_BAD and font_manager is not None and axis == "h":
            from aspose_tex._engine.tex_arith import print_scaled

            detail = "too wide" if axis == "h" else "too high"
            message = f"Overfull \\{kind} ({print_scaled(excess)}pt {detail})"
        category = OverfullBoxWarning if badness > INF_BAD else UnderfullBoxWarning
        warnings.warn(message + context, category, stacklevel=3)


def _badness_sink(expander: Expander):
    interp = getattr(expander, "_interpreter", None)
    if interp is None:
        return None
    return getattr(interp, "_set_badness", None)
