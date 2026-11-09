r"""Tests for the ``\overfullrule`` marker on overfull hboxes (TeX §666).

Unit tests drive ``append_overfull_rule`` directly; the integration tests
compile plain-TeX snippets to DVI and compare every rule ``walk_rules`` sees
with MiKTeX-pdfTeX 4.19 ``tex`` output measured on 2026-10-20.
"""
from __future__ import annotations

import warnings

import pytest

from aspose_tex import DviDevice, TeXJob, TeXOptions
from aspose_tex._engine.box_builder import (
    _measure_hlist,
    append_overfull_rule,
    set_glue_hbox,
)
from aspose_tex._engine.box_primitives import OverfullBoxWarning
from aspose_tex._engine.nodes import (
    RUNNING_DIMEN,
    CharNode,
    GlueNode,
    GlueOrder,
    GlueSign,
    HlistNode,
    RuleNode,
)
from aspose_tex._engine.registers import Glue
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._input.reader import StringInputSource
from tests._verification.dvi_walker import walk_rules

PT = 65536
HFUZZ = 6554  # plain's 0.1pt
RULE = 5 * PT  # plain's \overfullrule


@pytest.fixture()
def fm() -> FontManager:
    """FontManager loaded with cmr10 at design size."""
    mgr = FontManager()
    mgr.load_font("tenrm", "cmr10")
    mgr.select_font("tenrm")
    return mgr


def _packed(fm: FontManager, nodes: list, target: int) -> tuple[HlistNode, int]:
    """Pack *nodes* to *target* sp as ``\\hbox to`` does; return box and badness."""
    width, height, depth = _measure_hlist(nodes, fm)
    box = HlistNode(list=nodes, width=width, height=height, depth=depth,
                    shift_amount=0, glue_sign=GlueSign.NORMAL,
                    glue_order=GlueOrder.NORMAL, glue_set=0.0)
    return box, set_glue_hbox(box, target_width=target)


def _chars(text: str) -> list:
    return [CharNode(char=ord(c), font_name="tenrm") for c in text]


# ---------------------------------------------------------------------------
# append_overfull_rule — unit
# ---------------------------------------------------------------------------

def test_overfull_box_gets_running_rule_at_its_end(fm) -> None:
    box, badness = _packed(fm, _chars("abcdef"), 20 * PT)
    dims = (box.width, box.height, box.depth)

    assert append_overfull_rule(box, badness, fm, hfuzz=HFUZZ, overfull_rule=RULE)

    assert box.list[-1] == RuleNode(width=RULE, height=RUNNING_DIMEN, depth=RUNNING_DIMEN)
    # The marker sticks out past the box; the box keeps its packed size.
    assert (box.width, box.height, box.depth) == dims


def test_zero_overfullrule_draws_nothing(fm) -> None:
    box, badness = _packed(fm, _chars("abcdef"), 20 * PT)
    assert not append_overfull_rule(box, badness, fm, hfuzz=HFUZZ, overfull_rule=0)
    assert not any(isinstance(n, RuleNode) for n in box.list)


def test_excess_within_hfuzz_draws_nothing(fm) -> None:
    box, badness = _packed(fm, _chars("abcdef"), 20 * PT)
    assert not append_overfull_rule(box, badness, fm, hfuzz=200 * PT, overfull_rule=RULE)
    assert len(box.list) == 6


def test_excess_counts_finite_shrink(fm) -> None:
    """§666 measures the excess after the finite shrink is used up."""
    nodes = _chars("abc")
    natural = _measure_hlist(nodes, fm)[0]
    nodes.append(GlueNode(glue=Glue(0, 0, GlueOrder.NORMAL, 2 * PT, GlueOrder.NORMAL)))
    # 3pt over the target, 2pt of it shrinkable: 1pt left, under a 1pt fuzz.
    box, badness = _packed(fm, nodes, natural - 3 * PT)
    assert not append_overfull_rule(box, badness, fm, hfuzz=PT, overfull_rule=RULE)
    assert append_overfull_rule(box, badness, fm, hfuzz=PT - 1, overfull_rule=RULE)


@pytest.mark.parametrize("target", [100 * PT, None])
def test_box_that_is_not_overfull_draws_nothing(fm, target) -> None:
    nodes = _chars("abc")
    box, badness = _packed(fm, nodes, target if target else _measure_hlist(nodes, fm)[0])
    assert not append_overfull_rule(box, badness, fm, hfuzz=0, overfull_rule=RULE)


def test_infinite_shrink_is_never_overfull(fm) -> None:
    nodes = [*_chars("abc"), GlueNode(glue=Glue(0, 0, GlueOrder.NORMAL, PT, GlueOrder.FIL))]
    box, badness = _packed(fm, nodes, PT)
    assert not append_overfull_rule(box, badness, fm, hfuzz=0, overfull_rule=RULE)


# ---------------------------------------------------------------------------
# Compiled through the engine — measured against MiKTeX
# ---------------------------------------------------------------------------

WIDE = "Supercalifragilisticexpialidocious"
# (h, v, height+depth, width) of every rule on page 1, as dvi_walker reads the
# MiKTeX DVI (it does not advance h over glyphs, so h is a walker coordinate).
_MARK = (36410, 782791, 582542, RULE)
_CASES = {
    "paragraph line": (rf"\hsize=60pt \parindent=0pt {WIDE} word\par", [_MARK]),
    r"\hbox to": (rf"\hbox to 20pt{{{WIDE}}}", [_MARK]),
    r"\hbox spread": (r"\hbox spread -30pt{abc def ghi jkl}",
                      [(455110, 782791, 582542, RULE)]),
    r"paragraph in \vbox": (rf"\vbox{{\hsize=60pt \noindent {WIDE} word\par}}",
                            [(36410, 582542, 582542, RULE)]),
    r"\overfullrule=2pt": (rf"\overfullrule=2pt \hbox to 20pt{{{WIDE}}}",
                           [(36410, 782791, 582542, 2 * PT)]),
    r"\overfullrule at \par time": (
        rf"\hsize=60pt \parindent=0pt {WIDE} word\overfullrule=1pt\par",
        [(36410, 782791, 582542, PT)],
    ),
    r"\overfullrule=0pt": (rf"\overfullrule=0pt \hbox to 20pt{{{WIDE}}}", []),
    r"within \hfuzz": (rf"\hfuzz=200pt \hbox to 20pt{{{WIDE}}}", []),
    r"\hbadness<100 reports, no rule": (
        rf"\hfuzz=200pt \hbadness=99 \hbox to 20pt{{{WIDE}}}", []),
    "nested box": (rf"\hbox{{\hbox to 20pt{{{WIDE}}}x}}", [_MARK]),
    r"\hbox\bgroup": (rf"\hbox to 20pt\bgroup {WIDE}\egroup", [_MARK]),
    "rule spans a taller box": (
        rf"\hbox to 20pt{{\vrule height 20pt depth 5pt {WIDE}}}",
        [(0, 1638400, 1638400, 26214), (36410, 1638400, 1638400, RULE)],
    ),
    r"\unhbox keeps the marker": (
        r"\setbox0\hbox to 20pt{abcdef}\setbox2\hbox{\unhbox0}"
        r"\hbox{\vrule width\wd2 height 1pt}",
        [(0, 655360, 65536, 2184538)],
    ),
    r"\wd excludes the marker": (
        r"\setbox0\hbox to 20pt{abcdef}\hbox{\vrule width\wd0 height 1pt}\box0",
        [(0, 655360, 65536, 20 * PT), (18205, 1441792, 455111, RULE)],
    ),
    "inline math": (r"$\hbox to 5pt{abc}$", [(1328925, 655360, 455111, RULE)]),
    "display wider than the line": (
        r"\hsize=100pt \noindent x $$aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa$$ y\par",
        [(0, 2228224, 282168, RULE)],
    ),
    r"display with \eqno": (
        r"\hsize=100pt \noindent x $$aaaaaaaaaaaaaaaaaaaaaaaaaa\eqno(1)$$ y\par",
        [(0, 2228224, 282168, RULE)],
    ),
    r"\halign to (§800 packs without it)": (
        r"\halign to 10pt{#\tabskip=0pt\cr abcdefgh\cr}", []),
    r"\hbox to inside a cell": (r"\halign{\hbox to 5pt{#}\cr abcdefgh\cr}",
                                [(18205, 782791, 582542, RULE)]),
    "finite shrink short": (r"\hbox to 30pt{abc\hskip 10pt minus 2pt def}",
                            [(542493, 655360, 455111, RULE)]),
    "infinite shrink": (r"\hbox to 5pt{abc\hskip 0pt minus 1fil def}", []),
}


def _rules(body: str) -> list:
    job = TeXJob(StringInputSource(body + r"\bye"), DviDevice(),
                 options=TeXOptions(load_format="plain"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = job.run()
    return walk_rules(dvi)


@pytest.mark.parametrize("case", list(_CASES))
def test_rules_match_miktex(case) -> None:
    body, expected = _CASES[case]
    assert _rules(body) == [expected]


@pytest.mark.parametrize("rule", ["5pt", "0pt"])
def test_overfull_report_is_unchanged_by_the_marker(rule) -> None:
    job = TeXJob(StringInputSource(rf"\overfullrule={rule} \hbox to 20pt{{{WIDE}}}\bye"),
                 DviDevice(), options=TeXOptions(load_format="plain"))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        job.run()
    reports = [str(w.message) for w in caught if issubclass(w.category, OverfullBoxWarning)]
    # the report carries MiKTeX's measured excess, before the marker.
    assert reports == [r"Overfull \hbox (121.83368pt too wide)"]
