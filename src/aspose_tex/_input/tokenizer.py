"""TeX tokenizer: Knuth's N/M/S state machine over a character stream.

Implements FR-7, FR-9, FR-10.
See for the complete state-machine specification.
"""

from __future__ import annotations

import enum
from collections.abc import Iterator

from aspose_tex._input.catcode import Catcode, CatcodeTable
from aspose_tex._input.reader import InputReader, SourceLocation
from aspose_tex._input.token import CharToken, ControlSequenceToken, Token
from aspose_tex.exceptions import InputError

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

class _State(enum.Enum):
 N = "new_line" # beginning of line / after blank line
 M = "mid_line" # normal scanning — middle of line
 S = "skip_blanks" # skipping spaces (after control word or space token)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

class Tokenizer:
 """Converts the character stream from :class:`InputReader` into TeX tokens.

 Implements the three-state machine (N / M / S) from TeXbook §8.

 * IGNORED chars (catcode 9) are silently dropped; no state change.
 * Comments (catcode 14) consume the rest of the line including its
 end-of-line character; state becomes N afterwards.
 * INVALID chars (catcode 15) raise :class:`~aspose_tex.exceptions.InputError`.
 * A blank line (end-of-line in state N) yields
 ``ControlSequenceToken("par")``.

 Example::

 from aspose_tex._input import (
 CatcodeTable, InputReader, StringInputSource, Tokenizer,
 )

 reader = InputReader(StringInputSource(r"\\hello world"))
 tokens = list(Tokenizer(reader, CatcodeTable()))
 # [ControlSequenceToken("hello"),
 # CharToken('w', Catcode.LETTER), CharToken('o', Catcode.LETTER), ...]

 Args:
 reader: character source (:class:`InputReader` instance)
 catcodes: catcode table (shared with engine; mutable)
 """

 def __init__(self, reader: InputReader, catcodes: CatcodeTable) -> None:
 self._reader = reader
 self._catcodes = catcodes
 self._state: _State = _State.N
 self._peeked: Token | None = None
 # Pre-create the reader iterator once; we drive it manually.
 self._iter = iter(reader)
 # One-char lookahead from the reader (separate from token lookahead).
 self._next_char: tuple[str, SourceLocation] | None = None

 # ------------------------------------------------------------------
 # Reader helpers
 # ------------------------------------------------------------------

 def _read_char(self) -> tuple[str, SourceLocation] | None:
 """Consume and return the next (char, location) from the reader."""
 if self._next_char is not None:
 ch = self._next_char
 self._next_char = None
 return ch
 return next(self._iter, None)

 def _peek_char(self) -> tuple[str, SourceLocation] | None:
 """Peek at the next char without consuming it."""
 if self._next_char is None:
 self._next_char = next(self._iter, None)
 return self._next_char

 # ------------------------------------------------------------------
 # Token production
 # ------------------------------------------------------------------

 def _scan_control_sequence(self) -> Token:
 """Scan a control sequence name after an escape character.

 Returns the resulting :class:`ControlSequenceToken` and updates state.
 See §State Machine Rules for the exact rules.
 """
 nxt = self._peek_char()
 if nxt is None:
 # EOF immediately after escape — empty CS, stay in M
 self._state = _State.M
 return ControlSequenceToken("")

 c2, _loc = nxt
 cc2 = self._catcodes.get(c2)

 if cc2 == Catcode.LETTER:
 # Multi-letter control word: collect all consecutive letters.
 name_chars: list[str] = []
 while True:
 peek = self._peek_char()
 if peek is None:
 break
 ch, _ = peek
 if self._catcodes.get(ch) == Catcode.LETTER:
 self._read_char() # consume
 name_chars.append(ch)
 else:
 break
 self._state = _State.S
 return ControlSequenceToken("".join(name_chars))

 # Single-character control symbol.
 self._read_char() # consume c2
 if cc2 in (Catcode.SPACE, Catcode.END_OF_LINE):
 self._state = _State.S
 else:
 self._state = _State.M

 if cc2 == Catcode.SPACE:
 return ControlSequenceToken(" ")
 if cc2 == Catcode.END_OF_LINE:
 return ControlSequenceToken("")
 return ControlSequenceToken(c2)

 def _skip_comment(self) -> None:
 """Consume all chars up to and including the end-of-line after '%'.

 The InputReader always appends chr(13) (catcode END_OF_LINE) at the
 end of every line, so this is guaranteed to terminate. See .
 """
 while True:
 ch_loc = self._read_char()
 if ch_loc is None:
 break
 ch, loc = ch_loc
 if ch == chr(13):
 peek = self._peek_char()
 if peek is not None and peek[1].line == loc.line:
 continue
 break
 self._state = _State.N

 def _next_token(self) -> Token | None:
 """Advance the state machine by one token and return it, or None at EOF."""
 while True:
 ch_loc = self._read_char()
 if ch_loc is None:
 return None

 char, loc = ch_loc
 catcode = self._catcodes.get(char)

 # -- IGNORED: silently drop, no state change --
 if catcode == Catcode.IGNORED:
 continue

 # -- INVALID: hard error --
 if catcode == Catcode.INVALID:
 raise InputError(f"invalid character {char!r} at {loc}")

 # -- COMMENT: strip to end of line --
 if catcode == Catcode.COMMENT:
 self._skip_comment()
 continue

 # -- ESCAPE: control sequence --
 if catcode == Catcode.ESCAPE:
 return self._scan_control_sequence()

 # -- END_OF_LINE --
 if catcode == Catcode.END_OF_LINE:
 if self._state == _State.N:
 # Blank line → \par; stay in N
 return ControlSequenceToken("par")
 if self._state == _State.S:
 # Swallow; move to N
 self._state = _State.N
 continue
 # State M → produce space, move to N
 self._state = _State.N
 return CharToken(" ", Catcode.SPACE)

 # -- SPACE --
 if catcode == Catcode.SPACE:
 if self._state == _State.M:
 self._state = _State.S
 return CharToken(" ", Catcode.SPACE)
 # States N and S: swallow space
 continue

 # -- All other catcodes: produce a CharToken, state → M --
 self._state = _State.M
 return CharToken(char, catcode)

 # ------------------------------------------------------------------
 # Public interface
 # ------------------------------------------------------------------

 def peek(self) -> Token | None:
 """Return the next token without consuming it.

 Returns ``None`` when the stream is exhausted.

 Example::

 tok = tokenizer.peek()
 assert tok == next(iter(tokenizer))
 """
 if self._peeked is None:
 self._peeked = self._next_token()
 return self._peeked

 def __iter__(self) -> Iterator[Token]:
 """Yield tokens until the stream is exhausted.

 Example::

 for token in tokenizer:
 process(token)
 """
 while True:
 if self._peeked is not None:
 token = self._peeked
 self._peeked = None
 else:
 token = self._next_token()
 if token is None:
 return
 yield token
