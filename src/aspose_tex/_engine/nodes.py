"""TeX node types for the box model.

Implements: all node kinds used in horizontal
and vertical lists. Nodes use ``__slots__`` via dataclasses for memory
efficiency (NFR-1).

Conventions:
- All dimension fields are in scaled points (sp). 1 pt = 65536 sp.
- ``RUNNING_DIMEN`` sentinel (``-(1 << 30)``) marks "inherit from context"
 (used for rule node dimensions, per TeX semantics).
- ``INF_PENALTY`` / ``NEG_INF_PENALTY`` are the standard TeX break-point sentinels.

See the project documentation for design rationale.
"""
from __future__ import annotations

import copy
import dataclasses
from enum import IntEnum

from aspose_tex._engine.registers import Glue, GlueOrder

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RUNNING_DIMEN: int = -(1 << 30)
"""Sentinel for rule-node dimensions meaning "inherit from surrounding context"."""

INF_PENALTY: int = 10_000
"""Unconditional keep-together (e.g. ``\\nobreak``)."""

NEG_INF_PENALTY: int = -10_000
"""Unconditional break point (e.g. ``\\penalty-10000``)."""

INF_BAD: int = 10_000
"""Maximum finite badness value."""


# ---------------------------------------------------------------------------
# GlueSign — used in HlistNode / VlistNode after glue is set
# ---------------------------------------------------------------------------

class GlueSign(IntEnum):
 """Glue setting direction.

 NORMAL — box is at its natural size (no stretch or shrink applied).
 STRETCHING — glue is being stretched.
 SHRINKING — glue is being shrunk.
 """

 NORMAL = 0
 STRETCHING = 1
 SHRINKING = 2


class LeadersKind(IntEnum):
 r"""Leader distribution kind for ``\leaders`` family nodes."""

 NORMAL = 0
 C = 1
 X = 2


# ---------------------------------------------------------------------------
# Leaf nodes — frozen, immutable after creation
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True, slots=True)
class CharNode:
 """A typeset character.

 Dimensions are NOT stored here; they are looked up from the font at
 render time via ``FontManager.get_metrics(font_name).char_metrics(char)``.

 Attributes:
 char: Unicode code point (0-255 for TeX text fonts).
 font_name: Font identifier string as registered with ``FontManager``
 (e.g. ``"tenrm"``).

 Example::

 node = CharNode(char=ord('A'), font_name='tenrm')
 """

 char: int
 font_name: str


@dataclasses.dataclass(frozen=True, slots=True)
class KernNode:
 """Fixed inter-character or inter-word spacing.

 Attributes:
 width: Amount of space in sp (positive = gap, negative = overlap).
 explicit: ``True`` for ``\\kern`` primitive; ``False`` for automatic
 font kern from the lig/kern table.

 Example::

 node = KernNode(width=1000, explicit=True)
 """

 width: int
 explicit: bool


@dataclasses.dataclass(frozen=True, slots=True)
class GlueNode:
 """Stretchable/shrinkable space.

 Attributes:
 glue: A ``Glue`` value from ``registers.py``.

 Example::

 from aspose_tex._engine.registers import Glue, GlueOrder
 hfil = GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL))
 """

 glue: Glue


@dataclasses.dataclass(frozen=True, slots=True)
class PenaltyNode:
 """Line/page break incentive.

 Attributes:
 penalty: Value in range ``[-10000, 10000]``.
 Use ``INF_PENALTY`` / ``NEG_INF_PENALTY`` for absolute control.

 Example::

 node = PenaltyNode(penalty=INF_PENALTY) # \\nobreak
 """

 penalty: int


@dataclasses.dataclass(frozen=True, slots=True)
class RuleNode:
 """Filled rectangle (``\\hrule`` / ``\\vrule``).

 Attributes:
 width: Horizontal extent in sp; ``RUNNING_DIMEN`` = inherit.
 height: Height above baseline in sp; ``RUNNING_DIMEN`` = inherit.
 depth: Depth below baseline in sp; ``RUNNING_DIMEN`` = inherit.

 Example::

 node = RuleNode(width=65536 * 100, height=26214, depth=0)
 """

 width: int
 height: int
 depth: int


@dataclasses.dataclass(frozen=True, slots=True)
class DiscretionaryNode:
 """Line-break alternative from ``\\discretionary{pre}{post}{nobreak}``.

 The three replacement lists are immutable node tuples. M3 stores the
 alternatives and lets the linebreaker pass through the node; full branch
 selection is deferred to M4.
 """

 pre: tuple
 post: tuple
 nobreak: tuple


@dataclasses.dataclass(frozen=True, slots=True)
class LeadersNode:
 """Repeated rule or box payload across a glue skip.

 M3 stores the payload and treats the surrounding glue as the width shell.
 Backend repetition is deferred to a future release.
 """

 kind: LeadersKind
 payload: object
 glue: Glue


@dataclasses.dataclass(frozen=True, slots=True)
class MarkNode:
 r"""Page mark sentinel from ``\mark{...}``."""

 tokens: tuple


@dataclasses.dataclass(frozen=True, slots=True)
class InsertNode:
 r"""An ``\insert<n>{<vlist>}`` contribution.

 The page builder accumulates insert payloads by class before running the
 token-list output routine. The class number maps to the box register that
 receives the accumulated vlist; ``\holdinginserts != 0`` leaves the node
 in the body box instead.

 Attributes:
 class_: 8-bit box-register / insert-class number (0..255).
 vlist: Immutable tuple of vertical-mode child nodes.
 height: Natural height of the vlist in sp.
 depth: Natural depth of the vlist in sp.
 floating_penalty: ``\floatingpenalty`` snapshot in sp-less integer.
 split_top_skip: ``\splittopskip`` glue snapshot.
 split_max_depth: ``\splitmaxdepth`` snapshot in sp.

 Example::

 from aspose_tex._engine.registers import Glue, GlueOrder
 node = InsertNode(
 class_=254,
 vlist=(),
 height=0,
 depth=0,
 floating_penalty=0,
 split_top_skip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 split_max_depth=0,
 )
 """

 class_: int
 vlist: tuple
 height: int
 depth: int
 floating_penalty: int
 split_top_skip: Glue
 split_max_depth: int


@dataclasses.dataclass(frozen=True, slots=True)
class WhatsitNode:
 """Extensibility hook for special material (e.g. PDF specials).

 Attributes:
 data: Arbitrary payload; semantics defined by the producer.
 """

 data: object


# ---------------------------------------------------------------------------
# Box nodes — mutable (list + glue-set fields written after construction)
# ---------------------------------------------------------------------------

@dataclasses.dataclass(slots=True)
class HlistNode:
 """A horizontal box (``\\hbox``).

 Fields ``glue_sign``, ``glue_order``, and ``glue_set`` are written
 once by ``set_glue_hbox()`` after the list is finalized; before that
 they hold their default "natural size" values.

 Attributes:
 list: Ordered sequence of child nodes.
 width: Natural (or set) total width in sp.
 height: Height above baseline in sp.
 depth: Depth below baseline in sp.
 shift_amount: Vertical displacement in sp (positive = up for ``\\raise``,
 negative = down for ``\\lower``). Zero for ordinary hboxes.
 glue_sign: Direction of glue setting.
 glue_order: Infinity order of the dominant glue component.
 glue_set: Ratio applied to all glue of ``glue_order``; 0.0 before set.

 Example::

 box = HlistNode(list=[], width=0, height=0, depth=0, shift_amount=0,
 glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL,
 glue_set=0.0)
 """

 list: list # list[Node] — forward ref avoidance
 width: int
 height: int
 depth: int
 shift_amount: int
 glue_sign: GlueSign
 glue_order: GlueOrder
 glue_set: float


@dataclasses.dataclass(slots=True)
class VlistNode:
 """A vertical box (``\\vbox``).

 Attributes:
 list: Ordered sequence of child nodes (hboxes, glue, kerns, etc.).
 width: Width of the widest child in sp.
 height: Height above baseline in sp.
 depth: Depth below baseline in sp.
 shift_amount: Horizontal displacement in sp (``\\moveleft`` / ``\\moveright``).
 glue_sign: Direction of glue setting.
 glue_order: Infinity order of the dominant glue component.
 glue_set: Ratio; 0.0 before set.
 """

 list: list # list[Node] — forward ref avoidance
 width: int
 height: int
 depth: int
 shift_amount: int
 glue_sign: GlueSign
 glue_order: GlueOrder
 glue_set: float


# ---------------------------------------------------------------------------
# Union type alias
# ---------------------------------------------------------------------------

Node = (
 CharNode
 | HlistNode
 | VlistNode
 | GlueNode
 | KernNode
 | PenaltyNode
 | RuleNode
 | DiscretionaryNode
 | LeadersNode
 | MarkNode
 | InsertNode
 | WhatsitNode
)
"""Any TeX node that can appear in a horizontal or vertical list."""

# Tuple of all node types — used for isinstance checks at runtime.
NODE_TYPES: tuple = (
 CharNode,
 HlistNode,
 VlistNode,
 GlueNode,
 KernNode,
 PenaltyNode,
 RuleNode,
 DiscretionaryNode,
 LeadersNode,
 MarkNode,
 InsertNode,
 WhatsitNode,
)


# ---------------------------------------------------------------------------
# Deep-copy helper (used by \\copy)
# ---------------------------------------------------------------------------

def deep_copy_node(
 node: (
 CharNode
 | HlistNode
 | VlistNode
 | GlueNode
 | KernNode
 | PenaltyNode
 | RuleNode
 | DiscretionaryNode
 | LeadersNode
 | MarkNode
 | InsertNode
 | WhatsitNode
 ),
) -> (
 CharNode
 | HlistNode
 | VlistNode
 | GlueNode
 | KernNode
 | PenaltyNode
 | RuleNode
 | DiscretionaryNode
 | LeadersNode
 | MarkNode
 | InsertNode
 | WhatsitNode
):
 """Return a deep copy of *node* (for ``\\copy`` semantics).

 ``CharNode``, ``KernNode``, ``GlueNode``, ``PenaltyNode``, ``RuleNode``,
 ``LeadersNode``, ``MarkNode``, ``InsertNode``, ``WhatsitNode`` are frozen; returned
 as-is (immutable, safe to share).
 ``HlistNode`` and ``VlistNode`` are recursively copied.

 Example::

 original = HlistNode(list=[CharNode(65, 'tenrm')], width=100,
 height=50, depth=10, shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0)
 clone = deep_copy_node(original)
 assert clone is not original
 assert clone.list is not original.list
 """
 if isinstance(node, (HlistNode, VlistNode)):
 return copy.deepcopy(node)
 # All other node types are frozen dataclasses — immutable, safe to share.
 return node
