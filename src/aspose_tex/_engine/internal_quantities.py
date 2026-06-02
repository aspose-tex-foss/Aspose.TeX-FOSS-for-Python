r"""Internal-quantity registry for TeX pseudo-register readers.

This module implements the callback-backed dispatcher for quantities
such as ``\spacefactor`` and ``\pagetotal``. It mirrors the name-dispatch
shape of ``NamedParameterRegistry`` without allocating RegisterBank slots.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from enum import IntEnum
from typing import TYPE_CHECKING

from aspose_tex._engine.registers import Glue, _glue_to_tokens, _int_to_tokens, _sp_to_tokens
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, Token
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
 from aspose_tex._engine.expansion import Expander
 from aspose_tex._engine.interpreter import ModeKind, ModeStack


class QuantityKind(IntEnum):
 """Value category for a TeX internal quantity."""

 INT = 1
 DIMEN = 2
 SKIP = 3
 MUSKIP = 4


@dataclasses.dataclass(frozen=True, slots=True)
class _Entry:
 """One internal-quantity binding."""

 name: str
 kind: QuantityKind
 getter: Callable[[], int | Glue]
 setter: Callable[[int | Glue], None] | None = None
 allowed_modes: frozenset[ModeKind] | None = None


class InternalQuantityRegistry:
 r"""Lookup and dispatcher for callback-backed TeX internal quantities.

 The registry exposes pseudo-registers such as ``\spacefactor`` and
 ``\pagetotal`` while leaving storage with the owning component. Values are
 read through callbacks on every dispatch, so page-builder quantities stay
 live and no parallel ``RegisterBank`` slots are allocated.

 Args:
 mode_stack: Interpreter mode stack used to enforce per-quantity read
 and write guards.

 Example:
 >>> from aspose_tex._engine.interpreter import ModeStack
 >>> mode_stack = ModeStack()
 >>> state = {"spacefactor": 1000}
 >>> registry = InternalQuantityRegistry(mode_stack)
 >>> registry.register(
 ... "spacefactor",
 ... QuantityKind.INT,
 ... getter=lambda: state["spacefactor"],
 ... setter=lambda value: state.__setitem__("spacefactor", int(value)),
 ... )
 >>> entry = registry.lookup("spacefactor")
 """

 def __init__(self, mode_stack: ModeStack) -> None:
 self._mode_stack = mode_stack
 self._entries: dict[str, _Entry] = {}

 def register(
 self,
 name: str,
 kind: QuantityKind,
 getter: Callable[[], int | Glue],
 *,
 setter: Callable[[int | Glue], None] | None = None,
 allowed_modes: frozenset[ModeKind] | None = None,
 ) -> None:
 """Register one internal quantity.

 Raises:
 EngineError: If *name* is already registered.
 """
 if name in self._entries:
 raise EngineError(f"internal quantity \\{name} already registered")
 self._entries[name] = _Entry(
 name=name,
 kind=kind,
 getter=getter,
 setter=setter,
 allowed_modes=allowed_modes,
 )

 def lookup(self, name: str) -> _Entry | None:
 """Return the registered entry for *name*, if any."""
 return self._entries.get(name)

 def read_value(self, entry: _Entry) -> int | Glue:
 """Read an entry after enforcing its mode guard."""
 self._check_mode(entry)
 return entry.getter()

 def dispatch_assignment(self, entry: _Entry, expander: Expander) -> None:
 r"""Execute an assignment to ``\entry.name``."""
 if entry.setter is None:
 raise EngineError(f"\\{entry.name} is read-only")
 self._check_mode(entry)
 self._eat_optional_equals(expander)

 if entry.kind == QuantityKind.INT:
 from aspose_tex._engine.dimparser import parse_integer

 value: int | Glue = parse_integer(expander)
 elif entry.kind == QuantityKind.DIMEN:
 from aspose_tex._engine.dimparser import parse_dimen

 value = parse_dimen(expander)
 elif entry.kind in (QuantityKind.SKIP, QuantityKind.MUSKIP):
 from aspose_tex._engine.dimparser import parse_glue

 value = parse_glue(expander)
 else: # pragma: no cover - enum exhaustiveness guard
 raise EngineError(f"unsupported internal quantity kind: {entry.kind}")

 entry.setter(value)
 expander.fire_after_assignment()

 def dispatch_the(self, entry: _Entry, expander: Expander) -> list[Token]:
 r"""Return tokenized text for ``\the\entry.name``."""
 value = self.read_value(entry)
 if entry.kind == QuantityKind.INT:
 return _int_to_tokens(int(value))
 if entry.kind == QuantityKind.DIMEN:
 return _sp_to_tokens(int(value))
 if entry.kind in (QuantityKind.SKIP, QuantityKind.MUSKIP):
 if not isinstance(value, Glue):
 raise EngineError(f"\\{entry.name}: expected glue value")
 return _glue_to_tokens(value)
 raise EngineError(f"unsupported internal quantity kind: {entry.kind}")

 def _check_mode(self, entry: _Entry) -> None:
 if entry.allowed_modes is None:
 return
 if self._mode_stack.current not in entry.allowed_modes:
 label = _mode_label(entry.allowed_modes)
 raise EngineError(f"\\{entry.name} only valid in {label} mode")

 @staticmethod
 def _eat_optional_equals(expander: Expander) -> None:
 tok = expander.peek()
 while isinstance(tok, CharToken) and tok.catcode == Catcode.SPACE:
 expander._next_raw()
 tok = expander.peek()
 if isinstance(tok, CharToken) and tok.char == "=" and tok.catcode == Catcode.OTHER:
 expander._next_raw()


def _mode_label(modes: frozenset[ModeKind]) -> str:
 names = {mode.name for mode in modes}
 if {"HORIZONTAL", "RESTRICTED_HORIZONTAL"} <= names:
 return "horizontal"
 if {"OUTER_VERTICAL", "INTERNAL_VERTICAL"} <= names:
 return "vertical"
 return "/".join(sorted(name.lower() for name in names))
