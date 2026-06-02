"""Box construction: HBoxBuilder, VBoxBuilder, glue setting, badness.

Implements:
- ``HBoxBuilder`` processes character tokens and pre-built nodes,
 producing an ``HlistNode``.
- ``VBoxBuilder`` stacks horizontal boxes (and other vertical-mode material)
 into a ``VlistNode``.
- ``set_glue_hbox`` / ``set_glue_vbox`` set the glue-set fields in-place.
- ``compute_badness`` implements the standard TeX badness formula.

See the project documentation for design rationale.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from aspose_tex._engine.nodes import (
 INF_BAD,
 RUNNING_DIMEN,
 CharNode,
 DiscretionaryNode,
 GlueNode,
 GlueSign,
 HlistNode,
 KernNode,
 LeadersNode,
 PenaltyNode,
 RuleNode,
 VlistNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder

if TYPE_CHECKING:
 from aspose_tex._fonts.font_manager import FontManager


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _measure_hlist(
 nodes: list,
 font_manager: FontManager,
) -> tuple[int, int, int]:
 """Compute ``(width, height, depth)`` of a horizontal list.

 - ``width`` = sum of all node widths.
 - ``height`` = max height across all nodes.
 - ``depth`` = max depth across all nodes.

 For ``CharNode``: look up metrics via ``font_manager``.
 For ``GlueNode``: natural width = ``node.glue.width``; h = d = 0.
 For ``KernNode``: width = ``node.width``; h = d = 0.
 For ``PenaltyNode``, ``WhatsitNode``: zero contribution.
 For ``RuleNode``: use stored dimensions (``RUNNING_DIMEN`` treated as 0).
 For box nodes: use their stored width/height/depth.
 """
 total_w = 0
 max_h = 0
 max_d = 0
 for node in nodes:
 if isinstance(node, CharNode):
 m = font_manager.get_metrics(node.font_name)
 if m is not None:
 cm = m.char_metrics(node.char)
 total_w += cm.width
 if cm.height > max_h:
 max_h = cm.height
 if cm.depth > max_d:
 max_d = cm.depth
 elif isinstance(node, (HlistNode, VlistNode)):
 total_w += node.width
 if node.height > max_h:
 max_h = node.height
 if node.depth > max_d:
 max_d = node.depth
 elif isinstance(node, GlueNode):
 total_w += node.glue.width
 elif isinstance(node, KernNode):
 total_w += node.width
 elif isinstance(node, RuleNode):
 w = 0 if node.width == RUNNING_DIMEN else node.width
 h = 0 if node.height == RUNNING_DIMEN else node.height
 d = 0 if node.depth == RUNNING_DIMEN else node.depth
 total_w += w
 if h > max_h:
 max_h = h
 if d > max_d:
 max_d = d
 elif isinstance(node, DiscretionaryNode):
 w, h, d = _measure_hlist(list(node.nobreak), font_manager)
 total_w += w
 if h > max_h:
 max_h = h
 if d > max_d:
 max_d = d
 elif isinstance(node, LeadersNode):
 total_w += node.glue.width
 # PenaltyNode, WhatsitNode — no contribution
 return total_w, max_h, max_d


def _measure_vlist(
 nodes: list,
 font_manager: FontManager,
) -> tuple[int, int, int]:
 """Compute ``(width, height, depth)`` of a vertical list.

 - ``width`` = max width across all box nodes.
 - ``height`` = accumulated height: each box contributes prev_depth + box.height;
 glue/kerns add to height directly.
 - ``depth`` = depth of the last box node (0 if none).

 Algorithm:
 1. Iterate through nodes, tracking ``running_height`` and ``prev_depth``.
 2. For box nodes: ``running_height += prev_depth + node.height``;
 record ``prev_depth = node.depth`` and update ``max_width``.
 3. GlueNode: ``running_height += node.glue.width``.
 4. KernNode: ``running_height += node.width``.
 5. RuleNode: ``running_height += h + d`` (RUNNING_DIMEN treated as 0);
 update ``max_width``.
 6. PenaltyNode, WhatsitNode, CharNode: no contribution.
 7. Final height = running_height + prev_depth (the last box's contribution
 goes into depth, not height, so: height = running_height,
 depth = prev_depth after accounting for the algorithm above).

 Note: The standard TeX vertical-list geometry:
 - ``height`` is the distance from the top of the vbox to the baseline of the
 first box. For a simple stack of boxes without interline glue:
 ``vbox.height = h1.height``; successive boxes add ``h_i.depth + h_{i+1}.height``
 to the running height. The bottom box contributes only its depth to ``depth``.
 """
 max_w = 0
 running_h = 0
 prev_depth = 0
 current_depth = 0

 for node in nodes:
 if isinstance(node, (HlistNode, VlistNode)):
 running_h += prev_depth + node.height
 prev_depth = node.depth
 current_depth = node.depth
 if node.width > max_w:
 max_w = node.width
 elif isinstance(node, GlueNode):
 running_h += node.glue.width
 elif isinstance(node, KernNode):
 running_h += node.width
 elif isinstance(node, RuleNode):
 h = 0 if node.height == RUNNING_DIMEN else node.height
 d = 0 if node.depth == RUNNING_DIMEN else node.depth
 w = 0 if node.width == RUNNING_DIMEN else node.width
 running_h += prev_depth + h
 prev_depth = d
 current_depth = d
 if w > max_w:
 max_w = w
 # PenaltyNode, WhatsitNode, CharNode — no contribution

 return max_w, running_h, current_depth


def _vertical_extent(node) -> int:
 """Return the natural vertical contribution of one vertical-list node."""
 if isinstance(node, (HlistNode, VlistNode)):
 return node.height + node.depth
 if isinstance(node, GlueNode):
 return node.glue.width
 if isinstance(node, KernNode):
 return node.width
 if isinstance(node, RuleNode):
 h = 0 if node.height == RUNNING_DIMEN else node.height
 d = 0 if node.depth == RUNNING_DIMEN else node.depth
 return h + d
 return 0


def vsplit_at_height(
 box: VlistNode,
 target_height: int,
 *,
 splittopskip: Glue,
) -> tuple[VlistNode, VlistNode | None]:
 """Split *box* at *target_height* sp and return ``(top, residue)``.

 This is the M3 simplified ``\\vsplit`` algorithm: walk the
 vertical list from the front, stop before the first node that would exceed
 the requested height, and prepend ``\\splittopskip`` to the returned top
 piece when the split is non-empty. Precise ``\\splitmaxdepth`` handling is
 deferred to a future release.
 """
 split_idx = 0
 running = 0
 for idx, node in enumerate(box.list):
 extent = _vertical_extent(node)
 if idx > 0 and running + extent > target_height:
 break
 running += extent
 split_idx = idx + 1
 if running >= target_height:
 break

 head = list(box.list[:split_idx])
 tail = list(box.list[split_idx:])
 if head:
 while head and isinstance(head[0], (GlueNode, KernNode, PenaltyNode)):
 head.pop(0)
 head.insert(0, GlueNode(splittopskip))

 top = VlistNode(
 list=head,
 width=box.width,
 height=0,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 top.width, top.height, top.depth = _measure_vlist(top.list, _NullFontManager())
 if top.height < target_height:
 set_glue_vbox(top, target_height=target_height)

 if not tail:
 return top, None
 residue = VlistNode(
 list=tail,
 width=box.width,
 height=0,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 residue.width, residue.height, residue.depth = _measure_vlist(tail, _NullFontManager())
 return top, residue


class _NullFontManager:
 """Tiny measurement shim for vlist-only measurement paths."""

 def get_metrics(self, _font_name: str): # pragma: no cover - defensive
 return None


# ---------------------------------------------------------------------------
# Badness
# ---------------------------------------------------------------------------

def compute_badness(shortage: int, total_flex: int) -> int:
 """Return TeX badness for a box that needs *shortage* sp of flex.

 Standard TeX formula (TeXbook p. 97):
 - If ``shortage == 0``: return 0 (perfect fit).
 - If ``total_flex == 0`` or ratio > 1: return ``INF_BAD`` (10000).
 - Else: ``min(INF_BAD, round(100 * (shortage / total_flex) ** 3))``.

 Both arguments must be non-negative.

 Args:
 shortage: Absolute difference between target size and natural size.
 total_flex: Total stretch (stretching) or shrink (shrinking) in sp.

 Returns:
 Integer badness in range [0, 10000].

 Example::

 assert compute_badness(0, 1000) == 0
 assert compute_badness(500, 1000) == 12 # round(100 * 0.5**3)
 assert compute_badness(1001, 1000) == INF_BAD
 """
 if shortage == 0:
 return 0
 if total_flex == 0:
 return INF_BAD
 ratio = shortage / total_flex
 if ratio > 1.0:
 return INF_BAD
 return min(INF_BAD, round(100 * ratio ** 3))


# ---------------------------------------------------------------------------
# Glue setting
# ---------------------------------------------------------------------------

def _collect_stretch(nodes: list) -> dict:
 """Sum stretch per GlueOrder from all GlueNodes in nodes."""
 totals: dict[GlueOrder, int] = {o: 0 for o in GlueOrder}
 for node in nodes:
 if isinstance(node, GlueNode):
 totals[node.glue.stretch_order] += node.glue.stretch
 return totals


def _collect_shrink(nodes: list) -> dict:
 """Sum shrink per GlueOrder from all GlueNodes in nodes."""
 totals: dict[GlueOrder, int] = {o: 0 for o in GlueOrder}
 for node in nodes:
 if isinstance(node, GlueNode):
 totals[node.glue.shrink_order] += node.glue.shrink
 return totals


def _highest_order(totals: dict) -> GlueOrder:
 """Return the highest GlueOrder with nonzero total, or NORMAL if none."""
 for order in (GlueOrder.FILLL, GlueOrder.FILL, GlueOrder.FIL, GlueOrder.NORMAL):
 if totals[order] > 0:
 return order
 return GlueOrder.NORMAL


def set_glue_hbox(box: HlistNode, *, target_width: int) -> None:
 """Set glue-set fields on *box* in-place.

 Computes the stretch or shrink ratio required to reach *target_width*
 from the box's natural width (stored before this call as ``box.width``).
 Sets ``box.glue_sign``, ``box.glue_order``, ``box.glue_set``, and
 then updates ``box.width = target_width``.

 Does NOT emit overfull/underfull warnings — that is the caller's
 responsibility. See .
 """
 natural = box.width
 need = target_width - natural

 if need == 0:
 box.glue_sign = GlueSign.NORMAL
 box.glue_order = GlueOrder.NORMAL
 box.glue_set = 0.0
 box.width = target_width
 return

 if need > 0:
 totals = _collect_stretch(box.list)
 order = _highest_order(totals)
 total = totals[order]
 if total == 0:
 # No stretch available — overfull
 box.glue_sign = GlueSign.STRETCHING
 box.glue_order = GlueOrder.NORMAL
 box.glue_set = 0.0
 else:
 ratio = need / total
 box.glue_sign = GlueSign.STRETCHING
 box.glue_order = order
 box.glue_set = ratio
 else:
 # need < 0 — must shrink
 totals = _collect_shrink(box.list)
 order = _highest_order(totals)
 total = totals[order]
 if total == 0:
 box.glue_sign = GlueSign.SHRINKING
 box.glue_order = GlueOrder.NORMAL
 box.glue_set = 0.0
 else:
 ratio = (-need) / total
 if order == GlueOrder.NORMAL and ratio > 1.0:
 ratio = 1.0 # cap: cannot shrink past minimum
 box.glue_sign = GlueSign.SHRINKING
 box.glue_order = order
 box.glue_set = ratio

 box.width = target_width


def set_glue_vbox(box: VlistNode, *, target_height: int) -> None:
 """Set glue-set fields on *box* in-place (vertical analogue of ``set_glue_hbox``).

 Same algorithm as ``set_glue_hbox`` but operates on ``box.height``.
 Sets ``box.height = target_height`` after setting glue fields.
 """
 natural = box.height
 need = target_height - natural

 if need == 0:
 box.glue_sign = GlueSign.NORMAL
 box.glue_order = GlueOrder.NORMAL
 box.glue_set = 0.0
 box.height = target_height
 return

 if need > 0:
 totals = _collect_stretch(box.list)
 order = _highest_order(totals)
 total = totals[order]
 if total == 0:
 box.glue_sign = GlueSign.STRETCHING
 box.glue_order = GlueOrder.NORMAL
 box.glue_set = 0.0
 else:
 box.glue_sign = GlueSign.STRETCHING
 box.glue_order = order
 box.glue_set = need / total
 else:
 totals = _collect_shrink(box.list)
 order = _highest_order(totals)
 total = totals[order]
 if total == 0:
 box.glue_sign = GlueSign.SHRINKING
 box.glue_order = GlueOrder.NORMAL
 box.glue_set = 0.0
 else:
 ratio = (-need) / total
 if order == GlueOrder.NORMAL and ratio > 1.0:
 ratio = 1.0
 box.glue_sign = GlueSign.SHRINKING
 box.glue_order = order
 box.glue_set = ratio

 box.height = target_height


def _badness_for_box(box: HlistNode | VlistNode) -> int:
 """Return the finite-glue badness represented by a set box."""
 if box.glue_sign == GlueSign.NORMAL or box.glue_order != GlueOrder.NORMAL:
 return 0
 if box.glue_sign == GlueSign.STRETCHING:
 total = sum(
 n.glue.stretch for n in box.list
 if isinstance(n, GlueNode) and n.glue.stretch_order == GlueOrder.NORMAL
 )
 else:
 total = sum(
 n.glue.shrink for n in box.list
 if isinstance(n, GlueNode) and n.glue.shrink_order == GlueOrder.NORMAL
 )
 if total == 0:
 return INF_BAD
 shortage = round(box.glue_set * total)
 return compute_badness(shortage, total)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

class HBoxBuilder:
 """Accumulates nodes for one horizontal box.

 Usage::

 builder = HBoxBuilder(font_manager)
 builder.add_char(ord('H'), 'tenrm')
 builder.add_char(ord('i'), 'tenrm')
 box = builder.build()

 Args:
 font_manager: Used to look up character metrics and lig/kern tables
 when ``add_char`` is called.
 """

 def __init__(
 self,
 font_manager: FontManager,
 *,
 badness_sink: Callable[[int], None] | None = None,
 ) -> None:
 self._nodes: list = []
 self._font_manager = font_manager
 self._badness_sink = badness_sink

 def add_char(self, char: int, font_name: str) -> None:
 """Append a character, applying lig/kern with the previous character.

 Algorithm (applied only when the previous node is a ``CharNode``
 in the *same* font):

 1. Check for a ligature between the previous char and *char*.
 If found, replace the last ``CharNode`` with the ligature char
 and restart the check (loop until no more ligatures).
 2. Check for a kern between the previous char and *char*.
 If nonzero, insert a ``KernNode(kern_sp, explicit=False)``.
 3. Append ``CharNode(char, font_name)``.
 """
 metrics = self._font_manager.get_metrics(font_name)

 # Lig/kern processing — only when previous node is CharNode in same font
 if metrics is not None and self._nodes and isinstance(self._nodes[-1], CharNode):
 prev = self._nodes[-1]
 if prev.font_name == font_name:
 lig = metrics.ligature(prev.char, char)
 if lig is not None:
 # Replace the previous CharNode with the ligature glyph.
 # The current char is consumed by the ligature — do not append it.
 self._nodes[-1] = CharNode(char=lig, font_name=font_name)
 return
 # No ligature — check for kern
 kern_sp = metrics.kern(prev.char, char)
 if kern_sp:
 self._nodes.append(KernNode(width=kern_sp, explicit=False))

 self._nodes.append(CharNode(char=char, font_name=font_name))

 def add_kern(self, width: int, *, explicit: bool = True) -> None:
 """Append a ``KernNode``.

 Args:
 width: Space in sp.
 explicit: ``True`` for ``\\kern``; ``False`` for automatic font kern.
 """
 self._nodes.append(KernNode(width=width, explicit=explicit))

 def add_glue(self, glue: Glue) -> None:
 """Append a ``GlueNode``."""
 self._nodes.append(GlueNode(glue=glue))

 def add_penalty(self, penalty: int) -> None:
 """Append a ``PenaltyNode``."""
 self._nodes.append(PenaltyNode(penalty=penalty))

 def add_rule(self, width: int, height: int, depth: int) -> None:
 """Append a ``RuleNode``."""
 self._nodes.append(RuleNode(width=width, height=height, depth=depth))

 def add_box(self, box: HlistNode | VlistNode) -> None:
 """Append a sub-box node (nested ``\\hbox`` or ``\\vbox``)."""
 self._nodes.append(box)

 def build(
 self,
 *,
 target_width: int | None = None,
 spread: int | None = None,
 ) -> HlistNode:
 """Finalise and return the ``HlistNode``.

 1. Measure natural (width, height, depth) via ``_measure_hlist``.
 2. Compute ``final_width``:
 - ``target_width`` if given (``\\hbox to <d>``)
 - ``natural_width + spread`` if spread given (``\\hbox spread <d>``)
 - ``natural_width`` otherwise
 3. Construct HlistNode, call ``set_glue_hbox``, return.
 """
 nat_w, nat_h, nat_d = _measure_hlist(self._nodes, self._font_manager)

 if target_width is not None:
 final_width = target_width
 elif spread is not None:
 final_width = nat_w + spread
 else:
 final_width = nat_w

 box = HlistNode(
 list=self._nodes,
 width=nat_w,
 height=nat_h,
 depth=nat_d,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 set_glue_hbox(box, target_width=final_width)
 if self._badness_sink is not None:
 self._badness_sink(_badness_for_box(box))
 return box


class VBoxBuilder:
 """Accumulates nodes for one vertical box.

 Usage::

 vb = VBoxBuilder(font_manager)
 vb.add_hbox(hbox1)
 vb.add_hbox(hbox2)
 vbox = vb.build()
 """

 def __init__(
 self,
 font_manager: FontManager,
 *,
 badness_sink: Callable[[int], None] | None = None,
 ) -> None:
 self._nodes: list = []
 self._font_manager = font_manager
 self._badness_sink = badness_sink

 def add_hbox(self, box: HlistNode) -> None:
 """Append an ``HlistNode`` to the vertical list."""
 self._nodes.append(box)

 def add_vbox(self, box: VlistNode) -> None:
 """Append a ``VlistNode`` to the vertical list."""
 self._nodes.append(box)

 def add_kern(self, width: int) -> None:
 """Append a ``KernNode`` (vertical kern)."""
 self._nodes.append(KernNode(width=width, explicit=True))

 def add_glue(self, glue: Glue) -> None:
 """Append a ``GlueNode``."""
 self._nodes.append(GlueNode(glue=glue))

 def add_penalty(self, penalty: int) -> None:
 """Append a ``PenaltyNode``."""
 self._nodes.append(PenaltyNode(penalty=penalty))

 def add_rule(self, width: int, height: int, depth: int) -> None:
 """Append a ``RuleNode``."""
 self._nodes.append(RuleNode(width=width, height=height, depth=depth))

 def build(
 self,
 *,
 target_height: int | None = None,
 spread: int | None = None,
 ) -> VlistNode:
 """Finalise and return the ``VlistNode``.

 1. Measure natural (width, height, depth) via ``_measure_vlist``.
 2. Compute ``final_height``.
 3. Construct VlistNode, call ``set_glue_vbox``, return.
 """
 nat_w, nat_h, nat_d = _measure_vlist(self._nodes, self._font_manager)

 if target_height is not None:
 final_height = target_height
 elif spread is not None:
 final_height = nat_h + spread
 else:
 final_height = nat_h

 box = VlistNode(
 list=self._nodes,
 width=nat_w,
 height=nat_h,
 depth=nat_d,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 set_glue_vbox(box, target_height=final_height)
 if self._badness_sink is not None:
 self._badness_sink(_badness_for_box(box))
 return box
