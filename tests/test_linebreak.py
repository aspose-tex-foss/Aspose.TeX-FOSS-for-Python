"""Tests for the Knuth-Plass line-breaking algorithm.

Covers AC-1, AC-4, AC-5, AC-6.
"""
from __future__ import annotations

import pytest

from aspose_tex._engine.box_builder import compute_badness
from aspose_tex._engine.linebreak import (
    _FITNESS_DECENT,
    _FITNESS_LOOSE,
    _FITNESS_TIGHT,
    _FITNESS_VERY_LOOSE,
    LinebreakParams,
    _adjustment_ratio,
    _fitness_class,
    _line_demerits,
    break_paragraph,
)
from aspose_tex._engine.nodes import (
    INF_BAD,
    NEG_INF_PENALTY,
    GlueNode,
    GlueSign,
    HlistNode,
    PenaltyNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._fonts.font_manager import FontManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_params(hsize: int = 6553600) -> LinebreakParams:
    """Default LinebreakParams with given hsize (default 100pt)."""
    _zero = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
    return LinebreakParams(
        hsize=hsize,
        tolerance=200,
        pretolerance=100,
        linepenalty=10,
        adjdemerits=10000,
        leftskip=_zero,
        rightskip=_zero,
        parfillskip=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL),
    )


def _word_box(width_sp: int, height_sp: int = 458752, depth_sp: int = 0) -> HlistNode:
    """Return an HlistNode representing a word of given width."""
    return HlistNode(
        list=[],
        width=width_sp,
        height=height_sp,
        depth=depth_sp,
        shift_amount=0,
        glue_sign=GlueSign.NORMAL,
        glue_order=GlueOrder.NORMAL,
        glue_set=0.0,
    )


def _space_glue(natural_sp: int, stretch_sp: int, shrink_sp: int = 0) -> GlueNode:
    """Return a GlueNode for inter-word space."""
    return GlueNode(
        glue=Glue(
            width=natural_sp,
            stretch=stretch_sp,
            stretch_order=GlueOrder.NORMAL,
            shrink=shrink_sp,
            shrink_order=GlueOrder.NORMAL,
        )
    )


def _pt(pt: float) -> int:
    """Convert pt to scaled points."""
    return round(pt * 65536)


@pytest.fixture()
def fm() -> FontManager:
    """FontManager with cmr10 loaded (needed for _measure_hlist on CharNodes)."""
    mgr = FontManager()
    mgr.load_font("tenrm", "cmr10")
    mgr.select_font("tenrm")
    return mgr


# ---------------------------------------------------------------------------
# _adjustment_ratio unit tests
# ---------------------------------------------------------------------------

def test_adjustment_ratio_exact_fit() -> None:
    assert _adjustment_ratio(0, 1000, 1000) == 0.0


def test_adjustment_ratio_stretch() -> None:
    r = _adjustment_ratio(1000, 2000, 0)
    assert r is not None
    assert r == pytest.approx(0.5)


def test_adjustment_ratio_shrink_feasible() -> None:
    r = _adjustment_ratio(-1000, 0, 2000)
    assert r is not None
    assert r == pytest.approx(-0.5)


def test_adjustment_ratio_infeasible_no_shrink() -> None:
    assert _adjustment_ratio(-1000, 0, 0) is None


def test_adjustment_ratio_infeasible_over_shrink() -> None:
    # shrink_total=500, need=-1001 → r=-2.002 < -1 → None
    assert _adjustment_ratio(-1001, 0, 500) is None


def test_adjustment_ratio_no_stretch_returns_none() -> None:
    assert _adjustment_ratio(1000, 0, 0) is None


# ---------------------------------------------------------------------------
# Badness (delegates to compute_badness — just verify integration)
# ---------------------------------------------------------------------------

def test_badness_zero_perfect_fit() -> None:
    assert compute_badness(0, 1000) == 0


def test_badness_inf_no_flex() -> None:
    assert compute_badness(1, 0) == INF_BAD


# ---------------------------------------------------------------------------
# _fitness_class unit tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("badness", "stretched", "expected"),
    [
        (100, True, _FITNESS_VERY_LOOSE),   # TeX §853: b > 99
        (99, True, _FITNESS_LOOSE),
        (13, True, _FITNESS_LOOSE),         # b > 12
        (12, True, _FITNESS_DECENT),
        (0, False, _FITNESS_DECENT),
        (12, False, _FITNESS_DECENT),
        (13, False, _FITNESS_TIGHT),        # §855: shrunk, b > 12
        (INF_BAD, True, _FITNESS_VERY_LOOSE),  # no stretch at all
    ],
)
def test_fitness_class_follows_tex_badness_thresholds(badness, stretched, expected) -> None:
    assert _fitness_class(badness, stretched=stretched) == expected


# ---------------------------------------------------------------------------
# break_paragraph — structural tests
# ---------------------------------------------------------------------------

def test_empty_paragraph_returns_empty_list(fm: FontManager) -> None:
    result = break_paragraph([], _make_params(), fm)
    assert result == []


def test_all_discardable_paragraph_breaks_into_one_empty_line(fm: FontManager) -> None:
    """TeX §1096 line-breaks every non-void paragraph, glue-only ones too."""
    nodes = [
        GlueNode(glue=Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)),
        GlueNode(glue=Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)),
        PenaltyNode(penalty=NEG_INF_PENALTY),
    ]
    result = break_paragraph(nodes, _make_params(), fm)
    assert len(result) == 1
    assert (result[0].height, result[0].depth) == (0, 0)


def test_single_word_fits_in_one_line(fm: FontManager) -> None:
    # One 30pt word, parfillskip, sentinel — hsize=100pt → one line
    hsize = _pt(100)
    nodes = [
        _word_box(_pt(30)),
        GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),  # parfillskip
        PenaltyNode(penalty=NEG_INF_PENALTY),
    ]
    result = break_paragraph(nodes, _make_params(hsize), fm)
    assert len(result) == 1
    assert result[0].width == hsize


def test_forced_break_at_neg_inf_penalty(fm: FontManager) -> None:
    # word1 — penalty(-10000) — word2 — parfillskip — sentinel
    # Should produce exactly 2 lines regardless of widths
    hsize = _pt(200)
    nodes = [
        _word_box(_pt(30)),
        PenaltyNode(penalty=NEG_INF_PENALTY),
        _word_box(_pt(30)),
        GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
        PenaltyNode(penalty=NEG_INF_PENALTY),
    ]
    result = break_paragraph(nodes, _make_params(hsize), fm)
    assert len(result) == 2
    for line in result:
        assert line.width == hsize


def test_no_break_at_inf_penalty(fm: FontManager) -> None:
    # Two words separated by INF_PENALTY (= \nobreak) + space; should NOT break there.
    # The only valid break is at the GlueNode before parfillskip (or at the sentinel).
    hsize = _pt(200)
    # word1 — nobreak-penalty — space — word2 — parfillskip — sentinel
    nodes = [
        _word_box(_pt(30)),
        PenaltyNode(penalty=10000),   # INF_PENALTY — not a legal breakpoint
        _space_glue(_pt(5), _pt(5)),  # space after nobreak — not legal (preceded by penalty)
        _word_box(_pt(30)),
        GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
        PenaltyNode(penalty=NEG_INF_PENALTY),
    ]
    result = break_paragraph(nodes, _make_params(hsize), fm)
    # Both words fit on one line (hsize=200pt), so 1 line total
    assert len(result) == 1


def test_two_words_produce_two_lines_when_hsize_too_narrow(fm: FontManager) -> None:
    # Each word is 50pt, hsize=50pt — word1 alone is a perfect fit on line 1.
    # Breaking at the space gives bad=0 (perfect fit), so the algorithm will
    # choose the two-line solution over the single overfull line.
    hsize = _pt(50)
    nodes = [
        _word_box(_pt(50)),
        _space_glue(_pt(10), _pt(5)),
        _word_box(_pt(50)),
        GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
        PenaltyNode(penalty=NEG_INF_PENALTY),
    ]
    result = break_paragraph(nodes, _make_params(hsize), fm)
    assert len(result) == 2
    for line in result:
        assert line.width == hsize


def test_leftskip_rightskip_added(fm: FontManager) -> None:
    # Both leftskip and rightskip are non-zero; verify they appear in each line.
    hsize = _pt(100)
    lskip = Glue(_pt(5), 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
    rskip = Glue(_pt(5), 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
    params = LinebreakParams(
        hsize=hsize,
        tolerance=200,
        pretolerance=100,
        linepenalty=10,
        adjdemerits=10000,
        leftskip=lskip,
        rightskip=rskip,
        parfillskip=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL),
    )
    nodes = [
        _word_box(_pt(30)),
        GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
        PenaltyNode(penalty=NEG_INF_PENALTY),
    ]
    result = break_paragraph(nodes, params, fm)
    assert len(result) == 1
    line_list = result[0].list
    # First node must be leftskip GlueNode
    assert isinstance(line_list[0], GlueNode)
    assert line_list[0].glue.width == _pt(5)
    # Last node must be rightskip GlueNode
    assert isinstance(line_list[-1], GlueNode)
    assert line_list[-1].glue.width == _pt(5)


def test_parfillskip_last_line(fm: FontManager) -> None:
    # The last line should contain parfillskip (a FIL GlueNode) before the break.
    hsize = _pt(100)
    pfs = Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)
    params = _make_params(hsize)
    nodes = [
        _word_box(_pt(30)),
        GlueNode(glue=pfs),                      # parfillskip
        PenaltyNode(penalty=NEG_INF_PENALTY),
    ]
    result = break_paragraph(nodes, params, fm)
    assert len(result) == 1
    line_list = result[0].list
    # Find a GlueNode with FIL stretch in the last line
    fil_nodes = [n for n in line_list if isinstance(n, GlueNode)
                 and n.glue.stretch_order == GlueOrder.FIL]
    assert fil_nodes, "parfillskip GlueNode (FIL stretch) not found in last line"


def test_hfil_infinite_stretch(fm: FontManager) -> None:
    # A line containing hfil glue should end up with glue_order == FIL
    hsize = _pt(100)
    nodes = [
        _word_box(_pt(30)),
        GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),  # \hfil
        _word_box(_pt(30)),
        GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),  # parfillskip
        PenaltyNode(penalty=NEG_INF_PENALTY),
    ]
    result = break_paragraph(nodes, _make_params(hsize), fm)
    assert len(result) == 1
    line = result[0]
    assert line.glue_order == GlueOrder.FIL
    assert line.glue_sign == GlueSign.STRETCHING


def test_tolerance_accept_reject(fm: FontManager) -> None:
    # Badness slightly above pretolerance (100) but within tolerance (200).
    # Pass-1 should fail, pass-2 should succeed → still produces 1 or 2 lines.
    hsize = _pt(100)
    # word=60pt, space=10pt natural + 10pt stretch.
    # Line with just word+space+parfillskip: infinite stretch → bad=0.
    # Constructed so pretolerance pass would struggle but tolerance pass finds it.
    nodes = [
        _word_box(_pt(60)),
        _space_glue(_pt(10), _pt(10)),
        _word_box(_pt(40)),
        GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
        PenaltyNode(penalty=NEG_INF_PENALTY),
    ]
    # hsize=100pt, word1+space+word2=110pt > 100pt. Line must break somewhere.
    # word1=60pt alone: need=40pt, flex=10pt → ratio=4 → INF_BAD > pretolerance.
    # Pass-2 (tolerance=200): INF_BAD > 200, but parfillskip infinite → still breaks.
    result = break_paragraph(nodes, _make_params(hsize), fm)
    assert len(result) >= 1
    assert all(line.width == hsize for line in result)


def test_optimal_over_greedy(fm: FontManager) -> None:
    """Verify DP finds a better global solution than a greedy approach would.

    Setup: Three word boxes w1=20pt, w2=40pt, w3=40pt with spaces.
    hsize = 65pt.  A greedy "first fit" might break after w1 (leaving a
    short line), while DP finds that breaking after w2 leaves two balanced lines.
    """
    hsize = _pt(65)
    # w1=20, space=5+15str, w2=40, space=5+15str, w3=40
    # w1+space+w2 = 65pt → perfect fit, bad=0 for line1
    # Remaining: w3 = 40pt + parfillskip (infinite) → bad=0 for line2
    nodes = [
        _word_box(_pt(20)),
        _space_glue(_pt(5), _pt(15)),
        _word_box(_pt(40)),
        _space_glue(_pt(5), _pt(15)),
        _word_box(_pt(40)),
        GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
        PenaltyNode(penalty=NEG_INF_PENALTY),
    ]
    result = break_paragraph(nodes, _make_params(hsize), fm)
    # All lines on one page, exactly 2 lines (not 1 — all 3 words don't fit on 1 line)
    assert len(result) == 2
    for line in result:
        assert line.width == hsize

    # First line should contain w1 and w2 (not just w1) — i.e., 2 words on line1
    # This verifies DP chose break after w2, not after w1
    first_line_boxes = [n for n in result[0].list if isinstance(n, HlistNode)]
    assert len(first_line_boxes) == 2, (
        "DP should place 2 word-boxes on line 1 (w1+w2), not just w1"
    )


def test_line_stretched_past_ratio_one_is_feasible_within_tolerance(fm: FontManager) -> None:
    r""": a line with stretch ratio 1.1 has TeX badness 132, under \tolerance 200.

    The only legal break set is [w1 w2] [w3]: line 1 needs 11pt from 10pt of
    stretch.  Rating every ratio above 1 as 10000 made it infeasible, and the
    whole paragraph collapsed into one overfull line.
    """
    nodes = [
        _word_box(_pt(50)), _space_glue(_pt(10), _pt(10)),
        _word_box(_pt(29)), _space_glue(_pt(10), _pt(10)),
        _word_box(_pt(95)),
        GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
        PenaltyNode(penalty=NEG_INF_PENALTY),
    ]
    assert compute_badness(_pt(11), _pt(10)) == 132
    result = break_paragraph(nodes, _make_params(_pt(100)), fm)
    assert [len([n for n in line.list if isinstance(n, HlistNode)]) for line in result] == [2, 1]
    assert result[0].glue_set == pytest.approx(1.1)


class TestParagraphBreaksMatchMiktex:
    r"""Plain-TeX paragraphs whose best break stretches a line past ratio 1.

    Expected values are the natural widths (``\setbox3\hbox{\unhcopy2}``) of
    each line MiKTeX 24.4 sets.  Hyphenation is switched off
    (``\hyphenpenalty=10000``) because the engine does not hyphenate yet.
    """

    _TEXT = (
        "The quick brown fox jumps over the lazy dog while the five boxing "
        "wizards jump quickly and a wizard's job is to vex chumps quickly in "
        "fog. Pack my box with five dozen liquor jugs, then sphinx of black "
        "quartz judge my vow."
    )

    def test_230pt_paragraph_breaks_as_miktex(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # MiKTeX \tracingparagraphs: line 2 "while ... and a" is b=140, i.e.
        # stretched by ratio ~1.12 — feasible only under the §108 formula.
        from aspose_tex._engine.box_builder import _measure_hlist
        from aspose_tex._engine.interpreter import TeXInterpreter
        from aspose_tex._input.reader import StringInputSource
        from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

        widths: list[int] = []
        original = TeXInterpreter._contribute

        def capture(self, node) -> None:
            if (isinstance(node, HlistNode) and node.width == _pt(230)
                    and self._current_box_frame() is None):
                widths.append(_measure_hlist(node.list, self._font_manager)[0])
            original(self, node)

        monkeypatch.setattr(TeXInterpreter, "_contribute", capture)
        source = StringInputSource(
            "\\hsize=230pt \\hyphenpenalty=10000\n" + self._TEXT + "\\par\\end"
        )
        TeXJob(source, DviDevice(), options=TeXOptions()).run()

        assert widths == [14315998, 14095729, 14403382, 14445256, 7920769]


def test_overfull_warning_emitted(fm: FontManager) -> None:
    # Force overfull: one wide word with no break possible
    hsize = _pt(50)
    warnings: list[str] = []
    nodes = [
        _word_box(_pt(80)),   # wider than hsize, no shrink
        GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
        PenaltyNode(penalty=NEG_INF_PENALTY),
    ]
    result = break_paragraph(nodes, _make_params(hsize), fm, warnings=warnings)
    assert len(result) == 1
    assert any("Overfull" in w for w in warnings)


# ---------------------------------------------------------------------------
#: _line_demerits — 10^8 cap (pdftex.web §25248)
# ---------------------------------------------------------------------------

class TestLineDemerits:
    """Unit tests for the 10^8 cap in _line_demerits."""

    def test_cap_triggered_when_sum_ge_10000(self):
        # badness=10000, linepenalty=10 -> raw=10010 >= 10000 -> d=100_000_000
        # AC-1: _line_demerits(10000, 0, 10, 2, 2, 10000) == 100_000_000.0
        result = _line_demerits(10000, 0, 10, 2, 2, 10000)
        assert result == 100_000_000.0

    def test_no_cap_below_threshold(self):
        # badness=100, linepenalty=10 -> raw=110 < 10000 -> d=110*110=12100
        # AC-2: _line_demerits(100, 0, 10, 2, 2, 10000) == 12100
        result = _line_demerits(100, 0, 10, 2, 2, 10000)
        assert result == 12_100.0

    def test_cap_at_exact_boundary(self):
        # raw = 10000 exactly -> cap triggers
        result = _line_demerits(9990, 0, 10, 2, 2, 0)
        assert result == 100_000_000.0

    def test_cap_triggered_via_negative_sum(self):
        # Negative raw with |raw| >= 10000 also caps
        result = _line_demerits(0, 0, -10001, 2, 2, 0)
        assert result == 100_000_000.0

    def test_adjdemerits_added_when_fitness_differs(self):
        # fitness difference > 1 -> adjdemerits added on top
        # raw=10 -> d=100, fitness 0 vs 3 -> |3-0|=3 > 1 -> d += 10000
        result = _line_demerits(0, 0, 10, 0, 3, 10000)
        assert result == 100.0 + 10000.0
