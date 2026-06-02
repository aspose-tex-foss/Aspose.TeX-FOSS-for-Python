"""TeX token types: character tokens and control-sequence tokens.

Implements FR-8.
See the project documentation for design rationale.
"""

from __future__ import annotations

import dataclasses

from aspose_tex._input.catcode import Catcode


@dataclasses.dataclass(slots=True, frozen=True)
class CharToken:
 """A character token: a single character with its catcode at scan time.

 Frozen dataclass with ``__slots__`` for minimal memory use and hashability.

 Example::

 t = CharToken('A', Catcode.LETTER)
 assert t.char == 'A'
 assert t.catcode == Catcode.LETTER
 """

 char: str # single character
 catcode: Catcode


@dataclasses.dataclass(slots=True, frozen=True)
class ControlSequenceToken:
 """A control-sequence token produced by an escape character.

 ``name`` is the string of characters after the escape:

 * Multi-letter control word: ``name="def"`` for ``\\def``
 * Single-char control symbol: ``name="!"`` for ``\\!``
 * Space control symbol: ``name=" "`` for ``\\ `` (backslash-space)
 * End-of-line after escape: ``name=""`` (empty string)
 * Blank-line paragraph: ``ControlSequenceToken("par")``

 Frozen dataclass with ``__slots__`` for minimal memory use and hashability.

 Example::

 t = ControlSequenceToken("par")
 assert t.name == "par"
 """

 name: str # control sequence name without the leading backslash


# Type alias used throughout the engine pipeline.
Token = CharToken | ControlSequenceToken
