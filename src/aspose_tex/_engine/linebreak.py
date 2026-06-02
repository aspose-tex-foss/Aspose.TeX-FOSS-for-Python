"""Knuth-Plass optimal paragraph line-breaking algorithm.

Implements:
the pure algorithmic core — no I/O, no side effects.

See the project documentation for design rationale.
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from aspose_tex._engine.box_builder import _measure_hlist, compute_badness, set_glue_hbox
from aspose_tex._engine.nodes import (
 INF_BAD,
 NEG_INF_PENALTY,
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
# Fitness classes
# ---------------------------------------------------------------------------

_FITNESS_VERY_LOOSE: int = 0 # r > 1
_FITNESS_LOOSE: int = 1 # 0.5 < r ≤ 1
_FITNESS_DECENT: int = 2 # -0.5 ≤ r ≤ 0.5
_FITNESS_TIGHT: int = 3 # r < -0.5


# ---------------------------------------------------------------------------
# Public parameters dataclass
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True, slots=True)
class LinebreakParams:
 """All tunable parameters required by the line-breaker.

 All dimension fields are in scaled points (sp).

 Example::

 params = LinebreakParams(
 hsize=6054984,
 tolerance=200,
 pretolerance=100,
 linepenalty=10,
 adjdemerits=10000,
 leftskip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 rightskip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 parfillskip=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL),
 )
 """

 hsize: int
 tolerance: int
 pretolerance: int
 linepenalty: int
 adjdemerits: int
 leftskip: Glue
 rightskip: Glue
 parfillskip: Glue


# ---------------------------------------------------------------------------
# Internal DP node
# ---------------------------------------------------------------------------

@dataclasses.dataclass(slots=True)
class _Active:
 """One candidate break-chain node in the DP active list."""

 position: int # index into nodes where this break occurs; -1 = start
 line_number: int # 1-based line number ending at this break
 fitness: int # 0..3 fitness class
 total_demerits: float # accumulated demerits from start
 predecessor: _Active | None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _node_natural_width(node: object, font_manager: FontManager) -> int:
 """Return the natural width contribution of a single node in sp.

 CharNode → font character width from font_manager.
 GlueNode → natural glue width only.
 KernNode → kern width.
 HlistNode / VlistNode → stored width.
 RuleNode → stored width (RUNNING_DIMEN treated as 0).
 DiscretionaryNode → M3 nobreak-branch width.
 PenaltyNode, WhatsitNode → 0.
 """
 if isinstance(node, CharNode):
 m = font_manager.get_metrics(node.font_name)
 if m is not None:
 return m.char_metrics(node.char).width
 return 0
 if isinstance(node, GlueNode):
 return node.glue.width
 if isinstance(node, KernNode):
 return node.width
 if isinstance(node, (HlistNode, VlistNode)):
 return node.width
 if isinstance(node, RuleNode):
 return 0 if node.width == RUNNING_DIMEN else node.width
 if isinstance(node, DiscretionaryNode):
 return sum(_node_natural_width(child, font_manager) for child in node.nobreak)
 if isinstance(node, LeadersNode):
 return node.glue.width
 # PenaltyNode, WhatsitNode
 return 0


def _is_legal_breakpoint(nodes: list, i: int) -> bool:
 """Return True if position i is a legal breakpoint.

 Legal:
 - GlueNode at i, provided the immediately preceding item is not a
 GlueNode, PenaltyNode, or explicit KernNode.
 - PenaltyNode at i with penalty < INF_PENALTY (10000).
 """
 node = nodes[i]
 if isinstance(node, GlueNode):
 if i == 0:
 return False
 prev = nodes[i - 1]
 if isinstance(prev, (GlueNode, PenaltyNode)):
 return False
 return not (isinstance(prev, KernNode) and prev.explicit)
 if isinstance(node, PenaltyNode):
 return node.penalty < 10_000 # INF_PENALTY
 return isinstance(node, DiscretionaryNode)


def _adjustment_ratio(
 need: int,
 stretch_total: int,
 shrink_total: int,
) -> float | None:
 """Return glue adjustment ratio r, or None if infeasible.

 need > 0 (line too short): r = need / stretch_total; None if stretch_total == 0.
 need < 0 (line too long): r = need / shrink_total (negative); None if
 shrink_total == 0 or r < -1.
 need == 0: return 0.0.
 """
 if need == 0:
 return 0.0
 if need > 0:
 if stretch_total == 0:
 return None
 return need / stretch_total
 # need < 0
 if shrink_total == 0:
 return None
 r = need / shrink_total # negative
 if r < -1:
 return None
 return r


def _fitness_class(ratio: float) -> int:
 """Map adjustment ratio to fitness class 0..3."""
 if ratio > 1:
 return _FITNESS_VERY_LOOSE
 if ratio > 0.5:
 return _FITNESS_LOOSE
 if ratio >= -0.5:
 return _FITNESS_DECENT
 return _FITNESS_TIGHT


def _line_demerits(
 badness: int,
 penalty: int,
 linepenalty: int,
 prev_fitness: int,
 this_fitness: int,
 adjdemerits: int,
) -> float:
 """Compute per-line demerits per TeXbook p. 98.

 d = (linepenalty + badness)^2
 if penalty >= 0: d += penalty^2
 elif penalty > NEG_INF_PENALTY: d -= penalty^2
 if |this_fitness - prev_fitness| > 1: d += adjdemerits
 """
 raw = linepenalty + badness
 d = 100_000_000.0 if abs(raw) >= 10_000 else float(raw * raw) # See pdftex.web §25248
 if penalty >= 0:
 d += float(penalty * penalty)
 elif penalty > NEG_INF_PENALTY:
 d -= float(penalty * penalty)
 if abs(this_fitness - prev_fitness) > 1:
 d += adjdemerits
 return d


def _build_line(
 nodes: list,
 start: int,
 end: int,
 params: LinebreakParams,
 font_manager: FontManager,
 warnings: list[str] | None,
) -> HlistNode:
 """Build one typeset line from nodes[start:end].

 Prepends leftskip and appends rightskip (when non-trivial), then
 calls set_glue_hbox to set the line to params.hsize. Emits
 "Overfull hbox" / "Underfull hbox" strings into warnings if provided.
 """
 line_nodes: list = []

 ls = params.leftskip
 if ls.width or ls.stretch != 0 or ls.shrink != 0:
 line_nodes.append(GlueNode(glue=ls))

 for node in nodes[start:end]:
 if isinstance(node, DiscretionaryNode):
 line_nodes.extend(node.nobreak)
 else:
 line_nodes.append(node)

 rs = params.rightskip
 if rs.width or rs.stretch != 0 or rs.shrink != 0:
 line_nodes.append(GlueNode(glue=rs))

 nat_w, nat_h, nat_d = _measure_hlist(line_nodes, font_manager)

 box = HlistNode(
 list=line_nodes,
 width=nat_w,
 height=nat_h,
 depth=nat_d,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 set_glue_hbox(box, target_width=params.hsize)

 if warnings is not None:
 if nat_w > params.hsize:
 # Line too long — overfull
 warnings.append(
 f"Overfull \\hbox ({nat_w - params.hsize}sp too wide)"
 )
 elif (
 box.glue_sign == GlueSign.STRETCHING
 and box.glue_order == GlueOrder.NORMAL
 and box.glue_set > 1.0
 ):
 # Under-stretched with normal glue — underfull
 warnings.append("Underfull \\hbox (badness too high)")

 return box


# ---------------------------------------------------------------------------
# Prefix-sum helpers
# ---------------------------------------------------------------------------

def _build_prefix_sums(
 nodes: list,
 font_manager: FontManager,
) -> tuple[list[int], dict, list[int]]:
 """Precompute prefix sums for width, stretch (per order), and NORMAL shrink.

 Returns (sum_width, sum_stretch, sum_shrink_normal) where index k holds
 the cumulative total for nodes[0..k-1]. Each list has length len(nodes)+1.
 """
 n = len(nodes)
 sum_width = [0] * (n + 1)
 sum_stretch: dict[GlueOrder, list[int]] = {
 o: [0] * (n + 1) for o in GlueOrder
 }
 sum_shrink_normal = [0] * (n + 1)

 for i, node in enumerate(nodes):
 sum_width[i + 1] = sum_width[i] + _node_natural_width(node, font_manager)
 for o in GlueOrder:
 sum_stretch[o][i + 1] = sum_stretch[o][i]
 sum_shrink_normal[i + 1] = sum_shrink_normal[i]

 if isinstance(node, (GlueNode, LeadersNode)):
 sum_stretch[node.glue.stretch_order][i + 1] += node.glue.stretch
 if node.glue.shrink_order == GlueOrder.NORMAL:
 sum_shrink_normal[i + 1] += node.glue.shrink

 return sum_width, sum_stretch, sum_shrink_normal


def _highest_stretch_order(st: dict, orders: list) -> GlueOrder:
 """Return the highest GlueOrder with nonzero stretch in the given order list."""
 for o in (GlueOrder.FILLL, GlueOrder.FILL, GlueOrder.FIL, GlueOrder.NORMAL):
 if o in orders and st[o] > 0:
 return o
 return GlueOrder.NORMAL


# ---------------------------------------------------------------------------
# Main algorithm
# ---------------------------------------------------------------------------

def _run_dp(
 nodes: list,
 params: LinebreakParams,
 sum_width: list[int],
 sum_stretch: dict,
 sum_shrink_normal: list[int],
 max_badness: int,
 font_manager: FontManager,
) -> _Active | None:
 """Run one DP pass. Returns the best terminal active node, or None."""
 skip_width = params.leftskip.width + params.rightskip.width

 # Initial active node: position=-1 means "start of paragraph"
 active: list[_Active] = [
 _Active(
 position=-1,
 line_number=1,
 fitness=_FITNESS_DECENT,
 total_demerits=0.0,
 predecessor=None,
 )
 ]
 final_active: _Active | None = None

 for i in range(len(nodes)):
 if not _is_legal_breakpoint(nodes, i):
 continue

 node_i = nodes[i]
 penalty = node_i.penalty if isinstance(node_i, PenaltyNode) else 0

 is_forced = penalty == NEG_INF_PENALTY
 new_candidates: list[_Active] = []
 still_active: list[_Active] = []

 for a in active:
 j = a.position
 # Width of line from j+1 to i-1 (inclusive)
 # j==-1 means start: offset = sum_width[0] = 0
 j_offset = 0 if j == -1 else sum_width[j + 1]
 w = sum_width[i] - j_offset

 # Stretch and shrink sums for the same range
 st: dict[GlueOrder, int] = {}
 for o in GlueOrder:
 st_offset = 0 if j == -1 else sum_stretch[o][j + 1]
 st[o] = sum_stretch[o][i] - st_offset
 sh_offset = 0 if j == -1 else sum_shrink_normal[j + 1]
 sh = sum_shrink_normal[i] - sh_offset

 need = params.hsize - w - skip_width

 # Determine dominant stretch order
 dominant = GlueOrder.NORMAL
 for o in (GlueOrder.FILLL, GlueOrder.FILL, GlueOrder.FIL):
 if st[o] > 0:
 dominant = o
 break

 if dominant != GlueOrder.NORMAL:
 # Infinite stretch — always feasible when need >= 0
 if need >= 0:
 ratio: float | None = 0.0
 else:
 ratio = _adjustment_ratio(need, 0, sh)
 else:
 ratio = _adjustment_ratio(need, st[GlueOrder.NORMAL], sh)

 # Too long with no shrink — deactivate (unless forced break)
 if ratio is None and need < 0 and not is_forced:
 continue

 # Forced breaks consume the active node (it must break here, not continue).
 # Non-forced breaks leave the active node alive for future positions.
 if not is_forced:
 still_active.append(a)

 # Compute badness
 if dominant != GlueOrder.NORMAL and need >= 0:
 # Infinite stretch available — perfect fit
 bad = 0
 elif ratio is None:
 # Too short (no stretch) or overfull forced break — INF_BAD
 bad = INF_BAD
 elif need >= 0:
 bad = compute_badness(need, st[GlueOrder.NORMAL])
 else:
 bad = compute_badness(-need, sh)

 if bad > max_badness and not is_forced:
 # Infeasible for this pass — don't create a candidate
 continue

 fit = _fitness_class(ratio if ratio is not None else 0.0)
 d = _line_demerits(
 bad, penalty, params.linepenalty,
 a.fitness, fit, params.adjdemerits,
 )
 candidate = _Active(
 position=i,
 line_number=a.line_number + 1,
 fitness=fit,
 total_demerits=a.total_demerits + d,
 predecessor=a,
 )
 new_candidates.append(candidate)

 # Deduplicate new_candidates by position: keep best (min demerits) per position
 best_at: dict[int, _Active] = {}
 for cand in new_candidates:
 existing = best_at.get(cand.position)
 if existing is None or cand.total_demerits < existing.total_demerits:
 best_at[cand.position] = cand

 deduped = list(best_at.values())
 active = still_active + deduped

 # Collect terminal candidates only at the TRUE end-of-paragraph sentinel
 # (the last node in the list), not at intermediate \penalty-10000 nodes.
 if i == len(nodes) - 1 and isinstance(node_i, PenaltyNode) and node_i.penalty == NEG_INF_PENALTY:
 for cand in deduped:
 if final_active is None or cand.total_demerits < final_active.total_demerits:
 final_active = cand

 return final_active


def break_paragraph(
 nodes: list,
 params: LinebreakParams,
 font_manager: FontManager,
 *,
 warnings: list[str] | None = None,
) -> list[HlistNode]:
 """Run Knuth-Plass and return the typeset lines.

 The caller (exec_par) must have already appended parfillskip + a
 NEG_INF_PENALTY sentinel to nodes. An empty or all-discardable
 paragraph returns []. Each returned HlistNode has glue set to
 params.hsize via set_glue_hbox.

 Args:
 nodes: Paragraph node list ending with parfillskip + sentinel.
 params: All tunable parameters.
 font_manager: For character width lookups.
 warnings: Optional list; warning strings are appended here.

 Returns:
 List of set HlistNode lines.

 Example::

 from aspose_tex._engine.registers import Glue, GlueOrder
 params = LinebreakParams(
 hsize=6054984, tolerance=200, pretolerance=100,
 linepenalty=10, adjdemerits=10000,
 leftskip=Glue(0,0,GlueOrder.NORMAL,0,GlueOrder.NORMAL),
 rightskip=Glue(0,0,GlueOrder.NORMAL,0,GlueOrder.NORMAL),
 parfillskip=Glue(0,65536,GlueOrder.FIL,0,GlueOrder.NORMAL),
 )
 lines = break_paragraph([], params, font_manager)
 assert lines == []
 """
 if not nodes:
 return []

 # Check if all nodes are discardable
 has_content = any(
 not isinstance(n, (GlueNode, PenaltyNode, KernNode))
 for n in nodes
 )
 if not has_content:
 return []

 sum_width, sum_stretch, sum_shrink_normal = _build_prefix_sums(nodes, font_manager)

 # Pass 1: pretolerance
 final = _run_dp(
 nodes, params, sum_width, sum_stretch, sum_shrink_normal,
 params.pretolerance, font_manager,
 )

 # Pass 2: tolerance (if pass 1 failed)
 if final is None:
 final = _run_dp(
 nodes, params, sum_width, sum_stretch, sum_shrink_normal,
 params.tolerance, font_manager,
 )

 # If still None (degenerate), force a single line
 if final is None:
 # Build one line from all content
 line = _build_line(nodes, 0, len(nodes), params, font_manager, warnings)
 return [line]

 # Trace back the break chain
 chain = []
 node: _Active | None = final
 while node is not None and node.position != -1:
 chain.append(node.position)
 node = node.predecessor
 chain.reverse() # now in order: [pos1, pos2, ..., posN]

 # Build lines
 lines: list[HlistNode] = []
 start = 0
 for pos in chain:
 line = _build_line(nodes, start, pos, params, font_manager, warnings)
 lines.append(line)
 start = pos + 1

 return lines
