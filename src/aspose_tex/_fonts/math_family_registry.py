"""Math-family font assignment registry.

Stores the M3 ``\\textfont`` / ``\\scriptfont`` / ``\\scriptscriptfont``
family-to-font assignments for. Slots retain persistent loaded-font
keys; math typesetting resolves metrics through FontManager.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aspose_tex.exceptions import EngineError, FontError

if TYPE_CHECKING:
    from aspose_tex._engine.group import GroupStack
    from aspose_tex._fonts.font_manager import FontManager
    from aspose_tex._fonts.font_metrics import FontMetrics
    from aspose_tex._fonts.math_font_parameters import MathStyle


_FAMILY_COUNT = 16


class MathFamilyRegistry:
    """Stores math-family font keys for 16 TeX math families.

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

    def resolve_metrics(self, family: int, style: MathStyle) -> FontMetrics | None:
        """Return the loaded FontMetrics for ``(family, style)``, or None if unset.

        Maps the math style to the matching style-slot getter
        (``TEXT`` → :meth:`get_text`, ``SCRIPT`` → :meth:`get_script`,
        ``SCRIPTSCRIPT`` → :meth:`get_scriptscript``) and resolves the stored
        CS name through ``FontManager.get_metrics``.  Returns ``None`` when the
        family slot is unset; the caller (``MathFontParameters._resolve``)
        turns that into the "undefined" diagnostic.

        This is the → promotion (§D): the registry
        stays a router (it stores CS names only), while the live FontMetrics
        handle is fetched on demand from FontManager.

        Args:
            family: Math family 0-15.
            style:  Math style selecting the text/script/scriptscript slot.
        """
        self._check_family(family)
        cs_name = self._slot_for_style(style)[family]
        if cs_name is None:
            return None
        return self._font_manager.get_metrics(cs_name)

    def font_cs_for(self, family: int, style: MathStyle) -> str | None:
        """Return the font CS name for ``(family, style)``, or None if unset.

        / §C.1: ``mlist_to_hlist`` needs the DVI font CS (not the
        FontMetrics object) to stamp on a ``CharNode``.  This mirrors
        :meth:`resolve_metrics` but returns the stored CS name directly.

        Args:
            family: Math family 0-15.
            style:  Math style selecting the text/script/scriptscript slot.
        """
        self._check_family(family)
        return self._slot_for_style(style)[family]

    def _slot_for_style(self, style: MathStyle) -> list[str | None]:
        # Dispatch by the enum member name to avoid a runtime import cycle with
        # math_font_parameters (which imports this module).  See §D.
        name = style.name
        if name == "TEXT":
            return self._text
        if name == "SCRIPT":
            return self._script
        if name == "SCRIPTSCRIPT":
            return self._scriptscript
        raise EngineError(f"unknown math style {style!r}")

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
        if font_cs not in self._font_manager._fonts:
            try:
                font_cs = self._font_manager.font_id(font_cs)
            except FontError:
                raise FontError(f"\\{role}{family}: operand is not a font") from None
        global_ = self._group_stack.assignment_is_global(command_global=global_)
        if not global_:
            old = slots[family]
            self._group_stack.save((role, family), lambda: slots.__setitem__(family, old))
        else:
            self._group_stack.retain_global((role, family))
        slots[family] = font_cs
        self._group_stack.consume_global()

    @staticmethod
    def _check_family(family: int) -> None:
        if not (0 <= family < _FAMILY_COUNT):
            raise EngineError(f"math family {family} out of range 0-15")
