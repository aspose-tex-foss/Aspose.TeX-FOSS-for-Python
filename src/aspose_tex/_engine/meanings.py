r"""One current binding per control-sequence name ( D2).

TeX keeps a single equivalent per name (§222): the last assignment of any
kind — ``\def``, ``\let``, ``\chardef``, ``\countdef``, ``\font`` — replaces
the previous one, and a group restores it.  The engine stores those bindings
in four owners: the expander's macro table, the register aliases and the
``\chardef`` constants of :class:`RegisterSet`, and the font table of
:class:`FontManager`.  :class:`MeaningBindings` keeps them exclusive: each
definer releases the name from every other owner first, scoped exactly like
the assignment, and the readers ask it for ``\meaning`` text and ``\ifx``
identity.

Font bindings are scoped like every other owner; loaded records persist
independently of names, and FONT values are opaque keys.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aspose_tex._engine.expansion import Expander
    from aspose_tex._engine.group import GroupStack
    from aspose_tex._engine.registers import RegisterSet
    from aspose_tex._fonts.font_manager import FontManager


class BindingKind(Enum):
    """Owner of a control-sequence binding."""

    MACRO = "macro"
    REGISTER = "register"
    CONSTANT = "constant"
    FONT = "font"


@dataclasses.dataclass(frozen=True, slots=True)
class Binding:
    """The current binding of a name.

    Attributes:
        kind:  Which owner holds it.
        value: ``Meaning`` for MACRO, ``(family, index)`` for REGISTER,
               ``(kind, value)`` for CONSTANT, the loaded-font key for FONT.
    """

    kind: BindingKind
    value: object


class MeaningBindings:
    r"""Keeps a name bound in exactly one owner ( D2).

    Args:
        expander:     Owner of macros and ``\let`` meanings.
        register_set: Owner of register aliases and ``\chardef`` constants.
        font_manager: Owner of font names.
        group_stack:  Shared save stack ( keys of each owner).

    Example::

        bindings = MeaningBindings(expander, register_set, font_manager, group_stack)
        bindings.release("c", BindingKind.CONSTANT, is_global=False)
        register_set.define_constant("c", "chardef", 65)
        assert bindings.meaning_text("c") == '\\char"41'
    """

    def __init__(
        self,
        expander: Expander,
        register_set: RegisterSet,
        font_manager: FontManager,
        group_stack: GroupStack,
    ) -> None:
        self._expander = expander
        self._register_set = register_set
        self._font_manager = font_manager
        self._group_stack = group_stack

    # ------------------------------------------------------------------
    # Exclusivity
    # ------------------------------------------------------------------

    def release(self, name: str, keep: BindingKind, *, is_global: bool) -> None:
        """Remove *name* from every owner except *keep*, scoped like the assignment.

        A global assignment drops the pending restores of the released keys
        (§283); a local one saves the old binding for the group end.  The
        ``\\global`` flag is left for the definer that follows.

        Args:
            name:      Control-sequence name without backslash.
            keep:      The owner the caller is about to write.
            is_global: Whether the caller's assignment is global.
        """
        if keep is not BindingKind.MACRO:
            self._drop(("macro", name), self._expander._macros, name, is_global)
        if keep is not BindingKind.REGISTER:
            self._drop(("alias", name), self._register_set._aliases, name, is_global)
        if keep is not BindingKind.CONSTANT:
            self._drop(("const", name), self._register_set._constants, name, is_global)
        if keep is not BindingKind.FONT:
            self._drop(("font", name), self._font_manager._font_bindings, name, is_global)

    @contextmanager
    def scanning_binding(self, name: str, provisional: Binding,
                         *, is_global: bool) -> Iterator[None]:
        """Install a scan-time target meaning with bounded rollback.

        Args:
            name: Definition target without its escape character.
            provisional: FONT/font-zero or MACRO/frozen-relax binding.
            is_global: Effective scope captured before scanning operands.

        Yields:
            Control to the scanner and final definition writer.

        Raises:
            BaseException: Rethrows scanner/loader failures after restoring only
                this target's owner entries and save history.
        """
        from aspose_tex._engine.macro import PrimitiveMeaning
        if not ((provisional.kind is BindingKind.FONT
                and provisional.value == self._font_manager._nullfont_id)
                or (provisional.kind is BindingKind.MACRO
                and provisional.value == PrimitiveMeaning("relax"))):
            raise ValueError("Unsupported scan-time target meaning")
        tables = {"macro": self._expander._macros,
                  "alias": self._register_set._aliases,
                  "const": self._register_set._constants,
                  "font": self._font_manager._font_bindings}
        entries = {owner: (name in table, table.get(name)) for owner, table in tables.items()}
        keys = {(owner, name) for owner in tables}
        gs = self._group_stack
        start = len(gs._save_records)
        callbacks = [(record, record.restore) for record in gs._save_records if record.key in keys]
        memberships = [(frame, frame.saved_keys & keys) for frame in gs._frames]
        try:
            self.release(name, provisional.kind, is_global=is_global)
            if provisional.kind is BindingKind.FONT:
                self._font_manager.bind_font(name, provisional.value, is_global=is_global)
            else:
                macros = self._expander._macros
                if is_global:
                    gs.retain_global(("macro", name))
                else:
                    present, old = entries["macro"]
                    gs.save(("macro", name), lambda: macros.__setitem__(name, old)
                            if present else macros.pop(name, None))
                macros[name] = provisional.value
            yield
        except BaseException:
            for owner, table in tables.items():
                present, old = entries[owner]
                if present:
                    table[name] = old
                else:
                    table.pop(name, None)
            gs._save_records[start:] = [record for record in gs._save_records[start:]
                                       if record.key not in keys]
            for record, callback in callbacks:
                record.restore = callback
            for frame, saved in memberships:
                frame.saved_keys.difference_update(keys)
                frame.saved_keys.update(saved)
            raise

    def _drop(self, key: tuple, table: dict, name: str, is_global: bool) -> None:
        # A preceding local release may already have removed the entry, but
        # its saved binding must still be discarded by a global assignment.
        if is_global:
            self._group_stack.retain_global(key)
        if name not in table:
            return
        old = table[name]
        if not is_global:
            self._group_stack.save(key, lambda: table.__setitem__(name, old))
        del table[name]

    # ------------------------------------------------------------------
    # Readers
    # ------------------------------------------------------------------

    def binding_of(self, name: str) -> Binding | None:
        """Return the current binding of *name*, or ``None`` if it has none."""
        macros = self._expander._macros
        if name in macros:
            return Binding(BindingKind.MACRO, macros[name])
        alias = self._register_set.resolve_alias(name)
        if alias is not None:
            return Binding(BindingKind.REGISTER, alias)
        const = self._register_set.resolve_constant(name)
        if const is not None:
            return Binding(BindingKind.CONSTANT, const)
        if self._font_manager.is_font(name):
            return Binding(BindingKind.FONT, self._font_manager.font_id(name))
        return None

    def copy_binding(self, target: str, source: str, *, is_global: bool) -> bool:
        r"""Give *target* the register, constant or font binding of *source* (§1221).

        Macro-table meanings are copied by the expander itself.

        Returns:
            ``True`` if *source* had such a binding and it was copied.
        """
        binding = (Binding(BindingKind.FONT, source) if source.startswith("\x00font:")
                   else self.binding_of(source))
        if binding is None or binding.kind is BindingKind.MACRO:
            return False
        if binding.kind is BindingKind.REGISTER:
            family, index = binding.value  # type: ignore[misc]
            self._register_set.define_alias(target, family, index)
        elif binding.kind is BindingKind.CONSTANT:
            kind, value = binding.value  # type: ignore[misc]
            self._register_set.define_constant(target, kind, value)
        else:
            self.release(target, BindingKind.FONT, is_global=is_global)
            self._font_manager.alias_font(target, binding.value, is_global=is_global)
            if self._group_stack._global_pending:
                self._group_stack.consume_global()
        return True

    def meaning_key(self, name: str) -> object | None:
        r"""Return the ``\ifx`` identity of a register, constant or font binding."""
        binding = self.binding_of(name)
        if binding is None or binding.kind is BindingKind.MACRO:
            return None
        if binding.kind is BindingKind.REGISTER:
            return ("reg", *binding.value)  # type: ignore[misc]
        if binding.kind is BindingKind.CONSTANT:
            return tuple(binding.value)  # type: ignore[arg-type]
        return ("font", binding.value)

    def meaning_text(self, name: str) -> str | None:
        r"""Return what ``\meaning`` prints for a register, constant or font binding."""
        binding = self.binding_of(name)
        if binding is None or binding.kind is BindingKind.MACRO:
            return None
        if binding.kind is BindingKind.REGISTER:
            family, index = binding.value  # type: ignore[misc]
            return f"\\{family}{index}"
        if binding.kind is BindingKind.CONSTANT:
            kind, value = binding.value  # type: ignore[misc]
            return f'\\{"char" if kind == "chardef" else "mathchar"}"{value:X}'
        return "select font " + self._font_manager.font_name_text(binding.value)
