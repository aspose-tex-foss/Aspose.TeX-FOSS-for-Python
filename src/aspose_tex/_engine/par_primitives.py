r"""Paragraph accumulation and TeX primitive handlers for paragraph mode.

Implements:
ParagraphList, exec_par, exec_penalty, and infinite-glue helpers
(\\hfil, \\hfill, \\hfilneg, \\hss).

See the project documentation for design rationale.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from aspose_tex._engine.linebreak import LinebreakParams, break_paragraph
from aspose_tex._engine.nodes import (
    INF_PENALTY,
    NEG_INF_PENALTY,
    GlueNode,
    HlistNode,
    KernNode,
    LeadersNode,
    PenaltyNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder

if TYPE_CHECKING:
    from aspose_tex._engine.nodes import Node
    from aspose_tex._fonts.font_manager import FontManager


class ParagraphList:
    """Accumulates nodes for the current paragraph (horizontal mode).

    The caller (engine main loop) holds one instance per open paragraph.

    Example::

        pl = ParagraphList()
        assert pl.is_empty
        from aspose_tex._engine.nodes import CharNode
        pl.append(CharNode(char=ord('A'), font_name='tenrm'))
        assert not pl.is_empty
    """

    def __init__(
        self, parindent: int | None = None, *,
        language: int = 0, left_min: int = 1, right_min: int = 1,
    ) -> None:
        r"""Initialise with optional paragraph indentation.

        If *parindent* is not ``None``, prepend an empty HlistNode of width
        *parindent* sp — even a zero or negative one, as TeX §1091 does for
        every ``\indent``-ed paragraph.  ``None`` means ``\noindent`` (no box).
        The indentation box is NOT counted as content (is_empty stays True
        until a real non-discardable node is appended).

        Args:
            parindent: Indentation width in sp, or ``None`` for no indent box.
            language:  The paragraph's hyphenation language, recorded when it
                starts or resumes after a display (§1091, §6).
            left_min:  ``norm_min(\lefthyphenmin)`` recorded with it.
            right_min: ``norm_min(\righthyphenmin)`` recorded with it.

        ``current_language`` (TeX's ``clang``) starts at *language* and follows
        the language whatsits appended to the list (§1376-§1377, §7).
        ``start_line`` is the input line the paragraph began on, set by the
        interpreter for its line reports (§663, §8).

        Example::

            pl = ParagraphList(parindent=20 * 65_536, language=0, left_min=2, right_min=3)
            assert pl.is_empty
        """
        from aspose_tex._engine.nodes import GlueSign  # avoid circular at module level
        self._nodes: list = []
        self._has_content: bool = False
        self._language = language
        self._left_min = left_min
        self._right_min = right_min
        self.current_language = language
        self.start_line = 0

        if parindent is not None:
            indent_box = HlistNode(
                list=[],
                width=parindent,
                height=0,
                depth=0,
                shift_amount=0,
                glue_sign=GlueSign.NORMAL,
                glue_order=GlueOrder.NORMAL,
                glue_set=0.0,
            )
            self._nodes.append(indent_box)

    def append(self, node: Node) -> None:
        """Append a node to the paragraph list.

        Sets _has_content = True for non-discardable nodes
        (i.e. not GlueNode, PenaltyNode, or KernNode).

        Args:
            node: Node to append.
        """
        self._nodes.append(node)
        if not isinstance(node, (GlueNode, PenaltyNode, KernNode)):
            self._has_content = True

    @property
    def language(self) -> int:
        """The hyphenation language recorded for the paragraph (§1091)."""
        return self._language

    @property
    def left_min(self) -> int:
        """The left hyphenation minimum recorded with :attr:`language`."""
        return self._left_min

    @property
    def right_min(self) -> int:
        """The right hyphenation minimum recorded with :attr:`language`."""
        return self._right_min

    @property
    def is_empty(self) -> bool:
        """True if the paragraph has no non-discardable content."""
        return not self._has_content

    @property
    def nodes(self) -> list:
        """Read-only copy of the current node list."""
        return list(self._nodes)

    @property
    def last_node(self):
        """The tail node of the list, or ``None`` if it is empty.

        Cheap tail access for primitives that must inspect what precedes them
        (e.g. ``\\/``, TeX:The Program §1112) without copying the whole list.

        Example::

            pl = ParagraphList()
            assert pl.last_node is None
        """
        return self._nodes[-1] if self._nodes else None


def exec_par(
    par_list: ParagraphList,
    params: LinebreakParams,
    font_manager: FontManager,
    *,
    warnings: list[str] | None = None,
    disc_breaks: list[bool] | None = None,
    hyphenate: Callable[[list], list] | None = None,
    line_reports: list[tuple[str, list]] | None = None,
) -> list[HlistNode]:
    """Finalise the paragraph and run line breaking.

    Steps:
    1. If par_list holds no node at all → return [].  A list holding only
       its indent box or glue still breaks into one (empty-looking) line,
       as TeX §1096 line-breaks every paragraph but a void one.
    2. Replace the final glue with INF_PENALTY, or append that penalty.
    3. Append GlueNode(parfillskip) then PenaltyNode(NEG_INF_PENALTY).
    4. Call break_paragraph and return the result.

    Does NOT add \\parskip — the caller must prepend parskip glue to the
    vertical list before adding the returned lines.

    Args:
        par_list:     The accumulated paragraph list.
        params:       All line-breaking parameters.
        font_manager: For character width lookups.
        warnings:     Optional list; warning strings are appended here.
        disc_breaks:  Optional list; receives one flag per line, True when
                      the line ends at a discretionary (see break_paragraph).
        hyphenate:    Optional hyphenation step of the second pass (see
                      break_paragraph, §6).
        line_reports: Optional list; receives one ``(header, material)`` pair
                      per reported line (see break_paragraph, §8).

    Returns:
        List of set HlistNode lines, each of width params.hsize.

    Example::

        pl = ParagraphList()
        lines = exec_par(pl, params, font_manager)
        assert lines == []
    """
    if par_list.last_node is None:
        return []

    nodes = par_list.nodes

    # TeX §816 /: only the last glue is replaced. Earlier forced
    # penalties and kerns remain meaningful, including consecutive empty lines.
    if nodes and isinstance(nodes[-1], (GlueNode, LeadersNode)):
        nodes[-1] = PenaltyNode(penalty=INF_PENALTY)
    else:
        nodes.append(PenaltyNode(penalty=INF_PENALTY))

    # Append parfillskip and forced end-of-paragraph break
    nodes.append(GlueNode(glue=params.parfillskip))
    nodes.append(PenaltyNode(penalty=NEG_INF_PENALTY))

    return break_paragraph(
        nodes, params, font_manager, warnings=warnings, disc_breaks=disc_breaks,
        hyphenate=hyphenate, line_reports=line_reports,
    )


def exec_penalty(value: int, par_list: ParagraphList) -> None:
    """Append PenaltyNode(value) to par_list.

    Clamps value to [-INF_PENALTY, INF_PENALTY].

    Args:
        value:    Penalty value (will be clamped).
        par_list: Paragraph list to append to.

    Example::

        exec_penalty(-10000, pl)  # forced break
        exec_penalty(99999, pl)   # clamped to 10000
    """
    clamped = max(-INF_PENALTY, min(INF_PENALTY, value))
    par_list.append(PenaltyNode(penalty=clamped))


def make_hfil_glue() -> GlueNode:
    r"""Return a GlueNode for \hfil — 0pt plus 1fil.

    Returns:
        GlueNode with stretch_order=FIL, width=0, shrink=0.

    Example::

        node = make_hfil_glue()
        assert node.glue.stretch_order == GlueOrder.FIL
    """
    return GlueNode(
        glue=Glue(
            width=0,
            stretch=65536,
            stretch_order=GlueOrder.FIL,
            shrink=0,
            shrink_order=GlueOrder.NORMAL,
        )
    )


def make_hfill_glue() -> GlueNode:
    r"""Return a GlueNode for \hfill — 0pt plus 1fill.

    Returns:
        GlueNode with stretch_order=FILL, width=0, shrink=0.

    Example::

        node = make_hfill_glue()
        assert node.glue.stretch_order == GlueOrder.FILL
    """
    return GlueNode(
        glue=Glue(
            width=0,
            stretch=65536,
            stretch_order=GlueOrder.FILL,
            shrink=0,
            shrink_order=GlueOrder.NORMAL,
        )
    )


def make_hfilneg_glue() -> GlueNode:
    r"""Return a GlueNode for \hfilneg — 0pt plus -1fil.

    Returns:
        GlueNode with stretch_order=FIL, width=0, stretch=-65536.

    Example::

        node = make_hfilneg_glue()
        assert node.glue.stretch == -65536
    """
    return GlueNode(
        glue=Glue(
            width=0,
            stretch=-65536,
            stretch_order=GlueOrder.FIL,
            shrink=0,
            shrink_order=GlueOrder.NORMAL,
        )
    )


def make_hss_glue() -> GlueNode:
    r"""Return a GlueNode for \hss — 0pt plus 1fil minus 1fil.

    Returns:
        GlueNode with both stretch_order and shrink_order == FIL.

    Example::

        node = make_hss_glue()
        assert node.glue.stretch_order == GlueOrder.FIL
        assert node.glue.shrink_order == GlueOrder.FIL
    """
    return GlueNode(
        glue=Glue(
            width=0,
            stretch=65536,
            stretch_order=GlueOrder.FIL,
            shrink=65536,
            shrink_order=GlueOrder.FIL,
        )
    )
