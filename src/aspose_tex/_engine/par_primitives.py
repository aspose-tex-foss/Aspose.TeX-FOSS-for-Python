r"""Paragraph accumulation and TeX primitive handlers for paragraph mode.

Implements:
ParagraphList, exec_par, exec_penalty, and infinite-glue helpers
(\\hfil, \\hfill, \\hfilneg, \\hss).

See the project documentation for design rationale.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from aspose_tex._engine.linebreak import LinebreakParams, break_paragraph
from aspose_tex._engine.nodes import (
 INF_PENALTY,
 NEG_INF_PENALTY,
 GlueNode,
 HlistNode,
 KernNode,
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

 pl = ParagraphList(parindent=0)
 assert pl.is_empty
 from aspose_tex._engine.nodes import CharNode
 pl.append(CharNode(char=ord('A'), font_name='tenrm'))
 assert not pl.is_empty
 """

 def __init__(self, parindent: int = 0) -> None:
 """Initialise with optional paragraph indentation.

 If parindent > 0, prepend an empty HlistNode of width parindent sp.
 The indentation box is NOT counted as content (is_empty stays True
 until a real non-discardable node is appended).

 Args:
 parindent: Indentation width in sp.
 """
 from aspose_tex._engine.nodes import GlueSign # avoid circular at module level
 self._nodes: list = []
 self._has_content: bool = False

 if parindent > 0:
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
 def is_empty(self) -> bool:
 """True if the paragraph has no non-discardable content."""
 return not self._has_content

 @property
 def nodes(self) -> list:
 """Read-only copy of the current node list."""
 return list(self._nodes)


def exec_par(
 par_list: ParagraphList,
 params: LinebreakParams,
 font_manager: FontManager,
 *,
 warnings: list[str] | None = None,
) -> list[HlistNode]:
 """Finalise the paragraph and run line breaking.

 Steps:
 1. If par_list.is_empty → return [].
 2. Strip trailing discardable nodes (GlueNode, PenaltyNode, KernNode).
 3. Append GlueNode(parfillskip) then PenaltyNode(NEG_INF_PENALTY).
 4. Call break_paragraph and return the result.

 Does NOT add \\parskip — the caller must prepend parskip glue to the
 vertical list before adding the returned lines.

 Args:
 par_list: The accumulated paragraph list.
 params: All line-breaking parameters.
 font_manager: For character width lookups.
 warnings: Optional list; warning strings are appended here.

 Returns:
 List of set HlistNode lines, each of width params.hsize.

 Example::

 pl = ParagraphList()
 lines = exec_par(pl, params, font_manager)
 assert lines == []
 """
 if par_list.is_empty:
 return []

 nodes = par_list.nodes

 # Strip trailing discardable nodes
 while nodes and isinstance(nodes[-1], (GlueNode, PenaltyNode, KernNode)):
 nodes.pop()

 if not nodes:
 return []

 # Append parfillskip and forced end-of-paragraph break
 nodes.append(GlueNode(glue=params.parfillskip))
 nodes.append(PenaltyNode(penalty=NEG_INF_PENALTY))

 return break_paragraph(nodes, params, font_manager, warnings=warnings)


def exec_penalty(value: int, par_list: ParagraphList) -> None:
 """Append PenaltyNode(value) to par_list.

 Clamps value to [-INF_PENALTY, INF_PENALTY].

 Args:
 value: Penalty value (will be clamped).
 par_list: Paragraph list to append to.

 Example::

 exec_penalty(-10000, pl) # forced break
 exec_penalty(99999, pl) # clamped to 10000
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
 r"""Return a GlueNode for \hfilneg — 0pt minus 1fil.

 Returns:
 GlueNode with shrink_order=FIL, width=0, stretch=0.

 Example::

 node = make_hfilneg_glue()
 assert node.glue.shrink_order == GlueOrder.FIL
 """
 return GlueNode(
 glue=Glue(
 width=0,
 stretch=0,
 stretch_order=GlueOrder.NORMAL,
 shrink=65536,
 shrink_order=GlueOrder.FIL,
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
