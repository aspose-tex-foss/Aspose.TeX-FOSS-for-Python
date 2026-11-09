"""Tests for HBoxBuilder, VBoxBuilder, glue-setting, and badness.

Covers AC-1, AC-2, AC-3, AC-4, AC-5.
"""
from __future__ import annotations

import pytest

from aspose_tex._engine.box_builder import (
    HBoxBuilder,
    VBoxBuilder,
    _measure_hlist,
    _measure_vlist,
    compute_badness,
    set_glue_hbox,
    set_glue_vbox,
)
from aspose_tex._engine.nodes import (
    INF_BAD,
    OVERFULL_BAD,
    CharNode,
    GlueNode,
    GlueOrder,
    GlueSign,
    HlistNode,
    KernNode,
    VlistNode,
)
from aspose_tex._engine.registers import Glue
from aspose_tex._engine.registers import GlueOrder as RegGlueOrder
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._input.reader import StringInputSource

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fm() -> FontManager:
    """FontManager loaded with cmr10 at design size (10pt = 655360 sp)."""
    mgr = FontManager()
    mgr.load_font("tenrm", "cmr10")
    mgr.select_font("tenrm")
    return mgr


# Reference values from test_fonts_font_manager.py
CMR10_CHAR_A_WIDTH_SP = 491521
CMR10_KERN_AV_SP = -72819
CMR10_FI_LIGATURE_CODE = 12  # 'f'(102)+'i'(105) → char 12


# ---------------------------------------------------------------------------
# compute_badness
# ---------------------------------------------------------------------------

def test_badness_zero_shortage() -> None:
    assert compute_badness(0, 1000) == 0


def test_badness_zero_shortage_zero_flex() -> None:
    assert compute_badness(0, 0) == 0


def test_badness_no_flex() -> None:
    assert compute_badness(100, 0) == INF_BAD


def test_badness_ratio_half() -> None:
    # TeX §108: r = 500*297 // 1000 = 148; (148**3 + 2**17) // 2**18 = 12
    assert compute_badness(500, 1000) == 12


def test_badness_ratio_one() -> None:
    # r = 297 → (297**3 + 2**17) // 2**18 = 100
    assert compute_badness(1000, 1000) == 100


@pytest.mark.parametrize(
    ("shortage", "flex", "expected"),
    [
        (1001, 1000, 100),      # just past ratio 1 is still finite
        (1500, 1000, 336),      # 100 * 1.5**3 = 337.5, TeX's integer steps give 336
        (4344, 1000, 8189),     # r = 1290: the last finite step (TeX jumps to 10000)
        (4347, 1000, INF_BAD),  # r = 1291 > 1290
        (149, 297, 13),         # r = 149: the first ratio TeX rates "loose"
    ],
)
def test_badness_follows_tex_108_integer_formula(shortage, flex, expected) -> None:
    assert compute_badness(shortage, flex) == expected


@pytest.mark.parametrize(
    ("shortage", "flex", "expected"),
    [
        (7230584, 7230584, 100),        # t*297 branch at its limit
        (7230585, 7230585, 100),        # t div (s div 297) branch
        (7230585, 1663496, INF_BAD),    # r := t branch: s too small to divide safely
    ],
)
def test_badness_large_values_use_tex_overflow_branches(shortage, flex, expected) -> None:
    assert compute_badness(shortage, flex) == expected


def test_badness_capped_at_inf_bad() -> None:
    assert compute_badness(9999, 1) == INF_BAD


# ---------------------------------------------------------------------------
# _measure_hlist
# ---------------------------------------------------------------------------

def test_measure_hlist_single_char(fm) -> None:
    nodes = [CharNode(char=ord('A'), font_name='tenrm')]
    w, h, d = _measure_hlist(nodes, fm)
    assert w == CMR10_CHAR_A_WIDTH_SP
    assert h > 0
    assert d >= 0


def test_measure_hlist_glue_node(fm) -> None:
    glue = Glue(65536, 0, RegGlueOrder.NORMAL, 0, RegGlueOrder.NORMAL)
    nodes = [GlueNode(glue=glue)]
    w, h, d = _measure_hlist(nodes, fm)
    assert w == 65536
    assert h == 0
    assert d == 0


def test_measure_hlist_kern_node(fm) -> None:
    nodes = [KernNode(width=1000, explicit=True)]
    w, h, d = _measure_hlist(nodes, fm)
    assert w == 1000
    assert h == 0
    assert d == 0


def test_measure_hlist_hlist_node(fm) -> None:
    inner = HlistNode(
        list=[], width=50000, height=30000, depth=5000,
        shift_amount=0, glue_sign=GlueSign.NORMAL,
        glue_order=GlueOrder.NORMAL, glue_set=0.0,
    )
    w, h, d = _measure_hlist([inner], fm)
    assert w == 50000
    assert h == 30000
    assert d == 5000


def test_measure_hlist_empty(fm) -> None:
    w, h, d = _measure_hlist([], fm)
    assert w == 0
    assert h == 0
    assert d == 0


# ---------------------------------------------------------------------------
# _measure_vlist
# ---------------------------------------------------------------------------

def test_measure_vlist_two_hboxes(fm) -> None:
    h1 = HlistNode(list=[], width=200, height=50, depth=10,
                   shift_amount=0, glue_sign=GlueSign.NORMAL,
                   glue_order=GlueOrder.NORMAL, glue_set=0.0)
    h2 = HlistNode(list=[], width=300, height=40, depth=8,
                   shift_amount=0, glue_sign=GlueSign.NORMAL,
                   glue_order=GlueOrder.NORMAL, glue_set=0.0)
    w, h, d = _measure_vlist([h1, h2], fm)
    assert w == 300  # max of 200, 300
    # height: h1.height + h1.depth + h2.height = 50 + 10 + 40 = 100
    assert h == 50 + 10 + 40
    assert d == 8  # depth of last box


def test_measure_vlist_with_kern(fm) -> None:
    hb = HlistNode(list=[], width=100, height=50, depth=10,
                   shift_amount=0, glue_sign=GlueSign.NORMAL,
                   glue_order=GlueOrder.NORMAL, glue_set=0.0)
    kern = KernNode(width=32768, explicit=True)  # 0.5pt
    hb2 = HlistNode(list=[], width=100, height=30, depth=5,
                    shift_amount=0, glue_sign=GlueSign.NORMAL,
                    glue_order=GlueOrder.NORMAL, glue_set=0.0)
    _, h, _ = _measure_vlist([hb, kern, hb2], fm)
    # height: hb.height(50) + hb.depth(10) + kern(32768) + hb2.height(30)
    assert h == 50 + 10 + 32768 + 30


# ---------------------------------------------------------------------------
# set_glue_hbox
# ---------------------------------------------------------------------------

def _make_hbox(nat_width: int, nodes: list) -> HlistNode:
    return HlistNode(
        list=nodes, width=nat_width, height=0, depth=0, shift_amount=0,
        glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
    )


def test_set_glue_hbox_exact_fit() -> None:
    box = _make_hbox(1000, [])
    set_glue_hbox(box, target_width=1000)
    assert box.glue_sign == GlueSign.NORMAL
    assert box.glue_set == 0.0
    assert box.width == 1000


def test_set_glue_hbox_stretch_infinite() -> None:
    hfil = GlueNode(glue=Glue(0, 65536, RegGlueOrder.FIL, 0, RegGlueOrder.NORMAL))
    box = _make_hbox(500, [hfil])
    set_glue_hbox(box, target_width=1000)
    assert box.glue_sign == GlueSign.STRETCHING
    assert box.glue_order == GlueOrder.FIL
    assert box.glue_set > 0
    assert box.width == 1000


def test_set_glue_hbox_no_stretch_available() -> None:
    """Overfull: needs stretch but no glue present."""
    box = _make_hbox(500, [])
    set_glue_hbox(box, target_width=1000)
    assert box.glue_sign == GlueSign.STRETCHING
    assert box.glue_set == 0.0
    assert box.width == 1000


def test_set_glue_hbox_shrink() -> None:
    shrink_glue = GlueNode(glue=Glue(200000, 0, RegGlueOrder.NORMAL, 65536, RegGlueOrder.NORMAL))
    box = _make_hbox(1000, [shrink_glue])
    set_glue_hbox(box, target_width=900)
    assert box.glue_sign == GlueSign.SHRINKING
    # shortage = 1000 - 900 = 100 sp; total_shrink = 65536 sp → ratio = 100/65536
    assert box.glue_set == pytest.approx(100 / 65536, rel=1e-5)
    assert box.width == 900


def test_set_glue_hbox_shrink_capped() -> None:
    """Finite shrink: ratio capped at 1.0."""
    shrink_glue = GlueNode(glue=Glue(500000, 0, RegGlueOrder.NORMAL, 10, RegGlueOrder.NORMAL))
    box = _make_hbox(1000, [shrink_glue])
    set_glue_hbox(box, target_width=500)  # need 500sp shrink, only 10sp available
    assert box.glue_sign == GlueSign.SHRINKING
    assert box.glue_set == 1.0  # capped


def _finite(width: int, stretch: int = 0, shrink: int = 0) -> GlueNode:
    return GlueNode(glue=Glue(width, stretch, RegGlueOrder.NORMAL, shrink, RegGlueOrder.NORMAL))


class TestSetGlueReturnsLastBadness:
    """``set_glue_hbox``/``set_glue_vbox`` return TeX's ``last_badness``."""

    def test_exact_fit_is_zero(self) -> None:
        assert set_glue_hbox(_make_hbox(1000, [_finite(0, 10)]), target_width=1000) == 0

    def test_stretch_past_ratio_one_is_finite(self) -> None:
        # §658: badness(x, total_stretch) — ratio 1.5 is 336, not 10000.
        assert set_glue_hbox(_make_hbox(0, [_finite(0, 1000)]), target_width=1500) == 336

    def test_no_stretch_is_inf_bad(self) -> None:
        box = _make_hbox(500, [CharNode(char=ord("a"), font_name="tenrm")])
        assert set_glue_hbox(box, target_width=1000) == INF_BAD

    def test_empty_list_is_zero(self) -> None:
        # §658/§664 rate only a non-empty list: \hbox to 100pt{} has \badness 0.
        assert set_glue_hbox(_make_hbox(0, []), target_width=1000) == 0
        assert set_glue_hbox(_make_hbox(1000, []), target_width=10) == 0

    def test_infinite_glue_is_zero(self) -> None:
        hfil = GlueNode(glue=Glue(0, 65536, RegGlueOrder.FIL, 0, RegGlueOrder.NORMAL))
        assert set_glue_hbox(_make_hbox(500, [hfil]), target_width=10**6) == 0

    def test_shrink_within_limit(self) -> None:
        assert set_glue_hbox(_make_hbox(1000, [_finite(500, 0, 200)]), target_width=800) == 100

    def test_insufficient_shrink_is_overfull(self) -> None:
        # §664: total_shrink < -x  ->  last_badness := 1000000, glue_set 1.0.
        box = _make_hbox(1000, [_finite(500, 0, 200)])
        assert set_glue_hbox(box, target_width=799) == OVERFULL_BAD
        assert box.glue_set == 1.0

    def test_no_shrink_is_overfull(self) -> None:
        box = _make_hbox(1000, [CharNode(char=ord("a"), font_name="tenrm")])
        assert set_glue_hbox(box, target_width=10) == OVERFULL_BAD

    def test_vbox_uses_the_same_rules(self) -> None:
        def vbox(nat: int, nodes: list) -> VlistNode:
            return VlistNode(
                list=nodes, width=0, height=nat, depth=0, shift_amount=0,
                glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
            )
        assert set_glue_vbox(vbox(0, [_finite(0, 1000)]), target_height=1500) == 336
        assert set_glue_vbox(vbox(1000, [_finite(0, 0, 100)]), target_height=500) == OVERFULL_BAD


def _plain_badness(box: str) -> str:
    r"""Return ``\the\badness`` after ``\setbox0`` *box* under plain TeX."""
    import warnings

    from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

    body = rf"\setbox0{box}\message{{[\the\badness]}}\end"
    job = TeXJob(StringInputSource(body), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job.run()
    return next(m[1:-1] for m in job.messages if m.startswith("["))


class TestBadnessMatchesMiktex:
    r"""Expected values are MiKTeX 24.4 plain ``\the\badness`` of the same box."""

    @pytest.mark.parametrize(
        ("box", "miktex"),
        [
            # The four lines measured.
            (r"\hbox to 20pt{a\hskip 109224sp plus 218448sp b}", "1270"),
            (r"\hbox to 10pt{a\hskip 5pt minus 3.33pt b}", "1000000"),
            (r"\hbox to 20pt{$a\mskip 3mu plus 6mu b$}", "1810"),
            (r"\hbox to 10pt{$a\mskip 9mu minus 6mu b$}", "1000000"),
            # Stretch past ratio 1 stays finite up to r = 1290 (§108).
            (r"\hbox to 10pt{a\hskip 0pt plus 4pt}", "195"),
            (r"\hbox spread 3pt{a\hskip 3pt plus 2pt}", "336"),
            (r"\hbox to 20pt{a\hskip 0pt plus 2.5pt}", "10000"),
            (r"\hbox to 10pt{a\hskip 0pt plus 1pt}", "10000"),
            # No glue: underfull is 10000, overfull is 1000000; empty list is 0.
            (r"\hbox to 100pt{a}", "10000"),
            (r"\hbox to 1pt{a}", "1000000"),
            (r"\hbox to 100pt{}", "0"),
            (r"\hbox to 1pt{}", "0"),
            # Shrink: exactly enough is 100, short by any amount is overfull.
            (r"\hbox to 6pt{a\hskip 3pt minus 2pt}", "1000000"),
            (r"\hbox{a\hskip 3pt minus 2pt}", "0"),
            (r"\hbox to 1pt{a\hskip 0pt minus 1fil}", "0"),
            # vpack §676-§677 follows the same rules.
            (r"\vbox to 20pt{\hrule height 1pt\vskip 0pt plus 7pt}", "1997"),
            (r"\vbox to 3pt{\hrule height 5pt\vskip 0pt minus 2pt}", "100"),
            (r"\vbox to 2pt{\hrule height 5pt\vskip 0pt minus 1pt}", "1000000"),
            (r"\vbox to 20pt{\hrule height 1pt}", "10000"),
            (r"\vbox to 0pt{\hrule height 1pt}", "1000000"),
            (r"\vbox to 20pt{}", "0"),
        ],
    )
    def test_badness(self, box: str, miktex: str) -> None:
        assert _plain_badness(box) == miktex


# ---------------------------------------------------------------------------
# HBoxBuilder — AC-1, AC-2
# ---------------------------------------------------------------------------

def test_hbox_builder_single_char_width(fm) -> None:
    """AC-1: CharNode for 'A' in cmr10 has width matching TFM data."""
    builder = HBoxBuilder(fm)
    builder.add_char(ord('A'), 'tenrm')
    box = builder.build()
    assert box.width == CMR10_CHAR_A_WIDTH_SP


def test_hbox_builder_hello_width(fm) -> None:
    """AC-2: \\hbox{Hello} has correct total width."""
    builder = HBoxBuilder(fm)
    for ch in "Hello":
        builder.add_char(ord(ch), 'tenrm')
    box = builder.build()
    # Width should be at least sum of individual char widths (may include kerns)
    metrics = fm.get_metrics('tenrm')
    expected_min = sum(metrics.char_metrics(ord(c)).width for c in "Hello")
    assert box.width >= expected_min - 10  # allow for kern adjustments


def test_hbox_builder_natural_size_no_glue(fm) -> None:
    builder = HBoxBuilder(fm)
    builder.add_char(ord('A'), 'tenrm')
    box = builder.build()
    assert box.glue_sign == GlueSign.NORMAL
    assert box.glue_set == 0.0


def test_hbox_builder_to_width_with_hfil(fm) -> None:
    """AC-3: \\hbox to 200pt{text \\hfil} stretches glue."""
    target = 200 * 65536  # 200pt in sp
    builder = HBoxBuilder(fm)
    for ch in "text":
        builder.add_char(ord(ch), 'tenrm')
    builder.add_glue(Glue(0, 65536, RegGlueOrder.FIL, 0, RegGlueOrder.NORMAL))
    box = builder.build(target_width=target)
    assert box.width == target
    assert box.glue_sign == GlueSign.STRETCHING
    assert box.glue_order == GlueOrder.FIL


def test_hbox_builder_ligature(fm) -> None:
    """'f'+'i' in cmr10 should produce a ligature (char 12), not two chars."""
    builder = HBoxBuilder(fm)
    builder.add_char(ord('f'), 'tenrm')
    builder.add_char(ord('i'), 'tenrm')
    box = builder.build()
    # Should have exactly one CharNode (the fi ligature)
    char_nodes = [n for n in box.list if isinstance(n, CharNode)]
    assert len(char_nodes) == 1
    assert char_nodes[0].char == CMR10_FI_LIGATURE_CODE


def test_hbox_builder_kern_av(fm) -> None:
    """'A'+'V' in cmr10 should have a negative kern between them."""
    builder = HBoxBuilder(fm)
    builder.add_char(ord('A'), 'tenrm')
    builder.add_char(ord('V'), 'tenrm')
    box = builder.build()
    # Should contain a KernNode with the A-V kern
    kern_nodes = [n for n in box.list if isinstance(n, KernNode)]
    assert len(kern_nodes) == 1
    assert kern_nodes[0].width == CMR10_KERN_AV_SP
    assert kern_nodes[0].explicit is False


# ---------------------------------------------------------------------------
# VBoxBuilder — AC-5
# ---------------------------------------------------------------------------

def test_vbox_builder_two_hboxes(fm) -> None:
    """AC-5: \\vbox stacks hboxes vertically."""
    h1 = HlistNode(list=[], width=200, height=50, depth=10,
                   shift_amount=0, glue_sign=GlueSign.NORMAL,
                   glue_order=GlueOrder.NORMAL, glue_set=0.0)
    h2 = HlistNode(list=[], width=300, height=40, depth=8,
                   shift_amount=0, glue_sign=GlueSign.NORMAL,
                   glue_order=GlueOrder.NORMAL, glue_set=0.0)
    vb = VBoxBuilder(fm)
    vb.add_hbox(h1)
    vb.add_hbox(h2)
    vbox = vb.build()
    assert vbox.width == 300  # max of 200, 300
    assert vbox.height == 50 + 10 + 40  # h1.h + h1.d + h2.h
    assert vbox.depth == 8


def test_vbox_builder_with_kern(fm) -> None:
    """Vertical kern contributes to height."""
    h1 = HlistNode(list=[], width=100, height=50, depth=10,
                   shift_amount=0, glue_sign=GlueSign.NORMAL,
                   glue_order=GlueOrder.NORMAL, glue_set=0.0)
    h2 = HlistNode(list=[], width=100, height=30, depth=5,
                   shift_amount=0, glue_sign=GlueSign.NORMAL,
                   glue_order=GlueOrder.NORMAL, glue_set=0.0)
    vb = VBoxBuilder(fm)
    vb.add_hbox(h1)
    vb.add_kern(5 * 65536)  # 5pt kern
    vb.add_hbox(h2)
    vbox = vb.build()
    # height: 50 + 10 + 5*65536 + 30
    assert vbox.height == 50 + 10 + 5 * 65536 + 30


def test_vbox_builder_empty(fm) -> None:
    vb = VBoxBuilder(fm)
    vbox = vb.build()
    assert vbox.width == 0
    assert vbox.height == 0
    assert vbox.depth == 0


# ---------------------------------------------------------------------------
# Nested box
# ---------------------------------------------------------------------------

def test_hbox_builder_contains_vlist(fm) -> None:
    """AC-8 partial: nested HlistNode → VlistNode."""
    inner_hbox = HlistNode(list=[], width=100, height=30, depth=5,
                           shift_amount=0, glue_sign=GlueSign.NORMAL,
                           glue_order=GlueOrder.NORMAL, glue_set=0.0)
    vb = VBoxBuilder(fm)
    vb.add_hbox(inner_hbox)
    vbox = vb.build()

    outer = HBoxBuilder(fm)
    outer.add_box(vbox)
    hbox = outer.build()
    assert isinstance(hbox.list[0], VlistNode)
    assert hbox.width == vbox.width
