r"""Page mark registry for ``\mark`` and mark-reader expansion.

Implements the / M3 mark surface. The registry stores token
lists; output-routine rebinding in will consume the same state.
"""
from __future__ import annotations

from typing import Protocol

from aspose_tex._engine.nodes import HlistNode, MarkNode, VlistNode
from aspose_tex._input.token import Token
from aspose_tex.exceptions import EngineError


class MarksProvider(Protocol):
 """Expansion-side provider for TeX's five mark-reader primitives."""

 def get_marks_tokens(self, name: str) -> tuple[Token, ...]:
 """Return tokens for one mark reader name."""
 ...


class MarksRegistry:
 """Tracks page and split marks for the current interpreter run."""

 def __init__(self) -> None:
 self._top: tuple[Token, ...] = ()
 self._first: tuple[Token, ...] = ()
 self._bot: tuple[Token, ...] = ()
 self._split_first: tuple[Token, ...] = ()
 self._split_bot: tuple[Token, ...] = ()
 self._seen_first_this_page = False

 def execute_mark(self, tokens: tuple[Token, ...]) -> MarkNode:
 """Create a mark node carrying *tokens*."""
 return MarkNode(tokens=tokens)

 def record_mark_on_shipout(self, page_nodes: list) -> None:
 """Scan shipped page material and update first/bot mark state."""
 for node in self._walk_nodes(page_nodes):
 if not self._seen_first_this_page:
 self._first = node.tokens
 self._seen_first_this_page = True
 self._bot = node.tokens

 def first_mark(self) -> tuple[Token, ...]:
 """Return ``\firstmark`` tokens for the current output page."""
 return self._first

 def top_mark(self) -> tuple[Token, ...]:
 """Return ``\topmark`` tokens inherited from the previous page."""
 return self._top

 def bot_mark(self) -> tuple[Token, ...]:
 """Return ``\botmark`` tokens for the current output page."""
 return self._bot

 def split_first_mark(self) -> tuple[Token, ...]:
 r"""Return ``\splitfirstmark`` tokens from the most recent split."""
 return self._split_first

 def split_bot_mark(self) -> tuple[Token, ...]:
 r"""Return ``\splitbotmark`` tokens from the most recent split."""
 return self._split_bot

 def capture_split(self, head_nodes: list) -> None:
 """Capture first and bottom marks from split-off ``\vsplit`` material."""
 marks = [node.tokens for node in self._walk_nodes(head_nodes)]
 self._split_first = marks[0] if marks else ()
 self._split_bot = marks[-1] if marks else ()

 def reset_for_new_page(self) -> None:
 """Promote the shipped page's bottom mark and clear current-page state."""
 if self._seen_first_this_page:
 self._top = self._bot
 self._first = ()
 self._bot = ()
 self._seen_first_this_page = False

 def get_marks_tokens(self, name: str) -> tuple[Token, ...]:
 """Return the token list for one TeX mark-reader primitive."""
 if name == "firstmark":
 return self.first_mark()
 if name == "topmark":
 return self.top_mark()
 if name == "botmark":
 return self.bot_mark()
 if name == "splitfirstmark":
 return self.split_first_mark()
 if name == "splitbotmark":
 return self.split_bot_mark()
 raise EngineError(f"unknown mark reader: \\{name}")

 def _walk_nodes(self, nodes: list) -> list[MarkNode]:
 """Return mark nodes nested in *nodes* in list order."""
 found: list[MarkNode] = []
 for node in nodes:
 if isinstance(node, MarkNode):
 found.append(node)
 elif isinstance(node, (HlistNode, VlistNode)):
 found.extend(self._walk_nodes(node.list))
 return found
