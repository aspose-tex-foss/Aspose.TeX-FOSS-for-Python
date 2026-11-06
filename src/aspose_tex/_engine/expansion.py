"""TeX macro expansion engine.

Implements: macro definition (\\def/\\edef/\\gdef/\\xdef/\\let)
with ``\\long`` and ``\\outer`` prefixes (FR-1a/FR-1b;), expansion-time primitives
(\\expandafter/\\noexpand/\\csname), conditionals (\\if, \\ifx, \\ifnum, \\ifcat, \\iftrue,
\\iffalse, \\ifcase), token converters (\\the, \\number, \\string), and file inclusion
(\\input).

``\\long`` and ``\\outer`` may appear before any def command in any order and combination.
The flags are stored in :class:`~aspose_tex._engine.macro.MacroDefinition` but not yet
enforced (enforcement is deferred per spec).

Group handling note: ``{``/``}`` tokens and ``\\begingroup``/``\\endgroup``/
``\\aftergroup`` commands pass through to the interpreter for dispatch.  The Expander
retains ``\\global`` (prefix for ``\\def`` family) and ``\\currentgrouplevel`` (expands
to depth value).

See, and for design rationale.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable, Iterable, Iterator
from typing import TYPE_CHECKING, Protocol

from aspose_tex._engine.conditionals import _CondEntry, _ConditionalStack
from aspose_tex._engine.macro import (
    MacroDefinition,
    Meaning,
    PrimitiveMeaning,
    active_char_key,
)
from aspose_tex._input.catcode import Catcode, CatcodeTable
from aspose_tex._input.reader import FileInputSource, InputReader
from aspose_tex._input.token import CharToken, ControlSequenceToken, FontRefToken, PrimitiveRefToken, Token
from aspose_tex._input.tokenizer import Tokenizer
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
    from aspose_tex._engine.code_arrays import CodeArrays
    from aspose_tex._engine.group import GroupStack
    from aspose_tex._engine.interpreter import ModeKind
    from aspose_tex._engine.marks import MarksProvider
    from aspose_tex._engine.meanings import MeaningBindings
    from aspose_tex._engine.nodes import HlistNode, VlistNode

# ---------------------------------------------------------------------------
# Constants — sets of primitive names by category
# ---------------------------------------------------------------------------

_DEF_COMMANDS = frozenset({"def", "gdef", "edef", "xdef"})
_IF_COMMANDS = frozenset({
    "if", "ifx", "ifnum", "ifcat", "iftrue", "iffalse", "ifcase",
    "ifdim", "ifhmode", "ifvmode", "ifmmode", "ifvoid", "ifhbox",
    "ifvbox", "ifeof", "ifodd", "ifinner",
})
_MARKS_COMMANDS = frozenset({
    "firstmark", "topmark", "botmark", "splitfirstmark", "splitbotmark",
})

# Primitives that this expander executes inline but that are *commands* in TeX,
# not expandable: ``get_x_token`` hands them back to the caller unexecuted.
_COMMAND_PRIMITIVES = _DEF_COMMANDS | frozenset({
    "let", "futurelet", "afterassignment", "uppercase", "lowercase",
    "patterns", "hyphenation", "global", "long", "outer",
    "begingroup", "endgroup", "aftergroup",
})

# Primitives that expand (TeX §366/§367), plus ``\currentgrouplevel``, which
# this expander turns into digits: the targets a ``\let`` alias may carry and
# still be expandable.
_EXPANDABLE_PRIMITIVES = _IF_COMMANDS | _MARKS_COMMANDS | frozenset({
    "expandafter", "noexpand", "csname", "number", "string", "the", "meaning",
    "romannumeral", "jobname", "fontname", "input", "else", "fi", "or", "currentgrouplevel",
})

# Every name this expander handles itself, whatever the interpreter knows.
_EXPANDER_PRIMITIVES = _COMMAND_PRIMITIVES | _EXPANDABLE_PRIMITIVES | frozenset({
    "endcsname",
})

# The one meaning all undefined control sequences share (TeX §210
# ``undefined_cs``), as ``\ifx`` compares it.
_UNDEFINED = ("undefined",)

# What \meaning prints before a character of each category (§298).
_CHAR_MEANING = {
    Catcode.BEGIN_GROUP: "begin-group character ",
    Catcode.END_GROUP: "end-group character ",
    Catcode.MATH_SHIFT: "math shift character ",
    Catcode.ALIGNMENT: "alignment tab character ",
    Catcode.PARAMETER: "macro parameter character ",
    Catcode.SUPERSCRIPT: "superscript character ",
    Catcode.SUBSCRIPT: "subscript character ",
    Catcode.SPACE: "blank space ",
    Catcode.LETTER: "the letter ",
    Catcode.OTHER: "the character ",
}

_HEX_DIGITS = frozenset("0123456789ABCDEFabcdef")
_OCT_DIGITS = frozenset("01234567")
_DEC_DIGITS = frozenset("0123456789")


# ---------------------------------------------------------------------------
# RegisterProvider protocol
# ---------------------------------------------------------------------------

class RegisterProvider(Protocol):
    """Protocol for providing register values to the expansion engine.

    Implemented by the execution layer.
    """

    def get_tokens_for_the(self, token: Token, expander: Expander) -> list[Token]:
        """Return the token list representation of the register named by ``token``.

        ``expander`` is passed so the provider can read a register index from
        the token stream when the token names a register family (e.g. ``\\count``).

        Args:
            token:    The token immediately following ``\\the``.
            expander: The active expander (for reading additional tokens).

        Returns:
            A list of ``CharToken`` tokens representing the register value.

        Raises:
            EngineError: if the token does not name a readable register.
        """
        ...


class BoxProvider(Protocol):
    """Protocol for non-consuming box-register reads used by ``\\ifbox`` tests."""

    def peekbox(self, reg: int) -> HlistNode | VlistNode | None:
        """Return box register content without voiding it."""
        ...


# ---------------------------------------------------------------------------
# Expander
# ---------------------------------------------------------------------------

class Expander:
    """TeX macro expansion engine.

    Sits between the ``Tokenizer`` and the execution/typesetting layer.
    Expands all expandable tokens and processes definition commands; yields
    only unexpandable tokens to the caller.

    Internally maintains:

    - A token push-back stack (``_stack``) for ``\\expandafter``, parameter
      re-insertion, and ``\\noexpand`` suppression.
    - A flat macro table (``_macros``) mapping CS name → ``Meaning``.
    - A conditional stack (``_cond_stack``) for ``\\if..\\fi`` nesting.
    - An expansion depth counter to detect infinite recursion.

    Args:
        reader:            The ``InputReader`` instance (needed for ``\\input`` push).
        tokenizer:         The ``Tokenizer`` instance driven by ``reader``.
        catcodes:          The shared ``CatcodeTable`` (same instance as given to
                           ``Tokenizer``; ``\\catcode`` assignments mutate it).
        max_depth:         Maximum expansion recursion depth before ``EngineError``
                           is raised (default 100).
        register_provider: Optional provider for ``\\the`` (default None).

    Example::

        from aspose_tex._input import (
            StringInputSource, InputReader, CatcodeTable, Tokenizer
        )
        from aspose_tex._engine.expansion import Expander

        src      = StringInputSource(r'\\def\\hi{Hello}\\hi')
        reader   = InputReader(src)
        catcodes = CatcodeTable()
        tok      = Tokenizer(reader, catcodes)
        expander = Expander(reader, tok, catcodes)
        tokens   = list(expander)
        # [CharToken('H', LETTER), CharToken('e', LETTER), ...]
    """

    def __init__(
        self,
        reader: InputReader,
        tokenizer: Tokenizer,
        catcodes: CatcodeTable,
        max_depth: int = 100,
        register_provider: RegisterProvider | None = None,
        group_stack: GroupStack | None = None,
        input_resolver: Callable[[str], pathlib.Path] | None = None,
        mode_stack_provider: Callable[[], ModeKind] | None = None,
        box_provider: BoxProvider | None = None,
        job_name_provider: Callable[[], str] | None = None,
        code_arrays_provider: Callable[[], CodeArrays] | None = None,
        input_interceptor: Callable[[pathlib.Path], bool] | None = None,
    ) -> None:
        self._reader = reader
        self._tokenizer = tokenizer
        self._catcodes = catcodes
        self._max_depth = max_depth
        self._register_provider = register_provider
        self._group_stack = group_stack
        self._input_resolver = input_resolver
        # §2: True means the file's effect was applied, push nothing.
        self._input_interceptor = input_interceptor
        self._mode_stack_provider = mode_stack_provider
        self._box_provider = box_provider
        self._job_name_provider = job_name_provider
        self._code_arrays_provider = code_arrays_provider
        self._marks_provider: MarksProvider | None = None

        self._depth: int = 0
        self._stack: list[Token] = []           # LIFO push-back; _stack[-1] is next
        self._macros: dict[str, Meaning] = {}
        self._cond_stack: _ConditionalStack = _ConditionalStack()
        self._peeked: Token | None = None       # one-token peek cache
        self._edef_mode: bool = False
        self._the_output: list[Token] = []
        self._last_noexpand: bool = False
        self._operand_scan_depth: int = 0
        self._tokenizer_iter: Iterator[Token] = iter(self._tokenizer)
        self._long_pending: bool = False        # \\long prefix seen before \\def
        self._outer_pending: bool = False       # \\outer prefix seen before \\def
        self._after_assignment_token: Token | None = None
        # D2: one binding per name across macros, register aliases,
        # constants and fonts; wired by the interpreter.
        self._bindings: MeaningBindings | None = None

    def _release(self, name: str, *, is_global: bool) -> None:
        """Clear *name*'s non-macro bindings before a macro-table write ( D2)."""
        if self._bindings is not None:
            from aspose_tex._engine.meanings import BindingKind

            self._bindings.release(name, BindingKind.MACRO, is_global=is_global)

    # ------------------------------------------------------------------
    # Public token interface
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator[Token]:
        """Yield unexpandable tokens one at a time."""
        while True:
            # Only a token that becomes output keeps its alias (\edef, \message).
            tok = self._next_unexpandable(keep_aliases=self._edef_mode, command=True)
            if tok is None:
                return
            yield tok
            # scan_toks (§478) appends the complete \the result directly;
            # it is output, rather than input to the expansion loop.
            if self._the_output:
                output, self._the_output = self._the_output, []
                yield from output

    def peek(self) -> Token | None:
        """Return the next unexpandable token without consuming it.

        Returns ``None`` when the stream is exhausted.
        """
        if self._peeked is None:
            self._peeked = self._next_unexpandable()
        return self._peeked

    def peek_raw(self) -> Token | None:
        """Return the next *raw* (unexpanded) token without consuming it.

        Unlike :meth:`peek`, control sequences are NOT expanded or alias-
        resolved — ``\\bgroup`` is returned as its ``ControlSequenceToken``,
        not as the ``{`` it is ``\\let`` to.  Used by open-group box
        detection, which must distinguish a literal ``{`` (eager scan) from a
        ``\\bgroup`` alias (deferred-close open-group box).
        """
        if self._peeked is not None:
            return self._peeked
        tok = self._next_raw()
        if tok is not None:
            self._stack.append(tok)
        return tok

    def unpeek(self) -> None:
        """Move a cached :meth:`peek` token back onto the input push-back stack.

        :meth:`peek` parks its token in the one-slot ``_peeked`` cache, and
        :meth:`_next_raw` drains that cache *before* consulting ``_stack``.  A
        caller that peeks and then calls :meth:`push_tokens` would therefore be
        handed its pushed tokens *after* the peeked one — the stream order is
        inverted relative to what the code reads like.  Calling ``unpeek()``
        between the two restores written order, so the pushed tokens come first.

        The token is moved, not re-read: its already-resolved expansion state is
        preserved and the reader is not touched.  Calling this with nothing
        peeked is a no-op, so it is safe on any path.

        Example::

            expander.peek()                 # caches the next token
            expander.unpeek()               # park it back on the stack
            expander.push_tokens(template)  # template now arrives FIRST
        """
        if self._peeked is not None:
            self._stack.append(self._peeked)
            self._peeked = None

    def get_x_token(self) -> Token | None:
        r"""Return the next token after expansion, as TeX's ``get_x_token`` (§380).

        Macros, conditionals and the other expandable primitives are expanded
        until an unexpandable token arrives.  Unlike :meth:`peek` and
        iteration, the assignment commands this expander normally executes
        inline (``\def``, ``\let``, ``\global``, ...) are returned
        unexecuted, and a ``\let`` alias to an unexpandable token is returned
        as the alias itself, so a scanner that stops on it can push it back
        exactly as read.  Number, dimension and keyword scanners read with this
        (§440, §448, §407), so ``\def\x{5}\count1=\x`` scans 5.

        Returns ``None`` when the stream is exhausted.

        Example::

            expander.push_tokens(tokenize(r"\x5"))   # with \def\x{1}
            expander.get_x_token()                  # -> CharToken('1', OTHER)
            expander.get_x_token()                  # -> CharToken('5', OTHER)
        """
        return self._next_unexpandable(x_token=True)

    def push_tokens(self, tokens: list[Token]) -> None:
        """Push a list of tokens onto the front of the input stack.

        Tokens are pushed in reverse order so that ``tokens[0]`` is
        consumed first.

        Args:
            tokens: Tokens to push; first element will be yielded first.
        """
        for t in reversed(tokens):
            self._stack.append(t)

    # ------------------------------------------------------------------
    # Macro table access
    # ------------------------------------------------------------------

    @property
    def macros(self) -> dict[str, Meaning]:
        """The current macro/meaning table (CS name → Meaning)."""
        return self._macros

    def define(self, name: str, meaning: Meaning) -> None:
        """Store ``meaning`` under ``name`` in the macro table.

        Args:
            name:    Control sequence name (without leading backslash).
            meaning: A ``MacroDefinition`` or token alias.
        """
        self._macros[name] = meaning

    # ------------------------------------------------------------------
    # Private: raw token source
    # ------------------------------------------------------------------

    def _next_raw(self) -> Token | None:
        """Draw the next raw (unexpanded) token from stack or tokenizer."""
        if self._peeked is not None:
            tok = self._peeked
            self._peeked = None
            return tok
        if self._stack:
            return self._stack.pop()
        return next(self._tok_iter, None)

    @property
    def _tok_iter(self) -> Iterator[Token]:
        return self._tokenizer_iter

    # ------------------------------------------------------------------
    # Private: unexpandable dispatch
    # ------------------------------------------------------------------

    def _next_unexpandable(
        self, *, x_token: bool = False, keep_aliases: bool = False, expand_once: bool = False,
        command: bool = False,
    ) -> Token | None:
        """Return the next unexpandable token, expanding as needed.

        With ``x_token`` set, behave as :meth:`get_x_token`: stop at command
        primitives and at aliases of unexpandable tokens instead of executing
        or resolving them.  With ``keep_aliases`` set, return an alias of an
        unexpandable meaning as the alias, as full expansion stores it (§478);
        reads that look at the meaning (``\\if`` operands, ``\\csname``,
        number scanners) leave it unset.

        ``expand_once`` leaves an expansion's replacement on the input stack
        and returns ``None``; an unexpandable input token is returned normally.
        This is the single step required by ``\\expandafter`` (§368).
        """
        expanded = False
        while True:
            if expand_once and expanded:
                return None
            self._last_noexpand = False
            tok = self._next_raw()
            if tok is None:
                return None
            if self._operand_scan_depth and self._ifx_meaning(tok) == _UNDEFINED:
                self._undefined_operand_error(tok)

            # CharTokens: pass through to caller (See)
            # Group open/close ({/}) now handled by interpreter, not expander.
            # An active character is expanded like a control sequence (TeX
            # §358,); an undefined one goes to the interpreter, which
            # reports it.
            if isinstance(tok, CharToken):
                if tok.catcode != Catcode.ACTIVE:
                    return tok
                key = active_char_key(tok.char)
                meaning = self._macros.get(key)
                if meaning is None:
                    if (not (x_token or keep_aliases) and self._bindings is not None
                            and self._bindings.binding_of(key) is not None):
                        self._stack.append(ControlSequenceToken(key))
                        continue
                    return tok
                if isinstance(meaning, MacroDefinition):
                    self._expand_macro(tok.char, meaning)
                    expanded = True
                    continue
                if isinstance(meaning, PrimitiveMeaning):
                    if (x_token or keep_aliases) and meaning.name not in _EXPANDABLE_PRIMITIVES:
                        return tok
                    self._stack.append(PrimitiveRefToken(meaning.name))
                    continue
                if x_token or keep_aliases:
                    target = self._expandable_alias_target(key, meaning)
                    if target is None:
                        return tok
                    self._stack.append(target)
                    continue
                self._stack.append(meaning)  # type: ignore[arg-type]
                continue

            if isinstance(tok, FontRefToken):
                return tok

            # ControlSequenceToken: look up in dispatch table
            name = tok.name
            # D3: a \let alias of a primitive is that primitive, and a
            # PrimitiveRefToken is never looked up in the macro table again.
            frozen = isinstance(tok, PrimitiveRefToken)
            if not frozen:
                meaning = self._macros.get(name)
                if isinstance(meaning, PrimitiveMeaning):
                    # get_x_token and full expansion keep an alias of an
                    # unexpandable primitive as the alias (, §478)
                    if (x_token or keep_aliases) and meaning.name not in _EXPANDABLE_PRIMITIVES:
                        return tok
                    tok = PrimitiveRefToken(meaning.name)
                    name = tok.name
                    frozen = True

            if x_token and frozen:
                if name in _COMMAND_PRIMITIVES:
                    return tok
            elif x_token:
                meaning = self._macros.get(name)
                if meaning is not None and not isinstance(meaning, MacroDefinition):
                    target = self._expandable_alias_target(name, meaning)
                    if target is None:
                        return tok
                    self._stack.append(target)
                    continue
                if meaning is None and name in _COMMAND_PRIMITIVES:
                    return tok

            # 0. Stale prefix-flag guard (See FR-1a)
            # In TeX, \long/\outer before a non-def command is an error.
            # We clear the flags so they do not bleed into a subsequent \def.
            _is_prefix = name in ("long", "outer")
            if (
                not x_token
                and (self._long_pending or self._outer_pending)
                and name not in _DEF_COMMANDS
                and not _is_prefix
            ):
                self._long_pending = False
                self._outer_pending = False

            # 1. User-defined macro
            meaning = None if frozen else self._macros.get(name)
            if isinstance(meaning, MacroDefinition):
                self._expand_macro(name, meaning)
                expanded = True
                continue

            # 2. \let alias to a token
            if meaning is not None:
                # C1: a \let alias whose meaning is a CS of the SAME name
                # is a fixed point that resolves to a primitive of that name —
                # return it as unexpandable instead of re-looping.  TeX's \let
                # copies the *equivalent* (the primitive command code), so
                # `\let\endline=\cr` makes \endline ≡ primitive \cr, and a later
                # `\global\let\cr\endline` makes \cr ≡ that same primitive.  We
                # store \let aliases as by-name tokens, so without this guard the
                # pair forms a `\cr→\cr` self-cycle that spins _next_unexpandable
                # forever (plain.tex \bordermatrix).  A distinct primitive alias
                # (`\let\x\cr`) has meaning.name != name → falls through unchanged.
                if (
                    isinstance(meaning, ControlSequenceToken)
                    and meaning.name == name
                ):
                    return tok
                # Full expansion (\edef, \message, \write) keeps an alias of an
                # unexpandable meaning as the alias itself (§478): a name
                # \csname made \relax stays that name, \bgroup stays \bgroup.
                if keep_aliases:
                    target = self._expandable_alias_target(name, meaning)
                    if target is None:
                        return tok
                    self._stack.append(target)
                    continue
                # Push the aliased token back for re-processing
                self._stack.append(meaning)  # type: ignore[arg-type]
                continue

            #: a live non-macro owner is unexpandable even when
            # its name is also an expandable built-in. Frozen primitive aliases
            # have already resolved their meaning and bypass live bindings.
            if not frozen and self._bindings is not None:
                from aspose_tex._engine.meanings import BindingKind
                binding = self._bindings.binding_of(name)
                if binding is not None and binding.kind is not BindingKind.MACRO:
                    return tok

            expanded = name in _EXPANDABLE_PRIMITIVES

            # 3. Definition commands (non-expandable in \edef)
            if name in _DEF_COMMANDS:
                if self._edef_mode:
                    return tok  # pass through in edef mode
                self._exec_def(name)
                continue

            if name == "let":
                if self._edef_mode:
                    return tok
                self._exec_let()
                continue

            # 4. Expansion primitives
            if name == "expandafter":
                self._exec_expandafter()
                continue

            if name == "noexpand":
                raw = self._next_raw()
                if raw is None:
                    return None
                self._last_noexpand = True
                return raw  # yield as-is without expanding

            if name == "csname":
                result = self._exec_csname()
                self._stack.append(result)
                continue

            # 5. Conditionals
            if name in _IF_COMMANDS:
                self._exec_if(name)
                continue

            if name in _MARKS_COMMANDS:
                if self._marks_provider is not None:
                    self.push_tokens(list(self._marks_provider.get_marks_tokens(name)))
                continue

            if name in ("fi", "else", "or"):
                current = self._cond_stack.current()
                if current is not None and current.scanning:
                    # TeX §510: finish the operand scan before reconsidering
                    # this terminator; keep its frozen primitive meaning.
                    self._stack.append(PrimitiveRefToken(name))
                    return PrimitiveRefToken("relax")

            if name == "else":
                self._exec_else()
                continue

            if name == "fi":
                self._exec_fi()
                continue

            if name == "or":
                self._exec_or()
                continue

            if name == "fontname":
                from aspose_tex._fonts.font_manager import scan_font_id
                key = scan_font_id(self)
                self.push_tokens(_text_to_tokens(self._interpreter._font_manager.font_name_text(key)))
                continue

            # 6. Token converters
            if name == "number":
                self._exec_number()
                continue

            if name == "string":
                self._exec_string()
                continue

            if name == "the":
                if self._edef_mode and keep_aliases:
                    output = self.the_tokens()
                    if not output:
                        continue
                    self._the_output = output[1:]
                    return output[0]
                self._exec_the()
                continue

            if name == "futurelet":
                self._exec_futurelet()
                continue

            if name == "afterassignment":
                self._exec_afterassignment()
                continue

            if name == "meaning":
                self._exec_meaning()
                continue

            if name == "romannumeral":
                self._exec_romannumeral()
                continue

            if name == "jobname":
                self._exec_jobname()
                continue

            if name == "uppercase":
                self._exec_change_case(upper=True)
                continue

            if name == "lowercase":
                self._exec_change_case(upper=False)
                continue

            # §2: the interpreter owns the stores; a bare expander
            # keeps the balanced discard.
            if name in ("patterns", "hyphenation"):
                self._exec_hyph_data(name)
                continue

            # 7. \input
            if name == "input":
                # §2: only an \input reached while fetching the next
                # command (``command``), never inside an operand scan, may be
                # intercepted; the scan's assignment would otherwise follow it.
                self._exec_input(intercept=command and not self._edef_mode)
                continue

            # 8. Group primitives — \begingroup/\endgroup/\aftergroup now
            # handled by interpreter (See).  Only \global and
            # \currentgrouplevel remain in Expander.
            if name in ("begingroup", "endgroup", "aftergroup"):
                return tok  # pass through to interpreter

            if name == "global":
                self._exec_global()
                continue

            if name == "currentgrouplevel":
                self._exec_currentgrouplevel()
                continue

            # 9. Definition prefixes ( FR-1a / FR-1b) — See
            if name == "long":
                self._long_pending = True
                continue

            if name == "outer":
                self._outer_pending = True
                continue

            # 10. Unknown — yield as-is
            return tok

    def _expandable_alias_target(self, name: str, meaning: Meaning) -> Token | None:
        r"""Return the token a ``\let`` alias stands for if it is expandable.

        Follows chains of control-sequence aliases.  Returns ``None`` when the
        chain ends at a character, a command primitive, an unknown control
        sequence, or loops back on itself (``\let\cr\endline`` after
        ``\let\endline\cr``,).
        """
        seen = {name}
        while isinstance(meaning, ControlSequenceToken | PrimitiveMeaning):
            if isinstance(meaning, PrimitiveMeaning):  # D3
                return (PrimitiveRefToken(meaning.name)
                        if meaning.name in _EXPANDABLE_PRIMITIVES else None)
            target = self._macros.get(meaning.name)
            if isinstance(target, MacroDefinition):
                return meaning
            if target is None:
                return meaning if meaning.name in _EXPANDABLE_PRIMITIVES else None
            if meaning.name in seen:
                return None
            seen.add(meaning.name)
            meaning = target
        return None

    # ------------------------------------------------------------------
    # Macro expansion
    # ------------------------------------------------------------------

    def _expand_macro(self, name: str, macro: MacroDefinition) -> None:
        """Scan arguments and push replacement tokens onto the stack.

        Uses a non-decrementing step counter to detect infinite loops (e.g.
        \\def\\loop{\\loop}\\loop).  See.
        """
        self._depth += 1
        if self._depth > self._max_depth:
            raise EngineError(
                f"Expansion depth limit {self._max_depth} exceeded"
                f" while expanding \\{name}"
            )
        args = self._scan_args(macro.param_pattern)
        replacement: list[Token] = []
        for item in macro.replacement:
            if isinstance(item, int):
                replacement.extend(args.get(item, []))
            else:
                replacement.append(item)
        self.push_tokens(replacement)

    def _scan_args(self, param_pattern: tuple) -> dict[int, list[Token]]:
        """Scan macro arguments from the input per TeXbook Chapter 20.

        Delimiter tokens that appear BEFORE the first ``#``-parameter (or in a
        pattern with no parameters at all, like ``\\if@if{}``) must be
        consumed-and-matched literally from the input stream. See
        for the original bug where leading delimiters were silently skipped.
        """
        args: dict[int, list[Token]] = {}
        i = 0
        while i < len(param_pattern):
            item = param_pattern[i]
            if isinstance(item, int):
                param_num = item
                delimiters: list[Token] = []
                j = i + 1
                while j < len(param_pattern) and not isinstance(param_pattern[j], int):
                    delimiters.append(param_pattern[j])  # type: ignore[arg-type]
                    j += 1
                if delimiters:
                    args[param_num] = self._scan_delimited_arg(delimiters)
                    i = j  # skip past delimiters in pattern
                else:
                    args[param_num] = self._scan_undelimited_arg()
                    i += 1
            else:
                # Leading-delimiter run before any #-parameter (or in a no-#
                # pattern). Consume the entire run from input and match each
                # token exactly. Mismatch is an "Use of \cs doesn't match its
                # definition" error per TeXbook §200.
                run: list[Token] = []
                j = i
                while j < len(param_pattern) and not isinstance(param_pattern[j], int):
                    run.append(param_pattern[j])  # type: ignore[arg-type]
                    j += 1
                self._match_leading_delimiters(run)
                i = j
        return args

    def _match_leading_delimiters(self, expected: list[Token]) -> None:
        """Consume ``expected`` tokens from input, raising on mismatch."""
        for want in expected:
            got = self._next_raw()
            if got is None or not _tokens_match([got], [want]):
                raise EngineError(
                    "Use of macro doesn't match its definition "
                    f"(expected {want!r}, got {got!r})"
                )

    def _scan_undelimited_arg(self) -> list[Token]:
        """Scan one undelimited argument (single token or balanced group)."""
        # Skip implicit spaces per TeXbook §203
        tok = self._next_raw()
        while tok is not None and isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
            tok = self._next_raw()
        if tok is None:
            return []
        if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
            return self._scan_balanced_group()
        return [tok]

    def _scan_left_brace(self, command: str) -> None:
        r"""Consume a left brace, skipping expanded blanks and relax (§403).

        Read meanings without executing assignments; an alias of ``\relax``
        remains relax even if its source name has since been redefined.
        """
        while True:
            tok = self.get_x_token()
            meaning = self._let_meaning(tok) if tok is not None else None
            if isinstance(meaning, PrimitiveMeaning) and meaning.name == "relax":
                continue
            if isinstance(meaning, CharToken):
                if meaning.catcode == Catcode.SPACE:
                    continue
                if meaning.catcode == Catcode.BEGIN_GROUP:
                    return
            raise EngineError(f"Expected '{{' to open {command}, got {tok!r}")

    def _scan_balanced_group(self) -> list[Token]:
        """Read tokens until the matching END_GROUP, return inner tokens (not including braces)."""
        tokens: list[Token] = []
        depth = 0
        while True:
            tok = self._next_raw()
            if tok is None:
                raise EngineError("Unexpected end of input inside group")
            if isinstance(tok, CharToken):
                if tok.catcode == Catcode.BEGIN_GROUP:
                    depth += 1
                    tokens.append(tok)
                elif tok.catcode == Catcode.END_GROUP:
                    if depth == 0:
                        return tokens
                    depth -= 1
                    tokens.append(tok)
                else:
                    tokens.append(tok)
            else:
                tokens.append(tok)

    def _scan_delimited_arg(self, delimiters: list[Token]) -> list[Token]:
        """Scan tokens until the delimiter sequence at brace depth 0."""
        buf: list[Token] = []
        depth = 0
        dlen = len(delimiters)
        while True:
            tok = self._next_raw()
            if tok is None:
                raise EngineError("Runaway argument — unexpected end of input")
            if isinstance(tok, CharToken):
                if tok.catcode == Catcode.BEGIN_GROUP:
                    depth += 1
                elif tok.catcode == Catcode.END_GROUP:
                    depth -= 1
            if depth == 0:
                buf.append(tok)
                # Check if buf ends with the delimiter sequence
                if len(buf) >= dlen and _tokens_match(buf[-dlen:], delimiters):
                    return buf[:-dlen]
            else:
                buf.append(tok)
        # unreachable

    # ------------------------------------------------------------------
    # Definition commands
    # ------------------------------------------------------------------

    def _exec_def(self, cmd: str) -> None:
        """Execute \\def, \\gdef, \\edef, or \\xdef."""
        is_edef = cmd in ("edef", "xdef")
        # Read the control sequence name
        name_tok = self._next_raw()
        if not isinstance(name_tok, ControlSequenceToken) and not (
            isinstance(name_tok, CharToken) and name_tok.catcode == Catcode.ACTIVE
        ):
            raise EngineError(
                f"\\{cmd}: control sequence or active character expected,"
                f" got {name_tok!r}"
            )
        cs_name = (
            name_tok.name
            if isinstance(name_tok, ControlSequenceToken)
            else active_char_key(name_tok.char)
        )
        # Scan parameter text
        param_pattern = self._scan_param_pattern()
        # Scan replacement text (raw balanced group)
        raw_replacement = self._scan_balanced_group()
        if is_edef:
            replacement = tuple(self._expand_fully(raw_replacement))
        else:
            replacement = tuple(self._decode_replacement(raw_replacement))

        # Determine if this definition is global (See)
        is_global_cmd = cmd in ("gdef", "xdef")
        is_global = (is_global_cmd if self._group_stack is None else
                     self._group_stack.assignment_is_global(command_global=is_global_cmd))

        self._release(cs_name, is_global=is_global)
        # Save old meaning before overwriting, unless global
        if self._group_stack is not None and not is_global:
            old = self._macros.get(cs_name)
            gs = self._group_stack
            _name = cs_name  # capture for closure
            if old is None:
                gs.save(("macro", _name), lambda: self._macros.pop(_name, None))
            else:
                gs.save(("macro", _name), lambda: self._macros.__setitem__(_name, old))
        elif self._group_stack is not None:
            self._group_stack.retain_global(("macro", cs_name))

        # Consume \global flag whenever _global_pending is set — regardless of
        # whether globality also comes from the command itself (gdef/xdef).
        # Without this, \global\gdef leaves the flag set and corrupts the next
        # assignment.  See.
        if self._group_stack is not None and self._group_stack._global_pending:
            self._group_stack.consume_global()

        # Consume \long / \outer prefix flags ( FR-1a / FR-1b)
        long = self._long_pending
        outer = self._outer_pending
        self._long_pending = False
        self._outer_pending = False

        self.define(cs_name, MacroDefinition(param_pattern, replacement, long=long, outer=outer))
        self.fire_after_assignment()

    def _scan_param_pattern(self) -> tuple:
        """Read tokens until BEGIN_GROUP, building param_pattern tuple."""
        pattern: list = []
        while True:
            tok = self._next_raw()
            if tok is None:
                raise EngineError("Unexpected end of input scanning parameter text")
            if isinstance(tok, CharToken):
                if tok.catcode == Catcode.BEGIN_GROUP:
                    # Done — the { was already consumed
                    return tuple(pattern)
                if tok.catcode == Catcode.PARAMETER:
                    # Next must be a digit 1-9
                    next_tok = self._next_raw()
                    if (
                        isinstance(next_tok, CharToken)
                        and next_tok.catcode == Catcode.OTHER
                        and next_tok.char in "123456789"
                    ):
                        n = int(next_tok.char)
                        pattern.append(n)
                    elif (
                        isinstance(next_tok, CharToken)
                        and next_tok.catcode == Catcode.PARAMETER
                    ):
                        # ## in param text → literal # in replacement
                        pattern.append(CharToken("#", Catcode.PARAMETER))
                    else:
                        raise EngineError(
                            "Parameter character # must be followed by a digit 1-9 or #"
                        )
                else:
                    pattern.append(tok)
            else:
                pattern.append(tok)

    def _decode_replacement(self, tokens: list[Token]) -> list:
        """Convert raw replacement token list: replace #n with int n."""
        result: list = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if isinstance(tok, CharToken) and tok.catcode == Catcode.PARAMETER:
                i += 1
                if i >= len(tokens):
                    raise EngineError(
                        "Parameter character # must be followed by a digit 1-9 or #"
                    )
                next_tok = tokens[i]
                if (
                    isinstance(next_tok, CharToken)
                    and next_tok.catcode == Catcode.OTHER
                    and next_tok.char in "123456789"
                ):
                    result.append(int(next_tok.char))
                elif (
                    isinstance(next_tok, CharToken)
                    and next_tok.catcode == Catcode.PARAMETER
                ):
                    result.append(tok)  # ## → literal #
                else:
                    raise EngineError(
                        "Parameter character # must be followed by a digit 1-9 or #"
                    )
            else:
                result.append(tok)
            i += 1
        return result

    def _expand_fully(self, tokens: list[Token]) -> list[Token]:
        """Fully expand a token list (used by \\edef/\\xdef).

        Creates a sub-expander in edef mode that shares the macro table.
        """
        from aspose_tex._input import StringInputSource  # local import to avoid cycle

        # We need a dummy reader/tokenizer because the sub-expander needs
        # the constructor signature, but we'll push tokens directly onto the stack.
        dummy_src = StringInputSource("")
        dummy_reader = InputReader(dummy_src)
        dummy_catcodes = self._catcodes
        dummy_tok = Tokenizer(dummy_reader, dummy_catcodes)

        sub = Expander(
            dummy_reader,
            dummy_tok,
            dummy_catcodes,
            max_depth=self._max_depth,
            register_provider=self._register_provider,
            group_stack=self._group_stack,
            input_resolver=self._input_resolver,
            mode_stack_provider=self._mode_stack_provider,
            box_provider=self._box_provider,
            job_name_provider=self._job_name_provider,
            code_arrays_provider=self._code_arrays_provider,
        )
        sub._macros = self._macros  # share macro table
        sub._edef_mode = True
        sub._register_set = getattr(self, "_register_set", None)
        sub._named_params = getattr(self, "_named_params", None)
        sub._interpreter = getattr(self, "_interpreter", None)
        sub._marks_provider = self._marks_provider
        sub._bindings = self._bindings
        sub.push_tokens(tokens)
        return list(sub)

    def _exec_let(self) -> None:
        """Execute \\let\\a=\\b."""
        # Read the target name
        name_tok = self._next_raw()
        if not isinstance(name_tok, ControlSequenceToken) and not (
            isinstance(name_tok, CharToken) and name_tok.catcode == Catcode.ACTIVE
        ):
            raise EngineError(
                f"\\let: control sequence or active character expected,"
                f" got {name_tok!r}"
            )
        a_name = (
            name_tok.name
            if isinstance(name_tok, ControlSequenceToken)
            else active_char_key(name_tok.char)
        )
        # Skip optional spaces and optional =.  TeX tests cur_cmd = spacer
        # (§1221), so a token \let to a space is skipped like a typed one.
        tok = self._next_raw()
        while self._is_space_token(tok):
            tok = self._next_raw()
        if isinstance(tok, CharToken) and tok.char == "=" and tok.catcode == Catcode.OTHER:
            tok = self._next_raw()
            # Skip one optional space after =
            if self._is_space_token(tok):
                tok = self._next_raw()

        if tok is None:
            return
        self._assign_let(name_tok, a_name, tok)

    def _is_space_token(self, tok: Token | None) -> bool:
        """Return whether *tok* means a blank space (``cur_cmd = spacer``)."""
        if tok is None:
            return False
        if isinstance(tok, CharToken) and tok.catcode != Catcode.ACTIVE:
            return tok.catcode == Catcode.SPACE
        meaning = self._ifx_meaning(tok)
        return isinstance(meaning, tuple) and meaning[0] == "char" and meaning[2] == Catcode.SPACE

    def _assign_let(self, name_tok: Token, a_name: str, tok: Token) -> None:
        r"""Give *a_name* the current meaning of *tok*, as ``\let``/``\futurelet`` (§1221).

        The assignment is local unless ``\global`` is pending, and fires a
        pending ``\afterassignment`` token.
        """
        # An active character's current meaning is copied, as for a control
        # sequence (TeX §1221,); an undefined one is kept as the token.
        is_global = self._group_stack is None or self._group_stack.is_global_pending
        source_name = (tok.name if isinstance(tok, ControlSequenceToken)
                       else active_char_key(tok.char) if tok.catcode == Catcode.ACTIVE else None)
        if (source_name is not None and not isinstance(tok, PrimitiveRefToken)
                and source_name not in self._macros and self._bindings is not None
                and self._bindings.copy_binding(a_name, source_name, is_global=is_global)):
            # A register, constant or font binding is copied into its own
            # owner ( D2), including active-character keys.
            self.fire_after_assignment()
            return
        meaning = self._let_meaning(tok)

        self._release(a_name, is_global=is_global)
        # Save old meaning before \let assignment, unless global (See)
        if self._group_stack is not None and not self._group_stack.is_global_pending:
            old = self._macros.get(a_name)
            gs = self._group_stack
            _lname = a_name  # capture for closure
            if old is None:
                gs.save(("macro", _lname), lambda: self._macros.pop(_lname, None))
            else:
                gs.save(("macro", _lname), lambda: self._macros.__setitem__(_lname, old))
        elif self._group_stack is not None:
            self._group_stack.consume_global()
            self._group_stack.retain_global(("macro", a_name))

        self.define(a_name, meaning)
        if self._group_stack is not None:
            self._group_stack.consume_global()
        self.fire_after_assignment()

    def _let_meaning(self, tok: Token) -> Meaning:
        r"""Return the macro-table meaning ``\let`` copies from *tok* (§1221).

        A macro-table entry is copied as is; a built-in becomes
        :class:`PrimitiveMeaning` ( D3), so a later ``\def`` of that
        name does not reach the alias; an undefined name is kept as the token.
        """
        if isinstance(tok, PrimitiveRefToken):
            return PrimitiveMeaning(tok.name)
        if isinstance(tok, ControlSequenceToken):
            meaning = self._macros.get(tok.name)
            if meaning is not None:
                return meaning
            if tok.name in _EXPANDER_PRIMITIVES or (
                getattr(self, "_interpreter", None) is not None
                and self._is_primitive_name(tok.name)
            ):
                return PrimitiveMeaning(tok.name)
            return tok
        if tok.catcode == Catcode.ACTIVE:
            return self._macros.get(active_char_key(tok.char), tok)
        return tok

    # ------------------------------------------------------------------
    # Expansion primitives
    # ------------------------------------------------------------------

    def _exec_expandafter(self) -> None:
        """Execute \\expandafter: expand token after the next one first."""
        t1 = self._next_raw()
        if t1 is None:
            return
        t2 = self._next_raw()
        if t2 is None:
            if t1 is not None:
                self._stack.append(t1)
            return
        # Leave B's replacement unread until A is restored (§368). In
        # particular, a following noexpand can protect a macro replacement,
        # but cannot suppress an undefined expansion already attempted here.
        self._stack.append(t2)
        result_tok = self._next_unexpandable(x_token=True, expand_once=True)
        if result_tok is not None:
            self._stack.append(result_tok)
        self._stack.append(t1)

    def _exec_csname(self) -> ControlSequenceToken:
        """Execute \\csname...\\endcsname: collect chars, build CS name."""
        chars: list[str] = []
        while True:
            tok = self._next_unexpandable()
            if tok is None:
                raise EngineError("\\csname: missing \\endcsname")
            if isinstance(tok, ControlSequenceToken):
                if tok.name == "endcsname":
                    break
                raise EngineError(
                    f"\\csname: unexpected control sequence \\{self._diagnostic_cs_name(tok)} in csname"
                )
            chars.append(tok.char)
        name = "".join(chars)
        if self._cs_is_undefined(name):
            self._define_relax_locally(name)
        return ControlSequenceToken(name)

    def _define_relax_locally(self, name: str) -> None:
        r"""Give an undefined *name* the meaning ``\relax`` in the current group.

        TeX §372 does ``eq_define(cur_cs, relax, 256)``: a local definition
        that a pending ``\global`` does not reach, so the flag is left for the
        assignment it belongs to (``\global\expandafter\let\csname ...``).
        """
        if self._group_stack is not None:
            self._group_stack.save(("macro", name), lambda: self._macros.pop(name, None))
        self.define(name, PrimitiveMeaning("relax"))

    def _exec_futurelet(self) -> None:
        r"""Execute ``\futurelet\cs t1 t2`` using raw-token lookahead.

        A ``\let`` assignment of *t2*'s meaning (§1221): local unless
        ``\global``, and an ``\afterassignment`` token comes before *t1*.
        """
        cs_tok = self._next_raw()
        if not isinstance(cs_tok, ControlSequenceToken) and not (
            isinstance(cs_tok, CharToken) and cs_tok.catcode == Catcode.ACTIVE
        ):
            raise EngineError("\\futurelet expects a control sequence or active character")
        t1 = self._next_raw()
        t2 = self._next_raw()
        if t1 is None or t2 is None:
            raise EngineError("\\futurelet: missing lookahead token")
        a_name = (
            cs_tok.name
            if isinstance(cs_tok, ControlSequenceToken)
            else active_char_key(cs_tok.char)
        )
        self.push_tokens([t1, t2])
        self._assign_let(cs_tok, a_name, t2)

    def _exec_afterassignment(self) -> None:
        """Store the next raw token for insertion after the next assignment."""
        tok = self._next_raw()
        if tok is None:
            raise EngineError("\\afterassignment: missing token at end of input")
        self._after_assignment_token = tok

    def fire_after_assignment(self) -> None:
        """Insert and clear the pending ``\\afterassignment`` token, if any."""
        tok = self._after_assignment_token
        if tok is None:
            return
        self._after_assignment_token = None
        self.push_tokens([tok])

    def _exec_meaning(self) -> None:
        """Execute ``\\meaning <token>``."""
        tok = self._next_raw()
        if tok is None:
            return
        text = self._meaning_text(tok)
        self.push_tokens(_text_to_tokens(text))

    def _meaning_text(
        self, tok: Token, seen: frozenset[str] = frozenset(), *, show: bool = False
    ) -> str:
        r"""Return what ``\meaning`` prints for *tok* (TeX §296 ``print_meaning``).

        An active character is looked up like a control sequence, under its
        own key; a name without any meaning prints ``undefined``.
        With *show* set, a macro's text starts on a new line after
        ``macro:``, as ``\show`` writes it to the log (§296 ``print_ln``).
        """
        esc = self._escape_text()
        if isinstance(tok, CharToken):
            if tok.catcode != Catcode.ACTIVE:
                return _CHAR_MEANING.get(tok.catcode, "the character ") + tok.char
            key = active_char_key(tok.char)
            meaning = self._macros.get(key)
            if meaning is None:
                text = self._bindings.meaning_text(key) if self._bindings is not None else None
                return text if text is not None else "undefined"
        else:
            key = tok.name
            if isinstance(tok, FontRefToken):
                return "select font " + self._interpreter._font_manager.font_name_text(key)
            if isinstance(tok, PrimitiveRefToken):
                return esc + key
            meaning = self._macros.get(key)
            if meaning is None:
                text = self._bindings.meaning_text(key) if self._bindings is not None else None
                if text is not None:
                    return text
                return "undefined" if self._cs_is_undefined(key) else esc + key
        if isinstance(meaning, MacroDefinition):
            prefix = (esc + "long" if meaning.long else "") + (esc + "outer" if meaning.outer else "")
            kind = f"{prefix} macro:" if prefix else "macro:"
            params = self.token_list_text(meaning.param_pattern)
            body = self.token_list_text(meaning.replacement)
            return f"{kind}{chr(10) if show else ''}{params}->{body}"
        if isinstance(meaning, PrimitiveMeaning):  # D3
            return esc + meaning.name
        # A self-alias is the primitive of that name ( C1).
        if key in seen or (isinstance(meaning, ControlSequenceToken) and meaning.name == key):
            if isinstance(tok, ControlSequenceToken) and self._is_primitive_name(key):
                return esc + key
            return "undefined"
        if isinstance(meaning, ControlSequenceToken | CharToken):
            return self._meaning_text(meaning, seen | {key}, show=show)
        return str(meaning)

    def show_text(self, tok: Token) -> str:
        r"""Return the log text of ``\show`` for *tok* (TeX §1294).

        A control sequence or active character is named before ``=``; the
        meaning follows as :meth:`_meaning_text` gives it, and a period ends it.

        Example::

            # after \def\x{X}
            expander.show_text(ControlSequenceToken("x"))  # -> '> \\x=macro:\n->X.'
        """
        if isinstance(tok, ControlSequenceToken):
            esc = self._escape_text()
            name = (self._interpreter._font_manager.font_id_text(tok.name)
                    if isinstance(tok, FontRefToken) else tok.name)
            name = name if name else f"csname{esc}endcsname"
            prefix = f"{esc}{name}="
        elif tok.catcode == Catcode.ACTIVE:
            prefix = f"{tok.char}="
        else:
            prefix = ""
        return f"> {prefix}{self._meaning_text(tok, show=True)}."

    def token_list_text(self, tokens: Iterable[Token | int]) -> str:
        r"""Return the text TeX prints for a token list (§292 ``show_token_list``).

        A control word is followed by a space, as is a control symbol whose
        character is currently a letter (§262 ``print_cs``); the escape
        character is ``\escapechar``.  A macro parameter character is
        doubled, and a parameter number *n* in a macro body prints ``#n``.

        Args:
            tokens: Tokens, possibly with the parameter numbers of a macro's
                parameter text or body.

        Returns:
            The printed text.

        Example::

            expander.token_list_text([ControlSequenceToken("b"), CharToken("c", Catcode.LETTER)])
            # -> '\\b c'
        """
        esc = self._escape_text()
        parts: list[str] = []
        for tok in tokens:
            if isinstance(tok, int):
                parts.append(f"#{tok}")
            elif isinstance(tok, CharToken):
                parts.append(tok.char * 2 if tok.catcode == Catcode.PARAMETER else tok.char)
            elif isinstance(tok, FontRefToken):
                name = self._interpreter._font_manager.font_id_text(tok.name)
                # Font-id selectors always print a separator, even punctuation.
                # Ordinary CS and string converters retain their own rules.
                parts.append(esc + name + " ")
            elif not tok.name:
                parts.append(f"{esc}csname{esc}endcsname ")
            elif len(tok.name) == 1 and self._catcodes.get(tok.name) != Catcode.LETTER:
                parts.append(esc + tok.name)
            else:
                parts.append(f"{esc}{tok.name} ")
        return "".join(parts)

    def _escape_text(self) -> str:
        r"""Return the escape character TeX prints before a name (``\escapechar``)."""
        esc = self._read_escapechar()
        return chr(esc) if 0 <= esc <= 255 else ""

    def _diagnostic_cs_name(self, token: ControlSequenceToken) -> str:
        """Resolve a frozen selector before naming it in a scanner diagnostic."""
        if isinstance(token, FontRefToken):
            return self._interpreter._font_manager.font_id_text(token.name)
        return token.name

    def _exec_romannumeral(self) -> None:
        """Execute ``\\romannumeral n``."""
        from aspose_tex._engine.dimparser import parse_integer

        n = parse_integer(self)
        if n <= 0:
            return
        self.push_tokens([CharToken(c, Catcode.OTHER) for c in _to_roman(n)])

    def _exec_jobname(self) -> None:
        """Execute ``\\jobname``."""
        name = self._job_name_provider() if self._job_name_provider is not None else "texput"
        self.push_tokens(_text_to_tokens(name))

    def _exec_change_case(self, *, upper: bool) -> None:
        """Execute ``\\uppercase`` or ``\\lowercase``."""
        command = "uppercase" if upper else "lowercase"
        codes = self._code_arrays_provider() if self._code_arrays_provider is not None else None
        if codes is None:
            raise EngineError(f"\\{command}: code-array provider not available")
        try:
            self._scan_left_brace(f"\\{command}")
        except EngineError as exc:
            raise EngineError(f"\\{command} expects {{...}} balanced text") from exc
        converted: list[Token] = []
        for item in self._scan_balanced_group():
            if isinstance(item, CharToken):
                getter = codes.get_uccode if upper else codes.get_lccode
                code = getter(ord(item.char))
                converted.append(
                    CharToken(chr(code), item.catcode) if code != 0 else item
                )
            else:
                converted.append(item)
        self.push_tokens(converted)

    def _exec_hyph_data(self, name: str) -> None:
        r"""Execute ``\patterns`` / ``\hyphenation``; a ``\global`` prefix is ignored."""
        interpreter = getattr(self, "_interpreter", None)
        try:
            if interpreter is None:
                self._consume_balanced_text_discard(name)
                self.fire_after_assignment()
                return
            from aspose_tex._engine.hyph_primitives import exec_hyphenation, exec_patterns

            (exec_patterns if name == "patterns" else exec_hyphenation)(interpreter)
        finally:
            if self._group_stack is not None:
                self._group_stack.consume_global()

    def _consume_balanced_text_discard(self, command: str) -> None:
        try:
            self._scan_left_brace(f"\\{command}")
        except EngineError as exc:
            raise EngineError(f"\\{command} expects {{...}} balanced text") from exc
        self._scan_balanced_group()

    # ------------------------------------------------------------------
    # Conditional processing
    # ------------------------------------------------------------------

    def _exec_if(self, name: str) -> None:
        """Dispatch \\if* commands."""
        if name == "iftrue":
            self._cond_stack.push(_CondEntry("iftrue", True))
        elif name == "iffalse":
            self._cond_stack.push(_CondEntry("iffalse", False))
            self._skip_false_branch()
        elif name == "ifnum":
            self._exec_ifnum()
        elif name == "ifcat":
            self._exec_ifcat()
        elif name == "if":
            self._exec_if_char()
        elif name == "ifx":
            self._exec_ifx()
        elif name == "ifcase":
            self._exec_ifcase()
        elif name == "ifdim":
            self._exec_ifdim()
        elif name in ("ifhmode", "ifvmode", "ifmmode", "ifinner"):
            self._exec_ifmode(name)
        elif name in ("ifvoid", "ifhbox", "ifvbox"):
            self._exec_ifbox(name)
        elif name == "ifodd":
            self._exec_ifodd()
        elif name == "ifeof":
            self._exec_ifeof()
        else:
            raise EngineError(f"\\{name}: not a known \\if* primitive")

    def _exec_ifnum(self) -> None:
        """Execute \\ifnum n1 R n2."""
        from aspose_tex._engine.dimparser import parse_integer

        entry = _CondEntry("ifnum", False, scanning=True)
        self._cond_stack.push(entry)
        n1 = parse_integer(self)
        # Skip spaces, find relation
        rel_tok = self._next_raw()
        while isinstance(rel_tok, CharToken) and rel_tok.catcode == Catcode.SPACE:
            rel_tok = self._next_raw()
        if not isinstance(rel_tok, CharToken) or rel_tok.char not in "<=>":
            raise EngineError("\\ifnum: expected relation character < = >")
        rel = rel_tok.char
        n2 = parse_integer(self)
        if rel == "<":
            result = n1 < n2
        elif rel == "=":
            result = n1 == n2
        else:
            result = n1 > n2
        entry.true_branch = result
        entry.scanning = False
        if not result:
            self._skip_false_branch()

    def _exec_ifdim(self) -> None:
        """Execute \\ifdim d1 R d2."""
        from aspose_tex._engine.dimparser import parse_dimen

        entry = _CondEntry("ifdim", False, scanning=True)
        self._cond_stack.push(entry)
        d1 = parse_dimen(self)
        rel_tok = self._next_raw()
        while isinstance(rel_tok, CharToken) and rel_tok.catcode == Catcode.SPACE:
            rel_tok = self._next_raw()
        if not isinstance(rel_tok, CharToken) or rel_tok.char not in "<=>":
            raise EngineError("\\ifdim: expected relation character < = >")
        d2 = parse_dimen(self)
        result = (d1 < d2) if rel_tok.char == "<" else (d1 == d2) if rel_tok.char == "=" else (d1 > d2)
        entry.true_branch = result
        entry.scanning = False
        if not result:
            self._skip_false_branch()

    def _exec_ifmode(self, name: str) -> None:
        """Execute mode conditionals backed by the interpreter mode stack."""
        mode = self._mode_stack_provider() if self._mode_stack_provider is not None else None
        mode_name = getattr(mode, "name", "")
        result = False
        if name == "ifhmode":
            result = mode_name in {"HORIZONTAL", "RESTRICTED_HORIZONTAL"}
        elif name == "ifvmode":
            result = mode_name in {"OUTER_VERTICAL", "INTERNAL_VERTICAL"}
        elif name == "ifmmode":
            result = mode_name in {"MATH", "MATH_DISPLAY"}
        elif name == "ifinner":
            result = mode_name in {"RESTRICTED_HORIZONTAL", "INTERNAL_VERTICAL", "MATH"}
        self._cond_stack.push(_CondEntry(name, result))
        if not result:
            self._skip_false_branch()

    def _exec_ifbox(self, name: str) -> None:
        """Execute \\ifvoid<n> / \\ifhbox<n> / \\ifvbox<n>."""
        from aspose_tex._engine.dimparser import parse_integer
        from aspose_tex._engine.nodes import HlistNode, VlistNode

        if self._box_provider is None:
            raise EngineError(f"\\{name}: box provider not available")
        entry = _CondEntry(name, False, scanning=True)
        self._cond_stack.push(entry)
        idx = parse_integer(self, allow_negative=False)
        try:
            box = self._box_provider.peekbox(idx)
        except ValueError as exc:
            raise EngineError(f"box register index out of range: {idx}") from exc
        result = (
            box is None
            if name == "ifvoid"
            else isinstance(box, HlistNode)
            if name == "ifhbox"
            else isinstance(box, VlistNode)
        )
        entry.true_branch = result
        entry.scanning = False
        if not result:
            self._skip_false_branch()

    def _exec_ifodd(self) -> None:
        """Execute \\ifodd n."""
        from aspose_tex._engine.dimparser import parse_integer

        entry = _CondEntry("ifodd", False, scanning=True)
        self._cond_stack.push(entry)
        n = parse_integer(self)
        result = n % 2 != 0
        entry.true_branch = result
        entry.scanning = False
        if not result:
            self._skip_false_branch()

    def _exec_if_char(self) -> None:
        """Execute \\if T1 T2 (character code identity)."""
        entry = _CondEntry("if", False, scanning=True)
        self._cond_stack.push(entry)
        c1 = self._read_if_operand()[0]
        c2 = self._read_if_operand()[0]
        result = c1 == c2
        entry.true_branch = result
        entry.scanning = False
        if not result:
            self._skip_false_branch()

    def _exec_ifcat(self) -> None:
        """Execute \\ifcat T1 T2 (catcode identity)."""
        entry = _CondEntry("ifcat", False, scanning=True)
        self._cond_stack.push(entry)
        c1 = self._read_if_operand()[1]
        c2 = self._read_if_operand()[1]
        result = c1 == c2
        entry.true_branch = result
        entry.scanning = False
        if not result:
            self._skip_false_branch()

    def _read_if_operand(self) -> tuple[str | int, int]:
        """Read one comparison operand, including its recursive expansion reads."""
        self._operand_scan_depth += 1
        try:
            return self._if_operand(self._next_unexpandable())
        finally:
            self._operand_scan_depth -= 1

    def _undefined_operand_error(self, tok: Token) -> None:
        """Report an attempted undefined read using the interpreter's diagnostic."""
        name = tok.char if isinstance(tok, CharToken) else tok.name
        raise EngineError(
            f"Undefined control sequence \\{name} at {self._reader.current_location}"
        )

    def _if_operand(self, tok: Token | None) -> tuple[str | int, int]:
        r"""Return the (character code, category) ``\if``/``\ifcat`` compare (§506).

        A character, or a control sequence whose meaning is one (``\bgroup``),
        gives its own code and category; an active character that
        ``\noexpand`` left unexpanded gives its code and 13; every other token
        (``\relax`` and its aliases, macros, registers) gives code 256 and
        category 16, so any two of them are equal.
        """
        non_char = (256, 16)
        if tok is None:
            return non_char
        if not self._last_noexpand and self._ifx_meaning(tok) == _UNDEFINED:
            # The interpreter is fail-fast for undefined control sequences.
            # A token protected by noexpand was not read with expansion and
            # must instead retain TeX's non-character comparison code (§506).
            self._undefined_operand_error(tok)
        if isinstance(tok, CharToken) and tok.catcode == Catcode.ACTIVE:
            key = active_char_key(tok.char)
            meaning = self._macros.get(key)
            if (meaning is None and self._bindings is not None
                    and self._bindings.meaning_key(key) is not None):
                return non_char  # noexpand does not alter an unexpandable binding.
            if isinstance(meaning, CharToken) and meaning.catcode != Catcode.ACTIVE:
                return meaning.char, int(meaning.catcode)
            if isinstance(meaning, PrimitiveMeaning) and meaning.name not in _EXPANDABLE_PRIMITIVES:
                return non_char
            return tok.char, int(Catcode.ACTIVE)
        meaning = self._ifx_meaning(tok)
        if isinstance(meaning, tuple) and meaning[0] == "char":
            return meaning[1], int(meaning[2])
        return non_char

    def _exec_ifx(self) -> None:
        """Execute \\ifx T1 T2 (meaning identity, no expansion)."""
        entry = _CondEntry("ifx", False, scanning=True)
        self._cond_stack.push(entry)
        t1 = self._next_raw()
        t2 = self._next_raw()
        result = (
            t1 is not None
            and t2 is not None
            and self._ifx_meaning(t1) == self._ifx_meaning(t2)
        )
        entry.true_branch = result
        entry.scanning = False
        if not result:
            self._skip_false_branch()

    def _ifx_meaning(self, tok: Token) -> object:
        r"""Return a value two tokens share iff ``\ifx`` calls them equal.

        TeX compares the meanings (cmd, chr) of the two tokens, not the tokens
        (§507): a character stands for itself, while a control sequence stands
        for what it is bound to, so ``\let\next=a`` makes ``\ifx a\next``
        true.  ``\let`` aliases are stored by name and followed here to the
        macro, character or primitive they end at; every undefined control
        sequence shares one meaning (§210 ``undefined_cs``).
        """
        seen: set[str] = set()
        while True:
            if isinstance(tok, CharToken):
                if tok.catcode != Catcode.ACTIVE:
                    return ("char", tok.char, tok.catcode)
                # An active character is looked up like a control sequence.
                name = active_char_key(tok.char)
                meaning = self._macros.get(name)
                if meaning is None:
                    key = self._bindings.meaning_key(name) if self._bindings is not None else None
                    return key if key is not None else _UNDEFINED
            else:
                name = tok.name
                if isinstance(tok, FontRefToken):
                    return ("font", name)
                if isinstance(tok, PrimitiveRefToken):
                    return ("prim", name)
                meaning = self._macros.get(name)
                if meaning is None:
                    key = self._bindings.meaning_key(name) if self._bindings is not None else None
                    if key is not None:
                        return key
                    return _UNDEFINED if self._cs_is_undefined(name) else ("prim", name)
            if isinstance(meaning, MacroDefinition):
                return meaning
            if isinstance(meaning, PrimitiveMeaning):  # D3
                return ("prim", meaning.name)
            # A self-alias is the primitive of that name ( C1); an active
            # character \let to itself while undefined stays undefined.
            if name in seen or (
                isinstance(meaning, ControlSequenceToken) and meaning.name == name
            ):
                if isinstance(tok, ControlSequenceToken) and self._is_primitive_name(name):
                    return ("prim", name)
                return _UNDEFINED
            seen.add(name)
            tok = meaning

    def _cs_is_undefined(self, name: str) -> bool:
        r"""Return whether control sequence *name* has no meaning (TeX ``undefined_cs``).

        A name is defined when the macro table holds it, when this expander
        handles it, or when the interpreter recognises it
        (:meth:`TeXInterpreter.cs_has_meaning`).  A bare expander without an
        interpreter cannot tell a primitive from an undefined name and
        treats every name as defined.
        """
        return name not in self._macros and not self._is_primitive_name(name)

    def _is_primitive_name(self, name: str) -> bool:
        """Return whether *name* has a meaning outside the macro table.

        That is the primitive a self-alias stands for ( C1); a name
        ``\\let`` to itself while undefined has none.
        """
        if name in _EXPANDER_PRIMITIVES:
            return True
        interpreter = getattr(self, "_interpreter", None)
        return interpreter is None or interpreter.cs_has_meaning(name)

    def _exec_ifcase(self) -> None:
        """Execute \\ifcase n."""
        from aspose_tex._engine.dimparser import parse_integer

        entry = _CondEntry("ifcase", True, scanning=True)
        self._cond_stack.push(entry)
        n = parse_integer(self)
        entry.case_value = n
        entry.scanning = False
        if n != 0:
            self._skip_false_branch()

    def _exec_ifeof(self) -> None:
        """Execute \\ifeof<n> as always false in M3.

        Enforces the canonical TeX stream-number range 0..15 ( FR-11),
        matching :func:`aspose_tex._engine.io_primitives._read_stream_number`
        so that ``\\ifeof`` rejects the same out-of-range inputs as
        ``\\openin`` / ``\\openout`` / ``\\closein`` / ``\\closeout`` /
        ``\\read`` / ``\\write``.
        """
        from aspose_tex._engine.dimparser import parse_integer

        entry = _CondEntry("ifeof", False, scanning=True)
        self._cond_stack.push(entry)
        stream = parse_integer(self)
        if not 0 <= stream <= 15:
            raise EngineError(f"stream number out of range: {stream}")
        result = False
        entry.true_branch = result
        entry.scanning = False
        if not result:
            self._skip_false_branch()

    def _exec_else(self) -> None:
        """Execute \\else."""
        current = self._cond_stack.current()
        if current is None:
            raise EngineError("\\else without matching \\if")
        if current.in_else:
            raise EngineError("Extra \\else")
        current.in_else = True
        if current.true_branch:
            # We were in the true branch — skip the else branch
            self._skip_to_fi()
        # else: we were skipping (false branch active now) — just continue

    def _exec_fi(self) -> None:
        """Execute \\fi."""
        if self._cond_stack.depth() == 0:
            raise EngineError("\\fi without matching \\if")
        self._cond_stack.pop()

    def _exec_or(self) -> None:
        """Execute \\or (used by \\ifcase)."""
        current = self._cond_stack.current()
        if current is None or current.if_name != "ifcase":
            raise EngineError("Extra \\or")
        current.case_index += 1
        if current.case_index == current.case_value:
            # This is now the active branch — just continue processing
            pass
        else:
            # Skip to next \\or or \\fi
            self._skip_false_branch()

    def _conditional_role(self, tok: Token) -> str | None:
        r"""Return the conditional primitive *tok* currently means, else ``None``.

        Skipped branches are matched by meaning, as TeX's ``pass_text`` reads
        ``cur_cmd`` (§494): a ``\let`` or ``\newif`` alias of ``\iffalse``
        nests and ``\let\myfi=\fi`` ends the branch, while a macro whose
        name starts with ``if`` is not a conditional.  The token stays raw.
        See.
        """
        if isinstance(tok, CharToken) and tok.catcode != Catcode.ACTIVE:
            return None
        meaning = self._ifx_meaning(tok)
        if isinstance(meaning, tuple) and len(meaning) == 2 and meaning[0] == "prim":
            name = meaning[1]
            if name in _IF_COMMANDS or name in ("fi", "else", "or"):
                return name
        return None

    def _skip_false_branch(self) -> None:
        """Skip tokens until \\else, \\or (at depth 0), or \\fi (at depth 0).

        Handles nested \\if...\\fi pairs by counting nesting depth.
        Does NOT pop the current conditional entry.
        """
        depth = 0
        while True:
            tok = self._next_raw()
            if tok is None:
                raise EngineError("Unexpected end of input in conditional")
            name = self._conditional_role(tok)
            if name is None:
                continue
            if name in _IF_COMMANDS:
                depth += 1
            elif name == "fi":
                if depth == 0:
                    self._cond_stack.pop()
                    return
                depth -= 1
            elif name == "else" and depth == 0:
                current = self._cond_stack.current()
                if current is not None:
                    current.in_else = True
                return
            elif name == "or" and depth == 0:
                current = self._cond_stack.current()
                if current is not None and current.if_name == "ifcase":
                    current.case_index += 1
                    if current.case_index == current.case_value:
                        return  # This \or branch is active
                    # else keep skipping

    def _skip_to_fi(self) -> None:
        """Skip tokens until \\fi at depth 0. Used by \\else when true branch done."""
        depth = 0
        while True:
            tok = self._next_raw()
            if tok is None:
                raise EngineError("Unexpected end of input looking for \\fi")
            name = self._conditional_role(tok)
            if name is None:
                continue
            if name in _IF_COMMANDS:
                depth += 1
            elif name == "fi":
                if depth == 0:
                    self._cond_stack.pop()
                    return
                depth -= 1

    # ------------------------------------------------------------------
    # Integer scanning  (TeXbook §107)
    # ------------------------------------------------------------------

    def _scan_integer(self) -> int:
        """Scan an integer constant from the token stream."""
        # Skip leading spaces
        tok = self._next_raw()
        while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
            tok = self._next_raw()

        if tok is None:
            raise EngineError("Number expected")

        # Handle sign
        sign = 1
        while isinstance(tok, CharToken) and tok.catcode == Catcode.OTHER and tok.char in "+-":
            if tok.char == "-":
                sign = -sign
            tok = self._next_raw()
            while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
                tok = self._next_raw()

        if tok is None:
            raise EngineError("Number expected")

        if not isinstance(tok, CharToken) or tok.catcode != Catcode.OTHER:
            raise EngineError("Number expected")

        char = tok.char

        if char in _DEC_DIGITS:
            # Decimal
            digits = [char]
            while True:
                nxt = self._next_raw()
                if isinstance(nxt, CharToken) and nxt.char in _DEC_DIGITS and nxt.catcode == Catcode.OTHER:
                    digits.append(nxt.char)
                elif isinstance(nxt, CharToken) and nxt.catcode == Catcode.SPACE:
                    break  # skip one optional space
                else:
                    if nxt is not None:
                        self._stack.append(nxt)
                    break
            return sign * int("".join(digits))

        if char == "'":
            # Octal
            digits: list[str] = []
            while True:
                nxt = self._next_raw()
                if isinstance(nxt, CharToken) and nxt.char in _OCT_DIGITS and nxt.catcode == Catcode.OTHER:
                    digits.append(nxt.char)
                elif isinstance(nxt, CharToken) and nxt.catcode == Catcode.SPACE:
                    break
                else:
                    if nxt is not None:
                        self._stack.append(nxt)
                    break
            if not digits:
                raise EngineError("Number expected after '")
            return sign * int("".join(digits), 8)

        if char == '"':
            # Hexadecimal
            digits = []
            while True:
                nxt = self._next_raw()
                if (
                    isinstance(nxt, CharToken)
                    and nxt.catcode in (Catcode.OTHER, Catcode.LETTER)
                    and nxt.char in _HEX_DIGITS
                ):
                    digits.append(nxt.char)
                elif isinstance(nxt, CharToken) and nxt.catcode == Catcode.SPACE:
                    break
                else:
                    if nxt is not None:
                        self._stack.append(nxt)
                    break
            if not digits:
                raise EngineError("Number expected after \"")
            return sign * int("".join(digits), 16)

        if char == "`":
            # Character code
            nxt = self._next_raw()
            if nxt is None:
                raise EngineError("Number expected after `")
            if isinstance(nxt, CharToken):
                val = ord(nxt.char)
            elif isinstance(nxt, ControlSequenceToken):
                if len(nxt.name) == 1:
                    val = ord(nxt.name)
                elif nxt.name == "":
                    val = 13
                elif nxt.name == "\\":
                    val = ord("\\")
                else:
                    raise EngineError(f"Number expected after `, got \\{nxt.name}")
            else:
                raise EngineError("Number expected after `")
            # Skip optional space
            sp = self._next_raw()
            if not (isinstance(sp, CharToken) and sp.catcode == Catcode.SPACE) and sp is not None:
                self._stack.append(sp)
            return sign * val

        raise EngineError("Number expected")

    # ------------------------------------------------------------------
    # Token converters
    # ------------------------------------------------------------------

    def _exec_number(self) -> None:
        """Execute \\number: push decimal representation onto stack."""
        from aspose_tex._engine.dimparser import parse_integer

        n = parse_integer(self)
        s = str(n)
        tokens: list[Token] = [CharToken(c, Catcode.OTHER) for c in s]
        self.push_tokens(tokens)

    def _exec_string(self) -> None:
        """Execute ``\\string``: push string representation of the next token.

        For a control sequence ``\\foo``, emits the escape character (``\\``
        by default) followed by the CS name as OTHER-catcode chars (SPACE
        catcode for embedded spaces). Per TeXbook ch. 24, the escape character
        is the character whose code equals the integer parameter
        ``\\escapechar``; it is omitted entirely when ``\\escapechar`` is
        outside the ``0..255`` range. For a character token, emits the
        character itself unchanged. See.
        """
        tok = self._next_raw()
        if tok is None:
            return
        tokens: list[Token] = []
        if isinstance(tok, ControlSequenceToken):
            esc = self._read_escapechar()
            escape = chr(esc) if 0 <= esc <= 255 else ""
            if isinstance(tok, FontRefToken):
                text = escape + self._interpreter._font_manager.font_id_text(tok.name)
            elif tok.name:
                text = escape + tok.name
            else:
                # §263 sprint_cs: the null control sequence prints as
                # \csname\endcsname, each part with the escape character.
                text = f"{escape}csname{escape}endcsname"
            for c in text:
                catcode = Catcode.SPACE if c == " " else Catcode.OTHER
                tokens.append(CharToken(c, catcode))
        else:
            c = tok.char
            catcode = Catcode.SPACE if c == " " else Catcode.OTHER
            tokens.append(CharToken(c, catcode))
        self.push_tokens(tokens)

    def _read_escapechar(self) -> int:
        """Return the current value of ``\\escapechar`` (default 92 = ``\\``).

        Reads slot 298 of the register bank (§A.5 / named-parameter
        registry). Falls back to 92 when no ``RegisterSet`` is wired (unit
        tests that build an Expander without an interpreter).
        """
        regs = getattr(self, "_register_set", None)
        if regs is None:
            return 92
        try:
            return int(regs._bank.count[298])
        except (AttributeError, IndexError, KeyError):
            return 92

    def _exec_the(self) -> None:
        """Execute \\the: push register value tokens onto stack."""
        self.push_tokens(self.the_tokens())

    def the_tokens(self) -> list[Token]:
        r"""Read an internal quantity and return its ``\the`` token list (§465).

        The quantity is read with expansion (``get_x_token``), and a ``\let``
        alias of a primitive reads as that primitive, so after
        ``\let\cnt=\count`` the text ``\cnt5`` gives the value of ``\count5``.

        Returns:
            The tokens ``\the`` inserts.

        Raises:
            EngineError: if no register provider is wired, the input ends, or
                the token is not a readable quantity.

        Example::

            expander.push_tokens(tokenize(r"\cnt5"))   # with \let\cnt=\count
            expander.the_tokens()                     # -> the digits of \count5
        """
        if self._register_provider is None:
            raise EngineError("\\the: register provider not available")
        tok = self.get_x_token()
        if tok is None:
            raise EngineError("\\the: missing token")
        return self._register_provider.get_tokens_for_the(self.primitive_token(tok), self)

    def primitive_token(self, tok: Token) -> Token:
        r"""Return *tok* as the primitive it means when it is a ``\let`` alias of one.

        Readers of internal quantities dispatch on the primitive's name, so a
        control sequence or active character whose meaning is a
        :class:`PrimitiveMeaning` ( D3) becomes the matching
        :class:`PrimitiveRefToken`. An active owner binding becomes its
        control-sequence key, so existing quantity readers reach the
        copied binding ( D2). Other tokens are returned unchanged.

        Example::

            # after \let\wdd=\wd
            expander.primitive_token(ControlSequenceToken("wdd"))  # -> PrimitiveRefToken("wd")
        """
        if isinstance(tok, PrimitiveRefToken):
            return tok
        if isinstance(tok, ControlSequenceToken):
            meaning = self._macros.get(tok.name)
        elif tok.catcode == Catcode.ACTIVE:
            key = active_char_key(tok.char)
            meaning = self._macros.get(key)
            if (meaning is None and self._bindings is not None
                    and self._bindings.binding_of(key) is not None):
                return ControlSequenceToken(key)
        else:
            return tok
        if isinstance(meaning, PrimitiveMeaning):
            return PrimitiveRefToken(meaning.name)
        return tok

    # ------------------------------------------------------------------
    # File inclusion
    # ------------------------------------------------------------------

    def _exec_input(self, *, intercept: bool = False) -> None:
        """Execute \\input: push a new file source onto the input reader."""
        # Skip leading space
        tok = self._next_raw()
        while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
            tok = self._next_raw()

        if tok is None:
            return

        chars: list[str] = []
        # Collect filename: letters, digits, dots, slashes, underscores, dashes
        if isinstance(tok, CharToken) and tok.catcode == Catcode.BEGIN_GROUP:
            # Brace-delimited filename
            chars_in = self._scan_balanced_group()
            chars = [t.char for t in chars_in if isinstance(t, CharToken)]
        else:
            # Undelimited: collect until space or special char
            while tok is not None:
                if isinstance(tok, CharToken) and tok.catcode in (
                    Catcode.SPACE, Catcode.BEGIN_GROUP, Catcode.END_GROUP
                ):
                    break
                if isinstance(tok, CharToken):
                    chars.append(tok.char)
                tok = self._next_raw()

        filename = "".join(chars)
        path = (
            self._input_resolver(filename)
            if self._input_resolver is not None
            else pathlib.Path(filename)
        )
        if intercept and self._input_interceptor is not None and self._input_interceptor(path):
            return
        self._reader.push(FileInputSource(path))

    # ------------------------------------------------------------------
    # Group primitives
    # ------------------------------------------------------------------

    def _exec_global(self) -> None:
        """Handle ``\\global``: set the global flag on the group stack."""
        if self._group_stack is not None:
            self._group_stack.set_global()
        # Without a group stack, \global is silently ignored (no-op)

    def _exec_currentgrouplevel(self) -> None:
        """Handle ``\\currentgrouplevel``: push digit tokens for current depth."""
        depth = self._group_stack.depth if self._group_stack is not None else 0
        for ch in str(depth):
            self._stack.append(CharToken(ch, Catcode.OTHER))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tokens_match(buf: list[Token], delimiters: list[Token]) -> bool:
    """Return True if buf equals delimiters element-wise."""
    if len(buf) != len(delimiters):
        return False
    for a, b in zip(buf, delimiters, strict=True):
        if type(a) is not type(b):
            return False
        if (
            (isinstance(a, CharToken) and isinstance(b, CharToken) and (a.char != b.char or a.catcode != b.catcode))
            or (isinstance(a, ControlSequenceToken) and isinstance(b, ControlSequenceToken) and a.name != b.name)
        ):
            return False
    return True


def _text_to_tokens(text: str) -> list[Token]:
    """Convert text to TeX-ish character tokens for expansion results."""
    return [
        CharToken(
            c,
            Catcode.SPACE if c == " " else Catcode.LETTER if c.isalpha() else Catcode.OTHER,
        )
        for c in text
    ]


def _to_roman(n: int) -> str:
    parts: list[str] = []
    for value, text in (
        (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
        (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
        (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
    ):
        while n >= value:
            parts.append(text)
            n -= value
    return "".join(parts)
