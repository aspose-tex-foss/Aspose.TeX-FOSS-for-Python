"""Page builder: assembles vertical material into pages and fires the output routine.

Implements: PageBuilderConfig, ShipoutBackend,
OutputRoutineBase, PlainOutputRoutine, PageBuilder.

The PageBuilder is a stateful object owned by the engine (one instance per
document). It maintains the main vertical list (MVL), inserts interline
glue and topskip, detects page breaks, and calls the output routine.

See and for design rationale.
"""
from __future__ import annotations

import abc
import dataclasses
from typing import TYPE_CHECKING, Protocol

from aspose_tex._engine.box_builder import (
 _measure_hlist,
 _measure_vlist,
 set_glue_hbox,
 set_glue_vbox,
)
from aspose_tex._engine.box_primitives import _PREVDEPTH_SENTINEL
from aspose_tex._engine.nodes import (
 INF_PENALTY,
 NEG_INF_PENALTY,
 CharNode,
 GlueNode,
 GlueSign,
 HlistNode,
 InsertNode,
 KernNode,
 PenaltyNode,
 RuleNode,
 VlistNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._input.token import ControlSequenceToken
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
 from aspose_tex._engine.box_registers import BoxRegisterSet
 from aspose_tex._engine.expansion import Expander
 from aspose_tex._engine.inserts import InsertAccumulator
 from aspose_tex._engine.marks import MarksRegistry
 from aspose_tex._engine.named_parameters import NamedParameterRegistry
 from aspose_tex._engine.nodes import Node
 from aspose_tex._fonts.font_manager import FontManager

SENTINEL_FINISH_OUTPUT_CS = "\x00finish_output_cycle"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vlist_dims(nodes: list) -> tuple[int, int, int]:
 """Measure a vertical list of pre-built boxes/glue/kerns/penalties.

 Vertical lists in PageBuilder never contain CharNodes, so font_manager
 is unused (passed as None).
 """
 return _measure_vlist(nodes, None) # type: ignore[arg-type]


def _build_pagebody_vbox(
 body_nodes: list,
 config: PageBuilderConfig | None,
 font_manager: FontManager | None,
) -> VlistNode:
 r"""Wrap *body_nodes* in the plain-TeX ``\pagebody`` vbox shape.

 The helper exists so the legacy Python ``PlainOutputRoutine`` fast-path
 and the token-list ``\output`` path build ``\box255`` with the same body
 geometry. When *config* is present, the body is set to ``\vsize``.
 """
 nat_w, nat_h, nat_d = _measure_vlist(body_nodes, font_manager)
 body_box = VlistNode(
 list=body_nodes,
 width=nat_w,
 height=nat_h,
 depth=nat_d,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 if config is not None and config.vsize != nat_h:
 set_glue_vbox(body_box, target_height=config.vsize)
 return body_box


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclasses.dataclass(slots=True)
class PageBuilderConfig:
 """Mutable configuration for the page builder.

 Updated by the engine whenever the corresponding TeX registers change.
 All dimension fields in scaled points (sp). 1 pt = 65536 sp.

 Attributes:
 vsize: Target page height (\\vsize).
 Plain TeX default: 42152952 sp (≈ 8.9 in).
 hsize: Page width (\\hsize), read live by the output routine
 on every page shipout.
 Plain TeX default: 30785886 sp (6.5 in).
 topskip: Glue at top of first box (\\topskip).
 Plain TeX default: Glue(655360, 0, NORMAL, 0, NORMAL) = 10 pt.
 max_depth: Maximum depth of last box on page (\\maxdepth).
 Plain TeX default: 262144 sp (4 pt).
 baselineskip: Normal interline glue (\\baselineskip via \\normalbaselines).
 Plain TeX default: Glue(786432, 0, NORMAL, 0, NORMAL) = 12 pt.
 lineskip: Fallback interline glue (\\lineskip).
 Plain TeX default: Glue(65536, 0, NORMAL, 0, NORMAL) = 1 pt.
 lineskiplimit: Threshold for switching to \\lineskip (\\lineskiplimit).
 Plain TeX default: 0 sp.
 max_dead_cycles: Maximum consecutive output calls without \\shipout (\\maxdeadcycles).
 Plain TeX default: 25.

 Example::

 cfg = PageBuilderConfig(
 vsize=42152952,
 topskip=Glue(655360, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 max_depth=262144,
 baselineskip=Glue(786432, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 lineskip=Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 lineskiplimit=0,
 max_dead_cycles=25,
 )
 """

 vsize: int
 topskip: Glue
 max_depth: int
 baselineskip: Glue
 lineskip: Glue
 lineskiplimit: int
 max_dead_cycles: int
 # \hsize page width, mirrored from named-param slot 258.
 # Defaulted so existing PageBuilderConfig(...) call sites stay valid.
 hsize: int = 30_785_886


# ---------------------------------------------------------------------------
# Shipout backend protocol
# ---------------------------------------------------------------------------

class ShipoutBackend(Protocol):
 """Receives completed page boxes for output (DVI / PDF / SVG).

 Implemented by the backend modules ( onwards).

 Example::

 class NullBackend:
 def shipout(self, page_number: int, box: VlistNode) -> None:
 pass # discard — used in tests
 """

 def shipout(self, page_number: int, box: VlistNode) -> None:
 """Receive one completed page.

 Args:
 page_number: Current value of \\pageno (positive integer, starts at 1).
 box: The finalized page VlistNode.
 """
 ...


# ---------------------------------------------------------------------------
# Page number register protocol
# ---------------------------------------------------------------------------

class PageNumberRegister(Protocol):
 """Read/write access to \\pageno (aliased to \\count0 in plain TeX).

 Implemented by an adapter around ``RegisterSet`` in the interpreter;
 a plain-int-backed stub is supplied for unit tests.

 Example::

 class _IntPagenoStub:
 def __init__(self, v: int = 1) -> None:
 self._v = v
 def get_pageno(self) -> int:
 return self._v
 def set_pageno(self, v: int) -> None:
 self._v = v
 """

 def get_pageno(self) -> int:
 """Return current \\pageno (== \\count0)."""
 ...

 def set_pageno(self, value: int) -> None:
 """Set \\pageno (== \\count0)."""
 ...


# ---------------------------------------------------------------------------
# Output routine base
# ---------------------------------------------------------------------------

class OutputRoutineBase(abc.ABC):
 """Abstract output routine.

 In full TeX, the output routine is a token list (\\output).
 For M1/M2, it is a Python callback invoked by PageBuilder when a page is
 complete. The routine receives the raw main-vertical-list tail for the
 page (a list of nodes, already stripped of trailing discardables) and is
 responsible for wrapping it into a final shipout box (``\\pagebody`` in
 plain-TeX terminology) before calling ``backend.shipout()``.

 If the routine does not call ``backend.shipout()``, ``\\deadcycles`` is
 incremented.

 Example (test double)::

 class CapturingRoutine(OutputRoutineBase):
 def __init__(self):
 self.pages: list[VlistNode] = []
 def execute(self, body_nodes, page_number, backend):
 # Wrap the list into a minimal VlistNode and ship it.
 nat_w, nat_h, nat_d = _measure_vlist(body_nodes, None)
 box = VlistNode(list=body_nodes, width=nat_w, height=nat_h,
 depth=nat_d, shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL, glue_set=0.0)
 backend.shipout(page_number, box)
 self.pages.append(box)
 """

 @abc.abstractmethod
 def execute(
 self,
 body_nodes: list,
 page_number: int,
 backend: ShipoutBackend,
 ) -> None:
 """Execute the output routine.

 Args:
 body_nodes: The raw vertical-list tail assembled by the page builder
 for the current page (already stripped of trailing
 discardables). The routine owns the ``\\pagebody``
 wrap and the final VlistNode construction.
 page_number: Current \\pageno before shipout.
 backend: Shipout target. Routine must call ``backend.shipout()``
 exactly once.
 """
 ...


# ---------------------------------------------------------------------------
# Plain TeX output routine (M2 implementation — )
# ---------------------------------------------------------------------------

# 1 pt = 65_536 sp
_SP_PER_PT = 65_536
FOOTLINE_BASELINESKIP_SP = 24 * _SP_PER_PT # plain.tex \makefootline: 24pt
HEADLINE_SHIFT_SP = int(22.5 * _SP_PER_PT) # plain.tex \makeheadline: -22.5pt


def _to_roman_lowercase(n: int) -> str:
 """Convert a positive integer to a lowercase Roman numeral (TeX ``\\romannumeral``).

 Returns the empty string for ``n <= 0`` (matches ``\\romannumeral`` on a
 non-positive argument).

 Example::

 assert _to_roman_lowercase(1994) == "mcmxciv"
 """
 if n <= 0:
 return ""
 table = (
 (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
 (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
 (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
 )
 parts: list[str] = []
 for val, sym in table:
 while n >= val:
 parts.append(sym)
 n -= val
 return "".join(parts)


def _format_folio(pageno: int) -> str:
 """Format \\folio per plain.tex line 1151.

 If ``pageno < 0``, return ``\\romannumeral-\\pageno``
 (lowercase Roman). Otherwise return the decimal digits of ``pageno``.

 Example::

 assert _format_folio(12) == "12"
 assert _format_folio(0) == "0"
 assert _format_folio(-7) == "vii"
 """
 if pageno < 0:
 return _to_roman_lowercase(-pageno)
 return str(pageno)


def _hfil_glue() -> GlueNode:
 """0pt plus 1fil — used for the \\hss surrounding \\folio in the footline."""
 return GlueNode(Glue(0, _SP_PER_PT, GlueOrder.FIL, 0, GlueOrder.NORMAL))


def _hss_glue() -> GlueNode:
 """0pt plus 1fil minus 1fil — plain.tex \\hss."""
 return GlueNode(Glue(
 0, _SP_PER_PT, GlueOrder.FIL, _SP_PER_PT, GlueOrder.FIL,
 ))


class PlainOutputRoutine(OutputRoutineBase):
 """Plain-TeX default output routine, M2 implementation.

 Replicates plain.tex's ``\\plainoutput`` behaviour in Python (plain.tex
 itself is not loaded until M3). For each page:

 1. Wraps the body nodes in a ``\\vbox to\\vsize`` via
 :func:`set_glue_vbox`. Any ``\\vfil`` / ``\\vfill`` inside the body
 stretches into real space, so the page body fills ``\\vsize`` exactly.
 2. Builds an empty headline hbox (plain TeX default ``\\headline={\\hfil}``)
 shifted up by 22.5 pt via a preceding negative kern (matches
 ``\\makeheadline``). For M2 the headline is always empty; user
 ``\\headline={…}`` redefinition is deferred to M3.
 3. Builds a footline hbox of width ``hsize`` containing
 ``\\hss \\tenrm \\folio \\hss`` — CharNodes for each digit of
 ``\\folio`` surrounded by ``\\hss`` glue (plain TeX default
 ``\\footline={\\hss\\tenrm\\folio\\hss}``). The footline sits
 24 pt below the body's last baseline (``\\makefootline``).
 4. Ships the assembled VlistNode through ``backend.shipout()``.

 The ``\\folio`` value is read from the ``PageNumberRegister`` if wired;
 otherwise it falls back to the ``page_number`` argument.

 Args:
 hsize: Page width in sp (plain-TeX default: 6.5 in = 30_785_886).
 font_manager: FontManager used to resolve the ``tenrm`` font and
 produce CharNode metrics for folio digits. May be
 ``None`` for pure-vlist unit tests — in that case
 the footline is emitted empty (no digits).
 pageno_register: Optional ``PageNumberRegister``. If provided, the
 routine reads ``get_pageno()`` when typesetting
 \\folio. When ``None``, the ``page_number``
 argument is used.
 config: Optional ``PageBuilderConfig``. If provided, the
 routine reads ``config.vsize`` on each execute
 call and wraps the page body in
 ``\\vbox to\\vsize``. When ``None`` the body is
 built at its natural height (M1 behaviour —
 preserves unit tests that do not need vsize
 stretching).
 footline_baselineskip_sp: Distance from the body's last baseline to
 the footline baseline (plain TeX: 24 pt).
 headline_shift_sp: Distance the headline is shifted above the body
 top (plain TeX: 22.5 pt).

 Example::

 routine = PlainOutputRoutine(hsize=30_785_886, font_manager=fm, config=cfg)
 routine.execute(body_nodes, page_number=1, backend=dvi_backend)
 """

 def __init__(
 self,
 hsize: int,
 *,
 font_manager: FontManager | None = None,
 pageno_register: PageNumberRegister | None = None,
 config: PageBuilderConfig | None = None,
 footline_baselineskip_sp: int = FOOTLINE_BASELINESKIP_SP,
 headline_shift_sp: int = HEADLINE_SHIFT_SP,
 ) -> None:
 self._hsize = hsize
 self._font_manager = font_manager
 self._pageno_register = pageno_register
 self._config = config
 self._footline_baselineskip_sp = footline_baselineskip_sp
 self._headline_shift_sp = headline_shift_sp

 def execute(
 self,
 body_nodes: list,
 page_number: int,
 backend: ShipoutBackend,
 ) -> None:
 """Build a plain-TeX page VlistNode and ship it. See class docstring."""
 # Read \hsize live from the config on every shipout so user
 # \hsize assignments reach the page box, mirroring
 # how _build_pagebody reads self._config.vsize live. The constructor
 # hsize= argument is the no-config fallback (unit tests without a config).
 hsize = self._config.hsize if self._config is not None else self._hsize

 # 1. Page body wrapped in \vbox to\vsize.
 body_box = self._build_pagebody(body_nodes)

 # 2. Empty headline (plain TeX default \headline={\hfil}).
 headline = self._build_headline(hsize)

 # 3. Footline hbox typeset for \hss\tenrm\folio\hss.
 folio_value = (
 self._pageno_register.get_pageno()
 if self._pageno_register is not None
 else page_number
 )
 footline = self._build_footline(hsize, folio_value)

 # 4. Kern that seats the footline baseline 24 pt below the body.
 footline_kern_width = (
 self._footline_baselineskip_sp - body_box.depth - footline.height
 )
 footline_kern = KernNode(width=footline_kern_width, explicit=True)

 # 5. Headline positioning kern (negative — shifts the headline up,
 # then a compensating positive kern restores the body position).
 # In practice plain.tex handles this inside \makeheadline by using
 # \vbox to0pt — the headline takes zero vertical space in the
 # vlist. We reproduce the visual via KernNodes: first a kern of
 # -headline_shift that raises the headline, then the headline
 # hbox (natural height), then a kern that restores the position
 # so the body still starts at the page origin.
 pre_head_kern = KernNode(width=-self._headline_shift_sp, explicit=True)
 post_head_kern = KernNode(width=self._headline_shift_sp, explicit=True)

 page_nodes: list = [
 pre_head_kern,
 headline,
 post_head_kern,
 body_box,
 footline_kern,
 footline,
 ]
 width, height, depth = _vlist_dims(page_nodes)
 final_box = VlistNode(
 list=page_nodes,
 width=max(hsize, width, body_box.width),
 height=height,
 depth=depth,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 backend.shipout(page_number, final_box)

 # ------------------------------------------------------------------
 # Internals
 # ------------------------------------------------------------------

 def _build_pagebody(self, body_nodes: list) -> VlistNode:
 """Wrap *body_nodes* in a \\vbox to\\vsize.

 Uses ``set_glue_vbox`` so ``\\vfil`` / ``\\vfill`` inside the body
 stretches into real space. The target height is read from
 ``self._config.vsize`` if a config was wired; otherwise the body is
 built at its natural height (M1 behaviour — preserves unit tests
 that do not need vsize stretching).
 """
 return _build_pagebody_vbox(body_nodes, self._config, self._font_manager)

 def _build_headline(self, hsize: int) -> HlistNode:
 """Build the plain-TeX default headline (``\\headline={\\hfil}``).

 Zero-height, zero-depth HlistNode of width ``hsize``. For M2 always
 empty; user ``\\headline={…}`` redefinition is deferred to M3.
 """
 return HlistNode(
 list=[],
 width=hsize,
 height=0,
 depth=0,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )

 def _build_footline(self, hsize: int, folio_value: int) -> HlistNode:
 """Build the plain-TeX default footline (``\\hss\\tenrm\\folio\\hss``)."""
 nodes: list = [_hss_glue()]
 if self._font_manager is not None and self._font_manager.is_font("tenrm"):
 font_name = "tenrm"
 metrics = self._font_manager.get_metrics(font_name)
 if metrics is not None:
 for digit in _format_folio(folio_value):
 code = ord(digit)
 nodes.append(CharNode(char=code, font_name=font_name))
 nodes.append(_hss_glue())

 nat_w, nat_h, nat_d = _measure_hlist(nodes, self._font_manager) # type: ignore[arg-type]
 box = HlistNode(
 list=nodes,
 width=nat_w,
 height=nat_h,
 depth=nat_d,
 shift_amount=0,
 glue_sign=GlueSign.NORMAL,
 glue_order=GlueOrder.NORMAL,
 glue_set=0.0,
 )
 set_glue_hbox(box, target_width=hsize)
 return box


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _TrackingBackend:
 """Wraps a ShipoutBackend to detect when shipout() is called.

 Passed to output_routine.execute() so that any call to backend.shipout()
 — whether direct or via exec_shipout — triggers _record_shipout() on the
 PageBuilder, resetting dead_cycles.
 """

 def __init__(self, real_backend: ShipoutBackend, page_builder: PageBuilder) -> None:
 self._real = real_backend
 self._builder = page_builder

 def shipout(self, page_number: int, box: VlistNode) -> None:
 self._real.shipout(page_number, box)
 self._builder._record_shipout()


# ---------------------------------------------------------------------------
# Page builder
# ---------------------------------------------------------------------------

class PageBuilder:
 """Assembles typeset vertical material into pages.

 Maintains the main vertical list (MVL), inserts interline glue and topskip,
 detects page breaks, and fires the output routine.

 Usage::

 config = PageBuilderConfig(...)
 backend = MyDviBackend()
 builder = PageBuilder(config, backend)
 for line in exec_par(par_list, params, font_manager):
 builder.contribute(line)
 builder.end_of_document()

 Attributes:
 warnings: List of warning strings (e.g. "Overfull \\\\vbox ...") accumulated
 during processing. Callers may inspect after use.
 """

 def __init__(
 self,
 config: PageBuilderConfig,
 backend: ShipoutBackend,
 output_routine: OutputRoutineBase | None = None,
 *,
 pageno_register: PageNumberRegister | None = None,
 marks_registry: MarksRegistry | None = None,
 box_registers: BoxRegisterSet | None = None,
 insert_accumulator: InsertAccumulator | None = None,
 named_params: NamedParameterRegistry | None = None,
 expander: Expander | None = None,
 font_manager: FontManager | None = None,
 ) -> None:
 """Initialise the page builder.

 Args:
 config: Mutable configuration object; may be updated
 externally as registers change.
 backend: Shipout target.
 output_routine: Output routine to execute when a page is
 complete. If None, uses PlainOutputRoutine
 with hsize=0.
 pageno_register: Optional ``PageNumberRegister``. When provided
 the page counter is read from / written to the
 register (M2 replacement for plain.tex's
 ``\\advancepageno``). When None, an internal
 integer counter is used (M1 behaviour).
 marks_registry: Optional mark registry updated around
 output-routine execution.
 box_registers: Optional box-register bank for token-list
 output dispatch. ``\\box255`` is written here.
 insert_accumulator: Optional insert accumulator stub/full helper.
 named_params: Optional named-parameter registry for reading
 ``\\output`` and writing ``\\outputpenalty``.
 expander: Optional expander used to push ``\\output`` toks
 plus the private finish sentinel.
 font_manager: Optional font manager used to size ``\\box255``.
 """
 self._config = config
 self._backend = backend
 self._output_routine: OutputRoutineBase = (
 output_routine if output_routine is not None else PlainOutputRoutine(hsize=0)
 )
 self._pageno_register = pageno_register
 self._marks_registry = marks_registry
 self._box_registers = box_registers
 self._insert_accumulator = insert_accumulator
 self._named_params = named_params
 self._expander = expander
 self._font_manager = font_manager

 # Main vertical list state
 self._mvl: list = []
 self._page_total: int = 0
 self._page_depth: int = 0 # clamped depth of last box
 # TeXbook §253 / TeX:The Program §679: -1000 pt is the "ignore" sentinel
 # that suppresses the interline-glue prelude. See v5 Component 6.
 self._prev_depth: int = _PREVDEPTH_SENTINEL

 # Glue accumulators (per GlueOrder)
 self._page_stretch: dict[GlueOrder, int] = {o: 0 for o in GlueOrder}
 self._page_shrink: dict[GlueOrder, int] = {o: 0 for o in GlueOrder}

 # Break tracking — `_first_box_on_page` is the §1004 topskip gate AND
 # the §1098 parskip sentinel proxy. True until the first
 # baseline-bearing item (HlistNode, VlistNode, OR RuleNode contributed
 # while the page is still empty) is placed on the MVL; flipped to
 # False once topskip glue (or its rule-substituted analogue) has been
 # inserted. Read by TeXInterpreter._end_paragraph as the parskip
 # guard via the public PageBuilder.is_at_top_of_page property
 # ( Component 4 + v4).
 self._first_box_on_page: bool = True
 self._skip_interline_once: bool = False
 self._no_interline: bool = False
 self._last_break_idx: int | None = None
 self._last_break_penalty: int = 0

 # Output routine state
 self._dead_cycles: int = 0
 # Internal fallback counter (used when no register is wired).
 self._page_number: int = 1
 self._shipout_called: bool = False # per-output-routine-call flag
 self._output_is_user_redefined: bool = False
 self._pending_leftover: list = []
 self._pending_page_number: int | None = None

 # Warnings accumulator
 self.warnings: list[str] = []

 # ------------------------------------------------------------------
 # Public read-only properties (special registers)
 # ------------------------------------------------------------------

 @property
 def is_at_top_of_page(self) -> bool:
 """Whether the page is still waiting for its first baseline-bearing item.

 Returns:
 True when no baseline-bearing item (HlistNode, VlistNode, or a
 RuleNode contributed while the page was still empty) has been
 placed on the current page since the last page break. Returns
 False once such an item has been placed. Mid-page rule
 contributions do not flip the flag (it was already False). This
 property is read-only. See v4 for the rule-first flip
 policy widening.
 """
 return self._first_box_on_page

 @property
 def page_total(self) -> int:
 """\\pagetotal — accumulated natural height of material on current page (sp)."""
 return self._page_total

 @property
 def page_goal(self) -> int:
 """\\pagegoal — current page height goal (sp); equals config.vsize."""
 return self._config.vsize

 @property
 def page_depth(self) -> int:
 """\\pagedepth — depth of the last box on the current page (sp), clamped."""
 return self._page_depth

 @property
 def page_stretch(self) -> int:
 """\\pagestretch — total NORMAL-order stretch of glue on current page (sp)."""
 return self._page_stretch[GlueOrder.NORMAL]

 @property
 def page_fil_stretch(self) -> int:
 """\\pagefilstretch — total FIL-order stretch (sp)."""
 return self._page_stretch[GlueOrder.FIL]

 @property
 def page_filstretch(self) -> int:
 """Alias for \\pagefilstretch using callback spelling."""
 return self.page_fil_stretch

 @property
 def page_fill_stretch(self) -> int:
 """\\pagefillstretch — total FILL-order stretch (sp)."""
 return self._page_stretch[GlueOrder.FILL]

 @property
 def page_fillstretch(self) -> int:
 """Alias for \\pagefillstretch using callback spelling."""
 return self.page_fill_stretch

 @property
 def page_filll_stretch(self) -> int:
 """\\pagefilllstretch — total FILLL-order stretch (sp)."""
 return self._page_stretch[GlueOrder.FILLL]

 @property
 def page_filllstretch(self) -> int:
 """Alias for \\pagefilllstretch using callback spelling."""
 return self.page_filll_stretch

 @property
 def page_shrink(self) -> int:
 """\\pageshrink — total NORMAL-order shrink of glue on current page (sp)."""
 return self._page_shrink[GlueOrder.NORMAL]

 @property
 def dead_cycles(self) -> int:
 """\\deadcycles — number of output routine calls without a \\shipout."""
 return self._dead_cycles

 @property
 def insert_penalties(self) -> int:
 """\\insertpenalties — M3 stub; real split accounting lands in ."""
 return 0

 @property
 def page_number(self) -> int:
 """\\pageno — current page number.

 Read from the wired ``pageno_register`` when available; otherwise
 falls back to the internal counter.
 """
 if self._pageno_register is not None:
 return self._pageno_register.get_pageno()
 return self._page_number

 @property
 def output_cycle_pending(self) -> bool:
 """Whether a token-list output cycle is waiting for its sentinel."""
 return self._pending_page_number is not None

 # ------------------------------------------------------------------
 # Public mutators
 # ------------------------------------------------------------------

 def contribute(self, node: Node) -> None: # type: ignore[name-defined]
 """Contribute a node to the main vertical list.

 Dispatches by node type:
 - HlistNode / VlistNode: inserts interline glue or topskip first,
 then appends the box, then checks for a page break.
 - RuleNode ( v5): two sub-branches selected by
 ``_first_box_on_page``. Rule-first (page still empty) runs the
 topskip path (TeX:The Program §1004) then appends, accumulates
 ``_page_total``, sets ``_prev_depth = _PREVDEPTH_SENTINEL``
 (§679 `prev_depth ← ignore_depth`), and checks for a page
 break. Rule mid-page just appends and sets
 ``_prev_depth = _PREVDEPTH_SENTINEL`` (no interline glue
 prelude per §679, no ``_page_total`` update, no break check).
 - GlueNode: appends, records as break candidate, checks for break.
 - KernNode: appends, updates page_total.
 - PenaltyNode: appends, records as break candidate if penalty < INF_PENALTY,
 triggers immediate break if penalty == NEG_INF_PENALTY.
 - Other: appended as-is (no break check).

 Args:
 node: Any Node from nodes.py.

 Raises:
 EngineError: if dead_cycles exceeds config.max_dead_cycles.
 """
 if isinstance(node, (HlistNode, VlistNode)):
 self._insert_interline_or_topskip(node)
 self._mvl.append(node)
 self._update_page_totals_for_box(node)
 self._check_page_break()

 elif isinstance(node, RuleNode):
 # v4: TeX:The Program §679 (contribute_rule) vs §1078
 # (contribute_box) are different code paths. Rule-first on a page
 # hits §1004 (topskip) then appends; rule mid-page just appends
 # with a prev_depth update. See Measurements B + C + D.
 if self._first_box_on_page:
 # Rule-first: topskip path fires, flag flips, accumulate totals
 # so _check_page_break decides correctly.
 self._insert_interline_or_topskip(node)
 self._mvl.append(node)
 self._page_total += node.height + node.depth
 # v5: the `_prev_depth = ignore_depth` write is the
 # §679-correct sentinel; downstream interline-glue preludes
 # see the sentinel and skip the prelude entirely, matching
 # MiKTeX's body-vbox layout (Measurement E).
 self._prev_depth = _PREVDEPTH_SENTINEL
 self._check_page_break()
 else:
 # Rule mid-page: §679 path — append, set prev_depth, done.
 # No interline glue prelude (matches MiKTeX Measurements C + D).
 # No _page_total update; no _check_page_break. v5:
 # the `_prev_depth = ignore_depth` write is the §679-correct
 # sentinel; downstream interline-glue preludes see the
 # sentinel and skip the prelude entirely, matching MiKTeX's
 # body-vbox layout (Measurement E). The pre-v5 expression
 # `_prev_depth = node.depth` was a literal misread of §679
 # (§679 says `prev_depth ← ignore_depth`, NOT
 # `prev_depth ← rule.depth`).
 self._mvl.append(node)
 self._prev_depth = _PREVDEPTH_SENTINEL

 elif isinstance(node, GlueNode):
 self._mvl.append(node)
 self._page_total += node.glue.width
 self._page_stretch[node.glue.stretch_order] += node.glue.stretch
 self._page_shrink[GlueOrder.NORMAL] += node.glue.shrink # only NORMAL tracked
 self._last_break_idx = len(self._mvl) - 1
 self._last_break_penalty = 0
 self._check_page_break()

 elif isinstance(node, KernNode):
 self._mvl.append(node)
 self._page_total += node.width

 elif isinstance(node, PenaltyNode):
 self._mvl.append(node)
 if node.penalty == NEG_INF_PENALTY:
 # Forced break — do it immediately
 self._last_break_idx = len(self._mvl) - 1
 self._last_break_penalty = node.penalty
 self._do_page_break(len(self._mvl) - 1)
 elif node.penalty < INF_PENALTY:
 self._last_break_idx = len(self._mvl) - 1
 self._last_break_penalty = node.penalty
 self._check_page_break()

 elif isinstance(node, InsertNode):
 self._mvl.append(node)
 self._page_total += node.height + node.depth
 self._check_page_break()

 else:
 self._mvl.append(node)

 def end_of_document(self) -> None:
 """Flush remaining material (partial last page).

 If the MVL is non-empty and has at least one box, assemble and ship
 the remaining page. If the MVL contains only discardable nodes
 (GlueNode, KernNode, PenaltyNode) with no box, do not ship.
 """
 has_box = any(isinstance(n, (HlistNode, VlistNode)) for n in self._mvl)
 if not has_box:
 return

 # Ship everything remaining as the final page
 self._do_page_break(len(self._mvl))

 def skip_next_interline(self) -> None:
 """\\nointerlineskip — suppress interline glue before the NEXT box only."""
 self._skip_interline_once = True

 def off_interline(self) -> None:
 """\\offinterlineskip — permanently disable all interline glue."""
 self._no_interline = True

 def remove_last_node(self, *types: type) -> Node | None:
 """Remove the trailing MVL node when it matches one of ``types``.

 Implements the ``\\unskip`` / ``\\unkern`` / ``\\unpenalty`` tail-removal
 contract ( AC-6) on the page builder's main vertical list,
 with full rollback of the accumulators that ``contribute()`` wrote
 when the node was originally contributed. Bypassing the rollback
 (as the M3-era ``box_primitives._target_nodes(page_builder)._mvl.pop()``
 path did) corrupts ``_page_total`` / ``_page_stretch`` / ``_page_shrink``
 / ``_last_break_idx``; this helper closes that gap.

 Args:
 *types: Node types that are eligible for removal (e.g.
 ``GlueNode`` for ``\\unskip``). When ``self._mvl[-1]`` is
 not an instance of any listed type, this is a no-op and
 returns ``None`` — matching Knuth's "remove last node only
 when it is the right type" semantics.

 Returns:
 The popped node, or ``None`` when the MVL is empty or its tail
 does not match any of ``types``.
 """
 if not self._mvl:
 return None
 tail = self._mvl[-1]
 if not isinstance(tail, types):
 return None

 self._mvl.pop()
 popped_idx = len(self._mvl) # index the popped node had occupied

 # Roll back the per-node-type accumulators that contribute() wrote.
 if isinstance(tail, GlueNode):
 self._page_total -= tail.glue.width
 self._page_stretch[tail.glue.stretch_order] -= tail.glue.stretch
 self._page_shrink[GlueOrder.NORMAL] -= tail.glue.shrink
 elif isinstance(tail, KernNode):
 self._page_total -= tail.width
 # PenaltyNode: contribute() does not touch _page_total / stretch /
 # shrink for penalty nodes; only _last_break_idx / _last_break_penalty
 # are affected, and they are handled by the unified check below.

 # _last_break_idx invariant: it must point at a still-existing
 # position in _mvl, or be None. After a pop(), if it pointed at
 # popped_idx (the most recent break candidate was the node we just
 # removed) OR beyond the new tail, clear it. Conservative clear
 # matches the post-page-break reset path at _check_page_break. See
 # "Out of scope" — recovery of the previous break candidate
 # is deferred to a future release.
 if self._last_break_idx is not None and self._last_break_idx >= popped_idx:
 self._last_break_idx = None
 self._last_break_penalty = 0

 return tail

 # ------------------------------------------------------------------
 # Private methods
 # ------------------------------------------------------------------

 def _insert_interline_or_topskip(
 self, node: HlistNode | VlistNode | RuleNode,
 ) -> None:
 """Insert topskip (first item) or interline glue (subsequent items).

 Implements the interline glue algorithm (TeX:The Program §1001-§1004).
 Accepts any non-discardable vertical-list item that has a baseline
 (HlistNode, VlistNode, or RuleNode); the topskip formula reads
 ``node.height`` regardless of node kind, matching MiKTeX's behaviour
 on rule-first pages ( Measurement B).

 Note:
 Under v4, ``PageBuilder.contribute`` only calls this
 method for a ``RuleNode`` when ``_first_box_on_page`` is True
 (the topskip branch). The interline branch is never reached for
 rules because TeX:The Program §679 (``contribute_rule``) does NOT
 run the interline-glue prelude — only §1078 (``contribute_box``)
 does. See Measurements C and D.

 See for the full algorithm specification.
 """
 cfg = self._config
 if self._first_box_on_page:
 # Topskip: ensure first baseline is at topskip below top of page.
 topskip_nat = max(0, cfg.topskip.width - node.height)
 topskip_glue = Glue(
 topskip_nat,
 cfg.topskip.stretch,
 cfg.topskip.stretch_order,
 cfg.topskip.shrink,
 cfg.topskip.shrink_order,
 )
 self._mvl.append(GlueNode(topskip_glue))
 self._page_total += topskip_nat
 self._page_stretch[cfg.topskip.stretch_order] += cfg.topskip.stretch
 self._page_shrink[GlueOrder.NORMAL] += cfg.topskip.shrink
 self._first_box_on_page = False

 elif not self._skip_interline_once and not self._no_interline:
 # TeXbook §253: prev_depth <= -1000 pt is the "ignore" sentinel;
 # no interline glue is inserted. Set by TeX:The Program §679
 # (`contribute_rule`) and by `\nointerlineskip`
 # (plain.tex: `\prevdepth-1000\p@`). See v5 Component 6.
 if self._prev_depth <= _PREVDEPTH_SENTINEL:
 return
 # Normal interline glue (See ).
 ideal = cfg.baselineskip.width - self._prev_depth - node.height
 if ideal < cfg.lineskiplimit:
 interline = cfg.lineskip
 else:
 interline = Glue(
 ideal,
 cfg.baselineskip.stretch,
 cfg.baselineskip.stretch_order,
 cfg.baselineskip.shrink,
 cfg.baselineskip.shrink_order,
 )
 self._mvl.append(GlueNode(interline))
 self._page_total += interline.width
 self._page_stretch[interline.stretch_order] += interline.stretch
 self._page_shrink[GlueOrder.NORMAL] += interline.shrink

 else:
 # Suppress interline glue (once or permanently).
 if self._skip_interline_once:
 self._skip_interline_once = False
 # _no_interline stays True until explicitly cleared

 def _update_page_totals_for_box(self, box: HlistNode | VlistNode) -> None:
 """Update _page_total, _page_depth, _prev_depth after appending a box.

 Algorithm (TeX §982):
 page_total += _page_depth + box.height
 _page_depth = box.depth
 if _page_depth > config.max_depth:
 page_total += _page_depth - config.max_depth
 _page_depth = config.max_depth
 _prev_depth = box.depth (unclamped, for next interline calculation)
 """
 self._page_total += self._page_depth + box.height
 raw_depth = box.depth
 self._prev_depth = raw_depth
 if raw_depth > self._config.max_depth:
 self._page_total += raw_depth - self._config.max_depth
 self._page_depth = self._config.max_depth
 else:
 self._page_depth = raw_depth

 def _check_page_break(self) -> None:
 """Greedy page break check (M1 algorithm).

 Triggers _do_page_break() when page_total + page_depth > config.vsize.
 """
 if self._page_total + self._page_depth > self._config.vsize:
 if self._last_break_idx is not None:
 break_idx = self._last_break_idx
 self._last_break_idx = None # prevent re-entry with same idx
 self._do_page_break(break_idx)
 else:
 # Overfull page — no legal break found; ship everything
 self.warnings.append(
 f"Overfull \\vbox ({self._page_total + self._page_depth - self._config.vsize} sp too tall)"
 )
 self._do_page_break(len(self._mvl))

 def _do_page_break(self, break_idx: int) -> None:
 """Execute a page break at position break_idx in the MVL.

 Uses the byte-stable Python output routine while ``\\output`` is still
 untouched. After a user writes ``\\output={...}``, switches to the
 token-list path: put the page body into ``\\box255``, push the
 ``\\output`` toks followed by a private sentinel, and return to the
 interpreter loop.
 """
 # Step 1: split
 page_nodes = self._mvl[:break_idx]
 if break_idx < len(self._mvl):
 break_node = self._mvl[break_idx]
 # Discard the break node (GlueNode or PenaltyNode); keep KernNode
 if isinstance(break_node, (GlueNode, PenaltyNode)):
 leftover = self._mvl[break_idx + 1:]
 else:
 leftover = self._mvl[break_idx:]
 else:
 leftover = []

 # : only the single break node is removed (Step 1 above).
 # Other trailing discardables (e.g. \bye's \vfill) must reach
 # set_glue_vbox so \vbox to\vsize stretches as intended.

 # Step 2: increment dead_cycles
 self._dead_cycles += 1
 current_page_number = self.page_number
 if self._marks_registry is not None:
 self._marks_registry.record_mark_on_shipout(page_nodes)

 self._pending_leftover = list(leftover)
 self._pending_page_number = current_page_number
 self._shipout_called = False

 if self._should_use_token_list_output():
 self._start_token_list_output(page_nodes)
 return

 # Step 3: call output routine via a tracking wrapper that detects shipout.
 # The wrapper intercepts backend.shipout() and calls _record_shipout(),
 # so dead_cycles is reset whether the routine calls backend.shipout()
 # directly or via exec_shipout(). The output routine owns the
 # \pagebody wrap and the final VlistNode construction.
 tracking_backend = _TrackingBackend(self._backend, self)
 self._output_routine.execute(page_nodes, current_page_number, tracking_backend)
 self._finish_output_cycle()

 def _should_use_token_list_output(self) -> bool:
 """Return True when all collaborators are wired."""
 return (
 self._output_is_user_redefined
 and self._box_registers is not None
 and self._named_params is not None
 and self._expander is not None
 )

 def _start_token_list_output(self, page_nodes: list) -> None:
 r"""Prepare ``\box255`` and push ``\output`` toks plus sentinel."""
 assert self._box_registers is not None
 assert self._named_params is not None
 assert self._expander is not None

 page_nodes = self._extract_inserts_for_output(page_nodes)
 if self._insert_accumulator is not None:
 self._insert_accumulator.flush_to_box_registers(
 self._box_registers,
 self._font_manager,
 )

 body_box = _build_pagebody_vbox(page_nodes, self._config, self._font_manager)
 self._box_registers.setbox(255, body_box, global_=True)

 outputpenalty = self._named_params.lookup("outputpenalty")
 if outputpenalty is not None:
 self._named_params._register_set.set_count(
 outputpenalty.slot,
 self._last_break_penalty,
 _internal=True,
 )

 output = self._named_params.lookup("output")
 output_tokens = (
 self._named_params.dispatch_the(output, self._expander)
 if output is not None else []
 )
 self._expander.push_tokens([
 *output_tokens,
 ControlSequenceToken(SENTINEL_FINISH_OUTPUT_CS),
 ])

 def _extract_inserts_for_output(self, page_nodes: list) -> list:
 r"""Move inserts into per-class boxes unless ``\holdinginserts`` is set."""
 if self._insert_accumulator is None or self._holdinginserts_nonzero():
 return page_nodes
 kept: list = []
 for node in page_nodes:
 if isinstance(node, InsertNode):
 self._insert_accumulator.append(node)
 else:
 kept.append(node)
 return kept

 def _holdinginserts_nonzero(self) -> bool:
 r"""Return whether ``\holdinginserts`` is nonzero at output time."""
 if self._named_params is None:
 return False
 entry = self._named_params.lookup("holdinginserts")
 if entry is None:
 return False
 return self._named_params._register_set.get_count(entry.slot, _internal=True) != 0

 def _finish_output_cycle(self) -> None:
 r"""Run the page-cycle epilogue after output-routine execution.

 Called synchronously by the fast path, or by
 ``\x00finish_output_cycle`` after the token-list output body drains.
 """
 current_page_number = (
 self._pending_page_number
 if self._pending_page_number is not None
 else self.page_number
 )
 if self._marks_registry is not None:
 self._marks_registry.reset_for_new_page()

 # Step 4: check dead_cycles limit
 if self._dead_cycles > self._config.max_dead_cycles:
 raise EngineError(
 f"Output loop---? more than {self._config.max_dead_cycles} dead cycles"
 )

 if self._box_registers is not None and self._box_registers.copybox(255) is not None:
 self._box_registers.setbox(255, None, global_=True)

 # Step 5: advance pageno — plain.tex \advancepageno equivalent.
 if self._pageno_register is not None:
 self._pageno_register.set_pageno(current_page_number + 1)
 else:
 self._page_number = current_page_number + 1

 leftover = list(self._pending_leftover)
 self._pending_leftover = []
 self._pending_page_number = None

 # Step 6: reset page state
 self._mvl = []
 self._page_total = 0
 self._page_depth = 0
 self._prev_depth = _PREVDEPTH_SENTINEL # TeXbook §253 sentinel ( v5)
 self._page_stretch = {o: 0 for o in GlueOrder}
 self._page_shrink = {o: 0 for o in GlueOrder}
 self._first_box_on_page = True
 self._last_break_idx = None
 self._last_break_penalty = 0

 # Step 7: re-contribute leftover nodes.
 #
 # TeXbook §1000 ("the page is broken"): when the main vertical list is
 # recommenced after a page break, the leading run of discardable nodes
 # (glue, kern, penalty) at the top of the new page is discarded — the
 # fresh page's §1004 topskip supplies the top spacing instead. 
 # already discards the single break node (Step 1); this is the
 # complementary §1000 leading-discardables sweep. Without it,
 # the interline glue that sat between the last box of the shipped page
 # and the first box of the leftover leaks in atop the topskip and shifts
 # every continuation-page baseline down (: +3.111 pt on multipage).
 first_box = 0
 while first_box < len(leftover) and isinstance(
 leftover[first_box], (GlueNode, KernNode, PenaltyNode)
 ):
 first_box += 1
 for node in leftover[first_box:]:
 self.contribute(node)

 def _record_shipout(self) -> None:
 """Called by exec_shipout after backend.shipout().

 Resets _dead_cycles to 0 and sets _shipout_called flag.
 """
 self._dead_cycles = 0
 self._shipout_called = True
