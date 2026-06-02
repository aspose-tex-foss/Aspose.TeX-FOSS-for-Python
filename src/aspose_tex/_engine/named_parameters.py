"""Named TeX parameter registry: dispatcher for \\hsize, \\tolerance, etc.

Implements FR-10 through FR-15. Canonical pattern for
..022 — those specs register their entries against the same
``NamedParameterRegistry`` instance instead of growing scattered ``_exec_*``
handlers in the interpreter.

See for design rationale, slot map, and migration plan.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
 from aspose_tex._engine.expansion import Expander
 from aspose_tex._engine.group import GroupStack
 from aspose_tex._engine.registers import Glue, RegisterSet
 from aspose_tex._input.token import Token


class ParamKind(IntEnum):
 """Kind of a named TeX parameter ( FR-10)."""

 INT = 1
 DIMEN = 2
 SKIP = 3
 MUSKIP = 4
 TOKS = 5


@dataclasses.dataclass(slots=True)
class _Entry:
 """One named-parameter binding: CS name -> RegisterBank slot.

 Private to the engine; tests reach in via ``NamedParameterRegistry.lookup``.

 Mutable by design: ``on_set`` may be rebound after construction via
 :meth:`NamedParameterRegistry.set_on_set` (§Component 4c). The
 other fields are treated as immutable by convention — only ``on_set``
 is rebound post-registration.
 """

 name: str
 kind: ParamKind
 slot: int
 on_set: Callable[[Any], None] | None = None


class NamedParameterRegistry:
 """Lookup + dispatcher for TeX named parameters.

 Entries are populated at interpreter construction by
 ``_register_appendix_a()``; lookup is O(1) dict access (NFR-1). Storage
 delegates to ``RegisterSet`` for group save/restore — no parallel save
 mechanism is introduced (NFR-2).

 ``on_set`` lifecycle (two wiring paths):

 * **Registration-time.** Pass ``on_set=`` to :meth:`register`. Used by
 the ``PageBuilderConfig`` mirrors for ``\\vsize`` /
 ``\\maxdepth`` / ``\\topskip``, where the target object exists before
 ``_register_appendix_a`` is called.
 * **Post-construction.** Call :meth:`set_on_set` after registration.
 Used by §Component 4c for ``\\output`` and ``\\maxdeadcycles``,
 because their target (``PageBuilder``) is constructed *after*
 ``_register_appendix_a``. Reordering construction to wire those at
 registration time would break the mirrors above, so the
 two-path lifecycle is load-bearing — not transitional.

 Args:
 register_set: The RegisterSet whose RegisterBank holds the slot values.
 group_stack: Shared GroupStack (used only to honor ``\\global``;
 save-on-write is performed inside ``RegisterSet`` setters).

 Example::

 regs = RegisterSet(group_stack=group_stack)
 named = NamedParameterRegistry(regs, group_stack)
 named.register("hsize", ParamKind.DIMEN, 258, default=30_785_886)
 entry = named.lookup("hsize")
 # Dispatch \\hsize=6.5in:
 named.dispatch_assignment(entry, expander)
 # Dispatch \\the\\hsize:
 toks = named.dispatch_the(entry, expander)
 # Post-construction on_set bind (§Component 4c):
 named.set_on_set("output", lambda _v: page_builder.flip_gate())
 """

 __slots__ = ("_entries", "_group_stack", "_register_set", "_used_slots")

 def __init__(
 self, register_set: RegisterSet, group_stack: GroupStack
 ) -> None:
 self._register_set = register_set
 self._group_stack = group_stack
 self._entries: dict[str, _Entry] = {}
 self._used_slots: set[tuple[ParamKind, int]] = set()

 # ------------------------------------------------------------------
 # Catalog construction
 # ------------------------------------------------------------------

 def register(
 self,
 name: str,
 kind: ParamKind,
 slot: int,
 *,
 default: int | Glue | list[Token] | None = None,
 on_set: Callable[[Any], None] | None = None,
 ) -> None:
 """Register a named parameter and seed its initial value.

 Args:
 name: CS name without backslash (e.g. ``"hsize"``).
 kind: ParamKind enum value.
 slot: RegisterBank index. Named-param slots use the 256..319
 reserved pool; ``register()`` does not enforce this — the
 check is left to ``RegisterSet._check_internal_slot`` so
 test helpers may register at any internal slot.
 default: IniTeX / plain.tex default value, written via the matching
 ``RegisterSet.set_<kind>(slot, default, _internal=True)``
 bypassing GroupStack save (interpreter is not yet inside
 a group at construction time).
 on_set: Optional post-write hook called after every assignment with
 the new value. Used by the page-builder mirror in ;
 forbidden for new entries unless explicitly justified.

 Raises:
 EngineError: if ``name`` is already registered or if ``(kind, slot)``
 is already used.
 """
 if name in self._entries:
 raise EngineError(f"named parameter '{name}' already registered")
 slot_key = (kind, slot)
 if slot_key in self._used_slots:
 raise EngineError(
 f"named parameter slot {slot} already used for {kind.name}"
 )
 entry = _Entry(name=name, kind=kind, slot=slot, on_set=on_set)
 self._entries[name] = entry
 self._used_slots.add(slot_key)
 if default is not None:
 self._seed_default(entry, default)

 def lookup(self, name: str) -> _Entry | None:
 """Return the entry for ``name`` or ``None`` if not registered."""
 return self._entries.get(name)

 def set_on_set(
 self, name: str, callback: Callable[[Any], None] | None,
 ) -> None:
 """Bind (or clear) the ``on_set`` hook of an already-registered entry.

 Public companion to the ``on_set=`` constructor argument on
 :meth:`register`. Used for hooks whose target object is constructed
 *after* ``_register_appendix_a`` — §Component 4c specifies
 this path for ``\\output`` and ``\\maxdeadcycles``, whose
 ``PageBuilder`` / ``PageBuilderConfig`` targets are created later in
 ``TeXInterpreter.run_with_device``.

 Args:
 name: CS name of a previously registered parameter.
 callback: Hook invoked after every assignment with the new value,
 or ``None`` to clear an existing hook.

 Raises:
 EngineError: if ``name`` is not registered.
 """
 entry = self._entries.get(name)
 if entry is None:
 raise EngineError(
 f"cannot bind on_set: named parameter '{name}' is not registered"
 )
 entry.on_set = callback

 def _seed_default(self, entry: _Entry, default: Any) -> None:
 """Write the IniTeX default into the backing register slot.

 Bypasses GroupStack save by virtue of being called outside any open
 group (interpreter construction time — depth 0).
 """
 rs = self._register_set
 kind = entry.kind
 if kind == ParamKind.INT:
 rs.set_count(entry.slot, default, _internal=True)
 elif kind == ParamKind.DIMEN:
 rs.set_dimen(entry.slot, default, _internal=True)
 elif kind == ParamKind.SKIP:
 rs.set_skip(entry.slot, default, _internal=True)
 elif kind == ParamKind.MUSKIP:
 rs.set_muskip(entry.slot, default, _internal=True)
 elif kind == ParamKind.TOKS:
 rs.set_toks(entry.slot, list(default), _internal=True)
 else: # pragma: no cover — exhaustive by enum
 raise EngineError(f"unknown ParamKind {kind!r}")

 # ------------------------------------------------------------------
 # Dispatch
 # ------------------------------------------------------------------

 def dispatch_assignment(self, entry: _Entry, expander: Expander) -> None:
 """Execute ``\\<name> [=] <value>`` for a registered named parameter.

 Eats one optional ``=``; scans the value matching ``entry.kind``;
 writes via ``register_set.set_<kind>(entry.slot, value, _internal=True)``.
 ``\\global`` and group save/restore are handled by the existing setter.

 Raises:
 EngineError: on parse failure, kind/value mismatch, overflow.
 """
 from aspose_tex._engine.dimparser import (
 parse_dimen,
 parse_glue,
 parse_integer,
 )
 from aspose_tex._engine.registers import (
 _eat_optional_equals,
 _read_toks_value,
 )

 _eat_optional_equals(expander)
 rs = self._register_set
 kind = entry.kind
 if kind == ParamKind.INT:
 value: Any = parse_integer(expander)
 rs.set_count(entry.slot, value, _internal=True)
 elif kind == ParamKind.DIMEN:
 value = parse_dimen(expander)
 rs.set_dimen(entry.slot, value, _internal=True)
 elif kind == ParamKind.SKIP:
 value = parse_glue(expander)
 rs.set_skip(entry.slot, value, _internal=True)
 elif kind == ParamKind.MUSKIP:
 value = parse_glue(expander)
 rs.set_muskip(entry.slot, value, _internal=True)
 elif kind == ParamKind.TOKS:
 value = _read_toks_value(expander)
 rs.set_toks(entry.slot, value, _internal=True)
 else: # pragma: no cover — exhaustive by enum
 raise EngineError(f"unknown ParamKind {kind!r}")
 if entry.on_set is not None:
 entry.on_set(value)
 expander.fire_after_assignment()

 def dispatch_the(
 self, entry: _Entry, expander: Expander
 ) -> list[Token]:
 """Return the ``\\the\\<name>`` token list (delegates to RegisterSet helpers)."""
 # Avoid circular import at module load — these helpers are stable.
 from aspose_tex._engine.registers import (
 _glue_to_tokens,
 _int_to_tokens,
 _sp_to_tokens,
 )

 rs = self._register_set
 kind = entry.kind
 if kind == ParamKind.INT:
 return _int_to_tokens(rs.get_count(entry.slot, _internal=True))
 if kind == ParamKind.DIMEN:
 return _sp_to_tokens(rs.get_dimen(entry.slot, _internal=True))
 if kind == ParamKind.SKIP:
 return _glue_to_tokens(rs.get_skip(entry.slot, _internal=True))
 if kind == ParamKind.MUSKIP:
 return _glue_to_tokens(rs.get_muskip(entry.slot, _internal=True))
 if kind == ParamKind.TOKS:
 return list(rs.get_toks(entry.slot, _internal=True))
 raise EngineError(f"unknown ParamKind {kind!r}") # pragma: no cover


# ---------------------------------------------------------------------------
# Appendix A catalog ( / §"Slot Map")
# ---------------------------------------------------------------------------

# Each tuple is (name, slot, default). ``vsize`` (DIMEN slot 256), ``maxdepth``
# (DIMEN slot 257), and ``topskip`` (SKIP slot 256) are registered here as of
# ; their ``on_set`` mirrors are attached by ``_register_appendix_a``
# when ``page_config`` is provided so ``PageBuilderConfig`` keeps tracking
# user assignments after the legacy ``_exec_*`` handlers were retired.

_APPENDIX_A_INT: list[tuple[str, int, int]] = [
 ("pretolerance", 256, 0),
 ("tolerance", 257, 10000),
 ("hbadness", 258, 0),
 ("vbadness", 259, 0),
 ("linepenalty", 260, 0),
 ("hyphenpenalty", 261, 0),
 ("exhyphenpenalty", 262, 0),
 ("binoppenalty", 263, 0),
 ("relpenalty", 264, 0),
 ("clubpenalty", 265, 0),
 ("widowpenalty", 266, 0),
 ("displaywidowpenalty", 267, 0),
 ("brokenpenalty", 268, 0),
 ("predisplaypenalty", 269, 0),
 ("postdisplaypenalty", 270, 0),
 ("interlinepenalty", 271, 0),
 ("floatingpenalty", 272, 0),
 ("outputpenalty", 273, 0),
 ("doublehyphendemerits", 274, 0),
 ("finalhyphendemerits", 275, 0),
 ("adjdemerits", 276, 0),
 ("looseness", 277, 0),
 ("pausing", 278, 0),
 ("holdinginserts", 279, 0),
 ("tracingonline", 280, 0),
 ("tracingmacros", 281, 0),
 ("tracingstats", 282, 0),
 ("tracingparagraphs", 283, 0),
 ("tracingpages", 284, 0),
 ("tracingoutput", 285, 0),
 ("tracinglostchars", 286, 0),
 ("tracingcommands", 287, 0),
 ("tracingrestores", 288, 0),
 ("language", 289, 0),
 ("uchyph", 290, 1),
 ("lefthyphenmin", 291, 2),
 ("righthyphenmin", 292, 3),
 ("globaldefs", 293, 0),
 ("maxdeadcycles", 294, 25),
 ("hangafter", 295, 1),
 ("fam", 296, 0),
 ("mag", 297, 1000),
 ("escapechar", 298, 92),
 ("defaulthyphenchar", 299, -1),
 ("defaultskewchar", 300, -1),
 ("endlinechar", 301, 13),
 ("newlinechar", 302, -1),
 ("delimiterfactor", 303, 0),
 ("showboxbreadth", 304, 5),
 ("showboxdepth", 305, 3),
 ("errorcontextlines", 306, 5),
 # Slots 307 (\deadcycles) and 308 (\insertpenalties) were Appendix A
 # placeholders retired in — InternalQuantityRegistry now owns both
 # names (interpreter.py _build_internal_quantities); the placeholders
 # were unreachable through both _dispatch_cs and get_tokens_for_the.
]


def _build_appendix_a_dimen() -> list[tuple[str, int, int]]:
 """Return DIMEN entries with MAX_DIMEN-derived defaults resolved at call time."""
 from aspose_tex._engine.registers import MAX_DIMEN

 return [
 ("vsize", 256, 42_152_952), # 8.9in (plain.tex 340) — mirror
 ("maxdepth", 257, 262_144), # 4pt (plain.tex 341) — mirror
 ("hsize", 258, 30_785_886), # 6.5in (plain.tex 339)
 ("hfuzz", 259, 0),
 ("vfuzz", 260, 0),
 ("overfullrule", 261, 0),
 ("splitmaxdepth", 262, MAX_DIMEN),
 ("boxmaxdepth", 263, MAX_DIMEN),
 ("lineskiplimit", 264, 0),
 ("delimitershortfall", 265, 0),
 ("nulldelimiterspace", 266, 0),
 ("scriptspace", 267, 0),
 ("mathsurround", 268, 0),
 ("predisplaysize", 269, 0),
 ("displaywidth", 270, 0),
 ("displayindent", 271, 0),
 ("parindent", 272, 1_310_720), # 20pt
 ("hangindent", 273, 0),
 ("hoffset", 274, 0),
 ("voffset", 275, 0),
 # Slots 276..284 (\pagetotal, \pagegoal, \pagestretch,
 # \pagefilstretch, \pagefillstretch, \pagefilllstretch, \pageshrink,
 # \pagedepth, \prevdepth) were Appendix A placeholders retired in
 # — InternalQuantityRegistry now owns these page-state names
 # (interpreter.py _build_internal_quantities); the placeholders
 # were unreachable through both _dispatch_cs and get_tokens_for_the.
 ]


def _build_appendix_a_skip() -> list[tuple[str, int, Glue]]:
 """Return SKIP entries. ``topskip`` (slot 256) carries its IniTeX 10pt
 default and is mirrored onto ``PageBuilderConfig.topskip`` in ."""
 from aspose_tex._engine.registers import Glue, GlueOrder

 zero = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
 topskip = Glue(655_360, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL) # 10pt
 parfillskip = Glue(0, 65_536, GlueOrder.FIL, 0, GlueOrder.NORMAL)
 return [
 ("topskip", 256, topskip), # plain.tex 366 — mirror
 ("lineskip", 257, zero),
 ("baselineskip", 258, zero),
 ("parskip", 259, zero),
 ("abovedisplayskip", 260, zero),
 ("abovedisplayshortskip", 261, zero),
 ("belowdisplayskip", 262, zero),
 ("belowdisplayshortskip", 263, zero),
 ("leftskip", 264, zero),
 ("rightskip", 265, zero),
 ("splittopskip", 266, zero),
 ("tabskip", 267, zero),
 ("spaceskip", 268, zero),
 ("xspaceskip", 269, zero),
 ("parfillskip", 270, parfillskip),
 ]


def _build_appendix_a_muskip() -> list[tuple[str, int, Glue]]:
 """Return MUSKIP entries (slots 256-258)."""
 from aspose_tex._engine.registers import Glue, GlueOrder

 zero = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
 return [
 ("thinmuskip", 256, zero),
 ("medmuskip", 257, zero),
 ("thickmuskip", 258, zero),
 ]


_APPENDIX_A_TOKS: list[tuple[str, int, list[Token]]] = [
 ("output", 256, []),
 ("everypar", 257, []),
 ("everymath", 258, []),
 ("everydisplay", 259, []),
 ("everyhbox", 260, []),
 ("everyvbox", 261, []),
 ("everyjob", 262, []),
 ("everycr", 263, []),
 ("errhelp", 264, []),
]


def _register_appendix_a(
 named: NamedParameterRegistry,
 page_config: Any | None = None,
) -> None:
 """Populate ``named`` with the Appendix A catalog.

 98 entries land here as of : 51 INT (slots 256-306), 20 DIMEN
 (256-275), 15 SKIP (256-270), 3 MUSKIP (256-258), 9 TOKS (256-264).
 Slots 307-308 (INT) and 276-284 (DIMEN) were retired in because
 ``InternalQuantityRegistry`` intercepts those names before this registry
 is consulted in both ``_dispatch_cs`` and ``RegisterSet.get_tokens_for_the``.

 Clock counters (``\\year``, ``\\month``, ``\\day``, ``\\time``) are not
 in the registry — they remain as ``RegisterSet`` aliases at slots 0-3
 ( Q4).

 Args:
 named: A freshly constructed ``NamedParameterRegistry``.
 page_config: Optional ``PageBuilderConfig``. When provided,
 ``\\vsize`` / ``\\maxdepth`` / ``\\topskip`` / ``\\hsize``
 get ``on_set`` mirror callbacks so that user assignments
 keep ``PageBuilderConfig`` in sync — replaces the
 legacy ``_exec_vsize`` / ``_exec_topskip`` /
 ``_exec_maxdepth`` handlers retired by 
 (§"Migration plan"). ``\\hsize`` joined this set
 in / so the page box tracks the document
 width.
 """
 mirrors: dict[str, Callable[[Any], None]] = {}
 if page_config is not None:
 mirrors["vsize"] = lambda v: setattr(page_config, "vsize", v)
 mirrors["maxdepth"] = lambda v: setattr(page_config, "max_depth", v)
 mirrors["topskip"] = lambda v: setattr(page_config, "topskip", v)
 # \hsize → page-box width, read live by PlainOutputRoutine.execute
 #. Same mirror pattern as vsize/maxdepth.
 mirrors["hsize"] = lambda v: setattr(page_config, "hsize", v)

 for name, slot, default in _APPENDIX_A_INT:
 named.register(name, ParamKind.INT, slot, default=default)
 for name, slot, dimen_default in _build_appendix_a_dimen():
 named.register(
 name, ParamKind.DIMEN, slot,
 default=dimen_default, on_set=mirrors.get(name),
 )
 for name, slot, glue_default in _build_appendix_a_skip():
 named.register(
 name, ParamKind.SKIP, slot,
 default=glue_default, on_set=mirrors.get(name),
 )
 for name, slot, mu_default in _build_appendix_a_muskip():
 named.register(name, ParamKind.MUSKIP, slot, default=mu_default)
 for name, slot, toks_default in _APPENDIX_A_TOKS:
 named.register(name, ParamKind.TOKS, slot, default=toks_default)
