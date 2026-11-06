"""TeX group save/restore stack.

Implements:
save-on-first-write per group level, global override, and aftergroup queuing.

See the project documentation for design rationale.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from contextlib import contextmanager
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aspose_tex._input.token import Token


class GroupKind(Enum):
    """Kind of TeX group.

    BRACE       — opened by ``{`` (catcode 1), closed by ``}`` (catcode 2).
    SEMI_SIMPLE — opened by ``\\begingroup``, closed by ``\\endgroup``.
    """

    BRACE = auto()
    SEMI_SIMPLE = auto()


def _retained() -> None:
    """Restore of a record a later global assignment overrode (TeX §283)."""


@dataclasses.dataclass(slots=True)
class _SaveRecord:
    """One entry on the save stack (private)."""

    key: tuple                   # deduplication key, e.g. ("count", 5)
    restore: Callable[[], None]  # zero-arg callable that restores the old value


@dataclasses.dataclass(slots=True)
class _GroupFrame:
    """State for one open group level (private)."""

    kind: GroupKind
    saved_keys: set          # keys already saved in this frame (dedup)
    records_start: int       # index into _save_records where this frame begins
    aftergroup: list         # list[Token] to emit after group closes


class GroupStack:
    """TeX group save/restore stack.

    Manages group nesting, save/restore of scoped assignments, the ``\\global``
    prefix flag, and ``\\aftergroup`` token insertion.

    Design ( NFR-1, NFR-2): save-on-first-write — each item is saved
    at most once per group level.  Restoration is O(number of local assignments).

    See for full design rationale.

    Example::

        from aspose_tex._engine.group import GroupStack, GroupKind

        gs = GroupStack()
        gs.open_group(GroupKind.BRACE)

        # before modifying count[0]:
        old = bank.count[0]
        gs.save(("count", 0), lambda: bank.count.__setitem__(0, old))
        bank.count[0] = 42

        # on group close — count[0] is restored:
        aftergroup_tokens, kind = gs.close_group()
    """

    def __init__(self) -> None:
        self._frames: list[_GroupFrame] = []
        self._save_records: list[_SaveRecord] = []
        self._global_pending: bool = False
        self._globaldefs_source: Callable[[], int] | None = None
        self._local_assignment_depth = 0

    # ------------------------------------------------------------------
    # Group depth
    # ------------------------------------------------------------------

    @property
    def depth(self) -> int:
        """Current group nesting depth (0 = global level)."""
        return len(self._frames)

    # ------------------------------------------------------------------
    # Global flag
    # ------------------------------------------------------------------

    @property
    def is_global_pending(self) -> bool:
        """True if the next assignment should be global (``\\global`` was seen,
        or we are already at depth 0 where all assignments are inherently global).
        """
        return self.assignment_is_global()

    def set_globaldefs_source(self, source: Callable[[], int] | None) -> None:
        """Install the raw live globaldefs reader.

        Args:
            source: Zero-argument parameter reader, or None for standalone use.
        """
        self._globaldefs_source = source

    def assignment_is_global(self, *, command_global: bool = False) -> bool:
        """Determine assignment scope from globaldefs and explicit prefixes.

        Args:
            command_global: Whether the command is intrinsically gdef/xdef.

        Returns:
            Whether the assignment must invalidate pending local restores.
        """
        if self._local_assignment_depth:
            return False
        value = self._globaldefs_source() if self._globaldefs_source is not None else 0
        if not self._frames:
            return True
        if value != 0:
            return value > 0
        return self._global_pending or command_global

    @contextmanager
    def local_assignment(self):
        """Force automatic engine writes local, preserving the caller's prefix.

        No user tokens may execute inside the guard. Nesting and exceptions
        restore both guard state and explicit prefix.
        """
        pending = self._global_pending
        self._local_assignment_depth += 1
        try:
            yield
        finally:
            self._local_assignment_depth -= 1
            self._global_pending = pending

    def set_global(self) -> None:
        """Activate the global flag (called when ``\\global`` is processed)."""
        self._global_pending = True

    def consume_global(self) -> None:
        """Clear the global flag after the global assignment is performed."""
        self._global_pending = False

    # ------------------------------------------------------------------
    # Group open / close
    # ------------------------------------------------------------------

    def open_group(self, kind: GroupKind) -> None:
        """Push a new group frame onto the stack.

        Args:
            kind: Whether this is a BRACE or SEMI_SIMPLE group.
        """
        self._frames.append(
            _GroupFrame(
                kind=kind,
                saved_keys=set(),
                records_start=len(self._save_records),
                aftergroup=[],
            )
        )

    def close_group(self) -> tuple[list[Token], GroupKind]:
        """Pop the innermost group, restore all saved values.

        Returns:
            ``(aftergroup_tokens, group_kind)`` — aftergroup tokens should be
            pushed onto the Expander's input stack in *reverse* order so that
            the first token is processed first.

        Raises:
            EngineError: if there is no open group (too many ``}``).
        """
        from aspose_tex.exceptions import EngineError

        if not self._frames:
            raise EngineError("Too many }'s")
        frame = self._frames.pop()
        # Restore in LIFO order (last saved → first restored)
        records = self._save_records[frame.records_start :]
        del self._save_records[frame.records_start :]
        for record in reversed(records):
            record.restore()
        return list(frame.aftergroup), frame.kind

    # ------------------------------------------------------------------
    # Save interface
    # ------------------------------------------------------------------

    def save(self, key: tuple, restore_fn: Callable[[], None]) -> None:
        """Save an item for restoration when the current group closes.

        No-op if:

        - There is no open group (global level — nothing to restore).
        - ``key`` was already saved in the current frame (save-on-first-write).

        Args:
            key:        Deduplication key, e.g. ``("count", 5)``,
                        ``("macro", "foo")``, ``("catcode", "@")``.
            restore_fn: Zero-argument callable that restores the old value.
        """
        if not self._frames:
            return
        frame = self._frames[-1]
        if key in frame.saved_keys:
            return
        frame.saved_keys.add(key)
        self._save_records.append(_SaveRecord(key=key, restore=restore_fn))

    def retain_global(self, key: tuple) -> None:
        """Keep a global assignment to ``key`` when the open groups close.

        TeX §283 does not restore a saved value over one assigned globally
        since: ``{\\def\\a{1}\\gdef\\a{2}}`` leaves ``\\a`` as ``2``.  The
        pending restores of ``key`` are dropped in every open group, and a
        later local assignment saves the global value afresh.

        Args:
            key: The key a global assignment has just written.
        """
        for frame in self._frames:
            frame.saved_keys.discard(key)
        for record in self._save_records:
            if record.key == key:
                record.restore = _retained

    # ------------------------------------------------------------------
    # Aftergroup
    # ------------------------------------------------------------------

    def push_aftergroup(self, token: Token) -> None:
        """Queue ``token`` to be reinserted after the current group closes.

        Args:
            token: Token to emit after group exit.

        Raises:
            EngineError: if called outside a group.
        """
        from aspose_tex.exceptions import EngineError

        if not self._frames:
            raise EngineError("\\aftergroup used outside a group")
        self._frames[-1].aftergroup.append(token)
