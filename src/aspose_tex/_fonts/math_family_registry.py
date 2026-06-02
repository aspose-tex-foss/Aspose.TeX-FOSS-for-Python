"""Math-family font assignment registry.

Stores the M3 ``\\textfont`` / ``\\scriptfont`` / ``\\scriptscriptfont``
family-to-font control-sequence assignments for . The registry keeps
font names only; M4 math typesetting will resolve metrics through FontManager.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aspose_tex.exceptions import EngineError, FontError

if TYPE_CHECKING:
 from aspose_tex._engine.group import GroupStack
 from aspose_tex._fonts.font_manager import FontManager


_FAMILY_COUNT = 16


class MathFamilyRegistry:
 """Stores math-family font CS names for 16 TeX math families.

 Args:
 group_stack: Group save/restore stack used for local assignments.
 font_manager: Font manager used to validate assigned font CS names.

 Example:
 registry.set_text(0, "tenrm")
 assert registry.get_text(0) == "tenrm"
 """

 __slots__ = ("_font_manager", "_group_stack", "_script", "_scriptscript", "_text")

 def __init__(self, group_stack: GroupStack, font_manager: FontManager) -> None:
 self._group_stack = group_stack
 self._font_manager = font_manager
 self._text: list[str | None] = [None] * _FAMILY_COUNT
 self._script: list[str | None] = [None] * _FAMILY_COUNT
 self._scriptscript: list[str | None] = [None] * _FAMILY_COUNT

 def get_text(self, family: int) -> str | None:
 """Return the text-style font CS for *family*, or None if unset."""
 self._check_family(family)
 return self._text[family]

 def get_script(self, family: int) -> str | None:
 """Return the script-style font CS for *family*, or None if unset."""
 self._check_family(family)
 return self._script[family]

 def get_scriptscript(self, family: int) -> str | None:
 """Return the scriptscript-style font CS for *family*, or None if unset."""
 self._check_family(family)
 return self._scriptscript[family]

 def set_text(self, family: int, font_cs: str, *, global_: bool = False) -> None:
 """Assign the text-style font CS for *family*."""
 self._set("textfont", self._text, family, font_cs, global_=global_)

 def set_script(self, family: int, font_cs: str, *, global_: bool = False) -> None:
 """Assign the script-style font CS for *family*."""
 self._set("scriptfont", self._script, family, font_cs, global_=global_)

 def set_scriptscript(self, family: int, font_cs: str, *, global_: bool = False) -> None:
 """Assign the scriptscript-style font CS for *family*."""
 self._set("scriptscriptfont", self._scriptscript, family, font_cs, global_=global_)

 def _set(
 self,
 role: str,
 slots: list[str | None],
 family: int,
 font_cs: str,
 *,
 global_: bool,
 ) -> None:
 self._check_family(family)
 if not self._font_manager.is_font(font_cs):
 raise FontError(f"\\{role}{family}: \\{font_cs} is not a font")
 if not global_:
 old = slots[family]
 self._group_stack.save((role, family), lambda: slots.__setitem__(family, old))
 slots[family] = font_cs

 @staticmethod
 def _check_family(family: int) -> None:
 if not (0 <= family < _FAMILY_COUNT):
 raise EngineError(f"math family {family} out of range 0-15")
