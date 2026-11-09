"""Page builder: assembles vertical material into pages and fires the output routine.

Implements: PageBuilderConfig, ShipoutBackend,
OutputRoutineBase, PlainOutputRoutine, PageBuilder.

The PageBuilder is a stateful object owned by the engine (one instance per
document).  It owns TeX's contribution list and current page: contributions
are appended with their interline glue, and ``build_page`` - called by the
interpreter at TeX's call sites - moves them to the page, discards glue,
kerns and penalties before the first box, accounts for insertions, chooses
the least-cost break and fires the output routine.

See and for design rationale.
"""
from __future__ import annotations

import abc
import dataclasses
from collections import deque
from typing import TYPE_CHECKING, Protocol

from aspose_tex._engine.box_builder import (
    _measure_hlist,
    _measure_vlist,
    compute_badness,
    set_glue_hbox,
    set_glue_vbox,
)
from aspose_tex._engine.box_primitives import _PREVDEPTH_SENTINEL
from aspose_tex._engine.nodes import (
    INF_BAD,
    INF_PENALTY,
    RUNNING_DIMEN,
    CharNode,
    GlueNode,
    GlueSign,
    HlistNode,
    InsertNode,
    KernNode,
    LeadersNode,
    PenaltyNode,
    RuleNode,
    VlistNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._engine.tex_arith import x_over_n
from aspose_tex._engine.vert_break import (
    AWFUL_BAD,
    DEPLORABLE,
    EJECT_PENALTY,
    precedes_break,
    prune_page_top,
    vert_break,
)
from aspose_tex._input.token import ControlSequenceToken
from aspose_tex.exceptions import EngineError

if TYPE_CHECKING:
    from collections.abc import Callable

    from aspose_tex._engine.box_registers import BoxRegisterSet
    from aspose_tex._engine.expansion import Expander
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
    return _measure_vlist(nodes, None)  # type: ignore[arg-type]


def _build_pagebody_vbox(
    body_nodes: list,
    config: PageBuilderConfig | None,
    font_manager: FontManager | None,
) -> VlistNode:
    r"""Wrap *body_nodes* in the plain-TeX ``\pagebody`` vbox shape.

    The helper exists so the legacy Python ``PlainOutputRoutine`` fast-path
    and the token-list ``\output`` path build ``\box255`` with the same body
    geometry.  When *config* is present, the body is set to ``\vsize``.
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
    if config is not None and body_box.depth > config.max_depth:
        # §668/§1017: box255 is vpackaged with the page's max depth (plain's
        # \pagebody sets \boxmaxdepth\maxdepth); the excess depth moves into
        # the height, so less glue has to stretch.
        body_box.height += body_box.depth - config.max_depth
        body_box.depth = config.max_depth
        nat_h = body_box.height
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
    All dimension fields in scaled points (sp).  1 pt = 65536 sp.

    Attributes:
        vsize:           Target page height (\\vsize).
                         Plain TeX default: 42152952 sp (≈ 8.9 in).
        hsize:           Page width (\\hsize), read live by the output routine
                         on every page shipout.
                         Plain TeX default: 30785886 sp (6.5 in).
        topskip:         Glue at top of first box (\\topskip).
                         Plain TeX default: Glue(655360, 0, NORMAL, 0, NORMAL) = 10 pt.
        max_depth:       Maximum depth of last box on page (\\maxdepth).
                         Plain TeX default: 262144 sp (4 pt).
        baselineskip:    Normal interline glue (\\baselineskip via \\normalbaselines).
                         Plain TeX default: Glue(786432, 0, NORMAL, 0, NORMAL) = 12 pt.
        lineskip:        Fallback interline glue (\\lineskip).
                         Plain TeX default: Glue(65536, 0, NORMAL, 0, NORMAL) = 1 pt.
        lineskiplimit:   Threshold for switching to \\lineskip (\\lineskiplimit).
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

    Implemented by the backend modules (onwards).

    Example::

        class NullBackend:
            def shipout(self, page_number: int, box: VlistNode) -> None:
                pass   # discard — used in tests
    """

    def shipout(self, page_number: int, box: VlistNode) -> None:
        """Receive one completed page.

        Args:
            page_number: Current value of \\pageno (positive integer, starts at 1).
            box:         The finalized page VlistNode.
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
        """Assign \\pageno globally, as plain's \\global\\advance does."""
        ...


# ---------------------------------------------------------------------------
# Output routine base
# ---------------------------------------------------------------------------

class OutputRoutineBase(abc.ABC):
    """Abstract output routine.

    In full TeX, the output routine is a token list (\\output).
    Here it is a Python callback invoked by PageBuilder when a page is
    complete.  The routine receives the raw main-vertical-list tail for the
    page (a list of nodes, already stripped of trailing discardables) and is
    responsible for wrapping it into a final shipout box (``\\pagebody`` in
    plain-TeX terminology) before calling ``backend.shipout()``.

    This fast-path routine supplies the shipout part of plainoutput;
    PageBuilder performs plain's global advancepageno after it returns.

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
            body_nodes:  The raw vertical-list tail assembled by the page builder
                         for the current page (already stripped of trailing
                         discardables).  The routine owns the ``\\pagebody``
                         wrap and the final VlistNode construction.
            page_number: Current \\pageno before shipout.
            backend:     Shipout target.  Routine must call ``backend.shipout()``
                         exactly once.
        """
        ...


# ---------------------------------------------------------------------------
# Plain TeX output routine
# ---------------------------------------------------------------------------

# 1 pt = 65_536 sp
_SP_PER_PT = 65_536
FOOTLINE_BASELINESKIP_SP = 24 * _SP_PER_PT   # plain.tex \makefootline: 24pt
HEADLINE_SHIFT_SP = int(22.5 * _SP_PER_PT)    # plain.tex \makeheadline: -22.5pt


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
    (lowercase Roman).  Otherwise return the decimal digits of ``pageno``.

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
    """Plain-TeX default output routine.

    Replicates plain.tex's ``\\plainoutput`` behaviour in Python, for jobs
    that run without the plain format.  For each page:

    1. Wraps the body nodes in a ``\\vbox to\\vsize`` via
       :func:`set_glue_vbox`.  Any ``\\vfil`` / ``\\vfill`` inside the body
       stretches into real space, so the page body fills ``\\vsize`` exactly.
    2. Builds an empty headline hbox (plain TeX default ``\\headline={\\hfil}``)
       shifted up by 22.5 pt via a preceding negative kern (matches
       ``\\makeheadline``).  The headline is always empty; a user
       ``\\headline={…}`` is not read here.
    3. Builds a footline hbox of width ``hsize`` containing
       ``\\hss \\tenrm \\folio \\hss`` — CharNodes for each digit of
       ``\\folio`` surrounded by ``\\hss`` glue (plain TeX default
       ``\\footline={\\hss\\tenrm\\folio\\hss}``).  The footline sits
       24 pt below the body's last baseline (``\\makefootline``).
    4. Ships the assembled VlistNode through ``backend.shipout()``.

    The ``\\folio`` value is read from the ``PageNumberRegister`` if wired;
    otherwise it falls back to the ``page_number`` argument.

    Args:
        hsize:             Page width in sp (plain-TeX default: 6.5 in = 30_785_886).
        font_manager:      FontManager used to resolve the ``tenrm`` font and
                           produce CharNode metrics for folio digits.  May be
                           ``None`` for pure-vlist unit tests — in that case
                           the footline is emitted empty (no digits).
        pageno_register:   Optional ``PageNumberRegister``.  If provided, the
                           routine reads ``get_pageno()`` when typesetting
                           \\folio.  When ``None``, the ``page_number``
                           argument is used.
        config:            Optional ``PageBuilderConfig``.  If provided, the
                           routine reads ``config.vsize`` on each execute
                           call and wraps the page body in
                           ``\\vbox to\\vsize``.  When ``None`` the body is
                           built at its natural height (which
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
        """Build a plain-TeX page VlistNode and ship it.  See class docstring."""
        # Read \hsize live from the config on every shipout so user
        # \hsize assignments reach the page box, mirroring
        # how _build_pagebody reads self._config.vsize live.  The constructor
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
        #    then a compensating positive kern restores the body position).
        #    In practice plain.tex handles this inside \makeheadline by using
        #    \vbox to0pt — the headline takes zero vertical space in the
        #    vlist.  We reproduce the visual via KernNodes: first a kern of
        #    -headline_shift that raises the headline, then the headline
        #    hbox (natural height), then a kern that restores the position
        #    so the body still starts at the page origin.
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
        stretches into real space.  The target height is read from
        ``self._config.vsize`` if a config was wired; otherwise the body is
        built at its natural height (which preserves unit tests
        that do not need vsize stretching).
        """
        return _build_pagebody_vbox(body_nodes, self._config, self._font_manager)

    def _build_headline(self, hsize: int) -> HlistNode:
        """Build the plain-TeX default headline (``\\headline={\\hfil}``).

        Zero-height, zero-depth HlistNode of width ``hsize``.  Always
        empty; a user ``\\headline={…}`` is not read here.
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
            font_name = self._font_manager.font_id("tenrm")
            metrics = self._font_manager.get_metrics(font_name)
            if metrics is not None:
                for digit in _format_folio(folio_value):
                    code = ord(digit)
                    nodes.append(CharNode(char=code, font_name=font_name))
        nodes.append(_hss_glue())

        nat_w, nat_h, nat_d = _measure_hlist(nodes, self._font_manager)  # type: ignore[arg-type]
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

# TeX's page_contents states (§980): nothing yet, only insertions, a box.
PAGE_EMPTY: int = 0
PAGE_INSERTS_ONLY: int = 1
PAGE_BOX_THERE: int = 2

# §421: \pagegoal reads max_dimen while the page is empty.
MAX_DIMEN: int = 0o7777777777

# §1054 its_all_over: the penalty that flushes residual material at \end.
_END_PENALTY: int = -0o10000000000

_ZERO_GLUE = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)

_UNDO_COMMANDS = ((GlueNode, "unskip"), (KernNode, "unkern"), (PenaltyNode, "unpenalty"))


@dataclasses.dataclass(slots=True)
class _PageIns:
    r"""A page insertion record for one ``\insert`` class (§981).

    Attributes:
        class_:     The insertion class ``n``.
        split_up:   Whether an insertion of this class was split (§1010).
        height:     Material of class ``n`` committed to this page, plus the
                    box's previous contents (TeX's ``height(r)``).
        last_ins:   The last insertion of the class placed on the page.
        best_ins:   ``last_ins`` at the best break so far (``best_ins_ptr``).
        broken_ins: The insertion that was split.
        broken_at:  Index of the split point in ``broken_ins.vlist``; ``None``
                    when the best split is at its end.
    """

    class_: int
    split_up: bool = False
    height: int = 0
    last_ins: InsertNode | None = None
    best_ins: InsertNode | None = None
    broken_ins: InsertNode | None = None
    broken_at: int | None = None


def _scaled(value: int, count: int) -> int:
    r"""Scale *value* by ``\count n``/1000 the way §1009 does."""
    if count == 1000:
        return value
    return x_over_n(value, 1000) * count


class PageBuilder:
    """Assembles typeset vertical material into pages.

    Material is appended to the *contribution list* and only moved to the
    current page when the interpreter calls :meth:`build_page` at one of
    TeX's call sites (box end, paragraph start and end, ``\\penalty``,
    ``\\insert``, after a display, after an alignment, after ``\\output``,
    ``\\end``).  Moving follows TeX §1000: glue, kerns and penalties before
    the first box are discarded, legal breakpoints are costed (§1005) and the
    page fires at the best one.

    Usage::

        config = PageBuilderConfig(...)
        backend = MyDviBackend()
        builder = PageBuilder(config, backend)
        for line in exec_par(par_list, params, font_manager):
            builder.contribute(line)
        builder.build_page()
        builder.end_of_document()

    Attributes:
        warnings: List of warning strings (e.g. "Overfull \\\\vbox ...") accumulated
                  during processing.  Callers may inspect after use.
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
        named_params: NamedParameterRegistry | None = None,
        expander: Expander | None = None,
        font_manager: FontManager | None = None,
        on_output_start: Callable[[], None] | None = None,
    ) -> None:
        """Initialise the page builder.

        Args:
            config:           Mutable configuration object; may be updated
                              externally as registers change.
            backend:          Shipout target.
            output_routine:   Output routine to execute when a page is
                              complete.  If None, uses PlainOutputRoutine
                              with hsize=0.
            pageno_register:  Optional ``PageNumberRegister``.  When provided
                              the page counter is read from / written to the
                              register (the replacement for plain.tex's
                              ``\\advancepageno``).  When None, an internal
                              integer counter is used.
            marks_registry:   Optional mark registry updated around
                              output-routine execution.
            box_registers:    Optional box-register bank for token-list
                              output dispatch.  ``\\box255`` and the
                              insertion boxes are written here.
            named_params:     Optional named-parameter registry for reading
                              ``\\output``, insertion registers and writing
                              ``\\outputpenalty``.
            expander:         Optional expander used to push ``\\output`` toks
                              plus the private finish sentinel.
            font_manager:     Optional font manager used to size boxes.
            on_output_start:  Called when a token-list ``\\output`` is about
                              to run, so the interpreter can open the output
                              routine's own nest.
        """
        self._config = config
        self._backend = backend
        self._output_routine: OutputRoutineBase = (
            output_routine if output_routine is not None else PlainOutputRoutine(hsize=0)
        )
        self._pageno_register = pageno_register
        self._marks_registry = marks_registry
        self._box_registers = box_registers
        self._named_params = named_params
        self._expander = expander
        self._font_manager = font_manager
        self._on_output_start = on_output_start

        # The current page (TeX's page_head..page_tail) and the contribution
        # list that feeds it.
        self._mvl: list = []
        self._contrib: deque[Node] = deque()
        self._building: bool = False
        self._page_contents: int = PAGE_EMPTY

        # page_so_far (§982); reset only by _freeze_page_specs.
        self._page_goal: int = config.vsize
        self._page_total: int = 0
        self._page_depth: int = 0
        self._page_max_depth: int = config.max_depth
        self._page_stretch: dict[GlueOrder, int] = {o: 0 for o in GlueOrder}
        self._page_shrink: dict[GlueOrder, int] = {o: 0 for o in GlueOrder}

        # §679 contribution-side state: TeXbook §253 / §679 -1000 pt "ignore"
        # sentinel suppresses the interline glue before the first box.
        self._prev_depth: int = _PREVDEPTH_SENTINEL
        self._skip_interline_once: bool = False
        self._no_interline: bool = False

        # §996: the node most recently taken from the contribution list.
        self._last_moved: Node | None = None

        # §1005: least-cost break selection over the current page.
        self._best_break_idx: int | None = None
        self._best_break_penalty: int = INF_PENALTY
        self._best_break_total: int = 0
        self._best_size: int = config.vsize
        self._least_page_cost: int = AWFUL_BAD

        # Insertions (§1008-§1010, §1018-§1022).
        self._page_ins: dict[int, _PageIns] = {}
        self._insert_penalties: int = 0
        self._held_inserts: list[InsertNode] = []

        # Output routine state
        self._dead_cycles: int = 0
        # Internal fallback counter (used when no register is wired).
        self._page_number: int = 1
        self._shipout_called: bool = False  # per-output-routine-call flag
        self._output_is_user_redefined: bool = False
        self._output_active: bool = False

        # Warnings accumulator
        self.warnings: list[str] = []

    # ------------------------------------------------------------------
    # Public read-only properties (special registers)
    # ------------------------------------------------------------------

    @property
    def is_at_top_of_page(self) -> bool:
        """Whether no box or rule has reached the current page yet.

        Returns:
            True while TeX's ``page_contents`` is below ``box_there`` — the
            page is empty or holds only insertions.
        """
        return self._page_contents != PAGE_BOX_THERE

    def _page_so_far_hidden(self) -> bool:
        """§421: an empty page reads as unset unless ``\\output`` is active."""
        return self._page_contents == PAGE_EMPTY and not self.output_cycle_pending

    @property
    def page_total(self) -> int:
        """\\pagetotal — accumulated natural height of material on current page (sp)."""
        return 0 if self._page_so_far_hidden() else self._page_total

    @property
    def page_goal(self) -> int:
        """\\pagegoal — current page height goal (sp).

        ``\\maxdimen`` while the page is empty (§421); otherwise the value
        frozen when the first box or insertion arrived (§987), lowered by the
        insertions on the page (§1008-§1010).
        """
        return MAX_DIMEN if self._page_so_far_hidden() else self._page_goal

    @property
    def last_contributed_node(self) -> Node | None:
        """Return the tail of the contribution list, else the last moved node.

        TeX reads ``\\lastskip``/``\\lastpenalty``/``\\lastkern`` in vertical
        mode from the contribution list's tail, or — when it is empty — from
        the last node ``build_page`` took from it (§424, §996).

        Returns:
            The node, or ``None`` when nothing qualifies.
        """
        if self._contrib:
            return self._contrib[-1]
        return self._last_moved

    @property
    def page_depth(self) -> int:
        """\\pagedepth — depth of the last box on the current page (sp), clamped."""
        return 0 if self._page_so_far_hidden() else self._page_depth

    @property
    def page_stretch(self) -> int:
        """\\pagestretch — total NORMAL-order stretch of glue on current page (sp)."""
        return 0 if self._page_so_far_hidden() else self._page_stretch[GlueOrder.NORMAL]

    @property
    def page_fil_stretch(self) -> int:
        """\\pagefilstretch — total FIL-order stretch (sp)."""
        return 0 if self._page_so_far_hidden() else self._page_stretch[GlueOrder.FIL]

    @property
    def page_filstretch(self) -> int:
        """Alias for \\pagefilstretch using callback spelling."""
        return self.page_fil_stretch

    @property
    def page_fill_stretch(self) -> int:
        """\\pagefillstretch — total FILL-order stretch (sp)."""
        return 0 if self._page_so_far_hidden() else self._page_stretch[GlueOrder.FILL]

    @property
    def page_fillstretch(self) -> int:
        """Alias for \\pagefillstretch using callback spelling."""
        return self.page_fill_stretch

    @property
    def page_filll_stretch(self) -> int:
        """\\pagefilllstretch — total FILLL-order stretch (sp)."""
        return 0 if self._page_so_far_hidden() else self._page_stretch[GlueOrder.FILLL]

    @property
    def page_filllstretch(self) -> int:
        """Alias for \\pagefilllstretch using callback spelling."""
        return self.page_filll_stretch

    @property
    def page_shrink(self) -> int:
        """\\pageshrink — total NORMAL-order shrink of glue on current page (sp)."""
        return 0 if self._page_so_far_hidden() else self._page_shrink[GlueOrder.NORMAL]

    @property
    def dead_cycles(self) -> int:
        """\\deadcycles — number of output routine calls without a \\shipout."""
        return self._dead_cycles

    @dead_cycles.setter
    def dead_cycles(self, value: int) -> None:
        # §1246 alter_integer: a \deadcycles assignment is always global.
        self._dead_cycles = value

    @property
    def insert_penalties(self) -> int:
        r"""\\insertpenalties — split and floating penalties on the current page.

        While ``\output`` runs it is the number of held-over insertions
        (§1013, §1022).
        """
        return self._insert_penalties

    @insert_penalties.setter
    def insert_penalties(self, value: int) -> None:
        # §1246 alter_integer: an \insertpenalties assignment is always global.
        self._insert_penalties = value

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
        return self._output_active

    # ------------------------------------------------------------------
    # Contribution list
    # ------------------------------------------------------------------

    def contribute(self, node: Node) -> None:  # type: ignore[name-defined]
        """Append a node to the contribution list (§679 ``append_to_vlist``).

        A box is preceded by its interline glue.  Nothing is moved to the
        page: that is :meth:`build_page`'s job, called by the interpreter at
        TeX's call sites.

        Args:
            node: Any Node from nodes.py.
        """
        self._contrib.extend(self._append_to_vlist(node))

    def contribute_spliced(self, nodes: list) -> None:
        r"""Append unpackaged children without changing logical prevdepth.

        ``\unvbox`` material (§1110) and migrated ``\vadjust``/``\insert``
        material carry their own glue, so no interline glue is added
        Nothing is moved to the page.

        Args:
            nodes: Children returned by vertical unpackaging.
        """
        self._contrib.extend(nodes)

    def _append_to_vlist(self, node: Node) -> list:
        """Return *node* preceded by its §679 interline glue, if any.

        Updates ``_prev_depth`` (box → its depth, rule → the ignore sentinel).
        TeX computes the glue even at the top of a page; §1000 discards it
        there when it is moved.
        """
        items: list = []
        if isinstance(node, (HlistNode, VlistNode)):
            glue = self._interline_glue(node)
            if glue is not None:
                items.append(glue)
            self._prev_depth = node.depth
        elif isinstance(node, RuleNode):
            # TeX:The Program §679: prev_depth <- ignore_depth.
            self._prev_depth = _PREVDEPTH_SENTINEL
        items.append(node)
        return items

    def build_page(self) -> None:
        """Move the contribution list to the current page (§994 ``build_page``).

        Returns at once while a token-list output routine is active or when
        called re-entrantly (a synchronous output routine finishing inside a
        move — the outer loop carries on).  Stops early when a kern is the
        last contribution (§1000 waits for its successor) or when a page fires
        into a token-list ``\\output``.

        Raises:
            EngineError: if dead_cycles exceeds config.max_dead_cycles.
        """
        if self._building or self.output_cycle_pending:
            return
        self._building = True
        try:
            while self._contrib and not self.output_cycle_pending:
                node = self._contrib[0]
                self._last_moved = node
                if not self._move_to_page(node):
                    return
        finally:
            self._building = False

    def _move_to_page(self, node: Node) -> bool:
        """Move the head of the contribution list to the page (§1000-§1004).

        Returns:
            False when building must stop (kern awaiting its successor, or a
            token-list output routine started).
        """
        contents = self._page_contents
        if isinstance(node, (HlistNode, VlistNode, RuleNode)):
            if contents < PAGE_BOX_THERE:
                # §1001: \topskip goes in front of the first box and is moved
                # next as ordinary glue.
                if contents == PAGE_EMPTY:
                    self._freeze_page_specs(PAGE_BOX_THERE)
                else:
                    self._page_contents = PAGE_BOX_THERE
                self._contrib.appendleft(self._topskip_glue(node))
                return True
            self._page_total += self._page_depth + _extent(node.height)
            self._page_depth = _extent(node.depth)
            self._link_head()
            return True

        if isinstance(node, InsertNode):
            if contents == PAGE_EMPTY:
                self._freeze_page_specs(PAGE_INSERTS_ONLY)
            self._append_insertion(node)
            self._link_head()
            return True

        pi: int | None
        if isinstance(node, (GlueNode, LeadersNode)):
            if contents < PAGE_BOX_THERE:
                self._contrib.popleft()
                return True
            pi = 0 if precedes_break(self._mvl[-1] if self._mvl else None) else None
        elif isinstance(node, KernNode):
            if contents < PAGE_BOX_THERE:
                self._contrib.popleft()
                return True
            if len(self._contrib) == 1:
                return False  # §1000: a kern waits until its successor is known
            pi = 0 if isinstance(self._contrib[1], (GlueNode, LeadersNode)) else None
        elif isinstance(node, PenaltyNode):
            if contents < PAGE_BOX_THERE:
                self._contrib.popleft()
                return True
            pi = node.penalty
        else:
            # Marks, whatsits and anything else simply join the page.
            self._link_head()
            return True

        if pi is not None and pi < INF_PENALTY and self._try_break(pi):
            self._fire_up(node)
            return not self.output_cycle_pending

        if isinstance(node, (GlueNode, LeadersNode)):
            glue = node.glue
            self._page_stretch[glue.stretch_order] += glue.stretch
            if glue.shrink_order != GlueOrder.NORMAL and glue.shrink != 0:
                self.warnings.append("Infinite glue shrinkage found on current page")
            self._page_shrink[GlueOrder.NORMAL] += glue.shrink
            width = glue.width
        elif isinstance(node, KernNode):
            width = node.width
        else:
            width = None
        if width is not None:
            # §1004: glue and kerns fold the last box's depth into the total.
            self._page_total += self._page_depth + width
            self._page_depth = 0
        self._link_head()
        return True

    def _link_head(self) -> None:
        """Link the contribution list's head into the page (§1003)."""
        if self._page_depth > self._page_max_depth:
            self._page_total += self._page_depth - self._page_max_depth
            self._page_depth = self._page_max_depth
        self._mvl.append(self._contrib.popleft())

    def _topskip_glue(self, node: HlistNode | VlistNode | RuleNode) -> GlueNode:
        """Return the §1001 ``\\topskip`` glue for the page's first box."""
        topskip = self._config.topskip
        return GlueNode(Glue(
            max(0, topskip.width - _extent(node.height)),
            topskip.stretch, topskip.stretch_order,
            topskip.shrink, topskip.shrink_order,
        ))

    def _freeze_page_specs(self, contents: int) -> None:
        """Start measuring a page (§987 ``freeze_page_specs``)."""
        self._page_contents = contents
        self._page_goal = self._config.vsize
        self._page_max_depth = self._config.max_depth
        self._page_depth = 0
        self._page_total = 0
        self._page_stretch = {o: 0 for o in GlueOrder}
        self._page_shrink = {o: 0 for o in GlueOrder}
        self._reset_best_break()

    def _start_new_page(self) -> None:
        """Empty the current page (§991); ``page_so_far`` keeps its values."""
        self._page_contents = PAGE_EMPTY
        self._mvl = []
        self._last_moved = None
        self._page_depth = 0
        self._page_max_depth = 0
        self._page_ins.clear()

    def _try_break(self, penalty: int) -> bool:
        """Cost a legal breakpoint at the head of the contribution list (§1005).

        The breakpoint will be at ``_mvl[len(_mvl)]`` once linked.  It is
        recorded as the best break when its cost is the least so far (``<=``,
        so ties go to the later breakpoint), together with the page goal and
        each insertion class's last insertion.

        Args:
            penalty: The breakpoint's penalty (0 for glue and kern).

        Returns:
            True when the page must fire now, at the best break.
        """
        goal = self._page_goal
        page_total = self._page_total
        if page_total < goal:
            if any(self._page_stretch[order] != 0 for order in (
                GlueOrder.FIL, GlueOrder.FILL, GlueOrder.FILLL,
            )):
                badness = 0
            else:
                badness = compute_badness(
                    goal - page_total, self._page_stretch[GlueOrder.NORMAL],
                )
        elif page_total - goal > self._page_shrink[GlueOrder.NORMAL]:
            badness = AWFUL_BAD
        else:
            badness = compute_badness(
                page_total - goal, self._page_shrink[GlueOrder.NORMAL],
            )

        if badness < AWFUL_BAD:
            if penalty <= EJECT_PENALTY:
                cost = penalty
            elif badness < INF_BAD:
                cost = badness + penalty + self._insert_penalties
            else:
                cost = DEPLORABLE
        else:
            cost = badness
        if self._insert_penalties >= INF_PENALTY:
            cost = AWFUL_BAD

        if cost <= self._least_page_cost:
            self._best_break_idx = len(self._mvl)
            self._best_break_total = page_total
            self._best_size = goal
            self._least_page_cost = cost
            for record in self._page_ins.values():
                record.best_ins = record.last_ins
        return cost == AWFUL_BAD or penalty <= EJECT_PENALTY

    # ------------------------------------------------------------------
    # Insertions (§1008-§1010)
    # ------------------------------------------------------------------

    def _insert_class(self, class_: int) -> tuple[int, int, Glue, VlistNode | None]:
        r"""Return ``(\count n, \dimen n, \skip n, \box n)`` for class *class_*.

        Without a register set the class behaves as a plain unscaled,
        unlimited insertion with no ``\skip``.  A non-vbox ``\box n`` is
        reported and treated as void (§993 ``ensure_vbox``).
        """
        if self._named_params is None:
            count, dimen, skip = 1000, MAX_DIMEN, _ZERO_GLUE
        else:
            registers = self._named_params._register_set
            count = registers.get_count(class_)
            dimen = registers.get_dimen(class_)
            skip = registers.get_skip(class_)
        box = self._box_registers.copybox(class_) if self._box_registers is not None else None
        if box is not None and not isinstance(box, VlistNode):
            self.warnings.append("Insertions can only be added to a vbox")
            box = None
        return count, dimen, skip, box

    def _append_insertion(self, node: InsertNode) -> None:
        """Account for an insertion moved to the page (§1008-§1010).

        The page goal is lowered — never ``page_total`` raised — and an
        insertion that does not fit is split at its best break.
        """
        class_ = node.class_
        count, dimen, skip, box = self._insert_class(class_)
        record = self._page_ins.get(class_)
        if record is None:
            # §1009: once per class and page, reserve the box's current
            # contents and the \skip n glue.
            record = _PageIns(class_=class_)
            if box is not None:
                record.height = box.height + box.depth
            self._page_ins[class_] = record
            self._page_goal -= _scaled(record.height, count) + skip.width
            self._page_stretch[skip.stretch_order] += skip.stretch
            if skip.shrink_order != GlueOrder.NORMAL and skip.shrink != 0:
                self.warnings.append(
                    f"Infinite glue shrinkage inserted from \\skip {class_}",
                )
            self._page_shrink[GlueOrder.NORMAL] += skip.shrink

        if record.split_up:
            self._insert_penalties += node.floating_penalty
            return
        record.last_ins = node
        size = node.height + node.depth  # TeX's height(p) of an ins_node (§1100)
        delta = (
            self._page_goal - self._page_total - self._page_depth
            + self._page_shrink[GlueOrder.NORMAL]
        )
        needed = _scaled(size, count)
        if (needed <= 0 or needed <= delta) and size + record.height <= dimen:
            self._page_goal -= needed
            record.height += size
            return

        # §1010: split the insertion at its best break.
        if count <= 0:
            room = MAX_DIMEN
        else:
            room = self._page_goal - self._page_total - self._page_depth
            if count != 1000:
                room = x_over_n(room, count) * 1000
        room = min(room, dimen - record.height)
        break_at, best_size = vert_break(node.vlist, room, node.split_max_depth)
        record.height += best_size
        self._page_goal -= _scaled(best_size, count)
        record.split_up = True
        record.broken_at = break_at
        record.broken_ins = node
        if break_at is None:
            self._insert_penalties += EJECT_PENALTY
        elif isinstance(node.vlist[break_at], PenaltyNode):
            self._insert_penalties += node.vlist[break_at].penalty

    def _distribute_insertions(self, page_nodes: list) -> list:
        """Move the page's insertions into their boxes (§1018-§1022).

        Returns the page without the insertions it gave up; insertions that
        must wait go to ``_held_inserts`` and are counted in
        ``\\insertpenalties``.  With ``\\holdinginserts > 0`` nothing moves.
        """
        if self._box_registers is None or self._holdinginserts_nonzero():
            return page_nodes
        queues: dict[int, list] = {}
        for class_, record in self._page_ins.items():
            if record.best_ins is not None:
                box = self._box_registers.copybox(class_) if self._box_registers else None
                queues[class_] = list(box.list) if isinstance(box, VlistNode) else []

        kept: list = []
        for node in page_nodes:
            if not isinstance(node, InsertNode):
                kept.append(node)
                continue
            record = self._page_ins.get(node.class_)
            if record is None or record.best_ins is None:
                self._hold_insertion(node)
                continue
            material = list(node.vlist)
            held: InsertNode | None = None
            if record.best_ins is node:
                if (record.split_up and record.broken_ins is node
                        and record.broken_at is not None):
                    material = list(node.vlist[:record.broken_at])
                    rest = prune_page_top(node.vlist[record.broken_at:], node.split_top_skip)
                    if rest:
                        _w, rest_h, rest_d = _measure_vlist(rest, self._font_manager)
                        held = dataclasses.replace(
                            node, vlist=tuple(rest), height=rest_h, depth=rest_d,
                        )
                record.best_ins = None
                queues[node.class_].extend(material)
                self._set_insertion_box(node.class_, queues[node.class_])
            else:
                queues[node.class_].extend(material)
            if held is not None:
                self._hold_insertion(held)
        return kept

    def _hold_insertion(self, node: InsertNode) -> None:
        """Keep *node* for the next page (§1022)."""
        self._held_inserts.append(node)
        self._insert_penalties += 1

    def _set_insertion_box(self, class_: int, nodes: list) -> None:
        r"""Pack ``\box n`` at natural size from *nodes* (§1021)."""
        if self._box_registers is None:
            return
        width, height, depth = _measure_vlist(nodes, self._font_manager)
        self._box_registers.setbox(
            class_,
            VlistNode(
                list=list(nodes), width=width, height=height, depth=depth,
                shift_amount=0, glue_sign=GlueSign.NORMAL,
                glue_order=GlueOrder.NORMAL, glue_set=0.0,
            ),
            global_=True,
        )

    def _holdinginserts_nonzero(self) -> bool:
        r"""Return whether ``\holdinginserts`` is positive at output time."""
        if self._named_params is None:
            return False
        entry = self._named_params.lookup("holdinginserts")
        if entry is None:
            return False
        return self._named_params._register_set.get_count(entry.slot, _internal=True) > 0

    # ------------------------------------------------------------------
    # Firing the output routine (§1012-§1028)
    # ------------------------------------------------------------------

    def _fire_up(self, current: Node) -> None:
        """Break the page at the best breakpoint and run ``\\output`` (§1012).

        *current* is the contribution-list head that triggered the fire; it
        has not been linked into the page yet.
        """
        best = self._best_break_idx
        assert best is not None, "a firing breakpoint is always recorded first"
        overflow = self._best_break_total - self._best_size
        if self._least_page_cost == AWFUL_BAD and overflow > 0:
            self.warnings.append(f"Overfull \\vbox ({overflow} sp too tall)")

        # §1013: \outputpenalty; the break penalty itself becomes 10000 and
        # stays with the material after the break (§1000 discards it there).
        page_nodes = self._mvl[:best]
        rest = self._mvl[best:]
        break_node = rest[0] if rest else current
        if isinstance(break_node, PenaltyNode):
            self._best_break_penalty = break_node.penalty
            if rest:
                rest[0] = PenaltyNode(INF_PENALTY)
            else:
                self._contrib[0] = PenaltyNode(INF_PENALTY)
        else:
            self._best_break_penalty = INF_PENALTY
        self._contrib.extendleft(reversed(rest))

        if self._marks_registry is not None:
            self._marks_registry.fire_up(page_nodes)

        token_list = self._should_use_token_list_output()
        if token_list:
            assert self._box_registers is not None
            if self._box_registers.copybox(255) is not None:
                self.warnings.append("\\box255 is not void")
                self._box_registers.setbox(255, None, global_=True)

        self._insert_penalties = 0
        page_nodes = self._distribute_insertions(page_nodes)
        best_size = self._best_size
        page_max_depth = self._page_max_depth
        self._start_new_page()

        self._dead_cycles += 1
        current_page_number = self.page_number
        self._output_active = True
        self._shipout_called = False

        if token_list:
            self._start_token_list_output(
                _package_page_box(page_nodes, best_size, page_max_depth, self._font_manager),
            )
            return

        # §1023 default output: held-over insertions go straight back to the
        # contribution list.  The Python routine emulates \plainoutput, so it
        # still wraps the body to \vsize.
        self._contrib.extendleft(reversed(self._held_inserts))
        self._held_inserts = []
        tracking_backend = _TrackingBackend(self._backend, self)
        self._output_routine.execute(page_nodes, current_page_number, tracking_backend)
        self._advance_pageno()
        self.finish_output_cycle(None)

    def _advance_pageno(self) -> None:
        r"""Run plain's global, sign-aware \advancepageno for the fast path.

        Token-list outputs own their assignments themselves.
        """
        pageno = self.page_number
        value = pageno - 1 if pageno < 0 else pageno + 1
        if self._pageno_register is not None:
            self._pageno_register.set_pageno(value)
        else:
            self._page_number = value

    def _should_use_token_list_output(self) -> bool:
        """Return True when all collaborators are wired."""
        return (
            self._output_is_user_redefined
            and self._box_registers is not None
            and self._named_params is not None
            and self._expander is not None
        )

    def _start_token_list_output(self, page_box: VlistNode) -> None:
        r"""Set ``\box255``, open the output nest and push ``\output`` toks."""
        assert self._box_registers is not None
        assert self._named_params is not None
        assert self._expander is not None

        self._box_registers.setbox(255, page_box, global_=True)

        outputpenalty = self._named_params.lookup("outputpenalty")
        if outputpenalty is not None:
            self._named_params._register_set.set_count(
                outputpenalty.slot,
                self._best_break_penalty,
                _internal=True,
            )

        if self._on_output_start is not None:
            self._on_output_start()
        output = self._named_params.lookup("output")
        output_tokens = (
            self._named_params.dispatch_the(output, self._expander)
            if output is not None else []
        )
        self._expander.push_tokens([
            *output_tokens,
            ControlSequenceToken(SENTINEL_FINISH_OUTPUT_CS),
        ])

    def finish_output_cycle(self, output_nodes: list | None = None) -> None:
        r"""Resume page building after the output routine (§1026).

        Called synchronously by the Python fast path (``output_nodes`` is
        ``None``) or by the interpreter when the token-list ``\output`` has
        drained, with the vertical list the routine built in its own nest.
        Held-over insertions and that list go in front of the contribution
        list, then building resumes. Page numbers and marks are retained.

        Args:
            output_nodes: The output routine's vertical list (token-list path).

        Raises:
            EngineError: if dead_cycles exceeds config.max_dead_cycles.
        """
        if self._dead_cycles > self._config.max_dead_cycles:
            raise EngineError(
                f"Output loop---? more than {self._config.max_dead_cycles} dead cycles"
            )

        if self._box_registers is not None and self._box_registers.copybox(255) is not None:
            self.warnings.append("Output routine didn't use all of \\box255")
            self._box_registers.setbox(255, None, global_=True)

        self._output_active = False
        if output_nodes is not None:
            # §1026: \insertpenalties counted the held-over insertions.
            self._insert_penalties = 0
        front = [*self._held_inserts, *(output_nodes or [])]
        self._held_inserts = []
        self._contrib.extendleft(reversed(front))
        self.build_page()

    def _record_shipout(self) -> None:
        """Called by exec_shipout after backend.shipout().

        Resets _dead_cycles to 0 and sets _shipout_called flag.
        """
        self._dead_cycles = 0
        self._shipout_called = True

    # ------------------------------------------------------------------
    # End of the document (§1054)
    # ------------------------------------------------------------------

    def its_all_over(self) -> bool:
        r"""Try to finish the document as ``\end`` does (§1054 ``its_all_over``).

        When the page, the contribution list and ``\deadcycles`` are all
        empty the document is over.  Otherwise
        ``\hbox to\hsize{}\vfill\penalty-'10000000000`` is contributed and the
        page is built, which ships the residual material.

        Like TeX, the lists are checked *before* anything is built, so glue
        still waiting on the contribution list (``\vskip1pt\end``) ships a
        page.

        Returns:
            True when nothing is left; False when the caller must run any
            pending ``\output`` and try again.
        """
        if self.output_cycle_pending:
            return False
        if not self._mvl and not self._contrib and self._dead_cycles == 0:
            return True
        self._contrib.extend((
            HlistNode(
                list=[], width=self._config.hsize, height=0, depth=0,
                shift_amount=0, glue_sign=GlueSign.NORMAL,
                glue_order=GlueOrder.NORMAL, glue_set=0.0,
            ),
            GlueNode(Glue(0, _SP_PER_PT, GlueOrder.FILL, 0, GlueOrder.NORMAL)),
            PenaltyNode(_END_PENALTY),
        ))
        self.build_page()
        return False

    def end_of_document(self) -> None:
        """Flush remaining material through :meth:`its_all_over`.

        Stops early when a token-list output routine has to run first; the
        interpreter drains it and calls :meth:`its_all_over` again.
        """
        while not self.its_all_over():
            if self.output_cycle_pending:
                return

    # ------------------------------------------------------------------
    # Interline glue and tail removal
    # ------------------------------------------------------------------

    def skip_next_interline(self) -> None:
        """\\nointerlineskip — suppress interline glue before the NEXT box only."""
        self._skip_interline_once = True

    def off_interline(self) -> None:
        """\\offinterlineskip — permanently disable all interline glue."""
        self._no_interline = True

    def remove_last_node(self, *types: type) -> Node | None:
        """Remove the contribution list's tail when it matches one of ``types``.

        TeX never removes anything from the current page (§1105): with an
        empty contribution list ``\\unskip`` after glue reached the page, and
        ``\\unkern``/``\\unpenalty`` always, report "You can't use ... in
        vertical mode." and change nothing.

        Args:
            *types: Node types that are eligible for removal (e.g.
                ``GlueNode`` for ``\\unskip``).

        Returns:
            The popped node, or ``None`` when nothing was removed.
        """
        if self._contrib:
            if not isinstance(self._contrib[-1], types):
                return None
            return self._contrib.pop()
        for node_type, command in _UNDO_COMMANDS:
            if node_type in types:
                if node_type is not GlueNode or isinstance(
                    self._last_moved, (GlueNode, LeadersNode),
                ):
                    self.warnings.append(
                        f"You can't use `\\{command}' in vertical mode.",
                    )
                break
        return None

    def _interline_glue(self, node: HlistNode | VlistNode | RuleNode) -> GlueNode | None:
        """Return the §679 interline glue to put before *node*, or None.

        Consumes a pending ``\\nointerlineskip``; ``\\offinterlineskip``
        stays in force until explicitly cleared.
        """
        if self._skip_interline_once or self._no_interline:
            # Suppress interline glue (once or permanently).
            self._skip_interline_once = False
            return None
        # TeXbook §253: prev_depth <= -1000 pt is the "ignore" sentinel;
        # no interline glue is inserted.  Set by TeX:The Program §679
        # (`contribute_rule`) and by `\nointerlineskip`
        # (plain.tex: `\prevdepth-1000\p@`).  See v5 Component 6.
        if self._prev_depth <= _PREVDEPTH_SENTINEL:
            return None
        # Normal interline glue (See).  The three parameters are
        # read LIVE — `cfg` carries only their defaults, so a
        # `\baselineskip` assignment (plain TeX's `\displ@y` does
        # `\openup\jot`) reaches the computation instead of being ignored.
        baselineskip, lineskip, lineskiplimit = self._interline_params()
        ideal = baselineskip.width - self._prev_depth - node.height
        if ideal < lineskiplimit:
            return GlueNode(lineskip)
        return GlueNode(Glue(
            ideal,
            baselineskip.stretch,
            baselineskip.stretch_order,
            baselineskip.shrink,
            baselineskip.shrink_order,
        ))

    def _interline_params(self) -> tuple[Glue, Glue, int]:
        r"""Return the live ``(\baselineskip, \lineskip, \lineskiplimit)``.

        ``PageBuilderConfig`` is built once at interpreter
        construction, so reading these three from it meant **no** user
        assignment ever reached the interline computation — measurable without
        any display: ``\baselineskip=30pt`` still produced 12 pt glue.  The
        display families made it visible because plain TeX's ``\displ@y``
        applies ``\openup\jot`` (+3 pt to all three) on display entry.

        Read **per contribution**, not cached per page: ``\displ@y`` changes the
        values in the middle of a page, so a per-page snapshot would miss it.

        Each parameter falls back to its ``_config`` value individually when the
        named-parameter registry is absent (several tests construct a
        ``PageBuilder`` without one), does not register that name, or **still
        holds zero**.

        That last case is what makes the config a genuine default rather than
        dead weight: with ``load_format=False`` no format runs
        ``\normalbaselines``, so the registers read ``0/0/0`` while the config
        carries plain TeX's ``12 pt / 1 pt / 0``.  Taking the register value
        unconditionally there would silently collapse every interline gap to
        ``\lineskip`` — measured: the smoke-fixture byte-stability MD5s all moved.
        A document that genuinely wants ``\baselineskip=0pt`` sets it explicitly
        *and* loads a format, in which case the other two are non-zero and the
        interline computation behaves as TeX's does.

        Returns:
            ``(baselineskip, lineskip, lineskiplimit)`` — the first two as
            :class:`Glue`, the third in sp.
        """
        cfg = self._config
        if self._named_params is None:
            return cfg.baselineskip, cfg.lineskip, cfg.lineskiplimit

        registers = self._named_params._register_set

        def _skip(name: str, default: Glue) -> Glue:
            entry = self._named_params.lookup(name)
            if entry is None:
                return default
            live = registers.get_skip(entry.slot, _internal=True)
            return default if live.width == 0 else live

        def _dimen(name: str, default: int, *, live_baselineskip: bool) -> int:
            # \lineskiplimit is legitimately 0 in plain TeX, so "zero means
            # uninitialised" cannot be applied to it directly.  Track the
            # format's presence through \baselineskip instead: once that is
            # live, \lineskiplimit's register is authoritative too.
            entry = self._named_params.lookup(name)
            if entry is None or not live_baselineskip:
                return default
            return registers.get_dimen(entry.slot, _internal=True)

        baselineskip = _skip("baselineskip", cfg.baselineskip)
        has_live = baselineskip is not cfg.baselineskip
        return (
            baselineskip,
            _skip("lineskip", cfg.lineskip),
            _dimen("lineskiplimit", cfg.lineskiplimit, live_baselineskip=has_live),
        )

    def _reset_best_break(self) -> None:
        """Forget the best break of the current page."""
        self._best_break_idx = None
        self._best_break_penalty = INF_PENALTY
        self._best_break_total = 0
        self._least_page_cost = AWFUL_BAD


def _extent(value: int) -> int:
    """A rule's running dimension counts as zero in a vertical list."""
    return 0 if value == RUNNING_DIMEN else value


def _package_page_box(
    nodes: list, height: int, max_depth: int, font_manager: FontManager | None,
) -> VlistNode:
    r"""Pack the page into ``\box255`` exactly as §1017 does.

    ``vpackage(page, best_size, exactly, page_max_depth)``: the box is set to
    the page goal at the best break (lowered by the insertions), and depth
    beyond ``\maxdepth`` moves into the height.  TeX silences badness
    reports here, so no warning is produced.
    """
    width, nat_h, depth = _measure_vlist(nodes, font_manager)
    box = VlistNode(
        list=nodes, width=width, height=nat_h, depth=depth, shift_amount=0,
        glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
    )
    if box.depth > max_depth:
        box.height += box.depth - max_depth
        box.depth = max_depth
    set_glue_vbox(box, target_height=height)
    return box
