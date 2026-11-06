"""Alignment subsystem — execution phase.

Implements TeX's two-pass ``\\halign`` algorithm (TeX:The Program §768-§812):

- **Pass 0** (:func:`_parse_preamble`) — scan the preamble into per-column
  ``(u, v)`` template token lists plus an inter-column ``\\tabskip`` glue array.
- **Pass 1** (:func:`_scan_cell` per cell) — render each cell exactly once into
  a natural-width :class:`HlistNode`, recording a :class:`_CellRecord`; fire
  ``\\everycr`` at each row break.
- **Reduction** (:func:`_measure_columns`) — ``column_width[j] = max`` natural
  width over rows, with spanning-cell reconciliation.
- **Pass 2** (:func:`_emit_rows`) — repack each cell to its column width, join
  rows with ``\\tabskip`` glue, splice ``\\noalign`` material, stack into the
  result vlist.

This module's body replaced the load-without-execute stubs; the
import path stays at ``aspose_tex._engine.alignment`` (no rename) per
Q3.  ``\\valign`` ( cascade b) is the vertical mirror: cells are
wrapped as vboxes, columns measured by max natural height, and the result is an
hlist of column vboxes (the transpose of ``\\halign``'s vlist of row hboxes).

See the project documentation for design rationale.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING

from aspose_tex._engine.box_builder import (
    IGNORE_PREV_DEPTH,
    HBoxBuilder,
    VBoxBuilder,
    compute_interline_glue,
    set_glue_hbox,
    set_glue_vbox,
)
from aspose_tex._engine.box_primitives import (
    _HBoxDispatchContext,
    _list_tail_scope,
    _read_named_dimen,
    _read_named_skip,
    _scan_box_keyword,
    dispatch_hbox_token,
)
from aspose_tex._engine.group import GroupKind
from aspose_tex._engine.macro import PrimitiveMeaning
from aspose_tex._engine.nodes import (
    RUNNING_DIMEN,
    GlueNode,
    HlistNode,
    KernNode,
    RuleNode,
    VlistNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
    from aspose_tex._engine.interpreter import TeXInterpreter

# Named-parameter slots seeded by §A.5.  consumes
# them; it does NOT create new entries.
_TABSKIP_SLOT = 267
_EVERYCR_SLOT = 263

_ZERO_GLUE = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)

# TeX §138 null_flag: the width of a column no cell has measured yet (§801).
_NULL_FLAG = -(2**30)

# Cell terminators returned by _scan_cell.
_TERM_TAB = "&"
_TERM_SPAN = "span"
_TERM_CR = "cr"
_TERM_CRCR = "crcr"

# Sentinel control-sequence pushed after an ``\everycr`` token list so the
# recursion guard ( Q5) can detect when that list is fully consumed and
# re-enable firing.  The name starts with NUL so it can never collide with a
# user control sequence (matching the SENTINEL_FINISH_OUTPUT_CS idiom).
_EVERYCR_SENTINEL = "\x00endeverycr"


class AlignmentError(EngineError):
    """Raised for malformed preambles or illegal alignment-token positions."""


# ---------------------------------------------------------------------------
# Per-invocation state (call-stack-local — supports recursive \halign, Q6)
# ---------------------------------------------------------------------------

@dataclasses.dataclass(slots=True)
class _ColumnTemplate:
    """One preamble column template ``<u>#<v>`` as raw token lists."""

    u_tokens: list
    v_tokens: list


@dataclasses.dataclass(slots=True)
class _CellRecord:
    """One rendered cell plus its column placement ( Q8).

    ``box`` is an hbox for ``\\halign`` and a vbox for ``\\valign``.
    """

    box: HlistNode | VlistNode
    col_index: int
    span_count: int
    omit: bool
    adjustments: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass(slots=True)
class _NoalignRecord:
    """Cumulative raw material from adjacent noalign groups.

    Body execution owns interline glue and final logical depth. Pass 2 replays
    both, including when tail removal has left orphan interline glue.
    """

    nodes: list               # vertical (\halign) / horizontal (\valign) material
    prev_depth: int | None    # final executed-list depth; None only for valign


@dataclasses.dataclass(slots=True)
class _AlignmentState:
    """Mutable state for one ``\\halign`` / ``\\valign`` invocation."""

    templates: list           # list[_ColumnTemplate]
    tabskip: list             # list[Glue], len == len(templates) + 1
    rows: list                # list[list[_CellRecord]] | _NoalignRecord
    column_width: list        # list[int] (sp)
    vertical: bool
    # Index into ``templates`` where a repeating block begins (``&&`` / leading
    # ``&`` preamble, TeXbook p.241); -1 = no repeat. Used by ``\settabs`` /
    # ``\ialign`` whose preamble is one infinitely-repeating column template.
    repeat_from: int = -1
    firing_everycr: bool = False  # Q5 recursion guard
    # Interline-glue parameters captured live while the alignment
    # group is still open — \openup\jot's in-group \advance is rolled back by
    # the group close before pass 2 (_assemble_result) reads them, so they MUST
    # be snapshotted at row-collection time, not at emit time.
    baselineskip: Glue = _ZERO_GLUE
    lineskip: Glue = _ZERO_GLUE
    lineskiplimit: int = 0
    # Component 2: the optional `to <dimen>` / `spread <dimen>` width
    # spec.  Both None ⇒ rows keep their natural width, which is what every
    # spec-less `\halign` in the corpus does — so the default is byte-identical
    # to the pre- behaviour.  `\halign to\displaywidth` (the plain.tex
    # \displ@y families) is the case that made this load-bearing.
    target_width: int | None = None
    spread_width: int | None = None


# ---------------------------------------------------------------------------
# Stub handlers for out-of-context dispatch (cr/crcr/noalign/span/omit, &)
# ---------------------------------------------------------------------------

def _exec_cr() -> None:
    """``\\cr`` dispatched outside an alignment is a user error."""
    raise EngineError("\\cr outside \\halign/\\valign")


def _exec_crcr() -> None:
    """``\\crcr`` dispatched outside an alignment is a user error."""
    raise EngineError("\\crcr outside \\halign/\\valign")


def _exec_noalign() -> None:
    """``\\noalign`` dispatched outside an alignment is a user error."""
    raise EngineError("\\noalign outside \\halign/\\valign")


def _exec_span() -> None:
    """``\\span`` dispatched outside an alignment is a user error."""
    raise EngineError("\\span outside \\halign/\\valign")


def _exec_omit() -> None:
    """``\\omit`` dispatched outside an alignment is a user error."""
    raise EngineError("\\omit outside \\halign/\\valign")


def build_alignment_handlers(
    interpreter: TeXInterpreter,
) -> dict[str, Callable[[], None]]:
    """Return alignment primitive handlers keyed by control-sequence name.

    ``\\halign`` / ``\\valign`` execute their algorithm; ``\\cr`` / ``\\crcr``
    / ``\\noalign`` / ``\\span`` / ``\\omit`` raise ``EngineError`` when
    dispatched *outside* an active alignment (inside one they are intercepted
    by :func:`_scan_cell` / :func:`_emit_rows` before reaching ``_dispatch``).

    Args:
        interpreter: The owning interpreter; handlers reach its expander,
            mode stack, font manager, register set, box registers, and the
            ``_add_box_to_current_list`` sink through this handle.

    Returns:
        Mapping suitable for ``primitives.update(...)`` in
        ``TeXInterpreter._build_primitives``.
    """
    return {
        "halign": lambda: exec_halign(interpreter),
        "valign": lambda: exec_valign(interpreter),
        "cr": _exec_cr,
        "crcr": _exec_crcr,
        "noalign": _exec_noalign,
        "span": _exec_span,
        "omit": _exec_omit,
    }


# ---------------------------------------------------------------------------
# Live named-parameter reads
# ---------------------------------------------------------------------------

def _read_tabskip(interpreter: TeXInterpreter) -> Glue:
    """Return the live ``\\tabskip`` glue (SKIP 267)."""
    try:
        return interpreter._register_set.get_skip(_TABSKIP_SLOT, _internal=True)
    except Exception:  # pragma: no cover - defensive
        return _ZERO_GLUE


def _read_everycr(interpreter: TeXInterpreter) -> list:
    """Return the live ``\\everycr`` token list (TOKS 263)."""
    try:
        return list(interpreter._register_set.get_toks(_EVERYCR_SLOT, _internal=True))
    except Exception:  # pragma: no cover - defensive
        return []


# ---------------------------------------------------------------------------
# Pass 0 — preamble parser
# ---------------------------------------------------------------------------

def _parse_preamble(interpreter: TeXInterpreter, state: _AlignmentState) -> None:
    """Scan ``<u>#<v>&<u>#<v>&...\\cr`` into ``state.templates`` / ``state.tabskip``.

    Reads raw (unexpanded) tokens — templates are stored verbatim, matching
    ``\\def`` body storage.  A bare ``\\tabskip=<glue>`` appearing between
    ``&`` separators updates the tabskip slot for that gap (TeX:The Program
    §777-§782).  A ``&`` whose preceding segment is empty marks the start of a
    repeating template block (``&&`` / leading-``&``, TeXbook p.241), as used
    by ``\\settabs`` / ``\\ialign``.

    Raises:
        AlignmentError: on a non-empty ``&``-segment containing no ``#``
            placeholder, or end of input before the preamble-closing ``\\cr``.
    """
    expander = interpreter._expander

    # tabskip[0] = glue before the first column, captured at preamble entry.
    state.tabskip.append(_read_tabskip(interpreter))

    u_tokens: list = []
    v_tokens: list = []
    seen_hash = False

    def _segment_empty() -> bool:
        return not seen_hash and not u_tokens and not v_tokens

    def _flush_segment() -> None:
        nonlocal u_tokens, v_tokens, seen_hash
        if not seen_hash:
            raise AlignmentError("\\halign: missing # in alignment preamble")
        state.templates.append(_ColumnTemplate(u_tokens, v_tokens))
        state.tabskip.append(_read_tabskip(interpreter))
        u_tokens = []
        v_tokens = []
        seen_hash = False

    while True:
        tok = expander._next_raw()
        if tok is None:
            raise AlignmentError("\\halign: preamble ended without \\cr")

        # §783: a template's u-part never starts with a space, so a line break
        # after `&` adds nothing to the column. v-part spaces are kept (§784).
        if not seen_hash and not u_tokens and expander._is_space_token(tok):
            continue

        if isinstance(tok, CharToken):
            if tok.catcode == Catcode.ALIGNMENT:
                # A `&` with an empty preceding segment begins the repeating
                # block (the `&&` notation); it is not a column separator.
                if _segment_empty():
                    state.repeat_from = len(state.templates)
                    continue
                _flush_segment()
                continue
            if tok.catcode == Catcode.PARAMETER:
                if seen_hash:
                    raise AlignmentError(
                        "\\halign: more than one # in a preamble column"
                    )
                seen_hash = True
                continue
            (v_tokens if seen_hash else u_tokens).append(tok)
            continue

        if isinstance(tok, ControlSequenceToken):
            # Classify by meaning so a \let-alias of \cr/\crcr (e.g. \endline)
            # closes the preamble too (§Component 1).  \span is not a
            # preamble terminator, so only cr/crcr count here.
            resolved = _resolve_terminator_name(tok.name, interpreter)
            if resolved in (_TERM_CR, _TERM_CRCR):
                _flush_segment()
                return
            if tok.name == "tabskip":
                # Live assignment between columns updates the next gap.
                _assign_tabskip(interpreter)
                continue
            (v_tokens if seen_hash else u_tokens).append(tok)
            continue


def _assign_tabskip(interpreter: TeXInterpreter) -> None:
    """Consume ``=<glue>`` after a preamble ``\\tabskip`` and store it."""
    from aspose_tex._engine.dimparser import parse_glue

    expander = interpreter._expander
    tok = expander.peek()
    if isinstance(tok, CharToken) and tok.char == "=" and tok.catcode == Catcode.OTHER:
        expander._next_raw()
    glue = parse_glue(expander)
    entry = interpreter._named_params.lookup("tabskip")
    if entry is not None:
        interpreter._register_set.set_skip(entry.slot, glue, _internal=True)


# ---------------------------------------------------------------------------
# Pass 1 — cell scanner
# ---------------------------------------------------------------------------

def _scan_cell(
    interpreter: TeXInterpreter,
    state: _AlignmentState,
    col_index: int,
    builder: HBoxBuilder,
    ctx: _HBoxDispatchContext,
) -> tuple[str, bool]:
    """Scan one ``\\span`` segment into the logical cell's list.

    Consumes a leading ``\\omit`` (suppresses the column template).  Pushes the
    column ``u`` template, scans the segment body into *builder* (the list owned
    by :func:`_scan_horizontal_cell` for the whole ``\\span`` chain,)
    until a top-level ``&`` / ``\\span`` / ``\\cr`` / ``\\crcr`` terminator,
    and pushes the ``v`` template.  The caller packages the list.

    Args:
        interpreter: Owning interpreter.
        state:       The alignment's collection state.
        col_index:   Column of this segment (selects its template).
        builder:     The logical cell's shared horizontal list.
        ctx:         Dispatch context bound to *builder*.

    Returns:
        ``(terminator, omit)`` where ``terminator`` is one of
        ``_TERM_TAB`` / ``_TERM_SPAN`` / ``_TERM_CR`` / ``_TERM_CRCR``.

    Raises:
        AlignmentError: on end of input before a terminator.
    """
    expander = interpreter._expander
    font_manager = interpreter._font_manager
    group_stack = interpreter._group_stack
    box_regs = interpreter._box_regs

    # The TeX §791 cell group is opened by :func:`_collect_one_row` around the
    # whole `\span` chain ( Component 1), not here — see the comment at
    # that call site for why the boundary is the logical cell, not the segment.
    omit, template = _consume_omit_and_template(interpreter, state, col_index)

    # C5 /: a column whose u-template opens an argument brace
    # before its `$` (\leqalignno's `\rlap{$\@lign##$}`) is a macro-arg straddle
    # — the macro would grab its `{…}` argument past the cell terminator and
    # double-consume the cell's `$…$`. Text hboxes need the same balanced body:
    # ending their eager scan at the terminator would leave V's closing brace
    # with the cell instead of its owning box. Assemble `u + raw body + v`.
    if (
        not omit
        and template is not None
        and _u_template_pre_math_open_braces(template) > 0
    ):
        return _scan_math_macro_arg_cell(
            interpreter, state, col_index, template, omit, builder, ctx,
        )

    if not omit and template is not None and template.u_tokens:
        expander.push_tokens(list(template.u_tokens))

    inner_depth = 0
    pushed_v = False
    #: open-group box frames opened by THIS cell (e.g. \settabs's
    # \t@bbox \setbox\z@\hbox\bgroup) are detected by a rise above this baseline.
    base_box_depth = len(interpreter._box_construction_stack)

    # C2 /: mark that we are scanning an alignment cell so a math
    # $…$ cell ends at a top-level &/\cr/\span (the \endv boundary), and stash
    # this column's v-template for the math pump's \endv injection ( Q2).
    # The three pushes are popped together in the finally so an exception cannot
    # strand them.
    v_tokens = None if omit or template is None else (template.v_tokens or None)
    # Q6: a math u-template may open a brace that only the v-template
    # closes (\eqalign's `$\displaystyle{##}$` → U=`…$\displaystyle{`).  The
    # user's row `&`/\cr then arrives while the math pump's brace_depth equals
    # that straddling open count, NOT 0.  Stash the count of u-template braces
    # left open AFTER its opening `$` so the pump fires the \endv injection at
    # the right depth (a genuine `{a&b}` body shield is deeper still → untouched).
    u_open = 0 if omit or template is None else _u_template_open_braces(template)
    interpreter._alignment_cell_depth += 1
    interpreter._alignment_cell_vtemplate.append(v_tokens)
    interpreter._alignment_cell_pushed_v.append(False)
    interpreter._alignment_cell_ubrace.append(u_open)
    interpreter._alignment_cell_assembled_close.append(None)
    try:
        term = _scan_cell_body(
            interpreter, state, col_index, expander, font_manager,
            group_stack, box_regs, omit, template, builder, ctx,
            inner_depth, pushed_v, base_box_depth,
        )
        return term, omit
    finally:
        interpreter._alignment_cell_depth -= 1
        interpreter._alignment_cell_vtemplate.pop()
        interpreter._alignment_cell_pushed_v.pop()
        interpreter._alignment_cell_ubrace.pop()
        interpreter._alignment_cell_assembled_close.pop()


def _scan_math_macro_arg_cell(
    interpreter: TeXInterpreter,
    state: _AlignmentState,
    col_index: int,
    template: _ColumnTemplate,
    omit: bool,
    builder: HBoxBuilder,
    ctx: _HBoxDispatchContext,
) -> tuple[str, bool]:
    r"""Scan a math cell whose u-template opens a macro-argument brace (C5).

    For ``\leqalignno``'s ``\kern-\displaywidth\rlap{$\@lign##$}`` the ``\rlap``
    macro grabs ``{…}`` eagerly; if we pushed the u-template and scanned the
    body live, the macro would read past the cell terminator (its ``}`` is in
    the v-template) and the cell's ``$…$`` would be double-consumed.  Instead we
    collect the cell body *raw* (unexpanded) up to the by-meaning top-level
    terminator, then push ``u + body + v`` so the macro expands with a balanced
    argument — exactly as TeX applies the ``#``-substituted template before
    expansion. A text body's macros can still produce an earlier terminator;
    its queued V is then relocated at the execution boundary. Otherwise
    the normal cell scan runs to completion and the macro's generated
    ``\hbox`` (``\rlap``→``\hbox to\z@{#1\hss}``) is scanned in restricted
    horizontal mode with the cell's math inside.

    Returns:
        ``(terminator, omit)`` like :func:`_scan_cell`; the segment is
        scanned into the shared *builder*.
    """
    expander = interpreter._expander

    body, term = _collect_raw_cell_body(interpreter)

    # Assemble u + raw body + v.  The macro in u now sees its full `{…}` arg
    # (body + the v-template's closing `}`), so it expands balanced.
    assembled: list = list(template.u_tokens)
    assembled.extend(body)
    if template.v_tokens:
        assembled.extend(template.v_tokens)
    # Re-emit the assembled cell ahead of a sentinel terminator so the inner
    # scan (which sees no alignment terminator of its own) stops cleanly.
    terminator_tok = _make_terminator_token(term)
    expander.push_tokens([*assembled, terminator_tok])

    # Scan the assembled cell as an ordinary (omit-style) cell: the template is
    # already inlined, so suppress a second template application.
    return _scan_cell_assembled(
        interpreter, state, col_index, template, terminator_tok, builder, ctx,
    )


def _collect_raw_cell_body(
    interpreter: TeXInterpreter,
) -> tuple[list, str]:
    r"""Read a cell body *raw* up to the by-meaning top-level terminator (C5).

    Tracks begin/end-group depth so a brace-shielded ``&``/``\cr`` stays cell
    content.  Returns ``(body_tokens, terminator_kind)``; the terminator token
    is consumed (not included in the body).
    """
    expander = interpreter._expander
    body: list = []
    depth = 0
    while True:
        tok = expander._next_raw()
        if tok is None:
            raise AlignmentError(
                "\\halign: unexpected end of input (missing \\cr or })"
            )
        if depth == 0:
            term = _terminator_kind(tok, interpreter)
            if term is not None:
                return body, term
        if isinstance(tok, CharToken):
            if tok.catcode == Catcode.BEGIN_GROUP:
                depth += 1
            elif tok.catcode == Catcode.END_GROUP and depth > 0:
                depth -= 1
        body.append(tok)


def _scan_cell_assembled(
    interpreter: TeXInterpreter,
    state: _AlignmentState,
    col_index: int,
    template: _ColumnTemplate,
    terminator_tok,
    builder: HBoxBuilder,
    ctx: _HBoxDispatchContext,
) -> tuple[str, bool]:
    r"""Scan a cell whose template is already inlined on the stream (C5).

    Mirrors :func:`_scan_cell`'s body-scan/finally bracket but applies NO column
    template (the caller assembled ``u + body + v`` already) and stashes an
    empty v-template for math (the v-part is inlined). Text groups retain the
    queued V's identity and owning depth, so a macro-produced terminator can
    relocate it to the execution boundary without expanding the raw body early.
    The segment is scanned into the logical cell's shared *builder*
    and returns ``(terminator, True)``: the body is scanned omit-style.
    """
    expander = interpreter._expander
    font_manager = interpreter._font_manager
    group_stack = interpreter._group_stack
    box_regs = interpreter._box_regs

    base_box_depth = len(interpreter._box_construction_stack)

    interpreter._alignment_cell_depth += 1
    # A text hbox template stays text even when the alignment is hosted by
    # vcenter. Leave the existing assembled $...$ math route unchanged.
    text_close = not any(
        isinstance(token, CharToken) and token.catcode == Catcode.MATH_SHIFT
        for part in (template.u_tokens, template.v_tokens) for token in part
    )
    interpreter._alignment_cell_vtemplate.append(template.v_tokens if text_close else None)
    interpreter._alignment_cell_pushed_v.append(False)
    interpreter._alignment_cell_ubrace.append(0)
    interpreter._alignment_cell_assembled_close.append(
        (terminator_tok, group_stack.depth + _u_template_pre_math_open_braces(template))
        if text_close else None
    )
    # No group is opened here: this function is reached only via
    # :func:`_scan_math_macro_arg_cell`, which runs inside :func:`_scan_cell`'s
    # §791 cell group ( Component 1) — so the u-template's assignments are
    # already rolled back at cell end.  Opening a second group would nest
    # needlessly.
    try:
        term = _scan_cell_body(
            interpreter, state, col_index, expander, font_manager,
            group_stack, box_regs, True, None, builder, ctx,
            0, False, base_box_depth,
        )
        return term, True
    finally:
        interpreter._alignment_cell_depth -= 1
        interpreter._alignment_cell_vtemplate.pop()
        interpreter._alignment_cell_pushed_v.pop()
        interpreter._alignment_cell_ubrace.pop()
        interpreter._alignment_cell_assembled_close.pop()


def _scan_cell_body(
    interpreter: TeXInterpreter,
    state: _AlignmentState,
    col_index: int,
    expander,
    font_manager,
    group_stack,
    box_regs,
    omit: bool,
    template,
    builder: HBoxBuilder,
    ctx,
    inner_depth: int,
    pushed_v: bool,
    base_box_depth: int,
) -> str:
    """Cell-scan loop body, split out so ``_scan_cell`` can bracket it with the
    ``_alignment_cell_depth`` guard ( C2); returns the terminator."""
    while True:
        tok = expander._next_unexpandable()
        if tok is None:
            raise AlignmentError(
                "\\halign: unexpected end of input (missing \\cr or })"
            )

        # End-of-\everycr sentinel reached mid-cell — clear the guard and drop
        # the token (it carries no content); Q5.
        if _consume_everycr_sentinel(tok, state):
            continue

        # The raw assembled body may contain a macro that now expands to a
        # terminator. Close its owning template before ending the cell; the
        # injected V unwinds only U's groups, after U's local definitions ran.
        if (interpreter._alignment_cell_assembled_close[-1] is not None
                and _terminator_kind(tok, interpreter) is not None
                and interpreter._inject_cell_vtemplate(tok)):
            continue

        # Top-level terminators (only outside brace groups).  Checked BEFORE the
        # open-group routing below so the v-template fires (its \egroup closes
        # any cell box \t@bbox opened) at the terminator,.
        if inner_depth == 0:
            term = _terminator_kind(tok, interpreter)
            if term is not None:
                #: in a math cell the v-template is injected by the math
                # pump (run_inline_math_in_box._inject_cell_vtemplate) so its
                # `}$` closes the cell's `$`+braces before the terminator; that
                # consumes _alignment_cell_pushed_v.  Don't re-push it here.
                pump_pushed_v = (
                    interpreter._alignment_cell_pushed_v
                    and interpreter._alignment_cell_pushed_v[-1]
                )
                if (not pushed_v and not pump_pushed_v and not omit
                        and template is not None and template.v_tokens):
                    pushed_v = True
                    # Re-fire the v template, then the terminator (single push so
                    # v_tokens[0] is consumed first, terminator last).
                    expander.push_tokens(
                        [*template.v_tokens, _make_terminator_token(term)]
                    )
                    continue
                # A box the cell opened (\t@bbox) is closed by the v-template's
                # \egroup before we get here; if the frame is still open the
                # cell body is malformed.  The logical cell packages its list
                # once, after its last segment.
                return term

        #: a cell that opened an open-group box (\setbox\z@\hbox\bgroup
        # via \settabs's \t@bbox) routes ALL subsequent tokens through the
        # interpreter's main dispatch so chars/boxes flow into the box frame and
        # the deferred \egroup closes it — until the frame stack drains back to
        # the level it was at when the cell began.
        if len(interpreter._box_construction_stack) > base_box_depth:
            interpreter._dispatch(tok)
            continue

        # Brace tracking (brace-shielded &/\cr are literal cell content).
        # A brace is a command, so it ends the lig/kern run (§1038).
        if isinstance(tok, CharToken) and tok.catcode in (Catcode.BEGIN_GROUP, Catcode.END_GROUP):
            builder.end_run()
        if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
            inner_depth += 1
            group_stack.open_group(GroupKind.BRACE)
            continue
        if isinstance(tok, CharToken) and tok.catcode == Catcode.END_GROUP:
            if inner_depth == 0:
                raise AlignmentError("\\halign: unexpected } in alignment cell")
            inner_depth -= 1
            group_stack.close_group()
            continue

        # Recursive alignment inside a cell ( Q6): build a fresh
        # _AlignmentState and add the result vlist as a box node.
        if isinstance(tok, ControlSequenceToken) and tok.name in ("halign", "valign"):
            nested = _run_nested_alignment(interpreter, vertical=tok.name == "valign")
            builder.add_box(nested)
            continue

        # Box-register machinery (\setbox / \box / \copy / \global / \wd …) that
        # the shared horizontal dispatch does not handle is delegated to the
        # interpreter with the cell builder installed as the current hlist, so
        # \box\z@ etc. contribute to THIS cell. This drives the real plain.tex
        # \settabs / \+ \t@bbox cell template (\setbox\z@\hbox\bgroup … \box\z@).
        if isinstance(tok, ControlSequenceToken) and _is_delegated_cell_cs(
            interpreter, tok.name
        ):
            builder.end_run()  # §1038: delegated commands are run boundaries too.
            _delegate_cell_primitive(interpreter, builder, tok)
            continue

        dispatch_hbox_token(tok, ctx)


# Box-register / dimension primitives the shared horizontal dispatch does not
# handle but the \settabs / \+ cell template (\t@bbox / \t@bb@x) needs. They
# are delegated to the interpreter with the cell builder installed as the live
# horizontal list. \global is a prefix that the interpreter consumes together
# with the following \setbox.
_DELEGATED_CELL_CS = frozenset({
    "setbox", "box", "copy", "global", "wd", "ht", "dp",
})


def _is_delegated_cell_cs(interpreter: TeXInterpreter, name: str) -> bool:
    """Return True for cell tokens delegated to the interpreter's dispatch."""
    return name in _DELEGATED_CELL_CS


def _delegate_cell_primitive(
    interpreter: TeXInterpreter,
    builder: HBoxBuilder,
    tok: ControlSequenceToken,
) -> None:
    """Run one interpreter primitive with *builder* as the current hlist.

    Installs a :class:`ParagraphList` sharing ``builder``'s live node list,
    and pushes RESTRICTED_HORIZONTAL mode. Box-register commands contribute
    to this cell, and ``\\lastbox`` reads and removes its existing tail.
    A deferred box frame retains this context until its closing group restores
    the enclosing list and mode; no post-dispatch node splice is needed.
    """
    from aspose_tex._engine.interpreter import ModeKind
    from aspose_tex._engine.par_primitives import ParagraphList

    saved_par_list = interpreter._par_list
    saved_mode_depth = interpreter._mode_stack.depth
    cell_list = ParagraphList()
    # The delegate owns this cell's existing list, including removable boxes.
    cell_list._nodes = builder._nodes
    interpreter._par_list = cell_list
    interpreter._mode_stack.push(ModeKind.RESTRICTED_HORIZONTAL)
    base_box_depth = len(interpreter._box_construction_stack)
    opened_frame = False
    try:
        interpreter._dispatch_cs(tok)
        #: \setbox\z@\hbox\bgroup opens a deferred-close box frame that
        # OWNS the mode + _par_list it installed (saving cell_list to restore on
        # \egroup).  Leave that frame's context in place — tearing it down here
        # would strand the open box.  Re-point the frame's restore targets at
        # THIS delegate's pre-push state so _close_group_box fully unwinds the
        # delegate's RESTRICTED_HORIZONTAL push + cell_list install too.
        if len(interpreter._box_construction_stack) > base_box_depth:
            opened_frame = True
            frame = interpreter._box_construction_stack[base_box_depth]
            frame.restore_mode_depth = saved_mode_depth
            frame.saved_par_list = saved_par_list
    finally:
        if not opened_frame:
            interpreter._mode_stack.pop()
            interpreter._par_list = saved_par_list


def _consume_omit_and_template(
    interpreter: TeXInterpreter,
    state: _AlignmentState,
    col_index: int,
) -> tuple[bool, _ColumnTemplate | None]:
    """Peek for a leading ``\\omit``; resolve the column template for ``col_index``.

    Spaces before the cell's first token are skipped, as TeX §791 ``fin_col``
    does after ``&`` / ``\\span`` (``repeat get_x_or_protected until
    cur_cmd<>spacer``) before §788 ``init_col`` checks for ``\\omit`` — so
    ``a& b`` gets no leading interword glue and ``a& \\omit b`` is an
    ``\\omit``.  The row's first cell was already skipped by
    ``_peek_non_space`` at the row boundary (§785), where this is a no-op.
    """
    expander = interpreter._expander
    omit = False

    # Gap A: in a math \halign peek the cell's leading token RAW so a
    # bare math macro (\mathstrut) is not expanded before the u-template's `$`
    # opens math (see _peek_non_space).  `\omit` is a primitive, recognised raw.
    raw = interpreter._alignment_math_context > 0
    tok = _peek_non_space(interpreter)
    if not raw:
        #: peek() parks the token in the one-slot `_peeked` cache, which
        # `_next_raw` drains BEFORE `_stack` — so the u-template that _scan_cell
        # pushes next would land AFTER this cell's first token, putting the
        # template's `\quad` between the first two glyphs (10pt displacement +
        # a lost lig/kern pair).  Park it back on the stack so the push wins.
        # Removing this call silently re-introduces that rendering defect.
        expander.unpeek()
    if isinstance(tok, ControlSequenceToken) and tok.name == "omit":
        expander._next_unexpandable()
        omit = True

    return omit, _template_for(state, col_index)


def _u_template_pre_math_open_braces(template: _ColumnTemplate) -> int:
    r"""Net begin-group braces a math u-template opens BEFORE its ``$``.

    C5 (the macro-argument straddle): ``\leqalignno``'s number column
    is ``\kern-\displaywidth\rlap{$\@lign##$}`` — the ``{`` is opened *before*
    the ``$`` as the argument brace of the ``\rlap`` *macro* (``\rlap#1{\hbox
    to\z@{#1\hss}}``), whose matching ``}`` lives in the v-template.  Unlike a
    primitive ``\hbox{`` (\displaylines), which exec_hbox scans, a macro grabs
    its ``{…}`` argument eagerly when the cell scanner expands it — so it reads
    *past* the cell terminator looking for the ``}``, and the cell's ``$…$``
    gets double-consumed (the pump opens math on the same ``$`` the macro
    re-emits → ``mismatched $$``).  A non-zero pre-``$`` brace count signals this
    straddle so :func:`_scan_cell` assembles ``u + raw body + v`` and lets the
    macro expand with a balanced argument (TeX applies the whole template-with-
    ``#``-substituted before expansion).  ``\llap`` (``\hss`` before ``#1``)
    works without this only by accident of ordering; routing both through the
    assembly path is uniform and correct.
    """
    depth = 0
    for tok in template.u_tokens:
        if isinstance(tok, CharToken):
            if tok.catcode == Catcode.MATH_SHIFT:
                break
            if tok.catcode == Catcode.BEGIN_GROUP:
                depth += 1
            elif tok.catcode == Catcode.END_GROUP and depth > 0:
                depth -= 1
    return depth


def _u_template_open_braces(template: _ColumnTemplate) -> int:
    r"""Net begin-group braces left open by a math u-template after its ``$``.

    Q6: for a math column whose u-template opens math and then an
    unbalanced brace (``\eqalign``: ``\strut\hfil$\displaystyle{`` → one open
    ``{`` after the ``$``), the cell's ``&``/``\cr`` arrives while the math
    pump's brace depth equals this count, not 0.  Counting only braces AFTER
    the opening ``$`` (the part scanned *inside* the pump) gives the depth at
    which the pump must fire the ``\endv`` v-template injection.  Returns 0 for
    a template that does not open a straddling brace (``\matrix``: ``\hfil$``).
    """
    depth = 0
    seen_math = False
    for tok in template.u_tokens:
        if isinstance(tok, CharToken) and tok.catcode == Catcode.MATH_SHIFT:
            seen_math = True
            continue
        if not seen_math:
            continue
        if isinstance(tok, CharToken):
            if tok.catcode == Catcode.BEGIN_GROUP:
                depth += 1
            elif tok.catcode == Catcode.END_GROUP and depth > 0:
                depth -= 1
    return depth


def _template_for(state: _AlignmentState, col_index: int) -> _ColumnTemplate | None:
    """Return the template for ``col_index``, cycling the repeating block.

    Columns past the explicit template list reuse the repeating block (the
    ``&&`` preamble portion) when one was declared; otherwise there is no
    template (ragged-row cell with no column).
    """
    n = len(state.templates)
    if 0 <= col_index < n:
        return state.templates[col_index]
    if state.repeat_from >= 0 and n > state.repeat_from:
        cycle = n - state.repeat_from
        return state.templates[state.repeat_from + (col_index - state.repeat_from) % cycle]
    return None


def first_column_is_math(state: _AlignmentState) -> bool:
    r"""Return whether the first column's u-template opens math ( C2/C3).

    A math ``\halign`` (``\bordermatrix``'s eager ``\setbox\vbox{…\ialign{$##$…}}``,
    or the top-level display family ``\displaylines``/``\eqalignno``/``\leqalignno``
    whose cells are ``\hbox{$…##…$}``) runs WITHOUT a math ``\vcenter``, so
    ``interpreter._alignment_math_context`` is not set by
    ``build_math_vcenter_box``.  We detect such an alignment by its first
    column's u-template containing a top-level (brace-depth-0) ``$`` —
    every plain.tex math-alignment macro opens its cell math in the u-template.
    When true, :func:`_run_alignment` raises ``_alignment_math_context`` for the
    row collection so the cell-math shielding engages off the
    ``\vcenter`` path.  A text ``\halign`` (no ``$`` column) returns ``False``
    and is byte-identical.
    """
    if not state.templates:
        return False
    brace_depth = 0
    for tok in state.templates[0].u_tokens:
        if isinstance(tok, CharToken):
            if tok.catcode == Catcode.BEGIN_GROUP:
                brace_depth += 1
            elif tok.catcode == Catcode.END_GROUP and brace_depth > 0:
                brace_depth -= 1
            elif tok.catcode == Catcode.MATH_SHIFT and brace_depth == 0:
                return True
    return False


# Maximum \let-alias hops followed by _resolve_terminator_name before giving up
# (a defensive cap against a cyclic \let chain; real chains are 1-2 deep).
_ALIAS_RESOLVE_LIMIT = 32

# Alignment-internal primitive names a terminator alias may resolve to.
_TERMINATOR_PRIMITIVES = frozenset((_TERM_SPAN, _TERM_CR, _TERM_CRCR))


def _resolve_terminator_name(name: str, interpreter: TeXInterpreter) -> str | None:
    """Resolve a control-sequence *name* to an alignment-terminator primitive.

    Follows ``\\let``-alias links in the interpreter's macro table (e.g.
    ``\\let\\endline=\\cr`` stores ``endline -> ControlSequenceToken('cr')``)
    down to the underlying primitive, and returns that primitive's name if it
    is one of ``span`` / ``cr`` / ``crcr`` — else ``None`` (§Component
    1 / Q1-Q2).  The alignment primitives are *not* stored in ``_macros`` (they
    live in the interpreter's primitive registry), so a chain naturally
    terminates when a name is absent from the macro table.

    A name that is already a literal terminator primitive returns itself with
    no table walk (the common bare ``\\cr`` fast path).  The walk is
    cycle-guarded by :data:`_ALIAS_RESOLVE_LIMIT`.

    Args:
        name:        Control-sequence name (without backslash).
        interpreter: Owning interpreter; its expander's macro table is walked.

    Returns:
        ``"span"`` / ``"cr"`` / ``"crcr"`` if *name* resolves to that alignment
        primitive, else ``None``.
    """
    if name in _TERMINATOR_PRIMITIVES:
        return name
    macros = interpreter._expander._macros
    seen: set[str] = set()
    current = name
    for _ in range(_ALIAS_RESOLVE_LIMIT):
        if current in seen:
            return None  # cyclic \let chain — bail out
        seen.add(current)
        meaning = macros.get(current)
        if isinstance(meaning, PrimitiveMeaning):  # D3
            return meaning.name if meaning.name in _TERMINATOR_PRIMITIVES else None
        if not isinstance(meaning, ControlSequenceToken):
            return None  # not a CS alias (macro, char alias, or absent)
        target = meaning.name
        if target in _TERMINATOR_PRIMITIVES:
            return target
        current = target
    return None


def _terminator_kind(tok, interpreter: TeXInterpreter) -> str | None:
    """Return the terminator kind for *tok*, or None if it is not one.

    Classifies by *meaning*, not by name: a ``\\let``-alias of ``\\cr`` /
    ``\\crcr`` / ``\\span`` (such as plain.tex's ``\\let\\endline=\\cr``)
    resolves to its underlying primitive via :func:`_resolve_terminator_name`
    (§Component 1).
    """
    if isinstance(tok, CharToken) and tok.catcode == Catcode.ALIGNMENT:
        return _TERM_TAB
    if isinstance(tok, ControlSequenceToken):
        return _resolve_terminator_name(tok.name, interpreter)
    return None


def _make_terminator_token(term: str):
    """Re-materialise a terminator token to re-fire after the ``v`` template."""
    if term == _TERM_TAB:
        return CharToken("&", Catcode.ALIGNMENT)
    return ControlSequenceToken(term)


# ---------------------------------------------------------------------------
# Row collection
# ---------------------------------------------------------------------------

def _collect_rows(interpreter: TeXInterpreter, state: _AlignmentState) -> None:
    """Scan all rows + ``\\noalign`` material into ``state.rows`` (pass 1).

    Terminates when the alignment-closing ``}`` is reached at the row boundary.
    Fires ``\\everycr`` at each row break with a recursion guard (Q5).
    """
    expander = interpreter._expander
    prev_was_cr = False

    # TeX §791/§812 ( Component 2): the alignment keeps its OWN
    # \prevdepth chain while rows are collected.  The two-pass model
    # collects rows into `state.rows` and contributes nothing until pass 2, so
    # without the save/restore the per-row values would escape into the
    # enclosing list.
    #
    # Component 5: the chain STARTS from the inherited value — TeX does
    # not reset \prevdepth at an alignment.  Measured in MiKTeX 24.4 at the
    # leading \everycr firing: -1000pt for a \halign at the head of a fresh
    # \vbox (the *\vbox* seeds that, not the \halign), but 0.0pt after an
    # \hbox and 7.0pt after `\prevdepth=7pt`.  A display hands its value over
    # explicitly, because our two-pass model collects the rows before
    # `_end_paragraph` contributes the line whose depth TeX would have used.
    saved_prev_depth = interpreter._prev_depth
    pending = interpreter._pending_display_prev_depth
    if pending is not None:
        interpreter._pending_display_prev_depth = None
        interpreter._prev_depth = pending
    try:
        # TeX §785 ( Component 3): `align_peek` runs before EVERY attempt
        # to read a row — including the attempt that finds the closing `}` — and
        # each run fires \everycr.  The count is therefore `1 + rows`, with the
        # material interleaved as
        #     material(1) · row1 · material(2) · … · rowN · material(N+1).
        # `_collect_rows_body` already fires after each row, which supplies
        # firings 2…N+1 (the trailing one included); only the LEADING firing was
        # missing.  It runs here, with \prevdepth still at the sentinel seeded
        # just above, so plain.tex `\displ@y`'s `\ifdim\prevdepth>-1000\p@`
        # answers exactly as TeX's does — that guard is the reason the leading
        # firing emits the `\vskip` pair rather than a penalty.
        _fire_everycr_leading(interpreter, state)
        _collect_rows_body(interpreter, state, expander, prev_was_cr)
    finally:
        interpreter._prev_depth = saved_prev_depth


def _fire_everycr_leading(
    interpreter: TeXInterpreter, state: _AlignmentState,
) -> None:
    r"""Fire ``\everycr`` once before the first row and collect its material.

    The post-row firings push their token list onto the input stream and let
    the row loop pick the resulting ``\noalign`` up.  Nothing consumes the
    stream before the loop starts, so the leading firing instead scans its own
    material here and appends it to ``state.rows`` as the first entry — leaving
    the recursion guard clear for the loop that follows ( Component 3).

    Args:
        interpreter: Owning interpreter; its ``\prevdepth`` is at the alignment
            sentinel when this runs, as TeX's is at the same point.
        state:       Alignment collection state; receives the material.
    """
    toks = _read_everycr(interpreter)
    if not toks:
        return
    interpreter._expander.push_tokens(list(toks))
    while True:
        tok = _peek_non_space(interpreter)
        if not (
            isinstance(tok, ControlSequenceToken) and _primitive_name(tok, interpreter) == "noalign"
        ):
            break
        interpreter._expander._next_unexpandable()
        _append_noalign(interpreter, state)


def _collect_rows_body(
    interpreter: TeXInterpreter,
    state: _AlignmentState,
    expander,
    prev_was_cr: bool,
) -> None:
    """Row-collection loop proper, run inside the ``\\prevdepth`` chain."""
    while True:
        # TeX §785/§791: the row-boundary classification below is an
        # EXPANDING read (TeX's `align_peek` uses `get_x_token`), so a macro
        # standing at a row boundary is expanded — and anything non-structural
        # it expands to is *executed* there.  In TeX that execution already sits
        # inside the row/cell group, so a leading `\def` is rolled back at cell
        # end; classifying outside the group instead would let it escape.
        # Open the group FIRST and hand it to `_collect_one_row`, which reuses
        # it rather than opening a second one.  MiKTeX 24.4 ground truth:
        # `\halign{#\cr \def\g{Z}a\cr \g\cr}` renders `Y`, and so does the
        # macro-mediated `\def\ord{\def\g{Z}a}` form.
        interpreter._group_stack.open_group(GroupKind.BRACE)
        cell_group_owned = True
        try:
            tok = _peek_non_space(interpreter)
            if tok is None:
                raise AlignmentError(
                    "\\halign: unexpected end of input (missing \\cr or })"
                )

            # End-of-\everycr sentinel at the row boundary — clear the guard so
            # the next genuine row break may fire \everycr again ( Q5).
            if (
                isinstance(tok, ControlSequenceToken)
                and tok.name == _EVERYCR_SENTINEL
            ):
                expander._next_unexpandable()
                state.firing_everycr = False
                continue

            # Closing brace at a row boundary ends the alignment.
            if isinstance(tok, CharToken) and tok.catcode == Catcode.END_GROUP:
                expander._next_unexpandable()
                return

            # \crcr at the row boundary right after a \cr is a no-op (TeXbook
            # p.249): consume it WITHOUT applying the column template.
            # Otherwise a math \halign whose cell template opens an \hbox
            # (\displaylines's `\hbox to\displaywidth{$…$}`) would build a
            # spurious empty trailing cell for the wrapper `\crcr`, and that
            # hbox would swallow the alignment's own closing `}` ( C4).
            # Classified by meaning so a \let-alias of \crcr is recognised
            #.
            if (
                prev_was_cr
                and _terminator_kind(tok, interpreter) == _TERM_CRCR
            ):
                expander._next_unexpandable()
                continue

            # \noalign{...} between rows.  This is NOT cell material: TeX gives
            # \noalign its own group at alignment level, and MiKTeX confirms it
            # neither sees a preceding cell's \def nor leaks its own.  Close the
            # speculative cell group before scanning it.
            if isinstance(tok, ControlSequenceToken) and _primitive_name(tok, interpreter) == "noalign":
                expander._next_unexpandable()
                interpreter._group_stack.close_group()
                cell_group_owned = False
                _append_noalign(interpreter, state)
                # NOTE: do NOT clear prev_was_cr here.  \noalign is between-rows
                # material; a \crcr arriving after `\cr \noalign{…} \crcr` (the
                # \displ@y \everycr injects a \noalign between the row's \cr and
                # the wrapper \crcr) is still a no-op after the \cr (
                # C4).  The row-terminator state persists across \noalign.
                continue

            row, last_term = _collect_one_row(
                interpreter, state, preopened_group=True,
            )
        finally:
            if cell_group_owned:
                interpreter._group_stack.close_group()
        # \crcr right after a \cr produces an empty no-op row.
        if not (last_term == _TERM_CRCR and prev_was_cr and not row):
            state.rows.append(row)
            # Component 2: the row just finished is the box \prevdepth
            # must report to the `\everycr` body fired below.  The row hbox is
            # assembled in pass 2, so its depth is taken from the cells that
            # will form it — for an hbox that is exactly max(cell depth), which
            # is what `_pack_hrow` will compute.
            interpreter._prev_depth = _row_depth(row)
        prev_was_cr = True
        _fire_everycr(interpreter, state)


def _row_depth(row: list) -> int:
    """Depth in sp of the row hbox that *row*'s cells will be packed into.

    An hbox's depth is the maximum depth of its contents, so the row's depth is
    known from the cell boxes before pass 2 assembles them ( Component 2).

    Args:
        row: The row's ``_CellRecord`` list.

    Returns:
        The maximum cell depth, or 0 for an empty row.
    """
    return max((cell.box.depth for cell in row), default=0)


def _collect_one_row(
    interpreter: TeXInterpreter,
    state: _AlignmentState,
    *,
    preopened_group: bool = False,
) -> tuple[list, str]:
    """Scan one row's cells (across ``&`` / ``\\span``); return ``(cells, term)``.

    Args:
        interpreter: Owning interpreter.
        state:       The alignment's collection state.
        preopened_group: When True, the caller has already opened the §791 group
            for the row's FIRST logical cell (``_collect_rows_body`` does this so
            the row-boundary classification expands inside the cell's scope —
            ) and owns closing it.  Later cells in the same row still open
            and close their own group here.

    Returns:
        ``(cells, terminator)`` for the row.
    """
    cells: list = []
    col_index = 0
    first_cell = True

    while True:
        # TeX §791 ( Component 1): one LOGICAL cell is one group, so a
        # template's assignment is rolled back at cell end.  The group spans the
        # whole `\span` chain, because `\span`-merged segments are a single
        # logical cell: MiKTeX shows a `\def` in segment 1 is still visible in
        # segment 2 (`\span \message{\w}` reports the inner value) yet is gone
        # after the row.  Grouping each segment separately would break
        # `\multispan`, whose `\loop` keeps its state in a LOCAL `\def\body`
        # while `\sp@n` crosses segment boundaries.
        owns_group = not (first_cell and preopened_group)
        if owns_group:
            interpreter._group_stack.open_group(GroupKind.BRACE)
        try:
            # Both scanners return the whole `\span` chain as one logical cell.
            if state.vertical:
                interpreter._normal_paragraph()  # §787 init_span, local to the cell
                box, term, omit, span_count = _scan_vertical_cell(interpreter, state, col_index)
            else:
                box, term, omit, span_count = _scan_horizontal_cell(
                    interpreter, state, col_index,
                )
        finally:
            if owns_group:
                interpreter._group_stack.close_group()
        first_cell = False
        adjustments = [] if state.vertical else interpreter._extract_adjustments(box)
        cells.append(_CellRecord(box, col_index, span_count, omit, adjustments))
        col_index += span_count
        if term in (_TERM_CR, _TERM_CRCR):
            return cells, term
        # term == _TERM_TAB → next cell in the same row.


def _scan_horizontal_cell(
    interpreter: TeXInterpreter,
    state: _AlignmentState,
    col_index: int,
) -> tuple[HlistNode, str, bool, int]:
    """Execute one logical halign cell, keeping one list across ``\\span``.

    TeX §791 ``fin_col`` neither packages the cell nor calls ``init_span`` when
    a column ends with ``\\span``: the next column's ``u`` template continues
    the same horizontal list, so tail readers and removers (``\\lastbox``,
    ``\\lastkern``, ``\\unskip`` …) and the space factor see every earlier
    segment.  One builder, one dispatch context and one tail scope therefore
    own the whole chain, and the list is packaged once.

    Args:
        interpreter: Owning interpreter.
        state:       The alignment's collection state.
        col_index:   Column of the logical cell's first segment.

    Returns:
        ``(box, terminator, first_omit, span_count)``.

    Raises:
        AlignmentError: on end of input before a terminator.
    """
    expander = interpreter._expander
    font_manager = interpreter._font_manager
    builder = HBoxBuilder(font_manager)
    ctx = _HBoxDispatchContext(
        expander, font_manager, interpreter._group_stack, interpreter._box_regs, builder,
    )
    with _list_tail_scope(expander, builder):
        term, first_omit = _scan_cell(interpreter, state, col_index, builder, ctx)
        span_count = 1
        while term == _TERM_SPAN:
            # The v template's end is a command: the lig/kern run stops at the
            # segment boundary (§1034/§1038); nothing else is reset.
            builder.end_run()
            term, _omit = _scan_cell(
                interpreter, state, col_index + span_count, builder, ctx,
            )
            span_count += 1
    return builder.build(), term, first_omit, span_count


def _scan_vertical_cell(interpreter, state, col_index):
    """Execute one logical valign cell, preserving a nest across span segments."""
    from aspose_tex._engine.interpreter import ModeKind

    expander = interpreter._expander
    builder = VBoxBuilder(interpreter._font_manager)
    group_depth = interpreter._group_stack.depth
    span_count = 1
    with interpreter._internal_vertical_scope(builder):
        box_depth = len(interpreter._box_construction_stack)
        omit, template = _consume_omit_and_template(interpreter, state, col_index)
        first_omit = omit
        if not omit and template is not None:
            expander.unpeek()
            expander.push_tokens(list(template.u_tokens))
        pushed_v = False
        for token in interpreter._token_iter:
            at_boundary = (interpreter._group_stack.depth == group_depth
                           and len(interpreter._box_construction_stack) == box_depth)
            term = _terminator_kind(token, interpreter) if at_boundary else None
            if term is not None:
                if not pushed_v and not omit and template is not None and template.v_tokens:
                    expander.push_tokens([*template.v_tokens, token])
                    pushed_v = True
                    continue
                if interpreter._mode_stack.current == ModeKind.HORIZONTAL:
                    interpreter._end_paragraph()
                if term == _TERM_SPAN:
                    omit, template = _consume_omit_and_template(interpreter, state, col_index + span_count)
                    span_count += 1
                    expander.unpeek()
                    if not omit and template is not None:
                        expander.push_tokens(list(template.u_tokens))
                    pushed_v = False
                    continue
                box = builder.build()
                # fin_col's vpackage has maxdepth=0 (§800).
                box.height += box.depth
                box.depth = 0
                return box, term, first_omit, span_count
            if (at_boundary and isinstance(token, CharToken)
                    and token.catcode == Catcode.END_GROUP):
                raise AlignmentError("Missing \\cr in \\valign cell")
            interpreter._dispatch(token)
        raise AlignmentError("Unexpected end of input inside \\valign cell")


def _peek_non_space(interpreter: TeXInterpreter):
    """Peek the next unexpandable token, skipping spaces (§785 / §791).

    Used at the row boundary (``align_peek``) and at every cell start
    (``fin_col``, via :func:`_consume_omit_and_template`).

    Gap A: in a math ``\\vcenter`` ``\\halign``
    (``_alignment_math_context > 0``) the next row's first token may be a bare
    math macro (``\\matrix``'s strut row ``\\mathstrut``).  Expanding it here —
    while the surrounding mode is the outer formula's MATH — produces a
    ``\\mathchoice`` the restricted-horizontal cell scanner cannot place.  A
    *raw* peek leaves the body macro unexpanded; the cell's u-template ``$``
    then opens math (``run_inline_math_in_box``) so the macro expands as a math
    atom.  Structural row-boundary tokens (``}`` / ``\\noalign`` / the everycr
    sentinel / a by-meaning ``\\crcr``) are still recognised raw.
    """
    expander = interpreter._expander
    raw = interpreter._alignment_math_context > 0
    while True:
        tok = expander.peek_raw() if raw else expander.peek()
        if isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
            expander._next_unexpandable()
            continue
        return tok


def _fire_everycr(interpreter: TeXInterpreter, state: _AlignmentState) -> None:
    """Push ``\\everycr`` tokens onto the stream at a row break ( Q5).

    Guards against infinite recursion: while one ``\\everycr`` token list is
    still being consumed (``state.firing_everycr`` set), a subsequent row break
    does NOT re-fire.  A NUL-prefixed sentinel control sequence is pushed after
    the token list; ``_consume_everycr_sentinel`` clears the flag when it is
    reached, re-enabling firing for the next genuine row break.
    """
    if state.firing_everycr:
        return
    toks = _read_everycr(interpreter)
    if not toks:
        return
    state.firing_everycr = True
    interpreter._expander.push_tokens(
        [*toks, ControlSequenceToken(_EVERYCR_SENTINEL)]
    )


def _consume_everycr_sentinel(tok, state: _AlignmentState) -> bool:
    """Clear the ``\\everycr`` guard if *tok* is the sentinel; return whether it was."""
    if isinstance(tok, ControlSequenceToken) and tok.name == _EVERYCR_SENTINEL:
        state.firing_everycr = False
        return True
    return False


# ---------------------------------------------------------------------------
# \noalign vlist scanner
# ---------------------------------------------------------------------------

def _primitive_name(tok, interpreter):
    """Resolve structural aliases without expanding a body twice."""
    meaning = interpreter._expander._let_meaning(tok)
    return meaning.name if isinstance(meaning, PrimitiveMeaning) else None


def _append_noalign(interpreter: TeXInterpreter, state: _AlignmentState) -> None:
    """Execute adjacent bodies against one mutable list tail."""
    previous = state.rows[-1] if state.rows and isinstance(state.rows[-1], _NoalignRecord) else None
    record = previous if previous is not None else _NoalignRecord([], None)
    has_row = bool(state.rows) if previous is None else len(state.rows) > 1
    _scan_noalign(interpreter, in_valign=state.vertical, previous=record,
                  has_preceding_row=has_row)
    if previous is None:
        state.rows.append(record)


@contextmanager
def _noalign_row_barrier(nodes: list, active: bool):
    """Represent an unset row only during execution, never in returned nodes."""
    barrier = object() if active else None
    if barrier is not None:
        nodes.insert(0, barrier)
    try:
        yield
    finally:
        if barrier is not None:
            for index, node in enumerate(nodes):
                if node is barrier:
                    del nodes[index]
                    break


def _scan_noalign(
    interpreter: TeXInterpreter, *, in_valign: bool = False,
    previous: _NoalignRecord | None = None,
    has_preceding_row: bool = False,
) -> _NoalignRecord:
    """Return replay-ready raw material and final depth after ordinary execution.

    The preceding unset row signals nonemptiness while the body executes;
    its opaque tail barrier is removed before return, including on failure.
    """
    record = previous if previous is not None else _NoalignRecord([], None)
    if in_valign:
        return _scan_horizontal_noalign(interpreter, record)
    from aspose_tex._engine.interpreter import ModeKind

    incoming_depth = interpreter._prev_depth
    builder = VBoxBuilder(interpreter._font_manager)
    builder._nodes = record.nodes
    expander = interpreter._expander
    with (_noalign_row_barrier(record.nodes, has_preceding_row),
          interpreter._internal_vertical_scope(builder)):
        interpreter._prev_depth = incoming_depth
        expander._scan_left_brace("\\noalign")
        interpreter._group_stack.open_group(GroupKind.BRACE)
        interpreter._normal_paragraph()
        owner_depth = interpreter._group_stack.depth
        box_depth = len(interpreter._box_construction_stack)
        while True:
            tok = expander._next_unexpandable()
            if tok is None:
                raise AlignmentError("\\noalign: unexpected end of input")
            if isinstance(tok, CharToken) and tok.catcode == Catcode.END_GROUP:
                if interpreter._group_stack._frames[-1].kind != GroupKind.BRACE:
                    raise AlignmentError("} cannot close a semisimple noalign group")
                if (interpreter._group_stack.depth == owner_depth
                        and len(interpreter._box_construction_stack) == box_depth):
                    if interpreter._math_builder is not None:
                        raise AlignmentError("} cannot close the active noalign math group")
                    if interpreter._mode_stack.current == ModeKind.HORIZONTAL:
                        interpreter._end_paragraph()
                    final_depth = interpreter._prev_depth
                    tokens, _ = interpreter._group_stack.close_group()
                    expander.push_tokens(tokens)
                    break
            if (isinstance(tok, ControlSequenceToken)
                    and _primitive_name(tok, interpreter) == "endgroup"
                    and interpreter._group_stack.depth == owner_depth):
                raise AlignmentError("\\endgroup cannot close a noalign brace group")
            interpreter._dispatch(tok)
    record.prev_depth = final_depth
    interpreter._prev_depth = final_depth
    return record


def _scan_horizontal_noalign(
    interpreter: TeXInterpreter, record: _NoalignRecord,
) -> _NoalignRecord:
    """Reuse eager horizontal dispatch with isolated enclosing ownership."""
    expander = interpreter._expander
    groups = interpreter._group_stack
    builder = HBoxBuilder(interpreter._font_manager)
    builder._nodes = record.nodes
    ctx = _HBoxDispatchContext(expander, interpreter._font_manager, groups,
                               interpreter._box_regs, builder)
    # The ordinary scope restores paragraph/math/deferred-frame state on error;
    # the eager scope inside it owns the actual restricted horizontal list.
    with (interpreter._internal_vertical_scope(VBoxBuilder(interpreter._font_manager)),
          _list_tail_scope(expander, builder)):
        expander._scan_left_brace("\\noalign")
        groups.open_group(GroupKind.BRACE)
        owner_depth = groups.depth
        box_depth = len(interpreter._box_construction_stack)
        while True:
            tok = expander._next_unexpandable()
            if tok is None:
                raise AlignmentError("\\noalign: unexpected end of input")
            if len(interpreter._box_construction_stack) > box_depth:
                interpreter._dispatch(tok)
                continue
            if isinstance(tok, CharToken) and tok.catcode in (Catcode.BEGIN_GROUP, Catcode.END_GROUP):
                builder.end_run()
                if tok.catcode == Catcode.BEGIN_GROUP:
                    groups.open_group(GroupKind.BRACE)
                else:
                    if groups._frames[-1].kind != GroupKind.BRACE:
                        raise AlignmentError("} cannot close a semisimple noalign group")
                    closing = groups.depth == owner_depth
                    tokens, _ = groups.close_group()
                    expander.push_tokens(tokens)
                    if closing:
                        break
                continue
            if (isinstance(tok, ControlSequenceToken)
                    and _primitive_name(tok, interpreter) == "endgroup"
                    and groups.depth == owner_depth):
                raise AlignmentError("\\endgroup cannot close a noalign brace group")
            dispatch_hbox_token(tok, ctx)
    record.prev_depth = None
    return record


# ---------------------------------------------------------------------------
# Column-width measurement (pass-1 reduction)
# ---------------------------------------------------------------------------

def _measure_columns(state: _AlignmentState) -> None:
    """Reduce signed span constraints left to right, as TeX §801."""
    ncols = _ncols(state)
    width = [_NULL_FLAG] * ncols
    spans: list[dict[int, int]] = [{} for _ in range(ncols)]
    # Resolve repeats before any unused-column gap is cleared. Every emitter
    # reads this invocation-local array, never the named tabskip register.
    tabskip = [_tabskip_for(state, j) for j in range(ncols + 1)]
    for row in state.rows:
        if not isinstance(row, list):
            continue
        for cell in row:
            first = cell.col_index
            last = min(first + cell.span_count - 1, ncols - 1)
            extent = _cell_extent(cell.box, state.vertical)
            if cell.span_count == 1:
                width[first] = max(width[first], extent)
            else:
                spans[first][last] = max(spans[first].get(last, _NULL_FLAG), extent)

    for j in range(ncols):
        if width[j] == _NULL_FLAG:
            width[j] = 0
            tabskip[j + 1] = _ZERO_GLUE
        for last, extent in spans[j].items():
            remainder = extent - width[j] - tabskip[j + 1].width
            if last == j + 1:
                width[last] = max(width[last], remainder)
            else:
                spans[j + 1][last] = max(spans[j + 1].get(last, _NULL_FLAG), remainder)
    state.tabskip = tabskip
    state.column_width = width


def _ncols(state: _AlignmentState) -> int:
    """Return the column count: the explicit templates, widened by any rows.

    Repeating preambles (``\\settabs`` / ``\\ialign``) declare fewer templates
    than the rows use, so the true column count is the widest row's cell reach.
    """
    ncols = len(state.templates)
    for row in state.rows:
        if not isinstance(row, list):
            continue
        for cell in row:
            reach = cell.col_index + cell.span_count
            if reach > ncols:
                ncols = reach
    return ncols


def _cell_extent(box: HlistNode | VlistNode, vertical: bool) -> int:
    """Return a cell's aligned dimension: width (halign) or height+depth (valign)."""
    if vertical:
        return box.height + box.depth
    return box.width


def _glue_natural(glue: Glue) -> int:
    """Return the natural width of a glue value in sp."""
    return glue.width


# ---------------------------------------------------------------------------
# Pass 2 — row emission
# ---------------------------------------------------------------------------

def _emit_rows(
    interpreter: TeXInterpreter, state: _AlignmentState,
) -> HlistNode | VlistNode:
    """Repack cells and assemble the result list.

    ``\\halign`` → a vlist of row hboxes (cells joined left-to-right with
    ``\\tabskip`` glue).  ``\\valign`` → an hlist of column vboxes (cells
    stacked top-to-bottom; columns joined left-to-right with ``\\tabskip``
    glue between them); cascade b.
    """
    if state.vertical:
        return _emit_columns(state, interpreter._font_manager)

    #: stack the row hboxes with §807/§679 interline glue (the same
    # \baselineskip/\lineskip mechanism exec_vbox uses), tracking prev_depth
    # across rows.  \noalign material is spliced verbatim and resets the
    # interline chain per.
    out_nodes: list = []
    prev_depth = IGNORE_PREV_DEPTH
    for row in state.rows:
        if isinstance(row, _NoalignRecord):
            # Body execution has already calculated glue and final depth,
            # including assignments and removals.
            out_nodes.extend(row.nodes)
            prev_depth = row.prev_depth
            continue
        row_box = _emit_row(state, row)
        glue = compute_interline_glue(
            prev_depth=prev_depth,
            next_height=row_box.height,
            baselineskip=state.baselineskip,
            lineskip=state.lineskip,
            lineskiplimit=state.lineskiplimit,
        )
        if glue is not None:
            out_nodes.append(GlueNode(glue))
        out_nodes.append(row_box)
        for cell in row:
            out_nodes.extend(cell.adjustments)
        prev_depth = row_box.depth

    return _pack_vlist(out_nodes)


def _contributes_to_vertical_list(interpreter: TeXInterpreter) -> bool:
    """True iff a ``\\halign`` result lands directly in a real vertical list.

    : a top-level ``\\halign`` in outer/internal vertical mode with no
    open box-construction frame is contributed row-by-row to the enclosing
    vertical list (the page builder then owns interline glue + ``\\topskip``);
    otherwise (restricted-horizontal / math mode, or an open ``\\hbox\\bgroup`` /
    ``\\vbox\\bgroup`` frame whose builder receives boxes raw) the result is the
    packed vlist added via ``_add_box_to_current_list``.
    """
    from aspose_tex._engine.interpreter import ModeKind

    frame = interpreter._current_box_frame()
    if frame is not None and not frame.vertical:
        return False
    return interpreter._mode_stack.current in (
        ModeKind.OUTER_VERTICAL, ModeKind.INTERNAL_VERTICAL,
    )


def _is_display_top_level_alignment(interpreter: TeXInterpreter) -> bool:
    r"""True iff this ``\halign`` IS the display's top-level material (§812).

    Component 4 / Component 3.  A ``$$…$$`` whose body is an
    alignment — the plain.tex ``\displ@y`` families ``\eqalignno``,
    ``\leqalignno`` and ``\displaylines`` — must have its rows **spliced** into
    the enclosing vertical list individually, so the first row attracts its own
    ``\baselineskip`` and the ``\everycr`` ``\noalign`` glue reaches the list.
    Packing them into one box instead makes the page builder compute interline
    glue against the whole stack, which is the residual closes.

    **The predicate is deliberately structural, not mode-based**, and this is
    the maintenance risk flagged.  The five ``\vcenter`` legs
    (``\eqalign``, ``\matrix``, ``\pmatrix``, ``\cases``, ``\bordermatrix``)
    run in ``MATH_DISPLAY`` too, and must KEEP the packed path —
    they are byte-exact today.  What separates them is not the mode but the
    entry point: a ``\vcenter`` leg is built by
    :func:`_run_nested_alignment`, which never consults this function, while a
    ``\displ@y`` family reaches :func:`exec_halign` directly.  Measured for all
    six constructs; ``\bordermatrix`` in particular has
    ``_alignment_math_context == 0``, so testing that flag would misclassify it.

    An open box-construction frame still wins: ``\setbox0=\vbox{$$…$$}`` hands
    the box to the frame's builder, so the packed path is correct there.
    """
    from aspose_tex._engine.interpreter import ModeKind

    if interpreter._current_box_frame() is not None:
        return False
    return interpreter._mode_stack.current is ModeKind.MATH_DISPLAY


def _contribute_rows_to_vlist(
    interpreter: TeXInterpreter, state: _AlignmentState,
) -> None:
    """Contribute a ``\\halign``'s rows individually to the enclosing vlist.

    The TeX ``fin_align`` §812 model: the alignment's row boxes are
    appended to the *enclosing* vertical list one at a time, so the page
    builder's §679 ``_append_to_vlist`` spaces them
    (``\\baselineskip`` interline) and ``\\topskip``-positions the first row —
    NO pre-inserted interline glue on this path (that would
    double-count).  ``\\noalign`` material (rules / kerns / skips / penalties) is
    contributed verbatim between rows; a ``\\noalign`` rule resets the interline
    chain via ``_contribute`` (§679).  Used only when the result lands directly
    in a real vertical list (see :func:`exec_halign`).
    """
    for row in state.rows:
        if isinstance(row, _NoalignRecord):
            interpreter._splice_vertical_nodes(row.nodes)
            interpreter._set_prevdepth(row.prev_depth)
            continue
        interpreter._contribute(_emit_row(state, row))
        for cell in row:
            if cell.adjustments:
                interpreter._splice_vertical_nodes(cell.adjustments)
    interpreter._build_page_if_outer()  # §812 fin_align


def _emit_row(state: _AlignmentState, row: list) -> HlistNode:
    """Assemble one row hbox: tabskip, cell, tabskip, cell, ..., tabskip.

    When the alignment carried a ``to`` / ``spread`` width spec the finished row
    is set to that target ( Component 2), so the inter-column
    ``\\tabskip`` glue absorbs the difference — this is what makes
    ``\\eqalignno``'s ``\\centering`` tabskip push the equation number out to
    the right edge of ``\\displaywidth``.  Applied here, the single site both
    the packed (:func:`_emit_rows`) and spliced
    (:func:`_contribute_rows_to_vlist`) paths funnel through, so the two models
    cannot diverge.
    """
    ncols = _ncols(state)
    nodes: list = [GlueNode(_tabskip_for(state, 0))]
    reached = 0
    for cell in row:
        first = cell.col_index
        last = min(first + cell.span_count - 1, ncols - 1)
        target = sum(state.column_width[j] for j in range(first, last + 1))
        if cell.span_count > 1:
            target += sum(
                _glue_natural(_tabskip_for(state, j))
                for j in range(first + 1, last + 1)
            )
        set_glue_hbox(cell.box, target_width=target)
        nodes.append(cell.box)
        nodes.append(GlueNode(_tabskip_for(state, last + 1)))
        reached = last + 1
    # §803/§807: a short row takes the full alignment's extent and glue setting
    # from the prototype row, but its list ends at its last real cell's tabskip
    #. Missing columns are measured, then dropped, so
    # \lastbox and \unskip see the same tail as in TeX.
    real_tail = len(nodes)
    for j in range(reached, ncols):
        nodes.append(KernNode(width=state.column_width[j], explicit=False))
        nodes.append(GlueNode(_tabskip_for(state, j + 1)))
    box = _pack_hrow(nodes)
    target = _row_target_width(state, box.width)
    if target is not None:
        set_glue_hbox(box, target_width=target)
    del box.list[real_tail:]
    # §810: a cell takes the row's height and depth, so a running \vrule in a
    # cell spans the row and \lastbox reads the row's dimensions.
    for cell in row:
        cell.box.height = box.height
        cell.box.depth = box.depth
    return box


def _row_target_width(state: _AlignmentState, natural: int) -> int | None:
    """Resolve the row's target width from the ``to`` / ``spread`` spec.

    Args:
        state: The alignment state carrying the parsed spec.
        natural: The row's natural width in sp (the ``spread`` base).

    Returns:
        The target width in sp, or ``None`` when the alignment carried no spec
        and the row keeps its natural width.
    """
    if state.target_width is not None:
        return state.target_width
    if state.spread_width is not None:
        return natural + state.spread_width
    return None


def _emit_columns(state: _AlignmentState, font_manager) -> HlistNode:
    """Assemble the ``\\valign`` result: hlist of column vboxes (transpose).

    Each body "row" becomes one column vbox: its cells are repacked to the
    per-position aligned height (``column_width[col_index]``, which holds the
    vertical extent for ``\\valign``) and stacked.  The column vboxes are then
    placed side by side with ``\\tabskip`` glue between them — the horizontal
    mirror of the inter-column ``\\tabskip`` in ``\\halign``.  ``\\noalign``
    material is spliced between columns as raw horizontal nodes.
    """
    ncols = _ncols(state)
    nodes: list = []
    for row in state.rows:
        if isinstance(row, _NoalignRecord):
            # Splice raw material between columns (no \prevdepth in a \valign).
            nodes.extend(row.nodes)
            continue
        nodes.append(_emit_column(state, row, ncols))
    builder = HBoxBuilder(font_manager)
    builder._nodes = nodes
    return builder.build()


def _emit_column(state: _AlignmentState, row: list, ncols: int) -> VlistNode:
    """Stack one body row's cells into a column vbox, repacked to aligned height.

    The stacked cells are separated by vertical tabskip, with no interline glue.
    """
    cell_boxes: list = []
    reached = 0
    for cell in row:
        first = cell.col_index
        last = min(first + cell.span_count - 1, ncols - 1)
        target = sum(state.column_width[j] for j in range(first, last + 1))
        target += sum(_tabskip_for(state, j).width for j in range(first + 1, last + 1))
        set_glue_vbox(cell.box, target_height=target)
        cell_boxes.append(GlueNode(_tabskip_for(state, first)))
        cell_boxes.append(cell.box)
        reached = last + 1
    # The \halign rule of _emit_row: the list ends at the gap after the last
    # real cell; the rest only measures the column.
    real_tail = len(cell_boxes) + 1
    for j in range(reached, ncols):
        cell_boxes.append(GlueNode(_tabskip_for(state, j)))
        cell_boxes.append(KernNode(width=state.column_width[j], explicit=False))
    cell_boxes.append(GlueNode(_tabskip_for(state, ncols)))
    builder = VBoxBuilder(_NullFontManager())
    builder._nodes = cell_boxes
    target = state.target_width
    if state.spread_width is not None:
        box = builder.build(spread=state.spread_width)
    else:
        box = builder.build(target_height=target)
    del box.list[real_tail:]
    for cell in row:  # §810, the mirror of _emit_row: the column's width.
        cell.box.width = box.width
    return box


def _tabskip_for(state: _AlignmentState, idx: int) -> Glue:
    """Return the tabskip glue at gap index *idx* (0 = before first column).

    Gaps past the explicit list cycle through the repeating block's gaps when a
    repeating preamble (``&&``) is present, matching :func:`_template_for`.
    """
    if 0 <= idx < len(state.tabskip):
        return state.tabskip[idx]
    # Repeating preamble: cycle the gaps of the repeating block. tabskip has
    # len(templates)+1 entries; the repeating gaps start at repeat_from+1.
    if state.repeat_from >= 0:
        n = len(state.tabskip)  # == len(templates) + 1
        start = state.repeat_from + 1
        cycle = n - start
        if cycle > 0 and idx >= start:
            return state.tabskip[start + (idx - start) % cycle]
    return _ZERO_GLUE


def _pack_hrow(nodes: list) -> HlistNode:
    """Pack a finished row node list into a natural-width HlistNode."""
    builder = HBoxBuilder(_NullFontManager())
    builder._nodes = nodes
    return builder.build()


def _pack_vlist(nodes: list) -> VlistNode:
    """Pack the stacked rows + noalign material into a natural VlistNode."""
    builder = VBoxBuilder(_NullFontManager())
    builder._nodes = nodes
    return builder.build()


class _NullFontManager:
    """Measurement-only shim: alignment rows hold pre-built boxes/glue/rules."""

    _current = None

    def get_metrics(self, _font_name: str):  # pragma: no cover - defensive
        return None


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def exec_halign(interpreter: TeXInterpreter):
    """Execute ``\\halign[<spec>]{<preamble>\\cr<rows>}`` (§Algorithm).

    Builds a vlist of aligned row hboxes and adds it to the interpreter's
    current list.  Returns the vlist (useful when a box scanner drives the
    primitive directly).

    Raises:
        AlignmentError: on a malformed preamble or illegal alignment-token
            position.
    """
    state = _run_alignment(interpreter, vertical=False)
    #: a top-level \halign in a real vertical list splices its rows
    # individually so the page builder owns interline glue + \topskip (the
    # fin_align §812 model); a \halign consumed as a box (\setbox / \vbox /
    # \vcenter / RH / math) keeps the packed-with-glue vlist.
    if _contributes_to_vertical_list(interpreter):
        _contribute_rows_to_vlist(interpreter, state)
        return None
    # Component 4: a display whose body IS an alignment splices too, but
    # the rows must land INSIDE the \abovedisplayskip … \belowdisplayskip frame
    # that `_emit_display` builds — so hand them over rather than contributing
    # here.  See `_is_display_top_level_alignment` for why the predicate is
    # structural and why the \vcenter legs are unaffected.
    if _is_display_top_level_alignment(interpreter):
        interpreter._pending_display_alignment = _display_splice_nodes(state)
        return None
    result = _emit_rows(interpreter, state)
    interpreter._add_box_to_current_list(result)
    return result


def indent_display_rules(nodes: list, indent: int) -> list:
    r"""Box a display alignment's rules at ``\displayindent`` (§806).

    Rows take the indent as their shift; a rule has no shift of its own, so
    TeX packs it in an hbox.  Other ``\noalign`` material stays where it is.

    Args:
        nodes: The vertical nodes of one ``\noalign`` record, rules resolved.
        indent: The display's ``\displayindent`` in sp.

    Returns:
        *nodes*, with each rule boxed when *indent* is not zero.
    """
    if not indent:
        return nodes
    out: list = []
    for node in nodes:
        if isinstance(node, RuleNode):
            node = _pack_hrow([node])
            node.shift_amount = indent
        out.append(node)
    return out


def _display_splice_nodes(state: _AlignmentState) -> list:
    r"""Flatten a display alignment into the node sequence §812 contributes.

    Returns the rows and their ``\noalign`` material in source order — the
    ``material · row · material · … · row · material`` interleaving
    established — with **no** interline glue inserted: on the splice
    path the page builder owns interline spacing (§679), and pre-inserting it
    would double-count.

    Args:
        state: The finished alignment's collection state.

    Returns:
        A flat list of vertical-list nodes, ready for ``_emit_display`` to
        contribute one at a time between the display skips.  After a
        ``\noalign`` it holds the raw record, which ``_emit_display`` splices
        with its final logical depth.
    """
    nodes: list = []
    for row in state.rows:
        if isinstance(row, _NoalignRecord):
            nodes.append(row)
        else:
            box = _emit_row(state, row)
            nodes.append(box)
            # Migrated \vadjust material is not a row: raw, no indent, and the
            # next row's interline glue still sees this row's depth.
            adjustments = [n for cell in row for n in cell.adjustments]
            if adjustments:
                nodes.append(_NoalignRecord(adjustments, box.depth))
    return nodes


def exec_valign(interpreter: TeXInterpreter):
    """Execute ``\\valign[<spec>]{<preamble>\\cr<cols>}`` — vertical mirror.

    Builds an hlist of aligned column vboxes (the transpose of ``\\halign``)
    and adds it to the interpreter's current list.  Returns the hlist (useful
    when a box scanner drives the primitive directly).  See cascade b.

    Raises:
        AlignmentError: on a malformed preamble or illegal alignment-token
            position.
    """
    state = _run_alignment(interpreter, vertical=True)
    result = _emit_rows(interpreter, state)
    interpreter._add_box_to_current_list(result)
    return result


def _run_nested_alignment(
    interpreter: TeXInterpreter, *, vertical: bool,
) -> HlistNode | VlistNode:
    """Run a cell-nested ``\\halign`` / ``\\valign`` and return its box (Q6).

    Unlike :func:`exec_halign` / :func:`exec_valign`, the result is returned
    for the enclosing cell to add as a box node rather than contributed to the
    page list.
    """
    state = _run_alignment(interpreter, vertical=vertical)
    return _emit_rows(interpreter, state)


def _run_alignment(interpreter: TeXInterpreter, *, vertical: bool) -> _AlignmentState:
    """Open the alignment group, parse the preamble, and collect all rows."""
    expander = interpreter._expander

    # Optional ``to <dimen>`` / ``spread <dimen>`` ( Component 2) — the
    # parsed target is carried on the state and applied per row in _emit_row.
    target_width, spread_width = _scan_alignment_spec(interpreter)

    # Consume the opening brace.
    cs = "\\valign" if vertical else "\\halign"
    try:
        expander._scan_left_brace(cs)
    except EngineError as exc:
        raise AlignmentError(f"{cs}: expected {{ after preamble spec") from exc
    interpreter._group_stack.open_group(GroupKind.BRACE)

    state = _AlignmentState(
        templates=[],
        tabskip=[],
        rows=[],
        column_width=[],
        vertical=vertical,
        target_width=target_width,
        spread_width=spread_width,
    )
    _parse_preamble(interpreter, state)
    # C2/C3: a non-\vcenter math \halign (\bordermatrix eager
    # \setbox\vbox, or the display family) signals its cells are math cells via
    # a top-level `$` in the first column's u-template.  Raise the math-context
    # counter for the row collection so the cell-math shielding engages.
    # The \vcenter corpus already has the counter raised by build_math_vcenter_box
    # (this nests harmlessly); a text \halign leaves it at 0 → byte-identical.
    is_math = first_column_is_math(state)
    if is_math:
        interpreter._alignment_math_context += 1
    try:
        _collect_rows(interpreter, state)
    finally:
        if is_math:
            interpreter._alignment_math_context -= 1
    #: snapshot the interline-glue parameters WHILE the alignment group
    # is still open, so \openup\jot's in-group \advance\baselineskip\jot (the
    # \eqalign / display family) is visible — the group close below rolls it
    # back before pass 2 (_assemble_result) would otherwise read it.
    _capture_interline_params(interpreter, state)
    _measure_columns(state)
    if not vertical:
        # §800: diagnose the resolved preamble once, not each emitted row.
        from aspose_tex._engine.box_primitives import _warn_badness

        nodes = [GlueNode(_tabskip_for(state, 0))]
        for j in range(_ncols(state)):
            nodes.extend((KernNode(width=state.column_width[j], explicit=False),
                          GlueNode(_tabskip_for(state, j + 1))))
        box = _pack_hrow(nodes)
        target = _row_target_width(state, box.width)
        if target is not None:
            badness = set_glue_hbox(box, target_width=target)
            _warn_badness(box, badness, expander=expander,
                          font_manager=interpreter._font_manager, context=" in alignment")
        _resolve_running_rules(state, box)
    interpreter._group_stack.close_group()
    return state


def _resolve_running_rules(state: _AlignmentState, prototype: HlistNode) -> None:
    r"""Give the alignment's own rules the prototype row's dimensions (§806).

    ``fin_align`` walks the finished list, so this covers ``\noalign`` rules
    and ``\vadjust`` rules that migrated out of a cell, and no rule nested in
    a box.  Without it a running rule would take the enclosing box's width.
    """
    def resolve(nodes: list) -> None:
        for i, node in enumerate(nodes):
            if isinstance(node, RuleNode):
                nodes[i] = RuleNode(
                    width=prototype.width if node.width == RUNNING_DIMEN else node.width,
                    height=prototype.height if node.height == RUNNING_DIMEN else node.height,
                    depth=prototype.depth if node.depth == RUNNING_DIMEN else node.depth,
                )

    for row in state.rows:
        if isinstance(row, _NoalignRecord):
            resolve(row.nodes)
        else:
            for cell in row:
                resolve(cell.adjustments)


def _capture_interline_params(
    interpreter: TeXInterpreter, state: _AlignmentState,
) -> None:
    """Snapshot live ``\\baselineskip`` / ``\\lineskip`` / ``\\lineskiplimit``.

    Called inside the open alignment group ( Component 2) so any
    ``\\openup`` advance applied in the alignment body is captured before the
    group close reverts it.
    """
    expander = interpreter._expander
    baselineskip = _read_named_skip(expander, "baselineskip")
    lineskip = _read_named_skip(expander, "lineskip")
    if baselineskip is not None:
        state.baselineskip = baselineskip
    if lineskip is not None:
        state.lineskip = lineskip
    state.lineskiplimit = _read_named_dimen(expander, "lineskiplimit") or 0


def _scan_alignment_spec(interpreter: TeXInterpreter) -> tuple[int | None, int | None]:
    """Scan the optional ``to <dimen>`` / ``spread <dimen>`` before ``{``.

    Delegates to :func:`box_primitives._scan_box_keyword`, the project's single
    scanner for this TeX construct (``\\hbox``/``\\vbox``/``\\vtop``/leaders all
    use it) — the grammar is identical for ``\\halign``/``\\valign``, so there is
    one implementation rather than two that could drift apart.

    Runs before the :class:`_AlignmentState` exists, so the parsed dimension is
    *returned* for the caller to store rather than written directly (
    Component 2).  Before the alignment path parsed the dimension and
    threw it away, which silently packed every ``\\halign to <d>`` at its
    natural width.

    Args:
        interpreter: The interpreter whose token stream is being scanned.

    Returns:
        ``(target_width, spread_width)`` in sp; each is ``None`` when the
        corresponding keyword is absent.  At most one is ever non-``None``.
    """
    return _scan_box_keyword(interpreter._expander)
