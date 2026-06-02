"""Catcode table: the 16 TeX character categories and a mutable lookup table.

Implements FR-4, FR-5, FR-6.
Catcode changes are group-scoped ( FR-5 / ): when a ``GroupStack``
is provided, ``set()`` saves the old catcode before writing.

See and for design rationale.
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
 from aspose_tex._engine.group import GroupStack


class Catcode(enum.IntEnum):
 """The 16 TeX character categories (TeXbook §8).

 Example::

 assert Catcode.ESCAPE == 0
 assert Catcode.LETTER == 11
 """

 ESCAPE = 0
 BEGIN_GROUP = 1
 END_GROUP = 2
 MATH_SHIFT = 3
 ALIGNMENT = 4
 END_OF_LINE = 5
 PARAMETER = 6
 SUPERSCRIPT = 7
 SUBSCRIPT = 8
 IGNORED = 9
 SPACE = 10
 LETTER = 11
 OTHER = 12
 ACTIVE = 13
 COMMENT = 14
 INVALID = 15


# ---------------------------------------------------------------------------
# IniTeX default catcode table
# ---------------------------------------------------------------------------

def _build_default_table() -> list[Catcode]:
 """Return a 256-entry list with IniTeX catcode defaults (TeXbook Chapter 7)."""
 table = [Catcode.OTHER] * 256

 table[92] = Catcode.ESCAPE # backslash \
 table[123] = Catcode.BEGIN_GROUP # {
 table[125] = Catcode.END_GROUP # }
 table[36] = Catcode.MATH_SHIFT # $
 table[38] = Catcode.ALIGNMENT # &
 table[13] = Catcode.END_OF_LINE # CR — appended by InputReader at end of each line
 table[35] = Catcode.PARAMETER # #
 table[94] = Catcode.SUPERSCRIPT # ^
 table[95] = Catcode.SUBSCRIPT # _
 table[0] = Catcode.IGNORED # NUL
 table[32] = Catcode.SPACE # space
 for c in range(ord('a'), ord('z') + 1):
 table[c] = Catcode.LETTER
 for c in range(ord('A'), ord('Z') + 1):
 table[c] = Catcode.LETTER
 table[126] = Catcode.ACTIVE # ~
 table[37] = Catcode.COMMENT # %
 table[127] = Catcode.INVALID # DEL

 return table


_DEFAULT_TABLE: list[Catcode] = _build_default_table()


# ---------------------------------------------------------------------------
# CatcodeTable
# ---------------------------------------------------------------------------

class CatcodeTable:
 """Mutable mapping from character to :class:`Catcode`.

 Initialised with IniTeX defaults (TeXbook Chapter 7).
 Characters with code > 255 always return :attr:`Catcode.OTHER`.

 Example::

 tbl = CatcodeTable()
 assert tbl.get('\\\\') == Catcode.ESCAPE
 tbl.set('@', Catcode.LETTER)
 assert tbl.get('@') == Catcode.LETTER
 assert tbl.get('a') == Catcode.LETTER # unchanged
 """

 def __init__(self, group_stack: GroupStack | None = None) -> None:
 """Build table with IniTeX default catcodes.

 Args:
 group_stack: Optional group stack for catcode scoping.
 When provided, ``set()`` saves the old catcode before writing.
 """
 # Copy so each instance is independent and fully mutable.
 self._table: list[Catcode] = list(_DEFAULT_TABLE)
 self._group_stack = group_stack

 def get(self, char: str) -> Catcode:
 """Return the :class:`Catcode` for *char* (single character).

 Characters with code > 255 return :attr:`Catcode.OTHER`.

 Args:
 char: A single Unicode character.

 Returns:
 The catcode assigned to *char*.
 """
 code = ord(char)
 if code > 255:
 return Catcode.OTHER
 return self._table[code]

 def set(self, char: str, catcode: Catcode) -> None:
 """Assign *catcode* to *char* (single character, code 0-255).

 Args:
 char: A single character whose code is in range 0-255.
 catcode: The new catcode to assign.

 Raises:
 ValueError: if ``len(char) != 1`` or ``ord(char) > 255``.

 Example::

 tbl = CatcodeTable()
 tbl.set('@', Catcode.LETTER)
 """
 if len(char) != 1 or ord(char) > 255:
 raise ValueError(
 f"catcode can only be set for single-byte characters, got {char!r}"
 )
 code = ord(char)
 if self._group_stack is not None:
 if not self._group_stack.is_global_pending:
 old = self._table[code]
 table = self._table
 _code = code
 self._group_stack.save(
 ("catcode", char),
 lambda: table.__setitem__(_code, old),
 )
 else:
 self._group_stack.consume_global()
 self._table[code] = catcode
