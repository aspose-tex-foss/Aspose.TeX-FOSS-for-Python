"""Private conditional-stack implementation for the TeX expansion engine.

Used exclusively by Expander to track nested \\if...\\fi state.
See the project documentation for design rationale.
"""

from __future__ import annotations

import dataclasses

from aspose_tex.exceptions import EngineError


@dataclasses.dataclass(slots=True)
class _CondEntry:
 """State for one \\if level.

 Attributes:
 if_name: The name of the opening primitive (e.g. ``"ifnum"``).
 true_branch: Whether the condition evaluated to True.
 in_else: Whether the scanner has already passed ``\\else``.
 case_value: For ``\\ifcase``: the integer value being tested.
 case_index: For ``\\ifcase``: the index of the currently active branch (0-based).
 """

 if_name: str
 true_branch: bool
 in_else: bool = False
 case_value: int = 0 # only meaningful for \ifcase
 case_index: int = 0 # only meaningful for \ifcase


class _ConditionalStack:
 """LIFO stack of \\if levels.

 Provides push / pop / current access and depth query.

 Example::

 cs = _ConditionalStack()
 cs.push(_CondEntry("iftrue", True))
 assert cs.depth() == 1
 assert cs.current().true_branch is True
 cs.pop()
 assert cs.depth() == 0
 """

 def __init__(self) -> None:
 self._stack: list[_CondEntry] = []

 def push(self, entry: _CondEntry) -> None:
 """Push a new conditional level."""
 self._stack.append(entry)

 def pop(self) -> _CondEntry:
 """Pop and return the top conditional level.

 Raises:
 EngineError: if the stack is empty (unmatched \\fi).
 """
 if not self._stack:
 raise EngineError("\\fi without matching \\if")
 return self._stack.pop()

 def current(self) -> _CondEntry | None:
 """Return the top entry without removing it, or None if empty."""
 return self._stack[-1] if self._stack else None

 def depth(self) -> int:
 """Return the number of currently open \\if levels."""
 return len(self._stack)
