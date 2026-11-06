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

    char: str       # single character
    catcode: Catcode


@dataclasses.dataclass(slots=True, frozen=True)
class ControlSequenceToken:
    """A control-sequence token produced by an escape character.

    ``name`` is the string of characters after the escape:

    * Multi-letter control word: ``name="def"`` for ``\\def``
    * Single-char control symbol: ``name="!"`` for ``\\!``
    * Space control symbol: ``name=" "`` for ``\\ `` (backslash-space)
    * Any other control symbol is named by its character, whatever its
      catcode: ``name="\\t"`` for ``\\^^I``, ``name="\\r"`` for ``\\^^M``
      (TeX §354, amendment)
    * Escape at end of input: ``name=""`` (empty string)
    * Blank-line paragraph: ``ControlSequenceToken("par")``

    Frozen dataclass with ``__slots__`` for minimal memory use and hashability.

    Example::

        t = ControlSequenceToken("par")
        assert t.name == "par"
    """

    name: str       # control sequence name without the leading backslash


@dataclasses.dataclass(slots=True, frozen=True)
class PrimitiveRefToken(ControlSequenceToken):
    r"""A control sequence already resolved to the built-in named ``name``.

    The expander hands it on for a ``\let`` alias of a primitive (
    D3): it is dispatched as that primitive and never looked up in the macro
    table again, so ``\let\endgraf=\par \def\par{\endgraf}`` cannot recurse.
    It compares unequal to the plain token, as TeX's ``\endgraf`` is not
    ``\par`` for delimiter matching.

    Example::

        t = PrimitiveRefToken("par")
        assert isinstance(t, ControlSequenceToken) and t != ControlSequenceToken("par")
    """


@dataclasses.dataclass(slots=True, frozen=True)
class FontRefToken(ControlSequenceToken):
    """A frozen font selector whose name is a persistent key."""

    def __repr__(self) -> str:
        # Generic scanner errors may format a token without a manager.
        return "FontRefToken(<loaded font>)"


# Type alias used throughout the engine pipeline.
Token = CharToken | ControlSequenceToken
