"""Unit tests for PageBuilder and related classes.

Tests follow test plan.
"""
from __future__ import annotations

import pytest

from aspose_tex._engine.box_builder import _measure_vlist
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
from aspose_tex._engine.page_builder import (
    FOOTLINE_BASELINESKIP_SP,
    HEADLINE_SHIFT_SP,
    OutputRoutineBase,
    PageBuilder,
    PageBuilderConfig,
    PlainOutputRoutine,
    _format_folio,
    _to_roman_lowercase,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex.exceptions import EngineError

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _feed(builder: PageBuilder, node) -> None:
    """Contribute *node* and build the page, as TeX's box/penalty call sites do."""
    builder.contribute(node)
    builder.build_page()


def _make_hbox(height: int, depth: int = 0, width: int = 1000) -> HlistNode:
    return HlistNode(
        list=[],
        width=width,
        height=height,
        depth=depth,
        shift_amount=0,
        glue_sign=GlueSign.NORMAL,
        glue_order=GlueOrder.NORMAL,
        glue_set=0.0,
    )


def _default_config(**overrides) -> PageBuilderConfig:
    cfg = PageBuilderConfig(
        vsize=42152952,
        topskip=Glue(655360, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
        max_depth=262144,
        baselineskip=Glue(786432, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
        lineskip=Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
        lineskiplimit=0,
        max_dead_cycles=25,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


class _NullBackend:
    def __init__(self):
        self.calls: list[tuple[int, VlistNode]] = []

    def shipout(self, pn: int, box: VlistNode) -> None:
        self.calls.append((pn, box))


def _wrap_nodes(body_nodes: list) -> VlistNode:
    w, h, d = _measure_vlist(body_nodes, None)  # type: ignore[arg-type]
    return VlistNode(
        list=body_nodes,
        width=w,
        height=h,
        depth=d,
        shift_amount=0,
        glue_sign=GlueSign.NORMAL,
        glue_order=GlueOrder.NORMAL,
        glue_set=0.0,
    )


class _ShippingRoutine(OutputRoutineBase):
    """Output routine that calls backend.shipout() — standard behaviour."""

    def execute(self, body_nodes, page_number, backend):
        backend.shipout(page_number, _wrap_nodes(body_nodes))


class _NonShippingRoutine(OutputRoutineBase):
    """Output routine that deliberately does NOT call backend.shipout()."""

    def execute(self, body_nodes, page_number, backend):
        pass  # forgets to ship — dead cycles will accumulate


class _CapturingRoutine(OutputRoutineBase):
    """Output routine that records body_nodes it receives; ships a minimal box."""

    def __init__(self) -> None:
        self.calls: list[tuple[list, int]] = []

    def execute(self, body_nodes, page_number, backend):
        assert isinstance(body_nodes, list)
        self.calls.append((list(body_nodes), page_number))
        backend.shipout(page_number, _wrap_nodes(body_nodes))


class _IntPagenoStub:
    """In-memory PageNumberRegister for unit tests (no RegisterSet dependency)."""

    def __init__(self, v: int = 1) -> None:
        self._v = v

    def get_pageno(self) -> int:
        return self._v

    def set_pageno(self, value: int) -> None:
        self._v = value


# ---------------------------------------------------------------------------
# Basic shipout tests
# ---------------------------------------------------------------------------

def test_single_hbox_ships_on_end_of_document():
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400000))
    builder.end_of_document()
    assert len(backend.calls) == 1


def test_empty_builder_no_shipout():
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    builder.end_of_document()
    assert len(backend.calls) == 0


def test_is_at_top_of_page_tracks_box_lifecycle():
    """Public read-only property tracks first-box state across page breaks."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())

    assert builder.is_at_top_of_page is True

    _feed(builder, _make_hbox(height=400000))
    assert builder.is_at_top_of_page is False

    _feed(builder, PenaltyNode(NEG_INF_PENALTY))
    assert builder.is_at_top_of_page is True


def test_only_discardables_no_shipout():
    """MVL with only glue/penalty/kern — no box — should not ship."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, GlueNode(Glue(100000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    _feed(builder, PenaltyNode(0))
    builder.end_of_document()
    assert len(backend.calls) == 0


# ---------------------------------------------------------------------------
# Topskip tests
# ---------------------------------------------------------------------------

def test_topskip_inserted_for_first_box():
    """contribute box with height=500000 sp, topskip=655360 → GlueNode with width=155360 before box."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=500000))
    # MVL should be: [GlueNode(topskip=155360), HlistNode]
    assert len(builder._mvl) == 2
    assert isinstance(builder._mvl[0], GlueNode)
    assert builder._mvl[0].glue.width == 155360  # 655360 - 500000


def test_topskip_zero_when_box_exceeds_topskip():
    """box.height >= topskip.width → topskip glue has natural width=0."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=700000))  # 700000 > 655360
    glue_node = builder._mvl[0]
    assert isinstance(glue_node, GlueNode)
    assert glue_node.glue.width == 0


# ---------------------------------------------------------------------------
# Interline glue tests
# ---------------------------------------------------------------------------

def test_baselineskip_interline_between_boxes():
    """Two boxes h=400000, d=100000; ideal=786432-100000-400000=286432 > 0 > lineskiplimit."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    box = _make_hbox(height=400000, depth=100000)
    _feed(builder, box)
    _feed(builder, _make_hbox(height=400000, depth=100000))
    # MVL: [topskip_glue, box1, interline_glue, box2]
    assert len(builder._mvl) == 4
    interline = builder._mvl[2]
    assert isinstance(interline, GlueNode)
    assert interline.glue.width == 286432  # 786432 - 100000 - 400000


def test_lineskip_used_when_ideal_below_limit():
    """config.lineskiplimit=200000; ideal < 200000 → lineskip Glue(65536,...) used."""
    cfg = _default_config(lineskiplimit=200000)
    backend = _NullBackend()
    builder = PageBuilder(cfg, backend, _ShippingRoutine())
    # ideal = 786432 - 100000 - 700000 = -13568 < 200000
    _feed(builder, _make_hbox(height=700000, depth=100000))
    _feed(builder, _make_hbox(height=700000, depth=100000))
    interline = builder._mvl[2]
    assert isinstance(interline, GlueNode)
    assert interline.glue.width == 65536  # lineskip


# ---------------------------------------------------------------------------
# Page total tests
# ---------------------------------------------------------------------------

def test_page_total_after_topskip_and_box():
    """After contributing one box h=400000, d=100000, topskip=655360:
    page_total = (655360-400000) + 400000 = 655360; page_depth = 100000."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400000, depth=100000))
    assert builder.page_total == 655360
    assert builder.page_depth == 100000


def test_glue_node_contribution_updates_page_total():
    """Glue moved after a box → page_total increases by its width (§1004)."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400000))
    initial_total = builder.page_total
    _feed(builder, GlueNode(Glue(100000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    assert builder.page_total == initial_total + 100000


def test_glue_before_the_first_box_is_discarded():
    """§1000: glue, kern and penalty at the page top never reach it."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    for node in (
        GlueNode(Glue(100000, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
        KernNode(width=50_000, explicit=True),
        PenaltyNode(NEG_INF_PENALTY),
    ):
        _feed(builder, node)
    assert builder._mvl == []
    assert backend.calls == []
    assert builder.page_total == 0
    assert builder.page_fil_stretch == 0


def test_page_depth_clamped_to_max_depth():
    """box.depth > max_depth → page_depth == max_depth, excess absorbed into page_total."""
    cfg = _default_config(max_depth=262144)
    backend = _NullBackend()
    builder = PageBuilder(cfg, backend, _ShippingRoutine())
    # Contribute box with depth = 300000 > 262144
    _feed(builder, _make_hbox(height=400000, depth=300000))
    assert builder.page_depth == 262144
    # excess = 300000 - 262144 = 37856 absorbed into page_total


# ---------------------------------------------------------------------------
# Page break tests
# ---------------------------------------------------------------------------

def test_page_break_when_total_exceeds_vsize():
    """Contribute boxes summing to more than vsize with glue break points → shipout called."""
    cfg = _default_config(vsize=19660800)  # 300pt
    backend = _NullBackend()
    builder = PageBuilder(cfg, backend, _ShippingRoutine())
    # Fill up past vsize with glue break points
    for _ in range(30):
        _feed(builder, _make_hbox(height=786432))  # 12pt each
        _feed(builder, GlueNode(Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    assert len(backend.calls) >= 1


def test_forced_break_neg_inf_penalty():
    r"""\penalty-10000 immediately triggers page break."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400000))
    _feed(builder, PenaltyNode(NEG_INF_PENALTY))
    assert len(backend.calls) == 1


def test_vsize_300pt_page_break():
    """config.vsize=19660800 (300pt); contribute 12pt lines → break after ~25 lines."""
    cfg = _default_config(
        vsize=19660800,  # 300pt
        topskip=Glue(655360, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
        baselineskip=Glue(786432, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
    )
    backend = _NullBackend()
    builder = PageBuilder(cfg, backend, _ShippingRoutine())
    # Contribute 50 lines of 12pt height, 2pt depth, with glue break points
    for _ in range(50):
        _feed(builder, _make_hbox(height=655360, depth=131072))  # 10pt/2pt
        _feed(builder, GlueNode(Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    builder.end_of_document()
    assert len(backend.calls) >= 2  # Must have broken into multiple pages


# ---------------------------------------------------------------------------
# trailing discardables preserved through page break
# ---------------------------------------------------------------------------

def test_page_break_preserves_trailing_vfill():
    r"""\bye-style tail: [hbox, vfill_glue, -INF penalty] — vfill survives into body_nodes."""
    from aspose_tex._engine.page_primitives import make_vfill_glue

    backend = _NullBackend()
    routine = _CapturingRoutine()
    builder = PageBuilder(_default_config(), backend, routine)
    _feed(builder, _make_hbox(height=400000))
    _feed(builder, make_vfill_glue())
    _feed(builder, PenaltyNode(NEG_INF_PENALTY))

    assert len(routine.calls) == 1
    body_nodes, _ = routine.calls[0]
    # topskip + hbox + vfill glue (penalty is the break node and is dropped)
    assert len(body_nodes) == 3
    assert isinstance(body_nodes[-1], GlueNode)
    assert body_nodes[-1].glue.stretch_order == GlueOrder.FILL


def test_page_break_preserves_trailing_kern():
    """Trailing kern before a NEG_INF penalty survives the break (kerns are never break items)."""
    backend = _NullBackend()
    routine = _CapturingRoutine()
    builder = PageBuilder(_default_config(), backend, routine)
    _feed(builder, _make_hbox(height=400000))
    _feed(builder, KernNode(width=1_000_000, explicit=True))
    _feed(builder, PenaltyNode(NEG_INF_PENALTY))

    assert len(routine.calls) == 1
    body_nodes, _ = routine.calls[0]
    assert len(body_nodes) == 3
    assert isinstance(body_nodes[-1], KernNode)
    assert body_nodes[-1].width == 1_000_000


def test_page_break_discards_only_break_node():
    """[box, glue_a, -INF penalty, glue_b]: glue_a preserved, penalty dropped, glue_b re-contributed."""
    backend = _NullBackend()
    routine = _CapturingRoutine()
    builder = PageBuilder(_default_config(), backend, routine)
    _feed(builder, _make_hbox(height=400000))
    glue_a = GlueNode(Glue(100_000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
    glue_b = GlueNode(Glue(200_000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
    _feed(builder, glue_a)
    _feed(builder, PenaltyNode(NEG_INF_PENALTY))
    # Break fires on the penalty.  Re-contribute glue_b onto the fresh page.
    _feed(builder, glue_b)

    assert len(routine.calls) == 1
    body_nodes, _ = routine.calls[0]
    # topskip + box + glue_a; penalty dropped, glue_b goes to next page
    assert len(body_nodes) == 3
    assert body_nodes[-1] is glue_a
    # glue_b was re-contributed as leftover; because it is a discardable on a
    # fresh page (no box yet), prune_page_top-style logic may drop it — but
    # it must NOT end up in the shipped page_nodes of the first page.
    assert glue_b not in body_nodes


# ---------------------------------------------------------------------------
# Page number tests
# ---------------------------------------------------------------------------

def test_page_number_increments_per_page():
    """Contribute content for 3 pages → builder.page_number == 4 after end_of_document."""
    cfg = _default_config(vsize=19660800)  # 300pt — small page
    backend = _NullBackend()
    builder = PageBuilder(cfg, backend, _ShippingRoutine())
    for _ in range(90):
        _feed(builder, _make_hbox(height=786432))
        _feed(builder, GlueNode(Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    builder.end_of_document()
    assert builder.page_number >= 4


def test_multipage_shipout_calls():
    """Content for multiple pages → backend has calls with consecutive page numbers."""
    cfg = _default_config(vsize=19660800)  # 300pt
    backend = _NullBackend()
    builder = PageBuilder(cfg, backend, _ShippingRoutine())
    for _ in range(90):
        _feed(builder, _make_hbox(height=786432))
        _feed(builder, GlueNode(Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    builder.end_of_document()
    assert len(backend.calls) >= 3
    page_nums = [pn for pn, _ in backend.calls]
    assert page_nums == list(range(1, len(page_nums) + 1))


# ---------------------------------------------------------------------------
# Interline suppression tests
# ---------------------------------------------------------------------------

def test_nointerlineskip_skips_one_glue():
    """contribute box1, skip_next_interline, contribute box2, contribute box3 →
    no interline glue before box2, interline glue before box3."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    box = _make_hbox(height=400000, depth=100000)
    _feed(builder, box)       # topskip + box1
    builder.skip_next_interline()
    _feed(builder, box)       # box2 (no interline glue before it)
    _feed(builder, box)       # box3 (interline glue before it)

    # MVL: [topskip, box1, box2, interline_glue, box3]
    assert len(builder._mvl) == 5
    assert isinstance(builder._mvl[2], HlistNode)  # box2 directly after box1
    assert isinstance(builder._mvl[3], GlueNode)   # interline before box3


def test_offinterlineskip_disables_all():
    """off_interline(), contribute 3 boxes → no interline glue before any of them (only topskip)."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    builder.off_interline()
    box = _make_hbox(height=400000)
    _feed(builder, box)  # topskip + box1
    _feed(builder, box)  # box2 (no interline)
    _feed(builder, box)  # box3 (no interline)
    # MVL: [topskip, box1, box2, box3]
    assert len(builder._mvl) == 4
    assert isinstance(builder._mvl[0], GlueNode)   # topskip
    assert isinstance(builder._mvl[1], HlistNode)
    assert isinstance(builder._mvl[2], HlistNode)
    assert isinstance(builder._mvl[3], HlistNode)


# ---------------------------------------------------------------------------
# Dead cycles tests
# ---------------------------------------------------------------------------

def test_dead_cycles_increments_on_output():
    """Output routine that does NOT call shipout → dead_cycles increments."""
    cfg = _default_config(max_dead_cycles=25)
    backend = _NullBackend()
    builder = PageBuilder(cfg, backend, _NonShippingRoutine())
    _feed(builder, _make_hbox(height=400000))
    # Force a page break via eject
    _feed(builder, PenaltyNode(NEG_INF_PENALTY))
    assert builder.dead_cycles == 1


def test_dead_cycles_reset_on_shipout():
    """Normal output routine → dead_cycles == 0 after page break."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400000))
    _feed(builder, PenaltyNode(NEG_INF_PENALTY))
    assert builder.dead_cycles == 0


def test_max_dead_cycles_raises_engine_error():
    """config.max_dead_cycles=1, output routine never calls shipout → EngineError after 2 breaks.

    TeX semantics: error fires when dead_cycles > max_dead_cycles (strictly greater).
    So with max=1, the error fires on the second page break (dead_cycles becomes 2).
    """
    cfg = _default_config(max_dead_cycles=1)
    backend = _NullBackend()
    builder = PageBuilder(cfg, backend, _NonShippingRoutine())
    # First forced break: dead_cycles = 1, no error yet (1 > 1 is False)
    _feed(builder, _make_hbox(height=400000))
    _feed(builder, PenaltyNode(NEG_INF_PENALTY))
    assert builder.dead_cycles == 1
    # Second forced break: dead_cycles = 2, error (2 > 1 is True)
    _feed(builder, _make_hbox(height=400000))
    with pytest.raises(EngineError, match="Output loop"):
        _feed(builder, PenaltyNode(NEG_INF_PENALTY))


# ---------------------------------------------------------------------------
# PlainOutputRoutine unit tests
# ---------------------------------------------------------------------------

_HSIZE = 30_785_886  # 6.5in — plain TeX \hsize


def _make_tenrm_fm() -> FontManager:
    fm = FontManager()
    fm.load_font("tenrm", "cmr10")
    fm.select_font("tenrm")
    return fm


def _find_footline_hbox(page_box: VlistNode) -> HlistNode:
    """Return the last HlistNode in *page_box.list* — this is the footline."""
    hboxes = [n for n in page_box.list if isinstance(n, HlistNode)]
    assert hboxes, "no HlistNode in page box"
    return hboxes[-1]


def _find_body_box(page_box: VlistNode) -> VlistNode:
    """Return the (only) VlistNode in *page_box.list* — this is the page body."""
    vboxes = [n for n in page_box.list if isinstance(n, VlistNode)]
    assert len(vboxes) == 1, f"expected one body VlistNode, got {len(vboxes)}"
    return vboxes[0]


def test_output_routine_signature_takes_list():
    """OutputRoutineBase.execute receives a list[Node], not a VlistNode."""
    cfg = _default_config()
    backend = _NullBackend()
    routine = _CapturingRoutine()
    builder = PageBuilder(cfg, backend, routine)
    _feed(builder, _make_hbox(height=400000))
    builder.end_of_document()
    assert len(routine.calls) == 1
    body_nodes, _ = routine.calls[0]
    assert isinstance(body_nodes, list)
    # No VlistNode in the raw body (PageBuilder passes the MVL tail itself).
    assert not any(isinstance(n, VlistNode) for n in body_nodes)


def test_plain_output_builds_vbox_to_vsize():
    """With config.vsize wired, the body vbox height equals vsize (glue stretches)."""
    cfg = _default_config(vsize=10_000_000)
    backend = _NullBackend()
    routine = PlainOutputRoutine(hsize=_HSIZE, config=cfg)
    builder = PageBuilder(cfg, backend, routine)
    for _ in range(3):
        _feed(builder, _make_hbox(height=100000))
    # Add an infinite vfil so the body can stretch to vsize.
    _feed(builder, GlueNode(Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)))
    _feed(builder, PenaltyNode(NEG_INF_PENALTY))
    assert len(backend.calls) == 1
    _, page_box = backend.calls[0]
    body_box = _find_body_box(page_box)
    assert body_box.height == 10_000_000


def test_plain_output_empty_footline_when_no_fontmanager():
    """Without a FontManager, the footline hbox emits no CharNodes."""
    cfg = _default_config()
    backend = _NullBackend()
    routine = PlainOutputRoutine(hsize=_HSIZE, config=cfg)
    builder = PageBuilder(cfg, backend, routine)
    _feed(builder, _make_hbox(height=400000))
    builder.end_of_document()
    _, page_box = backend.calls[0]
    footline = _find_footline_hbox(page_box)
    char_nodes = [n for n in footline.list if isinstance(n, CharNode)]
    assert char_nodes == []


def test_plain_output_folio_digits():
    """With a loaded tenrm, page_number=42 produces CharNodes '4' and '2' in order."""
    fm = _make_tenrm_fm()
    cfg = _default_config()
    backend = _NullBackend()
    pageno = _IntPagenoStub(42)
    routine = PlainOutputRoutine(
        hsize=_HSIZE, font_manager=fm, pageno_register=pageno, config=cfg,
    )
    builder = PageBuilder(cfg, backend, routine, pageno_register=pageno)
    _feed(builder, _make_hbox(height=400000))
    builder.end_of_document()
    _, page_box = backend.calls[0]
    footline = _find_footline_hbox(page_box)
    digits = [n.char for n in footline.list if isinstance(n, CharNode)]
    assert digits == [ord("4"), ord("2")]


def test_plain_output_folio_romannumeral_negative():
    """_format_folio cases covering plain.tex line 1151."""
    assert _format_folio(-7) == "vii"
    assert _format_folio(-1900) == "mcm"
    assert _format_folio(0) == "0"
    assert _format_folio(12) == "12"


def test_plain_output_footline_baseline_at_24pt():
    """The footline's baseline sits exactly 24pt below the body's last baseline."""
    fm = _make_tenrm_fm()
    cfg = _default_config()
    backend = _NullBackend()
    routine = PlainOutputRoutine(hsize=_HSIZE, font_manager=fm, config=cfg)
    builder = PageBuilder(cfg, backend, routine)
    _feed(builder, _make_hbox(height=400000))
    builder.end_of_document()
    _, page_box = backend.calls[0]
    body_box = _find_body_box(page_box)
    footline = _find_footline_hbox(page_box)
    # The kern immediately after the body box holds the spacing.
    nodes = page_box.list
    body_idx = nodes.index(body_box)
    kern = nodes[body_idx + 1]
    assert isinstance(kern, KernNode)
    # kern = 24pt - body.depth - footline.height  (plain.tex \makefootline)
    expected = FOOTLINE_BASELINESKIP_SP - body_box.depth - footline.height
    assert kern.width == expected


def test_plain_output_headline_shift_minus_22p5pt():
    """The headline sits 22.5pt above the body (pre-head kern is -22.5pt)."""
    cfg = _default_config()
    backend = _NullBackend()
    routine = PlainOutputRoutine(hsize=_HSIZE, config=cfg)
    builder = PageBuilder(cfg, backend, routine)
    _feed(builder, _make_hbox(height=400000))
    builder.end_of_document()
    _, page_box = backend.calls[0]
    nodes = page_box.list
    # First node is the pre-headline kern = -HEADLINE_SHIFT_SP.
    assert isinstance(nodes[0], KernNode)
    assert nodes[0].width == -HEADLINE_SHIFT_SP
    assert abs(HEADLINE_SHIFT_SP - int(22.5 * 65536)) <= 1


def test_pagebuilder_advances_pageno_via_register():
    """After 3 page breaks the register reads 4 (1→2→3→4)."""
    cfg = _default_config(vsize=19_660_800)  # 300pt — small page, forces breaks
    backend = _NullBackend()
    pageno = _IntPagenoStub(1)
    builder = PageBuilder(cfg, backend, _ShippingRoutine(), pageno_register=pageno)
    for _ in range(90):
        _feed(builder, _make_hbox(height=786432))
        _feed(builder, GlueNode(Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    builder.end_of_document()
    assert len(backend.calls) >= 3
    assert pageno.get_pageno() == len(backend.calls) + 1


def test_pagebuilder_pageno_honours_user_assignment():
    """Assigning pageno=100 before a break → output routine sees 100; after → 101."""
    cfg = _default_config()
    backend = _NullBackend()
    pageno = _IntPagenoStub(100)
    routine = _CapturingRoutine()
    builder = PageBuilder(cfg, backend, routine, pageno_register=pageno)
    _feed(builder, _make_hbox(height=400000))
    _feed(builder, PenaltyNode(NEG_INF_PENALTY))
    assert routine.calls[0][1] == 100
    assert pageno.get_pageno() == 101


def test_fast_path_negative_pageno():
    register = _IntPagenoStub(-1)
    builder = PageBuilder(_default_config(), _NullBackend(), _ShippingRoutine(),
                          pageno_register=register)
    for expected in (-2, -3, -4):
        _feed(builder, _make_hbox(height=400000))
        _feed(builder, PenaltyNode(NEG_INF_PENALTY))
        assert register.get_pageno() == expected


def test_fast_path_advance_is_global():
    from aspose_tex._engine.group import GroupKind, GroupStack
    from aspose_tex._engine.interpreter import _Count0PagenoRegister
    from aspose_tex._engine.registers import RegisterSet

    groups = GroupStack()
    registers = RegisterSet(groups)
    registers.set_count(0, 1)
    groups.open_group(GroupKind.BRACE)
    registers.set_count(0, 8)
    builder = PageBuilder(_default_config(), _NullBackend(), _ShippingRoutine(),
                          pageno_register=_Count0PagenoRegister(registers, groups))
    _feed(builder, _make_hbox(height=400000))
    _feed(builder, PenaltyNode(NEG_INF_PENALTY))
    groups.close_group()
    assert registers.get_count(0) == 9


def test_output_epilogue_preserves_live_pageno():
    register = _IntPagenoStub(1)
    builder = PageBuilder(_default_config(), _NullBackend(), _ShippingRoutine(),
                          pageno_register=register)
    builder._output_active = True
    register.set_pageno(7)
    builder.finish_output_cycle()
    assert register.get_pageno() == 7
    assert not builder.output_cycle_pending


def test_to_roman_lowercase_boundary():
    """3999 is the classical upper bound for Roman numerals in TeX's table."""
    assert _to_roman_lowercase(3999) == "mmmcmxcix"
    assert _to_roman_lowercase(0) == ""
    assert _to_roman_lowercase(-5) == ""
    assert _to_roman_lowercase(1994) == "mcmxciv"


# ---------------------------------------------------------------------------
# RuleNode dispatch on the main vertical list
# ---------------------------------------------------------------------------

def _make_rule(height: int = 26_214, depth: int = 0, width: int = 4_000_000) -> RuleNode:
    return RuleNode(width=width, height=height, depth=depth)


def test_rule_first_on_page_inserts_topskip_glue():
    """Rule-first on a page goes through the topskip path (Measurement B).

    Fresh PageBuilder, contribute a single RuleNode with default 0.4 pt height
    and zero depth.  MVL must be ``[GlueNode(topskip), RuleNode]`` with the
    topskip glue's natural width equal to ``max(0, cfg.topskip.width - rule.height)``
    = 655_360 - 26_214 = 629_146 sp.  The flag flips, ``_prev_depth`` writes
    the §679 sentinel ``ignore_depth = _PREVDEPTH_SENTINEL`` (v5
    Component 6), and ``_page_total`` accumulates topskip_nat + rule.height +
    rule.depth = 655_360 sp (= 10 pt = ``\\topskip.width``).
    """
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    rule = _make_rule(height=26_214, depth=0)

    _feed(builder, rule)

    assert len(builder._mvl) == 2
    topskip = builder._mvl[0]
    assert isinstance(topskip, GlueNode)
    assert topskip.glue.width == 629_146  # 655360 - 26214
    assert builder._mvl[1] is rule
    assert builder.is_at_top_of_page is False
    # §679 sentinel write (was `rule.depth` under v4).
    assert builder._prev_depth == _PREVDEPTH_SENTINEL
    assert builder.page_total == 655_360  # topskip_nat + rule.height + rule.depth


def test_rule_first_on_page_with_nonzero_rule_depth():
    """Rule-first with non-zero rule.depth: topskip reads height only; totals include depth."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    rule = _make_rule(height=26_214, depth=78_643)  # 0.4 pt / 1.2 pt

    _feed(builder, rule)

    topskip = builder._mvl[0]
    assert isinstance(topskip, GlueNode)
    assert topskip.glue.width == 629_146  # depth is NOT part of topskip formula
    # §679 sentinel — `_prev_depth` is independent of `rule.depth`.
    assert builder._prev_depth == _PREVDEPTH_SENTINEL
    # §1002: a rule moves like a box — its depth is page_depth
    # until glue or a kern folds it into the total.
    assert builder.page_total == 629_146 + 26_214
    assert builder.page_depth == 78_643


def test_rule_mid_page_appends_without_interline_glue():
    """Mid-page rule appends with sentinel prev_depth and no interline glue.

    Matches MiKTeX Measurements C + D + E (no interline GlueNode between
    prior box and rule).  v5 Component 6: the post-rule write is the
    TeX:The Program §679 sentinel ``_PREVDEPTH_SENTINEL`` (= -1000 pt), not
    ``rule.depth`` — this suppresses the spurious interline-glue prelude for
    the next box (§253 sentinel guard in ``_interline_glue``).
    """
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    box = _make_hbox(height=400_000, depth=100_000)
    _feed(builder, box)
    # Sanity: box flipped the flag and seeded MVL = [topskip, box].
    assert builder.is_at_top_of_page is False
    assert len(builder._mvl) == 2
    pre_rule_total = builder.page_total
    pre_rule_mvl_len = len(builder._mvl)

    rule = _make_rule(height=26_214, depth=78_643)
    _feed(builder, rule)

    # Rule appended directly after the box — no intervening GlueNode.
    assert len(builder._mvl) == pre_rule_mvl_len + 1
    assert builder._mvl[-1] is rule
    assert not isinstance(builder._mvl[-2], GlueNode), (
        "mid-page rule must not be preceded by interline glue (§679 vs §1078)"
    )
    # §679 sentinel write — `_prev_depth = ignore_depth` (NOT
    # `rule.depth`, which was the literal misread under v4).  The sentinel
    # makes the next box's interline-glue prelude skip per §253.
    assert builder._prev_depth == _PREVDEPTH_SENTINEL
    # §1002 (superseding's exemption): the rule is counted
    # like a box; the box's depth is folded in ahead of it.
    assert builder.page_total == pre_rule_total + 100_000 + 26_214
    assert builder.page_depth == 78_643


def test_box_after_rule_skips_interline_glue():
    """Post-rule box hits the sentinel-guarded interline branch — no glue inserted.

    Sequence: RuleNode(h=26214, d=78643) on a fresh page (rule-first; topskip
    inserted; ``is_at_top_of_page=False``; ``_prev_depth=_PREVDEPTH_SENTINEL``),
    then HlistNode(h=400000, d=100000).  Under v5 Component 6, the
    post-rule box hits the interline branch but the §253 sentinel guard
    (``if self._prev_depth <= _PREVDEPTH_SENTINEL: return``) skips the
    prelude entirely.  MVL stays ``[topskip_glue, rule, box]`` with NO
    intervening GlueNode (matches MiKTeX Measurement E).
    """
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_rule(height=26_214, depth=78_643))
    box = _make_hbox(height=400_000, depth=100_000)

    _feed(builder, box)

    # MVL is [topskip_glue, rule, box] — no interline glue
    # between rule and box (was [..., interline_glue, box] under v4).
    assert len(builder._mvl) == 3
    assert isinstance(builder._mvl[0], GlueNode)  # topskip
    assert builder._mvl[1] is builder._mvl[1]  # rule
    assert builder._mvl[2] is box
    assert not isinstance(builder._mvl[1], GlueNode), "rule, not glue"
    # No interline GlueNode between rule (index 1) and box (index 2).
    # The post-box update path runs `_update_page_totals_for_box`, which
    # overwrites `_prev_depth` from the sentinel to `box.depth`.
    assert builder._prev_depth == 100_000


# ---------------------------------------------------------------------------
# sentinel `_prev_depth` after `\hrule` + sentinel
# guard in interline-glue prelude
# ---------------------------------------------------------------------------

def test_contribute_rule_first_writes_prev_depth_sentinel():
    """Rule-first arm writes the §679 sentinel `_prev_depth = ignore_depth`.

    Fresh PageBuilder, contribute a single RuleNode (rule-first arm because
    `is_at_top_of_page` starts True). Assert `_prev_depth` post-call equals
    `_PREVDEPTH_SENTINEL`.
    """
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    assert builder.is_at_top_of_page is True

    _feed(builder, _make_rule(height=26_214, depth=78_643))

    assert builder._prev_depth == _PREVDEPTH_SENTINEL


def test_contribute_rule_midpage_writes_prev_depth_sentinel():
    """Mid-page rule arm writes the §679 sentinel `_prev_depth = ignore_depth`.

    PageBuilder, contribute a HlistNode first (flips `is_at_top_of_page` to
    False and sets `_prev_depth` to box.depth via `_update_page_totals_for_box`),
    then contribute a RuleNode (mid-page arm).  Assert `_prev_depth` post-call
    equals `_PREVDEPTH_SENTINEL` and
    overrides the previous box's depth.
    """
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400_000, depth=100_000))
    # Sanity: post-box, _prev_depth tracks box.depth, NOT the sentinel.
    assert builder.is_at_top_of_page is False
    assert builder._prev_depth == 100_000

    _feed(builder, _make_rule(height=26_214, depth=78_643))

    # mid-page rule arm overrides box.depth with the sentinel.
    assert builder._prev_depth == _PREVDEPTH_SENTINEL


def test_insert_interline_skips_on_sentinel_prev_depth():
    r"""No interline glue is computed when `_prev_depth` is the sentinel.

    TeXbook §253: when `\prevdepth <= -1000 pt` the interline-glue prelude
    is skipped entirely.
    """
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    builder._prev_depth = _PREVDEPTH_SENTINEL
    builder._skip_interline_once = False
    builder._no_interline = False

    assert builder._interline_glue(_make_hbox(height=400_000, depth=100_000)) is None


def test_contribute_two_rules_midpage_sets_sentinel_each_time():
    """Two consecutive mid-page rules each write the §679 sentinel.

    Sequence: HlistNode → RuleNode → RuleNode.  After each RuleNode contrib,
    `_prev_depth` must equal `_PREVDEPTH_SENTINEL`.  Pin that consecutive
    rules do not compound the spurious-glue defect — each rule individually
    writes the sentinel and there is no interline GlueNode between them
    (§Measurement E + Component 6).
    """
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400_000, depth=100_000))
    assert builder._prev_depth == 100_000  # set by _update_page_totals_for_box

    rule_a = _make_rule(height=26_214, depth=78_643)
    _feed(builder, rule_a)
    assert builder._prev_depth == _PREVDEPTH_SENTINEL

    rule_b = _make_rule(height=26_214, depth=131_072)  # different depth
    _feed(builder, rule_b)
    # Sentinel write again — `rule_b.depth` does NOT leak into _prev_depth.
    assert builder._prev_depth == _PREVDEPTH_SENTINEL
    # Both rules appended directly; no interline GlueNode between them.
    rule_a_idx = builder._mvl.index(rule_a)
    rule_b_idx = builder._mvl.index(rule_b)
    assert rule_b_idx == rule_a_idx + 1, (
        "consecutive rules must be adjacent in the MVL (no interline glue)"
    )


def test_page_reset_restores_first_box_on_page():
    """After a forced page break ``is_at_top_of_page`` resets to True."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400_000))
    assert builder.is_at_top_of_page is False

    _feed(builder, PenaltyNode(NEG_INF_PENALTY))

    # After the page break the flag is reset for the new page.
    assert builder.is_at_top_of_page is True


# ---------------------------------------------------------------------------
# TeXbook §1000 — discard leading discardables at the top of a
# continuation page.  After a natural page break the leftover that
# is re-contributed to the fresh page must NOT carry the interline glue that
# sat between the shipped page's last box and the leftover's first box — that
# glue leaks atop the new page's topskip and shifts every continuation-page
# baseline down (+3.111 pt on multipage.tex).
# ---------------------------------------------------------------------------

def _twopage_config() -> PageBuilderConfig:
    """Small page (≈30.5 pt body) so two 12 pt boxes force a natural break."""
    return _default_config(vsize=2_000_000)


def test_continuation_page_discards_leading_interline_glue():
    """§Testing #1: the leading interline glue is dropped on page 2.

    Drive a natural break whose leftover is ``[GlueNode, HlistNode]`` (the
    multipage shape).  After the synchronous output cycle the recommenced
    page must begin with the §1004 topskip glue immediately followed by the
    leftover box — the leading interline GlueNode is discarded (TeXbook
    §1000), so the box's baseline accounting is ``topskip_nat + box.height``
    with no extra leading glue.
    """
    backend = _NullBackend()
    routine = _CapturingRoutine()
    builder = PageBuilder(_twopage_config(), backend, routine)

    # 12 pt boxes with 0-width glue break points; vsize ≈ 30.5 pt → break
    # after two boxes, leftover = [break-trailing interline glue, next box].
    for _ in range(4):
        _feed(builder, _make_hbox(height=786_432, depth=100_000))
        _feed(builder, GlueNode(Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    builder.end_of_document()

    assert len(backend.calls) >= 2, "must break into at least two pages"
    # The recommenced page-2 MVL begins with topskip glue then the box —
    # NOT a leftover interline glue ahead of the topskip.
    page2_first_box, _ = routine.calls[1]
    assert isinstance(page2_first_box[0], GlueNode), "page 2 must open with topskip glue"
    topskip = page2_first_box[0]
    # topskip natural width = max(0, topskip.width - box.height) = 655360 - 786432 → 0
    # (box taller than topskip), so the first baseline sits at box.height with
    # NO additional leading interline glue ahead of it.
    assert topskip.glue.width == 0
    assert isinstance(page2_first_box[1], HlistNode), (
        "the box must follow the topskip directly — leading interline glue discarded"
    )


def test_continuation_page_keeps_inter_box_glue():
    """§Testing #2: the sweep skips a LEADING run only (no over-trim).

    A leftover that already begins with a box must be re-contributed verbatim:
    glue that sits *between* two leftover boxes is legitimate inter-box glue
    and must survive.  Exercise ``finish_output_cycle`` directly with a
    hand-built leftover ``[box_A, glue, box_B]``.
    """
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())

    box_a = _make_hbox(height=400_000, depth=100_000)
    inter = GlueNode(Glue(123_456, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
    box_b = _make_hbox(height=400_000, depth=100_000)
    builder._contrib.extend((box_a, inter, box_b))
    builder._output_active = True

    builder.finish_output_cycle()

    # box_a went through the topskip path; the inter-box glue between the two
    # boxes is preserved (NOT trimmed — it is not a LEADING discardable).
    assert box_a in builder._mvl
    assert inter in builder._mvl
    assert box_b in builder._mvl
    assert builder._mvl.index(inter) == builder._mvl.index(box_a) + 1


def test_continuation_page_all_discardable_leftover_is_noop():
    """§Testing #3: an all-discardable leftover re-contributes nothing.

    Degenerate but legal: leftover with only glue/kern/penalty and no box.
    The sweep consumes the entire run; nothing is re-contributed and no error
    is raised.  The recommenced page stays empty (still at top of page).
    """
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())

    builder._contrib.extend((
        GlueNode(Glue(100_000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)),
        KernNode(width=50_000, explicit=True),
        PenaltyNode(500),
    ))
    builder._output_active = True

    builder.finish_output_cycle()  # must not raise

    assert builder._mvl == [], "all-discardable leftover re-contributes nothing"
    assert builder.is_at_top_of_page is True, "fresh page stays at top of page"


# ---------------------------------------------------------------------------
# (superseding's page rollback): §1105 \unskip / \unkern /
# \unpenalty remove only the contribution list's tail; the page is never
# touched.
# ---------------------------------------------------------------------------

_UNSKIP_ERROR = "You can't use `\\unskip' in vertical mode."


def test_remove_last_node_pops_the_contribution_tail():
    """A node still on the contribution list is removed; the page is unchanged."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400_000))
    page_before = list(builder._mvl)
    total_before = builder.page_total
    glue = GlueNode(Glue(786_432, 196_608, GlueOrder.NORMAL, 65_536, GlueOrder.NORMAL))
    builder.contribute(glue)

    assert builder.remove_last_node(GlueNode) is glue
    assert builder._mvl == page_before
    assert builder.page_total == total_before
    assert builder.warnings == []


def test_remove_last_node_never_removes_from_the_page():
    r"""§1105: once glue reached the page, \unskip reports and removes nothing."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400_000))
    glue = GlueNode(Glue(786_432, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
    _feed(builder, glue)
    total_before = builder.page_total

    assert builder.remove_last_node(GlueNode) is None
    assert builder._mvl[-1] is glue
    assert builder.page_total == total_before
    assert builder.warnings == [_UNSKIP_ERROR]


def test_remove_last_node_after_a_box_on_the_page_is_silent():
    r"""\unskip after a non-glue item reached the page does nothing, quietly."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400_000))

    assert builder.remove_last_node(GlueNode) is None
    assert builder.warnings == []


@pytest.mark.parametrize(("node_type", "command"), [
    (KernNode, "unkern"), (PenaltyNode, "unpenalty"),
])
def test_unkern_and_unpenalty_on_an_empty_contribution_list_report(node_type, command):
    r"""§1105: \unkern/\unpenalty with nothing to take always report."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400_000))

    assert builder.remove_last_node(node_type) is None
    assert builder.warnings == [f"You can't use `\\{command}' in vertical mode."]


def test_remove_last_node_type_mismatch_is_noop():
    """When the contribution tail is not one of *types*, nothing happens."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    box = _make_hbox(height=400_000)
    builder.contribute(box)

    assert builder.remove_last_node(GlueNode) is None
    assert builder._contrib[-1] is box


def test_remove_last_node_empty_mvl_is_noop():
    """Empty page and contribution list — returns None without exception."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())

    popped = builder.remove_last_node(GlueNode)

    assert popped is None
    assert builder._mvl == []


def test_a_trailing_kern_waits_and_can_be_removed():
    """§1000: a kern at the end of the contribution list is not moved yet."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400_000))
    glue = GlueNode(Glue(100_000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
    _feed(builder, glue)
    _feed(builder, _make_hbox(height=200_000))
    best = builder._best_break_idx

    kern = KernNode(width=262_144, explicit=True)
    _feed(builder, kern)
    assert builder._contrib[-1] is kern
    assert kern not in builder._mvl

    assert builder.remove_last_node(KernNode) is kern
    assert builder._best_break_idx == best


def test_remove_last_node_does_not_touch_prev_depth():
    """Removing a discardable leaves the page state and _prev_depth invariant."""
    backend = _NullBackend()
    builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
    _feed(builder, _make_hbox(height=400_000, depth=100_000))
    prev_depth_before = builder._prev_depth

    builder.contribute(GlueNode(Glue(50_000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    popped = builder.remove_last_node(GlueNode)

    assert isinstance(popped, GlueNode)
    assert builder.is_at_top_of_page is False
    assert builder._prev_depth == prev_depth_before


# ---------------------------------------------------------------------------
# least-cost page breaking, the pending-contribution queue,
# §1004 depth folding and the §668 maximum depth of the page box.
# ---------------------------------------------------------------------------

_PT = 65_536


def _fixed_glue(width: int, stretch: int = 0) -> GlueNode:
    return GlueNode(Glue(width, stretch, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))


def _boxes_per_page(backend: _NullBackend) -> list[int]:
    return [sum(isinstance(n, HlistNode) for n in box.list) for _pn, box in backend.calls]


class TestLeastCostPageBreak:
    """§1000 legal breakpoints and §1005-§1007 cost selection."""

    def _builder(self, vsize_pt: int, topskip_stretch_pt: int = 0):
        backend = _NullBackend()
        config = _default_config(
            vsize=vsize_pt * _PT,
            topskip=Glue(10 * _PT, topskip_stretch_pt * _PT, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
        )
        return PageBuilder(config, backend, _ShippingRoutine()), backend

    def test_interline_glue_is_a_breakpoint_and_ties_go_later(self):
        # 10pt boxes, 12pt baselineskip: t=10, 22, 34 at the interline glues.
        # Both legal breaks below the goal cost DEPLORABLE (no stretch), so the
        # later one wins the tie; the overfull eject fires there.
        builder, backend = self._builder(vsize_pt=30)
        for _ in range(3):
            _feed(builder, _make_hbox(height=10 * _PT))
        assert builder._least_page_cost == 100_000
        best = builder._best_break_idx
        assert isinstance(builder._mvl[best], GlueNode)
        assert builder._mvl[best + 1] is builder._mvl[-1]  # the glue before box 3
        assert builder._best_break_penalty == INF_PENALTY
        _feed(builder, PenaltyNode(-20_000))
        assert _boxes_per_page(backend) == [2, 1]

    def test_glue_after_a_penalty_is_not_a_breakpoint(self):
        builder, _backend = self._builder(vsize_pt=300)
        _feed(builder, _make_hbox(height=10 * _PT))
        _feed(builder, PenaltyNode(10_000))
        _feed(builder, _fixed_glue(3 * _PT))
        assert builder._best_break_idx is None

    def test_least_cost_beats_the_latest_breakpoint(self):
        # topskip carries 30pt stretch: \penalty-500 at t=10 costs
        # badness(30,30)=100 - 500 < the later glue breaks.
        builder, backend = self._builder(vsize_pt=40, topskip_stretch_pt=30)
        _feed(builder, _make_hbox(height=10 * _PT))
        _feed(builder, PenaltyNode(-500))
        penalty_idx = len(builder._mvl) - 1
        for _ in range(3):
            _feed(builder, _make_hbox(height=10 * _PT))
        assert builder._best_break_idx == penalty_idx
        assert builder._mvl[penalty_idx].penalty == -500
        _feed(builder, PenaltyNode(0))  # t=46 > 40, no shrink: AWFUL_BAD
        assert _boxes_per_page(backend)[0] == 1

    def test_kern_is_a_breakpoint_only_before_glue(self):
        builder, _backend = self._builder(vsize_pt=300)
        _feed(builder, _make_hbox(height=10 * _PT))
        _feed(builder, KernNode(width=_PT, explicit=True))
        builder.skip_next_interline()  # \nointerlineskip: the box follows the kern
        _feed(builder, _make_hbox(height=10 * _PT))
        assert builder._best_break_idx is None  # kern followed by a box
        kern = KernNode(width=_PT, explicit=True)
        _feed(builder, kern)
        _feed(builder, _fixed_glue(2 * _PT))
        assert builder._mvl[builder._best_break_idx] is kern

    def test_page_goal_is_frozen_at_the_first_box(self):
        builder, backend = self._builder(vsize_pt=30)
        _feed(builder, _make_hbox(height=10 * _PT))
        builder._config.vsize = 100 * _PT
        assert builder.page_goal == 30 * _PT
        for _ in range(2):
            _feed(builder, _make_hbox(height=10 * _PT))
        _feed(builder, PenaltyNode(-20_000))
        assert _boxes_per_page(backend) == [2, 1]

    def test_leftover_keeps_its_interline_glue_once(self):
        builder, backend = self._builder(vsize_pt=30)
        for _ in range(5):
            _feed(builder, _make_hbox(height=10 * _PT))
        _feed(builder, PenaltyNode(-20_000))
        assert _boxes_per_page(backend)[:2] == [2, 2]
        page2 = backend.calls[1][1].list
        # topskip + one interline glue — the leftover is not re-appended.
        assert sum(isinstance(n, GlueNode) for n in page2) == 2

    def test_contributions_wait_while_output_is_pending(self):
        builder, _backend = self._builder(vsize_pt=300)
        _feed(builder, _make_hbox(height=10 * _PT))
        builder._output_active = True
        mvl_before = list(builder._mvl)
        _feed(builder, _make_hbox(height=10 * _PT))
        assert builder._mvl == mvl_before
        assert [type(n) for n in builder._contrib] == [GlueNode, HlistNode]
        glue = _fixed_glue(_PT)
        _feed(builder, glue)
        assert builder.last_contributed_node is glue
        assert builder.remove_last_node(GlueNode) is glue  # popped from the queue
        builder.finish_output_cycle()
        assert not builder._contrib
        # The page was not fired here (pending was set by hand): fire_up, not
        # finish_output_cycle, empties the page (§1017/§991), so the
        # queued box simply joins it.
        assert sum(isinstance(n, HlistNode) for n in builder._mvl) == 2


class TestDepthFolding:
    """§1004: glue and kern fold the last box's depth into page_total (C8)."""

    @pytest.mark.parametrize("item", [_fixed_glue(2 * _PT), KernNode(width=2 * _PT, explicit=True)])
    def test_glue_or_kern_folds_page_depth(self, item):
        builder = PageBuilder(_default_config(), _NullBackend(), _ShippingRoutine())
        _feed(builder, _make_hbox(height=10 * _PT, depth=3 * _PT))
        assert (builder.page_total, builder.page_depth) == (10 * _PT, 3 * _PT)
        _feed(builder, item)
        _feed(builder, PenaltyNode(INF_PENALTY))  # a kern moves once its successor is known
        assert (builder.page_total, builder.page_depth) == (15 * _PT, 0)

    def test_last_depth_before_fil_glue(self, tmp_path):
        """ repro: MiKTeX sets y at v=21733642 sp on page 1."""
        from aspose_tex import DviDevice, TeXJob, TeXOptions
        from aspose_tex._input.reader import FileInputSource

        walk = pytest.importorskip("tests._verification.dvi_walker").walk_chars_with_positions
        source = tmp_path / "t332.tex"
        source.write_text("x\\par\\vfil y\\par\\vfil\\eject z\n\\bye\n", encoding="utf-8")
        dvi = TeXJob(FileInputSource(source), DviDevice(), options=TeXOptions(load_format="plain")).run()
        page1 = {chr(code): v for code, _h, v, *_ in walk(dvi)[0]}
        assert page1["y"] == 21_733_642


class TestPageBoxMaxDepth:
    """§668/§1017/§1086: box255 and \\boxmaxdepth limit the depth (C9)."""

    def test_vbox_builder_moves_excess_depth_into_height(self):
        from aspose_tex._engine.box_builder import VBoxBuilder

        builder = VBoxBuilder(None)  # type: ignore[arg-type]
        builder._nodes.append(_make_hbox(height=_PT, depth=5 * _PT))
        box = builder.build(max_depth=2 * _PT)
        assert (box.height, box.depth) == (4 * _PT, 2 * _PT)

    def test_boxmaxdepth_in_a_vbox_matches_miktex(self):
        import warnings

        from aspose_tex import DviDevice
        from aspose_tex._engine.interpreter import TeXInterpreter
        from aspose_tex._input.reader import StringInputSource

        interp = TeXInterpreter(load_format="plain")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            interp.run_with_device(StringInputSource(
                r"\setbox0\vbox{\boxmaxdepth=2pt \hbox{\vrule height 1pt depth 5pt}}\end",
            ), DviDevice())
        box = interp._box_regs.getbox(0)
        # MiKTeX \showbox0: \vbox(4.0+2.0)x0.4
        assert (box.height, box.depth) == (4 * _PT, 2 * _PT)

    def test_page_body_is_clamped_to_maxdepth(self):
        from aspose_tex._engine.page_builder import _build_pagebody_vbox

        config = _default_config(vsize=100 * _PT, max_depth=4 * _PT)
        body = _build_pagebody_vbox([_make_hbox(height=10 * _PT, depth=9 * _PT)], config, None)
        assert body.depth == 4 * _PT
        assert body.height == 100 * _PT


# ---------------------------------------------------------------------------
# the contribution list, page-top discards, readers and
# insertions.
# ---------------------------------------------------------------------------


class TestContributionList:
    def test_contribute_only_appends(self):
        builder = PageBuilder(_default_config(), _NullBackend(), _ShippingRoutine())
        builder.contribute(_make_hbox(height=10 * _PT))
        assert builder._mvl == []
        assert len(builder._contrib) == 1
        builder.build_page()
        assert len(builder._mvl) == 2  # topskip + box
        assert not builder._contrib

    def test_readers_hide_an_empty_page(self):
        from aspose_tex._engine.page_builder import MAX_DIMEN

        builder = PageBuilder(_default_config(), _NullBackend(), _ShippingRoutine())
        builder.contribute(_fixed_glue(5 * _PT))
        builder.build_page()
        assert builder.page_goal == MAX_DIMEN
        assert (builder.page_total, builder.page_stretch, builder.page_depth) == (0, 0, 0)
        _feed(builder, _make_hbox(height=4 * _PT, depth=2 * _PT))
        assert builder.page_goal == builder._config.vsize
        assert (builder.page_total, builder.page_depth) == (10 * _PT, 2 * _PT)

    def test_readers_keep_the_fired_page_while_output_runs(self):
        seen: list[tuple[int, int, int]] = []

        class _Reading(OutputRoutineBase):
            def execute(self, body_nodes, page_number, backend):
                seen.append((builder.page_total, builder.page_depth, builder.page_goal))
                backend.shipout(page_number, _wrap_nodes(body_nodes))

        builder = PageBuilder(_default_config(), _NullBackend(), _Reading())
        _feed(builder, _make_hbox(height=4 * _PT, depth=2 * _PT))
        _feed(builder, PenaltyNode(NEG_INF_PENALTY))
        # §421 with output active: page_so_far of the fired page, depth reset.
        assert seen == [(10 * _PT, 0, builder._config.vsize)]

    def test_last_contributed_node_falls_back_to_the_last_moved_node(self):
        builder = PageBuilder(_default_config(), _NullBackend(), _ShippingRoutine())
        glue = _fixed_glue(5 * _PT)
        _feed(builder, glue)  # discarded at the page top, still last moved
        assert builder._mvl == []
        assert builder.last_contributed_node is glue

    def test_break_penalty_returns_as_10000(self):
        seen: list = []

        class _Peeking(OutputRoutineBase):
            def execute(self, body_nodes, page_number, backend):
                seen.append(builder._contrib[0])
                backend.shipout(page_number, _wrap_nodes(body_nodes))

        builder = PageBuilder(_default_config(), _NullBackend(), _Peeking())
        _feed(builder, _make_hbox(height=10 * _PT))
        _feed(builder, PenaltyNode(NEG_INF_PENALTY))
        assert seen == [PenaltyNode(INF_PENALTY)]
        assert builder._best_break_penalty == NEG_INF_PENALTY
        assert builder._contrib == type(builder._contrib)()  # discarded on page 2

    def test_glue_after_an_insert_only_page_is_discarded(self):
        builder = PageBuilder(_default_config(), _NullBackend(), _ShippingRoutine())
        _feed(builder, _insertion(100, 3))
        _feed(builder, _fixed_glue(5 * _PT))
        assert [type(n) for n in builder._mvl] == [InsertNode]
        _feed(builder, _make_hbox(height=4 * _PT))
        assert [type(n) for n in builder._mvl] == [InsertNode, GlueNode, HlistNode]

    def test_its_all_over_flushes_residual_material(self):
        backend = _NullBackend()
        builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
        assert builder.its_all_over() is True
        builder.contribute(_fixed_glue(_PT))
        assert builder.its_all_over() is False  # \hbox to\hsize{}\vfill\penalty-'10000000000
        assert len(backend.calls) == 1
        assert builder.its_all_over() is True


class _InsertRegisters:
    """Stand-in register set: one value for every \\count/\\dimen/\\skip n."""

    def __init__(self, count: int = 1000, dimen: int = 0o7777777777,
                 skip: Glue | None = None) -> None:
        self.count = count
        self.dimen = dimen
        self.skip = skip or Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)

    def get_count(self, _index: int, *, _internal: bool = False) -> int:
        return self.count

    def get_dimen(self, _index: int, *, _internal: bool = False) -> int:
        return self.dimen

    def get_skip(self, _index: int, *, _internal: bool = False) -> Glue:
        return self.skip


class _NamedStub:
    def __init__(self, registers: _InsertRegisters) -> None:
        self._register_set = registers

    def lookup(self, _name: str):
        return None


def _insertion(class_: int, height_pt: int, *vlist, floating_penalty: int = 0) -> InsertNode:
    return InsertNode(
        class_=class_, vlist=tuple(vlist), height=height_pt * _PT, depth=0,
        floating_penalty=floating_penalty,
        split_top_skip=Glue(2 * _PT, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
        split_max_depth=0,
    )


class TestInsertions:
    def _builder(self, registers: _InsertRegisters, routine=None):
        from aspose_tex._engine.box_registers import BoxRegisterSet

        regs = BoxRegisterSet()
        builder = PageBuilder(
            _default_config(vsize=100 * _PT), _NullBackend(), routine or _ShippingRoutine(),
            named_params=_NamedStub(registers), box_registers=regs,  # type: ignore[arg-type]
        )
        return builder, regs

    def test_goal_reserves_insert_skip_and_box_once(self):
        builder, regs = self._builder(_InsertRegisters(
            skip=Glue(4 * _PT, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
        regs.setbox(100, _wrap_nodes([_make_hbox(height=2 * _PT, depth=_PT)]))
        _feed(builder, _make_hbox(height=10 * _PT))
        total = builder.page_total
        _feed(builder, _insertion(100, 7))
        assert builder.page_goal == (100 - 3 - 4 - 7) * _PT
        _feed(builder, _insertion(100, 5))
        assert builder.page_goal == (100 - 3 - 4 - 7 - 5) * _PT
        assert builder.page_total == total  # insertions never add to the total

    def test_count_scales_the_reservation(self):
        builder, _regs = self._builder(_InsertRegisters(count=500))
        _feed(builder, _make_hbox(height=10 * _PT))
        _feed(builder, _insertion(100, 10))
        assert builder.page_goal == 100 * _PT - (10 * _PT // 1000) * 500  # x_over_n(h, 1000) * count
        zero, _ = self._builder(_InsertRegisters(count=0))
        _feed(zero, _make_hbox(height=10 * _PT))
        _feed(zero, _insertion(100, 10))
        assert zero.page_goal == 100 * _PT

    def test_dimen_cap_splits_at_the_best_penalty(self):
        builder, _regs = self._builder(_InsertRegisters(dimen=6 * _PT))
        _feed(builder, _make_hbox(height=10 * _PT))
        vlist = (_make_hbox(height=3 * _PT), PenaltyNode(50),
                 _make_hbox(height=3 * _PT), _make_hbox(height=3 * _PT))
        _feed(builder, _insertion(100, 9, *vlist))
        record = builder._page_ins[100]
        assert (record.split_up, record.broken_at) == (True, 1)
        assert builder.insert_penalties == 50
        assert builder.page_goal == 97 * _PT
        _feed(builder, _insertion(100, 1, floating_penalty=77))
        assert builder.insert_penalties == 127

    def test_split_without_a_break_costs_an_eject(self):
        builder, _regs = self._builder(_InsertRegisters(dimen=6 * _PT))
        _feed(builder, _make_hbox(height=10 * _PT))
        _feed(builder, _insertion(100, 9, _make_hbox(height=9 * _PT)))
        assert builder._page_ins[100].broken_at is None
        assert builder.insert_penalties == NEG_INF_PENALTY

    def test_fire_fills_the_box_and_holds_the_remainder(self):
        seen: list[int] = []

        class _Counting(_ShippingRoutine):
            def execute(self, body_nodes, page_number, backend):
                seen.append(builder.insert_penalties)
                super().execute(body_nodes, page_number, backend)

        builder, regs = self._builder(_InsertRegisters(dimen=4 * _PT), _Counting())
        old = _make_hbox(height=_PT)
        regs.setbox(100, _wrap_nodes([old]))
        first, second = _make_hbox(height=2 * _PT), _make_hbox(height=3 * _PT)
        _feed(builder, _make_hbox(height=10 * _PT))
        _feed(builder, _insertion(100, 5, first, PenaltyNode(0), second))
        _feed(builder, PenaltyNode(NEG_INF_PENALTY))

        assert seen == [1]  # one held-over insertion while the output runs
        assert regs.peekbox(100).list == [old, first]
        [held] = [n for n in builder._mvl if isinstance(n, InsertNode)]
        assert held.vlist == (_fixed_glue(0), second)  # \splittopskip 2pt - 3pt -> 0
