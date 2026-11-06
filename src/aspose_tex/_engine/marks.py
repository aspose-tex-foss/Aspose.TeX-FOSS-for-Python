r"""Page mark registry for ``\mark`` and mark-reader expansion.

Implements mark readers and fire_up timing.
Page selection is the only page-mark transition; shipout/output end retain it.
"""
from __future__ import annotations

from typing import Protocol

from aspose_tex._engine.nodes import MarkNode
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
        self._top: tuple[Token, ...] | None = None
        self._first: tuple[Token, ...] | None = None
        self._bot: tuple[Token, ...] | None = None
        self._split_first: tuple[Token, ...] = ()
        self._split_bot: tuple[Token, ...] = ()

    def execute_mark(self, tokens: tuple[Token, ...]) -> MarkNode:
        """Create a mark node carrying *tokens*."""
        return MarkNode(tokens=tokens)

    def fire_up(self, page_nodes: list) -> None:
        r"""Update page marks at selection, per TeX §§1012/1014.

        Called once per selected page, before insertion distribution and
        before \output runs. Empty marks are non-null token lists.

        Args:
            page_nodes: Selected page material; only direct marks are scanned.
        """
        if self._bot is not None:
            self._top = self._bot
            self._first = None
        for node in self._walk_nodes(page_nodes):
            if self._first is None:
                self._first = node.tokens
            self._bot = node.tokens
        if self._top is not None and self._first is None:
            self._first = self._top

    def first_mark(self) -> tuple[Token, ...]:
        """Return ``\firstmark`` tokens for the current output page."""
        return () if self._first is None else self._first

    def top_mark(self) -> tuple[Token, ...]:
        """Return ``\topmark`` tokens inherited from the previous page."""
        return () if self._top is None else self._top

    def bot_mark(self) -> tuple[Token, ...]:
        """Return ``\botmark`` tokens for the current output page."""
        return () if self._bot is None else self._bot

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
        """Return direct marks only; ordinary boxes retain their marks (§1016)."""
        return [node for node in nodes if isinstance(node, MarkNode)]
