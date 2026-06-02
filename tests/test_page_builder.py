"""Unit tests for PageBuilder and related classes.

Tests follow test plan.
"""
from __future__ import annotations

import pytest

from aspose_tex._engine.box_builder import _measure_vlist
from aspose_tex._engine.box_primitives import _PREVDEPTH_SENTINEL
from aspose_tex._engine.nodes import (
 NEG_INF_PENALTY,
 CharNode,
 GlueNode,
 GlueSign,
 HlistNode,
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
 w, h, d = _measure_vlist(body_nodes, None) # type: ignore[arg-type]
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
 pass # forgets to ship — dead cycles will accumulate


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
 builder.contribute(_make_hbox(height=400000))
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

 builder.contribute(_make_hbox(height=400000))
 assert builder.is_at_top_of_page is False

 builder.contribute(PenaltyNode(NEG_INF_PENALTY))
 assert builder.is_at_top_of_page is True


def test_only_discardables_no_shipout():
 """MVL with only glue/penalty/kern — no box — should not ship."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(GlueNode(Glue(100000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
 builder.contribute(PenaltyNode(0))
 builder.end_of_document()
 assert len(backend.calls) == 0


# ---------------------------------------------------------------------------
# Topskip tests
# ---------------------------------------------------------------------------

def test_topskip_inserted_for_first_box():
 """contribute box with height=500000 sp, topskip=655360 → GlueNode with width=155360 before box."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=500000))
 # MVL should be: [GlueNode(topskip=155360), HlistNode]
 assert len(builder._mvl) == 2
 assert isinstance(builder._mvl[0], GlueNode)
 assert builder._mvl[0].glue.width == 155360 # 655360 - 500000


def test_topskip_zero_when_box_exceeds_topskip():
 """box.height >= topskip.width → topskip glue has natural width=0."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=700000)) # 700000 > 655360
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
 builder.contribute(box)
 builder.contribute(_make_hbox(height=400000, depth=100000))
 # MVL: [topskip_glue, box1, interline_glue, box2]
 assert len(builder._mvl) == 4
 interline = builder._mvl[2]
 assert isinstance(interline, GlueNode)
 assert interline.glue.width == 286432 # 786432 - 100000 - 400000


def test_lineskip_used_when_ideal_below_limit():
 """config.lineskiplimit=200000; ideal < 200000 → lineskip Glue(65536,...) used."""
 cfg = _default_config(lineskiplimit=200000)
 backend = _NullBackend()
 builder = PageBuilder(cfg, backend, _ShippingRoutine())
 # ideal = 786432 - 100000 - 700000 = -13568 < 200000
 builder.contribute(_make_hbox(height=700000, depth=100000))
 builder.contribute(_make_hbox(height=700000, depth=100000))
 interline = builder._mvl[2]
 assert isinstance(interline, GlueNode)
 assert interline.glue.width == 65536 # lineskip


# ---------------------------------------------------------------------------
# Page total tests
# ---------------------------------------------------------------------------

def test_page_total_after_topskip_and_box():
 """After contributing one box h=400000, d=100000, topskip=655360:
 page_total = (655360-400000) + 400000 = 655360; page_depth = 100000."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=400000, depth=100000))
 assert builder.page_total == 655360
 assert builder.page_depth == 100000


def test_glue_node_contribution_updates_page_total():
 """contribute GlueNode(width=100000) → page_total increases by 100000."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 initial_total = builder.page_total
 builder.contribute(GlueNode(Glue(100000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
 assert builder.page_total == initial_total + 100000


def test_page_depth_clamped_to_max_depth():
 """box.depth > max_depth → page_depth == max_depth, excess absorbed into page_total."""
 cfg = _default_config(max_depth=262144)
 backend = _NullBackend()
 builder = PageBuilder(cfg, backend, _ShippingRoutine())
 # Contribute box with depth = 300000 > 262144
 builder.contribute(_make_hbox(height=400000, depth=300000))
 assert builder.page_depth == 262144
 # excess = 300000 - 262144 = 37856 absorbed into page_total


# ---------------------------------------------------------------------------
# Page break tests
# ---------------------------------------------------------------------------

def test_page_break_when_total_exceeds_vsize():
 """Contribute boxes summing to more than vsize with glue break points → shipout called."""
 cfg = _default_config(vsize=19660800) # 300pt
 backend = _NullBackend()
 builder = PageBuilder(cfg, backend, _ShippingRoutine())
 # Fill up past vsize with glue break points
 for _ in range(30):
 builder.contribute(_make_hbox(height=786432)) # 12pt each
 builder.contribute(GlueNode(Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
 assert len(backend.calls) >= 1


def test_forced_break_neg_inf_penalty():
 r"""\penalty-10000 immediately triggers page break."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=400000))
 builder.contribute(PenaltyNode(NEG_INF_PENALTY))
 assert len(backend.calls) == 1


def test_vsize_300pt_page_break():
 """config.vsize=19660800 (300pt); contribute 12pt lines → break after ~25 lines."""
 cfg = _default_config(
 vsize=19660800, # 300pt
 topskip=Glue(655360, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 baselineskip=Glue(786432, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 )
 backend = _NullBackend()
 builder = PageBuilder(cfg, backend, _ShippingRoutine())
 # Contribute 50 lines of 12pt height, 2pt depth, with glue break points
 for _ in range(50):
 builder.contribute(_make_hbox(height=655360, depth=131072)) # 10pt/2pt
 builder.contribute(GlueNode(Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
 builder.end_of_document()
 assert len(backend.calls) >= 2 # Must have broken into multiple pages


# ---------------------------------------------------------------------------
# : trailing discardables preserved through page break
# ---------------------------------------------------------------------------

def test_page_break_preserves_trailing_vfill():
 r"""\bye-style tail: [hbox, vfill_glue, -INF penalty] — vfill survives into body_nodes."""
 from aspose_tex._engine.page_primitives import make_vfill_glue

 backend = _NullBackend()
 routine = _CapturingRoutine()
 builder = PageBuilder(_default_config(), backend, routine)
 builder.contribute(_make_hbox(height=400000))
 builder.contribute(make_vfill_glue())
 builder.contribute(PenaltyNode(NEG_INF_PENALTY))

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
 builder.contribute(_make_hbox(height=400000))
 builder.contribute(KernNode(width=1_000_000, explicit=True))
 builder.contribute(PenaltyNode(NEG_INF_PENALTY))

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
 builder.contribute(_make_hbox(height=400000))
 glue_a = GlueNode(Glue(100_000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
 glue_b = GlueNode(Glue(200_000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
 builder.contribute(glue_a)
 builder.contribute(PenaltyNode(NEG_INF_PENALTY))
 # Break fires on the penalty. Re-contribute glue_b onto the fresh page.
 builder.contribute(glue_b)

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
 cfg = _default_config(vsize=19660800) # 300pt — small page
 backend = _NullBackend()
 builder = PageBuilder(cfg, backend, _ShippingRoutine())
 for _ in range(90):
 builder.contribute(_make_hbox(height=786432))
 builder.contribute(GlueNode(Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
 builder.end_of_document()
 assert builder.page_number >= 4


def test_multipage_shipout_calls():
 """Content for multiple pages → backend has calls with consecutive page numbers."""
 cfg = _default_config(vsize=19660800) # 300pt
 backend = _NullBackend()
 builder = PageBuilder(cfg, backend, _ShippingRoutine())
 for _ in range(90):
 builder.contribute(_make_hbox(height=786432))
 builder.contribute(GlueNode(Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
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
 builder.contribute(box) # topskip + box1
 builder.skip_next_interline()
 builder.contribute(box) # box2 (no interline glue before it)
 builder.contribute(box) # box3 (interline glue before it)

 # MVL: [topskip, box1, box2, interline_glue, box3]
 assert len(builder._mvl) == 5
 assert isinstance(builder._mvl[2], HlistNode) # box2 directly after box1
 assert isinstance(builder._mvl[3], GlueNode) # interline before box3


def test_offinterlineskip_disables_all():
 """off_interline(), contribute 3 boxes → no interline glue before any of them (only topskip)."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.off_interline()
 box = _make_hbox(height=400000)
 builder.contribute(box) # topskip + box1
 builder.contribute(box) # box2 (no interline)
 builder.contribute(box) # box3 (no interline)
 # MVL: [topskip, box1, box2, box3]
 assert len(builder._mvl) == 4
 assert isinstance(builder._mvl[0], GlueNode) # topskip
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
 builder.contribute(_make_hbox(height=400000))
 # Force a page break via eject
 builder.contribute(PenaltyNode(NEG_INF_PENALTY))
 assert builder.dead_cycles == 1


def test_dead_cycles_reset_on_shipout():
 """Normal output routine → dead_cycles == 0 after page break."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=400000))
 builder.contribute(PenaltyNode(NEG_INF_PENALTY))
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
 builder.contribute(_make_hbox(height=400000))
 builder.contribute(PenaltyNode(NEG_INF_PENALTY))
 assert builder.dead_cycles == 1
 # Second forced break: dead_cycles = 2, error (2 > 1 is True)
 builder.contribute(_make_hbox(height=400000))
 with pytest.raises(EngineError, match="Output loop"):
 builder.contribute(PenaltyNode(NEG_INF_PENALTY))


# ---------------------------------------------------------------------------
# PlainOutputRoutine unit tests
# ---------------------------------------------------------------------------

_HSIZE = 30_785_886 # 6.5in — plain TeX \hsize


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
 builder.contribute(_make_hbox(height=400000))
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
 builder.contribute(_make_hbox(height=100000))
 # Add an infinite vfil so the body can stretch to vsize.
 builder.contribute(GlueNode(Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)))
 builder.contribute(PenaltyNode(NEG_INF_PENALTY))
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
 builder.contribute(_make_hbox(height=400000))
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
 builder.contribute(_make_hbox(height=400000))
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
 builder.contribute(_make_hbox(height=400000))
 builder.end_of_document()
 _, page_box = backend.calls[0]
 body_box = _find_body_box(page_box)
 footline = _find_footline_hbox(page_box)
 # The kern immediately after the body box holds the spacing.
 nodes = page_box.list
 body_idx = nodes.index(body_box)
 kern = nodes[body_idx + 1]
 assert isinstance(kern, KernNode)
 # kern = 24pt - body.depth - footline.height (plain.tex \makefootline)
 expected = FOOTLINE_BASELINESKIP_SP - body_box.depth - footline.height
 assert kern.width == expected


def test_plain_output_headline_shift_minus_22p5pt():
 """The headline sits 22.5pt above the body (pre-head kern is -22.5pt)."""
 cfg = _default_config()
 backend = _NullBackend()
 routine = PlainOutputRoutine(hsize=_HSIZE, config=cfg)
 builder = PageBuilder(cfg, backend, routine)
 builder.contribute(_make_hbox(height=400000))
 builder.end_of_document()
 _, page_box = backend.calls[0]
 nodes = page_box.list
 # First node is the pre-headline kern = -HEADLINE_SHIFT_SP.
 assert isinstance(nodes[0], KernNode)
 assert nodes[0].width == -HEADLINE_SHIFT_SP
 assert abs(HEADLINE_SHIFT_SP - int(22.5 * 65536)) <= 1


def test_pagebuilder_advances_pageno_via_register():
 """After 3 page breaks the register reads 4 (1→2→3→4)."""
 cfg = _default_config(vsize=19_660_800) # 300pt — small page, forces breaks
 backend = _NullBackend()
 pageno = _IntPagenoStub(1)
 builder = PageBuilder(cfg, backend, _ShippingRoutine(), pageno_register=pageno)
 for _ in range(90):
 builder.contribute(_make_hbox(height=786432))
 builder.contribute(GlueNode(Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
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
 builder.contribute(_make_hbox(height=400000))
 builder.contribute(PenaltyNode(NEG_INF_PENALTY))
 assert routine.calls[0][1] == 100
 assert pageno.get_pageno() == 101


def test_to_roman_lowercase_boundary():
 """3999 is the classical upper bound for Roman numerals in TeX's table."""
 assert _to_roman_lowercase(3999) == "mmmcmxcix"
 assert _to_roman_lowercase(0) == ""
 assert _to_roman_lowercase(-5) == ""
 assert _to_roman_lowercase(1994) == "mcmxciv"


# ---------------------------------------------------------------------------
# v4 — RuleNode dispatch on the main vertical list
# ---------------------------------------------------------------------------

def _make_rule(height: int = 26_214, depth: int = 0, width: int = 4_000_000) -> RuleNode:
 return RuleNode(width=width, height=height, depth=depth)


def test_rule_first_on_page_inserts_topskip_glue():
 """Rule-first on a page goes through the topskip path ( Measurement B).

 Fresh PageBuilder, contribute a single RuleNode with default 0.4 pt height
 and zero depth. MVL must be ``[GlueNode(topskip), RuleNode]`` with the
 topskip glue's natural width equal to ``max(0, cfg.topskip.width - rule.height)``
 = 655_360 - 26_214 = 629_146 sp. The flag flips, ``_prev_depth`` writes
 the §679 sentinel ``ignore_depth = _PREVDEPTH_SENTINEL`` ( v5
 Component 6), and ``_page_total`` accumulates topskip_nat + rule.height +
 rule.depth = 655_360 sp (= 10 pt = ``\\topskip.width``).
 """
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 rule = _make_rule(height=26_214, depth=0)

 builder.contribute(rule)

 assert len(builder._mvl) == 2
 topskip = builder._mvl[0]
 assert isinstance(topskip, GlueNode)
 assert topskip.glue.width == 629_146 # 655360 - 26214
 assert builder._mvl[1] is rule
 assert builder._first_box_on_page is False
 # v5: §679 sentinel write (was `rule.depth` under v4).
 assert builder._prev_depth == _PREVDEPTH_SENTINEL
 assert builder.page_total == 655_360 # topskip_nat + rule.height + rule.depth


def test_rule_first_on_page_with_nonzero_rule_depth():
 """Rule-first with non-zero rule.depth: topskip reads height only; totals include depth."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 rule = _make_rule(height=26_214, depth=78_643) # 0.4 pt / 1.2 pt

 builder.contribute(rule)

 topskip = builder._mvl[0]
 assert isinstance(topskip, GlueNode)
 assert topskip.glue.width == 629_146 # depth is NOT part of topskip formula
 # v5: §679 sentinel — `_prev_depth` is independent of `rule.depth`.
 assert builder._prev_depth == _PREVDEPTH_SENTINEL
 assert builder.page_total == 629_146 + 26_214 + 78_643 # 734_003 sp


def test_rule_mid_page_appends_without_interline_glue():
 """Mid-page rule appends with sentinel prev_depth; no glue, no page_total change.

 Matches MiKTeX Measurements C + D + E (no interline GlueNode between
 prior box and rule). v5 Component 6: the post-rule write is the
 TeX:The Program §679 sentinel ``_PREVDEPTH_SENTINEL`` (= -1000 pt), not
 ``rule.depth`` — this suppresses the spurious interline-glue prelude for
 the next box (§253 sentinel guard in ``_insert_interline_or_topskip``).
 """
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 box = _make_hbox(height=400_000, depth=100_000)
 builder.contribute(box)
 # Sanity: box flipped the flag and seeded MVL = [topskip, box].
 assert builder._first_box_on_page is False
 assert len(builder._mvl) == 2
 pre_rule_total = builder.page_total
 pre_rule_mvl_len = len(builder._mvl)

 rule = _make_rule(height=26_214, depth=78_643)
 builder.contribute(rule)

 # Rule appended directly after the box — no intervening GlueNode.
 assert len(builder._mvl) == pre_rule_mvl_len + 1
 assert builder._mvl[-1] is rule
 assert not isinstance(builder._mvl[-2], GlueNode), (
 "mid-page rule must not be preceded by interline glue (§679 vs §1078)"
 )
 # v5: §679 sentinel write — `_prev_depth = ignore_depth` (NOT
 # `rule.depth`, which was the literal misread under v4). The sentinel
 # makes the next box's interline-glue prelude skip per §253.
 assert builder._prev_depth == _PREVDEPTH_SENTINEL
 # page_total is unchanged by the rule contribution (matches pre-cascade
 # `else: _mvl.append(node)` arm — §679 vs §1078 path divergence).
 assert builder.page_total == pre_rule_total


def test_box_after_rule_skips_interline_glue():
 """Post-rule box hits the sentinel-guarded interline branch — no glue inserted.

 Sequence: RuleNode(h=26214, d=78643) on a fresh page (rule-first; topskip
 inserted; ``_first_box_on_page=False``; ``_prev_depth=_PREVDEPTH_SENTINEL``),
 then HlistNode(h=400000, d=100000). Under v5 Component 6, the
 post-rule box hits the interline branch but the §253 sentinel guard
 (``if self._prev_depth <= _PREVDEPTH_SENTINEL: return``) skips the
 prelude entirely. MVL stays ``[topskip_glue, rule, box]`` with NO
 intervening GlueNode (matches MiKTeX Measurement E).
 """
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_rule(height=26_214, depth=78_643))
 box = _make_hbox(height=400_000, depth=100_000)

 builder.contribute(box)

 # v5: MVL is [topskip_glue, rule, box] — no interline glue
 # between rule and box (was [..., interline_glue, box] under v4).
 assert len(builder._mvl) == 3
 assert isinstance(builder._mvl[0], GlueNode) # topskip
 assert builder._mvl[1] is builder._mvl[1] # rule
 assert builder._mvl[2] is box
 assert not isinstance(builder._mvl[1], GlueNode), "rule, not glue"
 # No interline GlueNode between rule (index 1) and box (index 2).
 # The post-box update path runs `_update_page_totals_for_box`, which
 # overwrites `_prev_depth` from the sentinel to `box.depth`.
 assert builder._prev_depth == 100_000


# ---------------------------------------------------------------------------
# v5 Component 6 — sentinel `_prev_depth` after `\hrule` + sentinel
# guard in interline-glue prelude
# ---------------------------------------------------------------------------

def test_contribute_rule_first_writes_prev_depth_sentinel():
 """Rule-first arm writes the §679 sentinel `_prev_depth = ignore_depth`.

 Fresh PageBuilder, contribute a single RuleNode (rule-first arm because
 `_first_box_on_page` starts True). Assert `_prev_depth` post-call equals
 `_PREVDEPTH_SENTINEL` ( v5 §Component 6 / Edit 6.2).
 """
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 assert builder._first_box_on_page is True

 builder.contribute(_make_rule(height=26_214, depth=78_643))

 assert builder._prev_depth == _PREVDEPTH_SENTINEL


def test_contribute_rule_midpage_writes_prev_depth_sentinel():
 """Mid-page rule arm writes the §679 sentinel `_prev_depth = ignore_depth`.

 PageBuilder, contribute a HlistNode first (flips `_first_box_on_page` to
 False and sets `_prev_depth` to box.depth via `_update_page_totals_for_box`),
 then contribute a RuleNode (mid-page arm). Assert `_prev_depth` post-call
 equals `_PREVDEPTH_SENTINEL` ( v5 §Component 6 / Edit 6.2) and
 overrides the previous box's depth.
 """
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=400_000, depth=100_000))
 # Sanity: post-box, _prev_depth tracks box.depth, NOT the sentinel.
 assert builder._first_box_on_page is False
 assert builder._prev_depth == 100_000

 builder.contribute(_make_rule(height=26_214, depth=78_643))

 # v5: mid-page rule arm overrides box.depth with the sentinel.
 assert builder._prev_depth == _PREVDEPTH_SENTINEL


def test_insert_interline_skips_on_sentinel_prev_depth():
 """`_insert_interline_or_topskip` returns early when `_prev_depth` is the sentinel.

 TeXbook §253: when `\\prevdepth <= -1000 pt` the interline-glue prelude
 is skipped entirely. v5 §Component 6 / Edit 6.1 lands the
 guard. Pin: with `_first_box_on_page = False` and `_prev_depth =
 _PREVDEPTH_SENTINEL` (and neither suppression flag set), a call to
 `_insert_interline_or_topskip(box)` must NOT append a GlueNode to the
 MVL nor mutate page totals/stretch/shrink accumulators.
 """
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 # Manually arm the sentinel-guard preconditions: page no longer empty,
 # prev_depth is the §253 sentinel, no `\nointerlineskip` / `\offinterlineskip`.
 builder._first_box_on_page = False
 builder._prev_depth = _PREVDEPTH_SENTINEL
 builder._skip_interline_once = False
 builder._no_interline = False
 pre_mvl_len = len(builder._mvl)
 pre_total = builder.page_total
 pre_stretch = dict(builder._page_stretch)
 pre_shrink = dict(builder._page_shrink)

 builder._insert_interline_or_topskip(_make_hbox(height=400_000, depth=100_000))

 # Guard fires: no glue node added, totals untouched.
 assert len(builder._mvl) == pre_mvl_len, (
 "sentinel guard must not append a GlueNode (§253 ignore_depth)"
 )
 assert builder.page_total == pre_total
 assert builder._page_stretch == pre_stretch
 assert builder._page_shrink == pre_shrink


def test_contribute_two_rules_midpage_sets_sentinel_each_time():
 """Two consecutive mid-page rules each write the §679 sentinel.

 Sequence: HlistNode → RuleNode → RuleNode. After each RuleNode contrib,
 `_prev_depth` must equal `_PREVDEPTH_SENTINEL`. Pin that consecutive
 rules do not compound the spurious-glue defect — each rule individually
 writes the sentinel and there is no interline GlueNode between them
 ( v5 §Measurement E + Component 6).
 """
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=400_000, depth=100_000))
 assert builder._prev_depth == 100_000 # set by _update_page_totals_for_box

 rule_a = _make_rule(height=26_214, depth=78_643)
 builder.contribute(rule_a)
 assert builder._prev_depth == _PREVDEPTH_SENTINEL

 rule_b = _make_rule(height=26_214, depth=131_072) # different depth
 builder.contribute(rule_b)
 # Sentinel write again — `rule_b.depth` does NOT leak into _prev_depth.
 assert builder._prev_depth == _PREVDEPTH_SENTINEL
 # Both rules appended directly; no interline GlueNode between them.
 rule_a_idx = builder._mvl.index(rule_a)
 rule_b_idx = builder._mvl.index(rule_b)
 assert rule_b_idx == rule_a_idx + 1, (
 "consecutive rules must be adjacent in the MVL (no interline glue)"
 )


def test_page_reset_restores_first_box_on_page():
 """After a forced page break the single-flag ``_first_box_on_page`` resets to True."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=400_000))
 assert builder._first_box_on_page is False

 builder.contribute(PenaltyNode(NEG_INF_PENALTY))

 # After the page break the flag is reset for the new page.
 assert builder._first_box_on_page is True


# ---------------------------------------------------------------------------
# : TeXbook §1000 — discard leading discardables at the top of a
# continuation page. After a natural page break the leftover that
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
 multipage shape). After the synchronous output cycle the recommenced
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
 builder.contribute(_make_hbox(height=786_432, depth=100_000))
 builder.contribute(GlueNode(Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
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
 and must survive. Exercise ``_finish_output_cycle`` directly with a
 hand-built leftover ``[box_A, glue, box_B]``.
 """
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())

 box_a = _make_hbox(height=400_000, depth=100_000)
 inter = GlueNode(Glue(123_456, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
 box_b = _make_hbox(height=400_000, depth=100_000)
 builder._pending_leftover = [box_a, inter, box_b]
 builder._pending_page_number = builder.page_number

 builder._finish_output_cycle()

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
 is raised. The recommenced page stays empty (still at top of page).
 """
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())

 builder._pending_leftover = [
 GlueNode(Glue(100_000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)),
 KernNode(width=50_000, explicit=True),
 PenaltyNode(500),
 ]
 builder._pending_page_number = builder.page_number

 builder._finish_output_cycle() # must not raise

 assert builder._mvl == [], "all-discardable leftover re-contributes nothing"
 assert builder._first_box_on_page is True, "fresh page stays at top of page"


# ---------------------------------------------------------------------------
# : PageBuilder.remove_last_node — V-mode \unskip / \unkern / \unpenalty
# accounting hardening.
# ---------------------------------------------------------------------------

def test_remove_last_node_pops_glue_and_rolls_back_accumulators():
 """§Testing #1: popping a GlueNode rolls back total/stretch/shrink
 and clears _last_break_idx when it pointed at the popped glue."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=400_000)) # flips _first_box_on_page

 total_before = builder._page_total
 stretch_before = builder._page_stretch[GlueOrder.NORMAL]
 shrink_before = builder._page_shrink[GlueOrder.NORMAL]
 glue = GlueNode(Glue(786_432, 196_608, GlueOrder.NORMAL, 65_536, GlueOrder.NORMAL))
 builder.contribute(glue)

 assert builder._last_break_idx == len(builder._mvl) - 1
 assert builder._page_total == total_before + 786_432
 assert builder._page_stretch[GlueOrder.NORMAL] == stretch_before + 196_608
 assert builder._page_shrink[GlueOrder.NORMAL] == shrink_before + 65_536

 popped = builder.remove_last_node(GlueNode)

 assert popped is glue
 assert builder._page_total == total_before
 assert builder._page_stretch[GlueOrder.NORMAL] == stretch_before
 assert builder._page_shrink[GlueOrder.NORMAL] == shrink_before
 assert builder._last_break_idx is None
 assert builder._last_break_penalty == 0


def test_remove_last_node_pops_kern_and_rolls_back_page_total():
 """§Testing #2: popping a KernNode rolls back _page_total only;
 glue accumulators are left untouched."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=400_000))

 total_before = builder._page_total
 stretch_before = builder._page_stretch[GlueOrder.NORMAL]
 shrink_before = builder._page_shrink[GlueOrder.NORMAL]
 kern = KernNode(width=524_288, explicit=True) # 8 pt
 builder.contribute(kern)

 assert builder._page_total == total_before + 524_288

 popped = builder.remove_last_node(KernNode)

 assert popped is kern
 assert builder._page_total == total_before
 assert builder._page_stretch[GlueOrder.NORMAL] == stretch_before
 assert builder._page_shrink[GlueOrder.NORMAL] == shrink_before


def test_remove_last_node_pops_penalty_and_clears_last_break():
 """§Testing #3: popping a finite PenaltyNode clears
 _last_break_idx / _last_break_penalty without touching totals."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=400_000))

 total_before = builder._page_total
 stretch_before = builder._page_stretch[GlueOrder.NORMAL]
 shrink_before = builder._page_shrink[GlueOrder.NORMAL]
 penalty = PenaltyNode(500)
 builder.contribute(penalty)

 assert builder._last_break_idx == len(builder._mvl) - 1
 assert builder._last_break_penalty == 500

 popped = builder.remove_last_node(PenaltyNode)

 assert popped is penalty
 assert builder._page_total == total_before
 assert builder._page_stretch[GlueOrder.NORMAL] == stretch_before
 assert builder._page_shrink[GlueOrder.NORMAL] == shrink_before
 assert builder._last_break_idx is None
 assert builder._last_break_penalty == 0


def test_remove_last_node_type_mismatch_is_noop():
 """§Testing #4: when the tail is not one of *types*, the call is
 a no-op — returns None, MVL and accumulators unchanged."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=400_000))

 mvl_len_before = len(builder._mvl)
 total_before = builder._page_total
 stretch_before = dict(builder._page_stretch)
 shrink_before = dict(builder._page_shrink)
 last_break_idx_before = builder._last_break_idx

 popped = builder.remove_last_node(GlueNode) # tail is HlistNode

 assert popped is None
 assert len(builder._mvl) == mvl_len_before
 assert builder._page_total == total_before
 assert builder._page_stretch == stretch_before
 assert builder._page_shrink == shrink_before
 assert builder._last_break_idx == last_break_idx_before


def test_remove_last_node_empty_mvl_is_noop():
 """§Testing #5: empty MVL — call returns None without exception."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())

 popped = builder.remove_last_node(GlueNode)

 assert popped is None
 assert builder._mvl == []


def test_remove_last_node_preserves_last_break_idx_when_pointing_earlier():
 """§Testing #6: when _last_break_idx points at an earlier node,
 popping a later kern must NOT clear the break candidate."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=400_000))
 glue = GlueNode(Glue(100_000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
 builder.contribute(glue)
 glue_idx = builder._mvl.index(glue)
 assert builder._last_break_idx == glue_idx

 builder.contribute(_make_hbox(height=200_000))
 # Contributing a box does not move _last_break_idx — it still points at glue.
 assert builder._last_break_idx == glue_idx

 kern = KernNode(width=262_144, explicit=True)
 builder.contribute(kern)
 assert builder._mvl[-1] is kern
 assert builder._last_break_idx == glue_idx # unchanged by kern contribution

 popped = builder.remove_last_node(KernNode)

 assert popped is kern
 assert builder._last_break_idx == glue_idx # earlier break candidate preserved


def test_remove_last_node_does_not_touch_first_box_on_page_or_prev_depth():
 """§Testing #7: popping discardable nodes leaves
 _first_box_on_page and _prev_depth invariant."""
 backend = _NullBackend()
 builder = PageBuilder(_default_config(), backend, _ShippingRoutine())
 builder.contribute(_make_hbox(height=400_000, depth=100_000))

 assert builder._first_box_on_page is False
 prev_depth_before = builder._prev_depth

 builder.contribute(GlueNode(Glue(50_000, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
 popped = builder.remove_last_node(GlueNode)

 assert isinstance(popped, GlueNode)
 assert builder._first_box_on_page is False
 assert builder._prev_depth == prev_depth_before
