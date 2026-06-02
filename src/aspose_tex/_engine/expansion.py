"""TeX macro expansion engine.

Implements: macro definition (\\def/\\edef/\\gdef/\\xdef/\\let)
with ``\\long`` and ``\\outer`` prefixes (FR-1a/FR-1b; ), expansion-time primitives
(\\expandafter/\\noexpand/\\csname), conditionals (\\if, \\ifx, \\ifnum, \\ifcat, \\iftrue,
\\iffalse, \\ifcase), token converters (\\the, \\number, \\string), and file inclusion
(\\input).

``\\long`` and ``\\outer`` may appear before any def command in any order and combination.
The flags are stored in :class:`~aspose_tex._engine.macro.MacroDefinition` but not yet
enforced (enforcement is deferred per spec).

Group handling note: ``{``/``}`` tokens and ``\\begingroup``/``\\endgroup``/
``\\aftergroup`` commands pass through to the interpreter for dispatch. The Expander
retains ``\\global`` (prefix for ``\\def`` family) and ``\\currentgrouplevel`` (expands
to depth value).

See , , and for design rationale.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Protocol

from aspose_tex._engine.conditionals import _CondEntry, _ConditionalStack
from aspose_tex._engine.macro import MacroDefinition, Meaning
from aspose_tex._input.catcode import Catcode, CatcodeTable
from aspose_tex._input.reader import FileInputSource, InputReader
from aspose_tex._input.token import CharToken, ControlSequenceToken, Token
from aspose_tex._input.tokenizer import Tokenizer
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
 from aspose_tex._engine.code_arrays import CodeArrays
 from aspose_tex._engine.group import GroupStack
 from aspose_tex._engine.interpreter import ModeKind
 from aspose_tex._engine.marks import MarksProvider
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
 token: The token immediately following ``\\the``.
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
 reader: The ``InputReader`` instance (needed for ``\\input`` push).
 tokenizer: The ``Tokenizer`` instance driven by ``reader``.
 catcodes: The shared ``CatcodeTable`` (same instance as given to
 ``Tokenizer``; ``\\catcode`` assignments mutate it).
 max_depth: Maximum expansion recursion depth before ``EngineError``
 is raised (default 100).
 register_provider: Optional provider for ``\\the`` (default None).

 Example::

 from aspose_tex._input import (
 StringInputSource, InputReader, CatcodeTable, Tokenizer
 )
 from aspose_tex._engine.expansion import Expander

 src = StringInputSource(r'\\def\\hi{Hello}\\hi')
 reader = InputReader(src)
 catcodes = CatcodeTable()
 tok = Tokenizer(reader, catcodes)
 expander = Expander(reader, tok, catcodes)
 tokens = list(expander)
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
 ) -> None:
 self._reader = reader
 self._tokenizer = tokenizer
 self._catcodes = catcodes
 self._max_depth = max_depth
 self._register_provider = register_provider
 self._group_stack = group_stack
 self._input_resolver = input_resolver
 self._mode_stack_provider = mode_stack_provider
 self._box_provider = box_provider
 self._job_name_provider = job_name_provider
 self._code_arrays_provider = code_arrays_provider
 self._marks_provider: MarksProvider | None = None

 self._depth: int = 0
 self._stack: list[Token] = [] # LIFO push-back; _stack[-1] is next
 self._macros: dict[str, Meaning] = {}
 self._cond_stack: _ConditionalStack = _ConditionalStack()
 self._peeked: Token | None = None # one-token peek cache
 self._edef_mode: bool = False
 self._tokenizer_iter: Iterator[Token] = iter(self._tokenizer)
 self._long_pending: bool = False # \\long prefix seen before \\def
 self._outer_pending: bool = False # \\outer prefix seen before \\def
 self._after_assignment_token: Token | None = None

 # ------------------------------------------------------------------
 # Public token interface
 # ------------------------------------------------------------------

 def __iter__(self) -> Iterator[Token]:
 """Yield unexpandable tokens one at a time."""
 while True:
 tok = self._next_unexpandable()
 if tok is None:
 return
 yield tok

 def peek(self) -> Token | None:
 """Return the next unexpandable token without consuming it.

 Returns ``None`` when the stream is exhausted.
 """
 if self._peeked is None:
 self._peeked = self._next_unexpandable()
 return self._peeked

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
 name: Control sequence name (without leading backslash).
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

 def _next_unexpandable(self) -> Token | None:
 """Return the next unexpandable token, expanding as needed."""
 while True:
 tok = self._next_raw()
 if tok is None:
 return None

 # CharTokens: pass through to caller (See )
 # Group open/close ({/}) now handled by interpreter, not expander.
 if isinstance(tok, CharToken):
 return tok

 # ControlSequenceToken: look up in dispatch table
 name = tok.name

 # 0. Stale prefix-flag guard (See / FR-1a)
 # In TeX, \long/\outer before a non-def command is an error.
 # We clear the flags so they do not bleed into a subsequent \def.
 _is_prefix = name in ("long", "outer")
 if (self._long_pending or self._outer_pending) and name not in _DEF_COMMANDS and not _is_prefix:
 self._long_pending = False
 self._outer_pending = False

 # 1. User-defined macro
 meaning = self._macros.get(name)
 if isinstance(meaning, MacroDefinition):
 self._expand_macro(name, meaning)
 continue

 # 2. \let alias to a token
 if meaning is not None:
 # Push the aliased token back for re-processing
 self._stack.append(meaning) # type: ignore[arg-type]
 continue

 # 3. Definition commands (non-expandable in \edef)
 if name in _DEF_COMMANDS:
 if self._edef_mode:
 return tok # pass through in edef mode
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
 return raw # yield as-is without expanding

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

 if name == "else":
 self._exec_else()
 continue

 if name == "fi":
 self._exec_fi()
 continue

 if name == "or":
 self._exec_or()
 continue

 # 6. Token converters
 if name == "number":
 self._exec_number()
 continue

 if name == "string":
 self._exec_string()
 continue

 if name == "the":
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

 # no-op balanced consumers: handled in expansion so no
 # interpreter-level registration is required.
 if name in ("patterns", "hyphenation"):
 self._consume_balanced_text_discard(name)
 continue

 # 7. \input
 if name == "input":
 self._exec_input()
 continue

 # 8. Group primitives — \begingroup/\endgroup/\aftergroup now
 # handled by interpreter (See ). Only \global and
 # \currentgrouplevel remain in Expander.
 if name in ("begingroup", "endgroup", "aftergroup"):
 return tok # pass through to interpreter

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

 # ------------------------------------------------------------------
 # Macro expansion
 # ------------------------------------------------------------------

 def _expand_macro(self, name: str, macro: MacroDefinition) -> None:
 """Scan arguments and push replacement tokens onto the stack.

 Uses a non-decrementing step counter to detect infinite loops (e.g.
 \\def\\loop{\\loop}\\loop). See .
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
 delimiters.append(param_pattern[j]) # type: ignore[arg-type]
 j += 1
 if delimiters:
 args[param_num] = self._scan_delimited_arg(delimiters)
 i = j # skip past delimiters in pattern
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
 run.append(param_pattern[j]) # type: ignore[arg-type]
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
 else name_tok.char
 )
 # Scan parameter text
 param_pattern = self._scan_param_pattern()
 # Scan replacement text (raw balanced group)
 raw_replacement = self._scan_balanced_group()
 if is_edef:
 replacement = tuple(self._expand_fully(raw_replacement))
 else:
 replacement = tuple(self._decode_replacement(raw_replacement))

 # Determine if this definition is global (See )
 is_global_cmd = cmd in ("gdef", "xdef")
 is_global = is_global_cmd or (
 self._group_stack is not None and self._group_stack.is_global_pending
 )

 # Save old meaning before overwriting, unless global
 if self._group_stack is not None and not is_global:
 old = self._macros.get(cs_name)
 gs = self._group_stack
 _name = cs_name # capture for closure
 if old is None:
 gs.save(("macro", _name), lambda: self._macros.pop(_name, None))
 else:
 gs.save(("macro", _name), lambda: self._macros.__setitem__(_name, old))

 # Consume \global flag whenever _global_pending is set — regardless of
 # whether globality also comes from the command itself (gdef/xdef).
 # Without this, \global\gdef leaves the flag set and corrupts the next
 # assignment. See .
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
 result.append(tok) # ## → literal #
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
 from aspose_tex._input import StringInputSource # local import to avoid cycle

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
 sub._macros = self._macros # share macro table
 sub._edef_mode = True
 sub._register_set = getattr(self, "_register_set", None)
 sub._named_params = getattr(self, "_named_params", None)
 sub._interpreter = getattr(self, "_interpreter", None)
 sub._marks_provider = self._marks_provider
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
 else name_tok.char
 )
 # Skip optional spaces and optional =
 tok = self._next_raw()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = self._next_raw()
 if isinstance(tok, CharToken) and tok.char == "=" and tok.catcode == Catcode.OTHER:
 tok = self._next_raw()
 # Skip one optional space after =
 if isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = self._next_raw()

 if tok is None:
 return
 # tok is the right-hand side
 meaning = self._macros.get(tok.name, tok) if isinstance(tok, ControlSequenceToken) else tok

 # Save old meaning before \let assignment, unless global (See )
 if self._group_stack is not None and not self._group_stack.is_global_pending:
 old = self._macros.get(a_name)
 gs = self._group_stack
 _lname = a_name # capture for closure
 if old is None:
 gs.save(("macro", _lname), lambda: self._macros.pop(_lname, None))
 else:
 gs.save(("macro", _lname), lambda: self._macros.__setitem__(_lname, old))
 elif self._group_stack is not None:
 self._group_stack.consume_global()

 self.define(a_name, meaning)
 self.fire_after_assignment()

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
 # Expand t2 by pushing it back and consuming one unexpandable result.
 # Per TeXbook: \expandafter A B → expand B one step, then A.
 # Strategy: run _next_unexpandable() once (which expands t2), push t1 before result.
 self._stack.append(t2)
 result_tok = self._next_unexpandable()
 # Stack (top first) after expansion: [rest-of-t2-expansion...]
 # Push t1 on top so output order is: t1, result_tok, rest-of-t2...
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
 f"\\csname: unexpected control sequence \\{tok.name} in csname"
 )
 chars.append(tok.char)
 name = "".join(chars)
 # If undefined, define as \relax equivalent (undefined = just pass through)
 return ControlSequenceToken(name)

 def _exec_futurelet(self) -> None:
 """Execute ``\\futurelet\\cs t1 t2`` using raw-token lookahead."""
 cs_tok = self._next_raw()
 t1 = self._next_raw()
 t2 = self._next_raw()
 if not isinstance(cs_tok, ControlSequenceToken):
 raise EngineError("\\futurelet expects a control sequence")
 if t1 is None or t2 is None:
 raise EngineError("\\futurelet: missing lookahead token")
 meaning = self._macros.get(t2.name, t2) if isinstance(t2, ControlSequenceToken) else t2
 self.define(cs_tok.name, meaning)
 self.push_tokens([t1, t2])

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

 def _meaning_text(self, tok: Token) -> str:
 if isinstance(tok, CharToken):
 if tok.catcode == Catcode.SPACE:
 return "space character "
 if tok.catcode == Catcode.LETTER:
 return f"the letter {tok.char}"
 return f"the character {tok.char}"
 meaning = self._macros.get(tok.name)
 if isinstance(meaning, MacroDefinition):
 body = "".join(_token_to_text(t) for t in meaning.replacement if not isinstance(t, int))
 return f"macro:->{body}"
 if isinstance(meaning, ControlSequenceToken | CharToken):
 return self._meaning_text(meaning)
 return f"\\{tok.name}" if meaning is None else str(meaning)

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
 tok = self._next_raw()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = self._next_raw()
 if not isinstance(tok, CharToken) or tok.catcode != Catcode.BEGIN_GROUP:
 raise EngineError(f"\\{command} expects {{...}} balanced text")
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

 def _consume_balanced_text_discard(self, command: str) -> None:
 tok = self._next_raw()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 tok = self._next_raw()
 if not isinstance(tok, CharToken) or tok.catcode != Catcode.BEGIN_GROUP:
 raise EngineError(f"\\{command} expects {{...}} balanced text")
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
 self._cond_stack.push(_CondEntry("ifnum", result))
 if not result:
 self._skip_false_branch()

 def _exec_ifdim(self) -> None:
 """Execute \\ifdim d1 R d2."""
 from aspose_tex._engine.dimparser import parse_dimen

 d1 = parse_dimen(self)
 rel_tok = self._next_raw()
 while isinstance(rel_tok, CharToken) and rel_tok.catcode == Catcode.SPACE:
 rel_tok = self._next_raw()
 if not isinstance(rel_tok, CharToken) or rel_tok.char not in "<=>":
 raise EngineError("\\ifdim: expected relation character < = >")
 d2 = parse_dimen(self)
 result = (d1 < d2) if rel_tok.char == "<" else (d1 == d2) if rel_tok.char == "=" else (d1 > d2)
 self._cond_stack.push(_CondEntry("ifdim", result))
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
 self._cond_stack.push(_CondEntry(name, result))
 if not result:
 self._skip_false_branch()

 def _exec_ifodd(self) -> None:
 """Execute \\ifodd n."""
 from aspose_tex._engine.dimparser import parse_integer

 n = parse_integer(self)
 result = n % 2 != 0
 self._cond_stack.push(_CondEntry("ifodd", result))
 if not result:
 self._skip_false_branch()

 def _exec_if_char(self) -> None:
 """Execute \\if T1 T2 (character code identity)."""
 t1 = self._next_unexpandable()
 t2 = self._next_unexpandable()
 c1 = t1.char if isinstance(t1, CharToken) else None
 c2 = t2.char if isinstance(t2, CharToken) else None
 result = (c1 is not None and c1 == c2)
 self._cond_stack.push(_CondEntry("if", result))
 if not result:
 self._skip_false_branch()

 def _exec_ifcat(self) -> None:
 """Execute \\ifcat T1 T2 (catcode identity)."""
 t1 = self._next_unexpandable()
 t2 = self._next_unexpandable()
 result = t1.catcode == t2.catcode if isinstance(t1, CharToken) and isinstance(t2, CharToken) else False
 self._cond_stack.push(_CondEntry("ifcat", result))
 if not result:
 self._skip_false_branch()

 def _exec_ifx(self) -> None:
 """Execute \\ifx T1 T2 (meaning identity, no expansion)."""
 t1 = self._next_raw()
 t2 = self._next_raw()
 if isinstance(t1, ControlSequenceToken) and isinstance(t2, ControlSequenceToken):
 m1 = self._macros.get(t1.name)
 m2 = self._macros.get(t2.name)
 result = (m1 == m2)
 elif isinstance(t1, CharToken) and isinstance(t2, CharToken):
 result = (t1.char == t2.char and t1.catcode == t2.catcode)
 else:
 result = False
 self._cond_stack.push(_CondEntry("ifx", result))
 if not result:
 self._skip_false_branch()

 def _exec_ifcase(self) -> None:
 """Execute \\ifcase n."""
 from aspose_tex._engine.dimparser import parse_integer

 n = parse_integer(self)
 entry = _CondEntry("ifcase", True, case_value=n, case_index=0)
 self._cond_stack.push(entry)
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

 stream = parse_integer(self)
 if not 0 <= stream <= 15:
 raise EngineError(f"stream number out of range: {stream}")
 result = False
 self._cond_stack.push(_CondEntry("ifeof", result))
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
 if not isinstance(tok, ControlSequenceToken):
 continue
 name = tok.name
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
 return # This \or branch is active
 # else keep skipping

 def _skip_to_fi(self) -> None:
 """Skip tokens until \\fi at depth 0. Used by \\else when true branch done."""
 depth = 0
 while True:
 tok = self._next_raw()
 if tok is None:
 raise EngineError("Unexpected end of input looking for \\fi")
 if not isinstance(tok, ControlSequenceToken):
 continue
 name = tok.name
 if name in _IF_COMMANDS:
 depth += 1
 elif name == "fi":
 if depth == 0:
 self._cond_stack.pop()
 return
 depth -= 1

 # ------------------------------------------------------------------
 # Integer scanning (TeXbook §107)
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
 break # skip one optional space
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
 character itself unchanged. See .
 """
 tok = self._next_raw()
 if tok is None:
 return
 tokens: list[Token] = []
 if isinstance(tok, ControlSequenceToken):
 esc = self._read_escapechar()
 if 0 <= esc <= 255:
 tokens.append(CharToken(chr(esc), Catcode.OTHER))
 for c in tok.name:
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
 if self._register_provider is None:
 raise EngineError("\\the: register provider not available")
 tok = self._next_raw()
 if tok is None:
 raise EngineError("\\the: missing token")
 result = self._register_provider.get_tokens_for_the(tok, self)
 self.push_tokens(result)

 # ------------------------------------------------------------------
 # File inclusion
 # ------------------------------------------------------------------

 def _exec_input(self) -> None:
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


def _token_to_text(tok: Token) -> str:
 if isinstance(tok, CharToken):
 return tok.char
 return "\\" + tok.name


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
