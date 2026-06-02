"""Input reader: lazy character stream over a stack of TeX input sources.

Implements FR-1 (file + string input), FR-2 (position tracking),
FR-3 (^^ notation decoding), and FR-11 (input stack for \\input).
See the project documentation for design rationale.
"""

from __future__ import annotations

import abc
import dataclasses
import io
import pathlib
from collections.abc import Iterator

from aspose_tex.exceptions import InputError

# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

_HEX_DIGITS = frozenset("0123456789abcdef")


@dataclasses.dataclass(slots=True, frozen=True)
class SourceLocation:
 """Immutable position marker attached to every character for error messages.

 Example::

 loc = SourceLocation("main.tex", line=3, column=7)
 assert f"{loc.filename}:{loc.line}:{loc.column}" == "main.tex:3:7"
 """

 filename: str # source name; empty string for anonymous string input
 line: int # 1-based line number
 column: int # 1-based column in the original (pre-^^ expansion) line


# ---------------------------------------------------------------------------
# Abstract source
# ---------------------------------------------------------------------------

class InputSource(abc.ABC):
 """Abstract single input source — one file or one string buffer.

 Implementors must provide :meth:`name` and :meth:`read_line`.
 """

 @property
 @abc.abstractmethod
 def name(self) -> str:
 """Human-readable identifier used in error messages and SourceLocation."""

 @abc.abstractmethod
 def read_line(self) -> str | None:
 """Return the next logical line WITHOUT a trailing newline, or None at EOF."""


# ---------------------------------------------------------------------------
# Concrete sources
# ---------------------------------------------------------------------------

class FileInputSource(InputSource):
 """Reads TeX source from a file on disk.

 The file is opened lazily on the first :meth:`read_line` call, and one
 line at a time — no buffering of the entire file.

 Example::

 src = FileInputSource(pathlib.Path("article.tex"))
 line = src.read_line() # first line, no newline suffix
 """

 def __init__(self, path: pathlib.Path) -> None:
 self._path = path
 self._file: io.TextIOWrapper | None = None

 @property
 def name(self) -> str:
 return str(self._path)

 def read_line(self) -> str | None:
 if self._file is None:
 try:
 self._file = self._path.open(encoding="utf-8")
 except OSError as exc:
 raise InputError(f"cannot open '{self._path}': {exc.strerror}") from exc
 raw = self._file.readline()
 if raw == "":
 self._file.close()
 self._file = None
 return None
 return raw.rstrip("\r\n")

 def __del__(self) -> None:
 if self._file is not None:
 self._file.close()
 self._file = None


class StringInputSource(InputSource):
 """Reads TeX source from an in-memory :class:`str` or :class:`bytes` value.

 ``bytes`` input is decoded as UTF-8.

 Example::

 src = StringInputSource(r"\\hello world", name="snippet")
 line = src.read_line()
 """

 def __init__(self, text: str | bytes, name: str = "<string>") -> None:
 if isinstance(text, bytes):
 try:
 text = text.decode("utf-8")
 except UnicodeDecodeError as exc:
 raise InputError(f"input '{name}' is not valid UTF-8") from exc
 # splitlines() handles all newline variants; empty string yields []
 self._lines = text.splitlines()
 self._index = 0
 self._name = name

 @property
 def name(self) -> str:
 return self._name

 def read_line(self) -> str | None:
 if self._index >= len(self._lines):
 return None
 line = self._lines[self._index]
 self._index += 1
 return line


# ---------------------------------------------------------------------------
# ^^ notation decoder
# ---------------------------------------------------------------------------

def _expand_caret_caret(line: str) -> list[tuple[str, int]]:
 """Decode all ``^^`` escape sequences in *line*.

 Returns a list of ``(char, 1-based-column)`` pairs where the column
 is the position of the **first** caret in the original string.

 Rules (TeXbook §8):

 * ``^^XY`` — X and Y are both lowercase hex digits → ``chr(int("XY", 16))``
 (consumes 4 characters)
 * ``^^X`` — any other X with code *c* → ``chr(c+64)`` if c < 64 else
 ``chr(c-64)`` (consumes 3 characters)
 * Any ``^`` that does not start a valid ``^^`` sequence is passed through.

 See for precedence rules.
 """
 result: list[tuple[str, int]] = []
 i = 0
 n = len(line)
 while i < n:
 col = i + 1 # 1-based
 if (
 line[i] == "^"
 and i + 1 < n
 and line[i + 1] == "^"
 and i + 2 < n
 ):
 x = line[i + 2]
 # Try the two-hex-digit form first (higher precedence)
 if i + 3 < n and x in _HEX_DIGITS and line[i + 3] in _HEX_DIGITS:
 result.append((chr(int(line[i + 2 : i + 4], 16)), col))
 i += 4
 else:
 c = ord(x)
 result.append((chr(c + 64) if c < 64 else chr(c - 64), col))
 i += 3
 else:
 result.append((line[i], col))
 i += 1
 return result


# ---------------------------------------------------------------------------
# Internal stack frame
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _StackFrame:
 """Mutable read state for one source on the input stack."""

 source: InputSource
 line: int = 0 # current line number (0 = not yet read any line)
 _char_buf: list[tuple[str, int]] = dataclasses.field(default_factory=list)
 _buf_pos: int = 0

 def next_char(self) -> tuple[str, SourceLocation] | None:
 """Return next ``(char, SourceLocation)`` or ``None`` when exhausted."""
 while self._buf_pos >= len(self._char_buf):
 raw = self.source.read_line()
 if raw is None:
 return None
 self.line += 1
 expanded = _expand_caret_caret(raw)
 # Append TeX end-of-line character; column = past end of raw line
 expanded.append((chr(13), len(raw) + 1))
 self._char_buf = expanded
 self._buf_pos = 0

 char, col = self._char_buf[self._buf_pos]
 self._buf_pos += 1
 return char, SourceLocation(self.source.name, self.line, col)


# ---------------------------------------------------------------------------
# InputReader
# ---------------------------------------------------------------------------

class InputReader:
 """Manages a stack of :class:`InputSource` objects and provides a
 character-by-character stream with ``^^`` notation decoded and
 line/column positions attached.

 After a source is exhausted the reader automatically pops to the
 previous source on the stack. Call :meth:`push` when the TeX engine
 processes an ``\\input`` primitive; the next characters will come from
 the new source.

 Example::

 reader = InputReader(FileInputSource(pathlib.Path("main.tex")))
 for char, loc in reader:
 process(char, loc)

 # Inside \\input handling:
 reader.push(FileInputSource(pathlib.Path("chapter1.tex")))
 """

 __slots__ = ("_last_loc", "_peeked", "_stack")

 def __init__(self, source: InputSource) -> None:
 self._stack: list[_StackFrame] = [_StackFrame(source)]
 self._peeked: tuple[str, SourceLocation] | None = None
 self._last_loc: SourceLocation | None = None

 # ------------------------------------------------------------------
 # Stack management
 # ------------------------------------------------------------------

 def push(self, source: InputSource) -> None:
 """Push *source* on top of the stack; subsequent characters come from it."""
 self._peeked = None # invalidate lookahead
 self._stack.append(_StackFrame(source))

 def pop(self) -> None:
 """Explicitly pop the top source.

 Raises:
 InputError: if the stack is already empty.
 """
 if not self._stack:
 raise InputError("input stack underflow")
 self._peeked = None
 self._stack.pop()

 # ------------------------------------------------------------------
 # Character access
 # ------------------------------------------------------------------

 def _advance(self) -> tuple[str, SourceLocation] | None:
 """Pull the next raw character from the stack, popping exhausted frames."""
 while self._stack:
 result = self._stack[-1].next_char()
 if result is not None:
 return result
 self._stack.pop()
 return None

 def peek(self) -> tuple[str, SourceLocation] | None:
 """Return the next ``(char, location)`` without consuming it.

 Returns ``None`` when all sources are exhausted.
 """
 if self._peeked is None:
 self._peeked = self._advance()
 return self._peeked

 def __iter__(self) -> Iterator[tuple[str, SourceLocation]]:
 """Yield ``(char, location)`` pairs until all sources are exhausted."""
 while True:
 if self._peeked is not None:
 item = self._peeked
 self._peeked = None
 else:
 item = self._advance()
 if item is None:
 return
 self._last_loc = item[1]
 yield item

 # ------------------------------------------------------------------
 # Properties
 # ------------------------------------------------------------------

 @property
 def current_location(self) -> SourceLocation:
 """Position of the last character returned (or start position)."""
 if self._last_loc is not None:
 return self._last_loc
 if not self._stack:
 return SourceLocation("", 0, 0)
 return SourceLocation(self._stack[-1].source.name, 0, 0)

 @property
 def at_end(self) -> bool:
 """``True`` when no more characters will be produced."""
 return self.peek() is None
