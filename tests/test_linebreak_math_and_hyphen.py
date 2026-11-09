r""" Components 5-7: the line breaks the fixtures depend on.

* §866 — glue inside a formula is not a breakpoint;
* §761/§767 — ``\binoppenalty``/``\relpenalty`` after Bin/Rel atoms of a
  formula in a paragraph, never in ``\hbox`` or display math;
* §1039 — an empty discretionary after the font's ``\hyphenchar`` in a
  paragraph; §576 — ``\font`` takes ``\defaulthyphenchar``;
* §869/§859 — discretionary penalties and hyphen demerits.

Every expectation is a MiKTeX 24.4 ``\showbox`` or line-content measurement.
"""
import warnings
from itertools import pairwise
from pathlib import Path

import pytest

from aspose_tex import DviDevice, TeXJob, TeXOptions
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.linebreak import (
    LinebreakParams,
    _build_prefix_sums,
    _is_legal_breakpoint,
    _run_dp,
)
from aspose_tex._engine.nodes import (
    CharNode,
    DiscretionaryNode,
    GlueNode,
    GlueSign,
    HlistNode,
    KernNode,
    MathNode,
    PenaltyNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._input.reader import StringInputSource

walk = pytest.importorskip("tests._verification.dvi_walker").walk_chars_with_positions


def _run(src: str) -> TeXInterpreter:
    interp = TeXInterpreter(load_format="plain")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(StringInputSource(src + r"\end"), DviDevice())
    return interp


def _paragraph_items(src: str) -> list:
    """The first line box's contents of ``\\setbox0\\vbox{<src>}``."""
    box = _run(r"\setbox0\vbox{\hsize=6.5in \noindent " + src + r"\par}")._box_regs.getbox(0)
    lines = [node for node in box.list if isinstance(node, HlistNode)]
    return lines[0].list


def _hbox_items(src: str) -> list:
    return _run(r"\setbox0\hbox{" + src + "}")._box_regs.getbox(0).list


def _penalties_after_chars(items: list) -> list[tuple[str, int]]:
    """(glyph, penalty) for every penalty directly after a ``+`` or ``=``."""
    out = []
    for node, nxt in pairwise(items):
        if (isinstance(node, CharNode) and chr(node.char) in "+="
                and isinstance(nxt, PenaltyNode)):
            out.append((chr(node.char), nxt.penalty))
    return out


def _paragraph_list(src: str, monkeypatch) -> list:
    """The horizontal list handed to the line breaker for ``\\noindent <src>``.

    Lines replace an unbroken discretionary by its (empty) no-break branch,
    so the §1039 node is checked before line breaking.
    """
    from aspose_tex._engine import interpreter as interpreter_module

    captured: list[list] = []
    original = interpreter_module.exec_par

    def capture(par_list, *args, **kwargs):
        captured.append(list(par_list.nodes))
        return original(par_list, *args, **kwargs)

    monkeypatch.setattr(interpreter_module, "exec_par", capture)
    _run(r"\setbox0\vbox{\noindent " + src + r"\par}")
    return captured[-1]


# --- §767 Bin/Rel penalties ------------------------------------------------

@pytest.mark.parametrize(("formula", "expected"), [
    ("$a+b=c$", [("+", 700), ("=", 500)]),
    ("$x=+y$", [("=", 500)]),             # the + after = became Ord
    (r"$a=\relax=b$", [("=", 500)]),      # Rel followed by Rel: none on the first
    ("$a+{}$", [("+", 700)]),             # any following item counts
])
def test_paragraph_math_bin_rel_penalties(formula, expected):
    assert _penalties_after_chars(_paragraph_items("A " + formula + " end.")) == expected


def test_binoppenalty_infinite_suppresses_the_penalty():
    items = _paragraph_items(r"\binoppenalty=10000 A $a+b=c$ end.")
    assert _penalties_after_chars(items) == [("=", 500)]


def test_penalty_precedes_the_next_atoms_spacing_glue():
    items = _paragraph_items("A $a+b$ end.")
    plus = next(i for i, n in enumerate(items) if isinstance(n, CharNode) and n.char == ord("+"))
    assert isinstance(items[plus + 1], PenaltyNode)
    assert isinstance(items[plus + 2], GlueNode)


def test_hbox_and_display_math_get_no_penalties():
    assert not any(isinstance(n, PenaltyNode) for n in _hbox_items("A $a+b=c$ B"))
    box = _run(r"\setbox0\vbox{\noindent A $$a+b=c$$ B\par}")._box_regs.getbox(0)
    display = [n for n in box.list if isinstance(n, HlistNode)][1]
    assert not any(isinstance(n, PenaltyNode) for n in display.list)


# --- §1039 explicit hyphen, §576 \defaulthyphenchar -----------------------

def test_explicit_hyphen_in_paragraph_gets_empty_discretionary(monkeypatch):
    items = _paragraph_list("page-builder", monkeypatch)
    dash = next(i for i, n in enumerate(items) if isinstance(n, CharNode) and n.char == ord("-"))
    disc = items[dash + 1]
    assert isinstance(disc, DiscretionaryNode)
    assert (disc.pre, disc.post, disc.nobreak) == ((), (), ())


def test_no_automatic_discretionary_in_hbox():
    assert not any(isinstance(n, DiscretionaryNode) for n in _hbox_items("page-builder"))


@pytest.mark.parametrize(('source', 'glyphs'), [
    ('a--b c---d e-f', [123, 124, 45]),
    (r'a-\char45 b-\dash c---d', [123, 123, 124]),
    (r'\def\dash{-}a-\dash b---c', [123, 124]),
    (r'\hyphenchar\tenrm=`i fi ffi ff', [12, 14]),
    (r'\hyphenchar\tenrm=12 fi ffi ff', []),
    (r'\hyphenchar\tenrm=-1 a--b c---d e-f', []),
    ('a--{}-b', [123, 45]),
])
def test_original_tail_hyphenchar_after_resolved_run(source, glyphs, monkeypatch):
    items = _paragraph_list(r'\chardef\dash=45 ' + source, monkeypatch)
    assert [node.char for node, nxt in pairwise(items)
            if isinstance(node, CharNode) and isinstance(nxt, DiscretionaryNode)] == glyphs


def test_automatic_disc_precedes_real_font_kern(monkeypatch):
    items = _paragraph_list(r'\hyphenchar\tenrm=`A AV', monkeypatch)
    index = next(i for i, n in enumerate(items) if isinstance(n, CharNode) and n.char == ord('A'))
    assert isinstance(items[index + 1], DiscretionaryNode)
    assert isinstance(items[index + 2], KernNode) and items[index + 2].width < 0


def test_font_takes_defaulthyphenchar():
    # defaults initialize a newly allocated font, not a reused one.
    interp = _run(r"\defaulthyphenchar=`\! \font\x=cmr10 at11pt \relax")
    assert interp._font_manager.hyphenchar("x") == ord("!")
    assert interp._font_manager.hyphenchar("tenrm") == ord("-")


def test_reused_font_preserves_hyphenchar_despite_changed_default():
    interp = _run(r"\defaulthyphenchar=`\! \font\x=cmr10 \relax")
    assert interp._font_manager.hyphenchar("x") == ord("-")
    assert interp._font_manager.font_id("x") == interp._font_manager.font_id("tenrm")


# --- §866 no glue break inside math, §869/§859 discretionary charges ------

def test_glue_inside_a_formula_is_not_a_breakpoint():
    nodes = [CharNode(char=97, font_name="tenrm"), MathNode(width=0, after=False),
             CharNode(char=120, font_name="teni"), GlueNode(Glue(1, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)),
             CharNode(char=61, font_name="tenrm"), MathNode(width=0, after=True)]
    assert _is_legal_breakpoint(nodes, 3) is True
    assert _is_legal_breakpoint(nodes, 3, in_math=True) is False


def _params(**kw) -> LinebreakParams:
    zero = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
    base = dict(hsize=100, tolerance=10000, pretolerance=-1, linepenalty=0,
                adjdemerits=0, leftskip=zero, rightskip=zero,
                parfillskip=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL))
    base.update(kw)
    return LinebreakParams(**base)


def _disc_paragraph(pre: tuple) -> list:
    """`A` + disc + `B` + fill: the only legal break is the discretionary."""
    rule_a, rule_b = _box(100), _box(100)
    return [rule_a, DiscretionaryNode(pre=pre, post=(), nobreak=()), rule_b,
            PenaltyNode(10000), GlueNode(Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
            PenaltyNode(-10000)]


def _box(width: int) -> HlistNode:
    return HlistNode(list=[], width=width, height=0, depth=0, shift_amount=0,
                     glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0)


def _demerits(nodes: list, params: LinebreakParams) -> float:
    """Total demerits of the chosen breaks (one pass at ``params.tolerance``)."""
    widths, stretch, shrink = _build_prefix_sums(nodes, None)
    final = _run_dp(nodes, params, widths, stretch, shrink, params.tolerance, None,
                    final_pass=True)
    return final.total_demerits


@pytest.mark.parametrize(("pre", "penalty_field"), [((), "exhyphenpenalty"),
                                                    ((_box(0),), "hyphenpenalty")])
def test_discretionary_break_is_charged_its_penalty(pre, penalty_field):
    nodes = _disc_paragraph(pre)
    base = _demerits(nodes, _params())
    charged = _demerits(nodes, _params(**{penalty_field: 50}))
    assert charged - base == 50 * 50


def test_final_hyphen_demerits_after_a_hyphenated_line():
    # A | disc | B glue C: the final line "B C" follows the hyphenated "A".  A
    # second (much worse) path through the glue keeps two active nodes alive,
    # so the final break is not §855's artificial one-node case.
    nodes = [_box(100), DiscretionaryNode(pre=(), post=(), nobreak=()), _box(60),
             GlueNode(Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)), _box(40),
             PenaltyNode(10000), GlueNode(Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
             PenaltyNode(-10000)]
    base = _demerits(nodes, _params())
    assert _demerits(nodes, _params(finalhyphendemerits=5000)) - base == 5000


# --- end to end: the two combined_document lines ---------------------------

_PROBE_LINES = {
    "relation": (
        r"\hsize=6.5in \nopagenumbers \noindent Pack my box with five dozen liquor jugs. "
        r"When $a$ and $b$ are given, the sum $a+b$ follows, and the relation $x=y$ "
        r"closes the argument for this second paragraph of ordinary body text.\par\bye",
        # MiKTeX line ends
        ["relation", "text."],
    ),
}


def _line_ends(src: str, tmp_path: Path) -> list[str]:
    path = tmp_path / "probe.tex"
    path.write_text(src, encoding="utf-8")
    from aspose_tex._input.reader import FileInputSource
    dvi = TeXJob(FileInputSource(path), DviDevice(), options=TeXOptions(load_format="plain")).run()
    rows: dict[int, str] = {}
    for page in walk(dvi):
        for code, _h, v, *_rest in page:
            rows[v] = rows.get(v, "") + (chr(code) if 32 < code < 127 else "?")
    return [rows[v] for v in sorted(rows)]


def test_relation_paragraph_breaks_before_the_formula(tmp_path):
    src, ends = _PROBE_LINES["relation"]
    lines = _line_ends(src, tmp_path)
    assert [line.endswith(end) for line, end in zip(lines, ends, strict=True)] == [True, True]
