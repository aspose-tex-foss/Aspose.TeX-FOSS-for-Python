"""Tests for ParagraphList, exec_par, exec_penalty, and glue helpers.

Covers AC-1, AC-5, AC-7, AC-8.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from aspose_tex._engine.linebreak import LinebreakParams
from aspose_tex._engine.nodes import (
    INF_PENALTY,
    NEG_INF_PENALTY,
    CharNode,
    GlueNode,
    GlueSign,
    HlistNode,
    KernNode,
    PenaltyNode,
)
from aspose_tex._engine.par_primitives import (
    ParagraphList,
    exec_par,
    exec_penalty,
    make_hfil_glue,
    make_hfill_glue,
    make_hfilneg_glue,
    make_hss_glue,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._fonts.font_manager import FontManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pt(pt: float) -> int:
    return round(pt * 65536)


def _make_params(hsize: int = _pt(100)) -> LinebreakParams:
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


def _word_box(width_sp: int) -> HlistNode:
    return HlistNode(
        list=[],
        width=width_sp,
        height=_pt(7),
        depth=0,
        shift_amount=0,
        glue_sign=GlueSign.NORMAL,
        glue_order=GlueOrder.NORMAL,
        glue_set=0.0,
    )


def _space() -> GlueNode:
    return GlueNode(glue=Glue(_pt(5), _pt(5), GlueOrder.NORMAL, _pt(2), GlueOrder.NORMAL))


@pytest.fixture()
def fm() -> FontManager:
    mgr = FontManager()
    mgr.load_font("tenrm", "cmr10")
    mgr.select_font("tenrm")
    return mgr


# ---------------------------------------------------------------------------
# ParagraphList tests
# ---------------------------------------------------------------------------

def test_paragraph_list_empty_on_init() -> None:
    pl = ParagraphList()
    assert pl.is_empty is True


def test_paragraph_list_parindent_not_counted_as_content() -> None:
    pl = ParagraphList(parindent=_pt(20))
    # Indent box prepended, but no real content yet
    assert pl.is_empty is True
    # The indent box is still in the node list
    assert len(pl.nodes) == 1
    assert isinstance(pl.nodes[0], HlistNode)
    assert pl.nodes[0].width == _pt(20)


@pytest.mark.parametrize("width", [0, -_pt(10)])
def test_paragraph_list_zero_and_negative_indent_still_get_a_box(width: int) -> None:
    r"""TeX §1091: ``\indent`` appends the indent box whatever ``\parindent`` is."""
    pl = ParagraphList(parindent=width)
    assert pl.is_empty is True
    assert [type(n) for n in pl.nodes] == [HlistNode]
    assert pl.nodes[0].width == width


def test_paragraph_list_without_parindent_has_no_box() -> None:
    assert ParagraphList().nodes == []


def test_paragraph_list_content_after_append() -> None:
    pl = ParagraphList()
    pl.append(CharNode(char=ord('A'), font_name='tenrm'))
    assert pl.is_empty is False


def test_paragraph_list_glue_does_not_count_as_content() -> None:
    pl = ParagraphList()
    pl.append(GlueNode(glue=Glue(65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    assert pl.is_empty is True


def test_paragraph_list_penalty_does_not_count_as_content() -> None:
    pl = ParagraphList()
    pl.append(PenaltyNode(penalty=0))
    assert pl.is_empty is True


def test_paragraph_list_kern_does_not_count_as_content() -> None:
    pl = ParagraphList()
    pl.append(KernNode(width=1000, explicit=True))
    assert pl.is_empty is True


def test_paragraph_list_nodes_returns_copy() -> None:
    pl = ParagraphList()
    pl.append(_word_box(_pt(10)))
    copy1 = pl.nodes
    copy2 = pl.nodes
    assert copy1 is not copy2


# ---------------------------------------------------------------------------
# exec_par tests
# ---------------------------------------------------------------------------

def test_exec_par_empty_returns_empty(fm: FontManager) -> None:
    pl = ParagraphList()
    result = exec_par(pl, _make_params(), fm)
    assert result == []


@pytest.mark.parametrize("tail,retained", [
    ([GlueNode(Glue(196608, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))], 0),
    ([KernNode(262144, explicit=True)], 1),
    ([PenaltyNode(0)], 1),
    ([GlueNode(Glue(196608, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)),
      KernNode(262144, explicit=True)], 2),
    ([GlueNode(Glue(196608, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)),
      GlueNode(Glue(262144, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))], 1),
])
def test_section816_preserves_prior_tail_nodes_and_dimensions(fm, tail, retained):
    pl = ParagraphList()
    content = _word_box(655360)
    pl.append(content)
    for node in tail:
        pl.append(node)
    params = replace(_make_params(), parfillskip=Glue(131072, 196608, GlueOrder.FIL, 0, GlueOrder.NORMAL))
    lines = exec_par(pl, params, fm)
    assert len(lines) == 1
    result = lines[0].list
    assert result[:1 + retained] == [content, *tail[:retained]]
    assert isinstance(result[1 + retained], PenaltyNode)
    assert result[1 + retained].penalty == INF_PENALTY
    assert isinstance(result[2 + retained], GlueNode)
    assert result[2 + retained].glue == params.parfillskip
    assert pl.nodes == [content, *tail]  # normalization owns a copy


def test_exec_par_all_discardable_still_breaks_into_one_line(fm: FontManager) -> None:
    """§1096: only a void list is skipped; a discardable-only one sets a line."""
    pl = ParagraphList()
    pl.append(GlueNode(glue=Glue(_pt(5), 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    pl.append(PenaltyNode(penalty=0))
    result = exec_par(pl, _make_params(), fm)
    assert len(result) == 1
    assert (result[0].height, result[0].depth) == (0, 0)


def test_exec_par_indent_box_only_breaks_into_one_line(fm: FontManager) -> None:
    """An ``\\indent\\par`` paragraph holds only its indent box yet sets a line."""
    pl = ParagraphList(parindent=_pt(20))
    assert pl.is_empty
    result = exec_par(pl, _make_params(), fm)
    assert len(result) == 1
    assert result[0].list[0].width == _pt(20)


def test_exec_par_hello_world(fm: FontManager) -> None:
    # Two word boxes + space — should return at least one line
    pl = ParagraphList()
    pl.append(_word_box(_pt(20)))
    pl.append(_space())
    pl.append(_word_box(_pt(20)))
    result = exec_par(pl, _make_params(_pt(100)), fm)
    assert len(result) >= 1
    for line in result:
        assert isinstance(line, HlistNode)
        assert line.width == _pt(100)


def test_exec_par_penalty_forces_break(fm: FontManager) -> None:
    pl = ParagraphList()
    pl.append(_word_box(_pt(20)))
    pl.append(PenaltyNode(penalty=NEG_INF_PENALTY))
    pl.append(_word_box(_pt(20)))
    result = exec_par(pl, _make_params(_pt(100)), fm)
    assert len(result) == 2


def test_exec_par_strips_trailing_glue(fm: FontManager) -> None:
    # Trailing GlueNode and PenaltyNode should be stripped before line-breaking
    pl = ParagraphList()
    pl.append(_word_box(_pt(20)))
    pl.append(GlueNode(glue=Glue(_pt(5), 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    pl.append(PenaltyNode(penalty=0))
    # Adding trailing glue after the last real node
    pl.append(GlueNode(glue=Glue(_pt(5), 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)))
    result = exec_par(pl, _make_params(_pt(100)), fm)
    # Should succeed without crash and produce one line
    assert len(result) == 1


def test_exec_par_parindent_box_included(fm: FontManager) -> None:
    # parindent box should be in the first line
    indent = _pt(20)
    pl = ParagraphList(parindent=indent)
    pl.append(_word_box(_pt(30)))
    result = exec_par(pl, _make_params(_pt(100)), fm)
    assert len(result) >= 1
    first_line_boxes = [n for n in result[0].list if isinstance(n, HlistNode)]
    # First box in first line should be the indentation box
    assert first_line_boxes[0].width == indent


# ---------------------------------------------------------------------------
# exec_penalty tests
# ---------------------------------------------------------------------------

def test_exec_penalty_inserts_penalty_node() -> None:
    pl = ParagraphList()
    exec_penalty(-10000, pl)
    nodes = pl.nodes
    assert len(nodes) == 1
    assert isinstance(nodes[0], PenaltyNode)
    assert nodes[0].penalty == -10000


def test_exec_penalty_clamps_high() -> None:
    pl = ParagraphList()
    exec_penalty(99999, pl)
    assert pl.nodes[0].penalty == INF_PENALTY


def test_exec_penalty_clamps_low() -> None:
    pl = ParagraphList()
    exec_penalty(-99999, pl)
    assert pl.nodes[0].penalty == NEG_INF_PENALTY


def test_exec_penalty_zero() -> None:
    pl = ParagraphList()
    exec_penalty(0, pl)
    assert pl.nodes[0].penalty == 0


# ---------------------------------------------------------------------------
# Glue helper tests
# ---------------------------------------------------------------------------

def test_make_hfil_glue_properties() -> None:
    node = make_hfil_glue()
    assert isinstance(node, GlueNode)
    assert node.glue.width == 0
    assert node.glue.stretch == 65536
    assert node.glue.stretch_order == GlueOrder.FIL
    assert node.glue.shrink == 0
    assert node.glue.shrink_order == GlueOrder.NORMAL


def test_make_hfill_glue_properties() -> None:
    node = make_hfill_glue()
    assert isinstance(node, GlueNode)
    assert node.glue.stretch_order == GlueOrder.FILL
    assert node.glue.shrink == 0


def test_make_hfilneg_glue_properties() -> None:
    node = make_hfilneg_glue()
    assert isinstance(node, GlueNode)
    assert node.glue.stretch == -65536
    assert node.glue.stretch_order == GlueOrder.FIL
    assert node.glue.shrink == 0
    assert node.glue.shrink_order == GlueOrder.NORMAL


def test_make_hss_glue_properties() -> None:
    node = make_hss_glue()
    assert isinstance(node, GlueNode)
    assert node.glue.stretch_order == GlueOrder.FIL
    assert node.glue.shrink_order == GlueOrder.FIL
    assert node.glue.stretch == 65536
    assert node.glue.shrink == 65536


# ---------------------------------------------------------------------------
# \parindent is read when the paragraph starts
# ---------------------------------------------------------------------------


_TEXT = (
    "The quick brown fox jumps over the lazy dog while the five boxing "
    "wizards jump quickly and a wizard's job is to vex chumps quickly in fog."
)


def _paragraph_lines(body: str, monkeypatch: pytest.MonkeyPatch, hsize: int) -> list[HlistNode]:
    r"""Run *body* under plain TeX and return the contributed ``hsize``-wide lines."""
    from aspose_tex._engine.interpreter import TeXInterpreter
    from aspose_tex._input.reader import StringInputSource
    from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

    lines: list[HlistNode] = []
    original = TeXInterpreter._contribute

    def capture(self, node) -> None:
        if (isinstance(node, HlistNode) and node.width == hsize
                and self._current_box_frame() is None):
            lines.append(node)
        original(self, node)

    monkeypatch.setattr(TeXInterpreter, "_contribute", capture)
    TeXJob(StringInputSource(body + r"\end"), DviDevice(), options=TeXOptions()).run()
    return lines


class TestParindentIsLive:
    r"""The indent box is as wide as ``\parindent`` at paragraph start, as in TeX §1091."""

    @pytest.mark.parametrize(
        ("setting", "expected"),
        [
            (r"\parindent=0pt", 0),
            (r"\parindent=-10pt", -_pt(10)),
            (r"\parindent=35pt", _pt(35)),
            ("", _pt(20)),  # plain's default
        ],
    )
    def test_indent_box_width(self, setting, expected, monkeypatch) -> None:
        lines = _paragraph_lines(setting + r" \hsize=100pt A\par", monkeypatch, _pt(100))
        first = lines[0].list[0]
        assert isinstance(first, HlistNode) and not first.list
        assert first.width == expected

    def test_group_local_value_is_restored(self, monkeypatch) -> None:
        lines = _paragraph_lines(
            r"\hsize=100pt {\parindent=0pt A\par} B\par", monkeypatch, _pt(100)
        )
        assert [line.list[0].width for line in lines] == [0, _pt(20)]

    def test_noindent_has_no_indent_box(self, monkeypatch) -> None:
        lines = _paragraph_lines(r"\hsize=100pt \noindent A\par", monkeypatch, _pt(100))
        assert isinstance(lines[0].list[0], CharNode)

    @pytest.mark.parametrize(
        ("setting", "miktex_widths"),
        [
            (r"\parindent=0pt", [14716498, 14938596, 10183586]),
            (r"\parindent=-10pt", [15189815, 14920393, 9073112]),
        ],
    )
    def test_paragraph_breaks_as_miktex(self, setting, miktex_widths, monkeypatch) -> None:
        r"""MiKTeX 24.4 natural widths (``\hbox{\unhcopy}``) of each line, first to last.

        With the indent stuck at 20pt every line was measured too wide and the
        paragraph broke elsewhere.  Hyphenation is off: the engine has none yet.
        """
        from aspose_tex._engine.box_builder import _measure_hlist
        from aspose_tex._fonts.font_manager import FontManager

        lines = _paragraph_lines(
            setting + r" \hsize=230pt \hyphenpenalty=10000 " + _TEXT + r"\par",
            monkeypatch, _pt(230),
        )
        fm = FontManager()
        fm.load_font("tenrm", "cmr10")
        assert [_measure_hlist(line.list, fm)[0] for line in lines] == miktex_widths
