"""TeX code arrays: \\mathcode, \\delcode, \\sfcode, \\lccode, \\uccode.

Implements FR-2 through FR-6. Catcode storage stays in
``_input/catcode.py`` (tokenizer-domain) — see §"Open questions" Q2.

Each array is a 256-entry ``list[int]`` with IniTeX defaults
(TeXbook Chapter 7 + plain.tex 49-51 comment block). Group save/restore
reuses the existing ``GroupStack`` save-on-first-write machinery
, with namespace keys ``("mathcode", char)``, ``("delcode", char)``,
etc., distinct from ``("count", n)`` / ``("catcode", char)``.

See the project documentation for design rationale.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
 from aspose_tex._engine.group import GroupStack


# ---------------------------------------------------------------------------
# IniTeX default tables (built once at module import)
# ---------------------------------------------------------------------------

def _build_default_mathcode() -> list[int]:
 """IniTeX default mathcode table (TeX:TheProgram §232)."""
 table = [0] * 256
 for c in range(256):
 if 0x30 <= c <= 0x39: # '0'..'9'
 table[c] = c + 0x7000
 elif 0x41 <= c <= 0x5A or 0x61 <= c <= 0x7A: # 'A'..'Z' / 'a'..'z'
 table[c] = c + 0x7100
 else:
 table[c] = c
 return table


def _build_default_delcode() -> list[int]:
 """IniTeX default delcode table: -1 everywhere except '.' = 0."""
 table = [-1] * 256
 table[ord(".")] = 0
 return table


def _build_default_sfcode() -> list[int]:
 """IniTeX default sfcode table: 1000 everywhere except A..Z = 999."""
 table = [1000] * 256
 for c in range(ord("A"), ord("Z") + 1):
 table[c] = 999
 return table


def _build_default_lccode() -> list[int]:
 """IniTeX default lccode table.

 Lowercase letters self-map; uppercase letters map to their lowercase
 counterpart; everything else is 0.
 """
 table = [0] * 256
 for c in range(ord("a"), ord("z") + 1):
 table[c] = c
 for c in range(ord("A"), ord("Z") + 1):
 table[c] = c + 32 # 'A' + 32 = 'a'
 return table


def _build_default_uccode() -> list[int]:
 """IniTeX default uccode table.

 Uppercase letters self-map; lowercase letters map to their uppercase
 counterpart; everything else is 0.
 """
 table = [0] * 256
 for c in range(ord("A"), ord("Z") + 1):
 table[c] = c
 for c in range(ord("a"), ord("z") + 1):
 table[c] = c - 32 # 'a' - 32 = 'A'
 return table


_DEFAULT_MATHCODE: Final[list[int]] = _build_default_mathcode()
_DEFAULT_DELCODE: Final[list[int]] = _build_default_delcode()
_DEFAULT_SFCODE: Final[list[int]] = _build_default_sfcode()
_DEFAULT_LCCODE: Final[list[int]] = _build_default_lccode()
_DEFAULT_UCCODE: Final[list[int]] = _build_default_uccode()


# ---------------------------------------------------------------------------
# Range bounds
# ---------------------------------------------------------------------------

_MATHCODE_MAX: Final[int] = 0x8000
_DELCODE_MAX: Final[int] = 0xFFFFFF
_DELCODE_MIN: Final[int] = -1
_SFCODE_MAX: Final[int] = 32767
_LCCODE_MAX: Final[int] = 255
_UCCODE_MAX: Final[int] = 255


def _check_char_code(char_code: int) -> None:
 if not (0 <= char_code <= 255):
 raise EngineError(f"char code {char_code} out of range 0-255")


# ---------------------------------------------------------------------------
# CodeArrays
# ---------------------------------------------------------------------------

class CodeArrays:
 """Five 256-entry int arrays with IniTeX defaults and group save/restore.

 Args:
 group_stack: Optional ``GroupStack``. When provided, ``set_<name>``
 methods save the old value to the current group frame on
 first write per , mirroring ``CatcodeTable`` and
 ``RegisterSet`` patterns.

 Example::

 from aspose_tex._engine.code_arrays import CodeArrays

 codes = CodeArrays()
 codes.set_sfcode(ord(')'), 0)
 assert codes.get_sfcode(ord(')')) == 0
 """

 __slots__ = ("_group_stack", "delcode", "lccode", "mathcode", "sfcode", "uccode")

 def __init__(self, group_stack: GroupStack | None = None) -> None:
 self.mathcode: list[int] = list(_DEFAULT_MATHCODE)
 self.delcode: list[int] = list(_DEFAULT_DELCODE)
 self.sfcode: list[int] = list(_DEFAULT_SFCODE)
 self.lccode: list[int] = list(_DEFAULT_LCCODE)
 self.uccode: list[int] = list(_DEFAULT_UCCODE)
 self._group_stack = group_stack

 # ------------------------------------------------------------------
 # mathcode
 # ------------------------------------------------------------------

 def get_mathcode(self, char_code: int) -> int:
 """Return mathcode for ``char_code`` (0..255)."""
 _check_char_code(char_code)
 return self.mathcode[char_code]

 def set_mathcode(self, char_code: int, value: int) -> None:
 """Set mathcode for ``char_code`` to ``value`` (0..0x8000).

 Raises:
 EngineError: if ``char_code`` or ``value`` is out of range.
 """
 _check_char_code(char_code)
 if not (0 <= value <= _MATHCODE_MAX):
 raise EngineError(
 f"\\mathcode value {value} out of range 0-32768"
 )
 self._save_and_set("mathcode", char_code, value)

 # ------------------------------------------------------------------
 # delcode
 # ------------------------------------------------------------------

 def get_delcode(self, char_code: int) -> int:
 """Return delcode for ``char_code`` (0..255)."""
 _check_char_code(char_code)
 return self.delcode[char_code]

 def set_delcode(self, char_code: int, value: int) -> None:
 """Set delcode for ``char_code`` to ``value`` (-1..0xFFFFFF).

 Raises:
 EngineError: if ``char_code`` or ``value`` is out of range.
 """
 _check_char_code(char_code)
 if not (_DELCODE_MIN <= value <= _DELCODE_MAX):
 raise EngineError(
 f"\\delcode value {value} out of range -1..16777215"
 )
 self._save_and_set("delcode", char_code, value)

 # ------------------------------------------------------------------
 # sfcode
 # ------------------------------------------------------------------

 def get_sfcode(self, char_code: int) -> int:
 """Return sfcode for ``char_code`` (0..255)."""
 _check_char_code(char_code)
 return self.sfcode[char_code]

 def set_sfcode(self, char_code: int, value: int) -> None:
 """Set sfcode for ``char_code`` to ``value`` (0..32767).

 Raises:
 EngineError: if ``char_code`` or ``value`` is out of range.
 """
 _check_char_code(char_code)
 if not (0 <= value <= _SFCODE_MAX):
 raise EngineError(
 f"\\sfcode value {value} out of range 0-32767"
 )
 self._save_and_set("sfcode", char_code, value)

 # ------------------------------------------------------------------
 # lccode
 # ------------------------------------------------------------------

 def get_lccode(self, char_code: int) -> int:
 """Return lccode for ``char_code`` (0..255)."""
 _check_char_code(char_code)
 return self.lccode[char_code]

 def set_lccode(self, char_code: int, value: int) -> None:
 """Set lccode for ``char_code`` to ``value`` (0..255).

 Raises:
 EngineError: if ``char_code`` or ``value`` is out of range.
 """
 _check_char_code(char_code)
 if not (0 <= value <= _LCCODE_MAX):
 raise EngineError(
 f"\\lccode value {value} out of range 0-255"
 )
 self._save_and_set("lccode", char_code, value)

 # ------------------------------------------------------------------
 # uccode
 # ------------------------------------------------------------------

 def get_uccode(self, char_code: int) -> int:
 """Return uccode for ``char_code`` (0..255)."""
 _check_char_code(char_code)
 return self.uccode[char_code]

 def set_uccode(self, char_code: int, value: int) -> None:
 """Set uccode for ``char_code`` to ``value`` (0..255).

 Raises:
 EngineError: if ``char_code`` or ``value`` is out of range.
 """
 _check_char_code(char_code)
 if not (0 <= value <= _UCCODE_MAX):
 raise EngineError(
 f"\\uccode value {value} out of range 0-255"
 )
 self._save_and_set("uccode", char_code, value)

 # ------------------------------------------------------------------
 # Internals
 # ------------------------------------------------------------------

 def _save_and_set(self, family: str, char_code: int, value: int) -> None:
 """Save the old value to the group stack (unless global) then write."""
 table = getattr(self, family)
 if self._group_stack is not None:
 if not self._group_stack.is_global_pending:
 old = table[char_code]
 _cc = char_code
 self._group_stack.save(
 (family, _cc),
 lambda: table.__setitem__(_cc, old),
 )
 else:
 self._group_stack.consume_global()
 table[char_code] = value
