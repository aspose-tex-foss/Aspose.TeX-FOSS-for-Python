r""" raw math material, measured with MiKTeX 24.4."""
import json
import re
from pathlib import Path

import pytest

from aspose_tex import DviDevice, PdfDevice, SvgDevice
from aspose_tex._engine.nodes import RUNNING_DIMEN, PenaltyNode, RuleNode
from aspose_tex.exceptions import EngineError
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_leaders_shipout import _SP_PER_BP, _compile
from tests.test_linebreak_math_and_hyphen import _hbox_items, _paragraph_items, _penalties_after_chars, _run
from tests.test_plain_tie import _messages, _tfm_width


@pytest.mark.parametrize("body,dims", [
    (r"\vrule", (26214, 0, 0)),
    (r"\vrule height30pt depth0pt", (26214, 1966080, 0)),
    (r"x\vrule width1pt y", (784916, 282168, 127431)),
    (r"\left(\vrule height30pt depth0pt\right)", (1173096, 1966080, 1605649)),
    (r"\left(\vrule height13pt depth0pt\right)", (991054, 950279, 622600)),
    (r"\strut x", (374556, 557056, 229376)),
    (r"a^{\vrule height4pt depth1pt}\mathchoice{\vrule height3pt}"
     r"{\vrule height5pt}{\vrule height7pt}{\vrule height9pt}b", (712870, 499969, 0)),
])
def test_raw_rule_dimensions(body, dims):
    box = _run(r"\setbox0\hbox{$" + body + "$}")._box_regs.getbox(0)
    assert (box.width, box.height, box.depth) == dims


def test_running_rule_survives_packing_and_paints():
    box = _run(r"\setbox0\hbox{$x\vrule width1pt y$}")._box_regs.getbox(0)
    rule = next(n for n in box.list if isinstance(n, RuleNode))
    assert (rule.height, rule.depth) == (RUNNING_DIMEN, RUNNING_DIMEN)
    data = _compile(r"\noindent $x\vrule width1pt y$\par", DviDevice())
    rules = []
    assert walk_chars_with_positions(data, _tfm_width(), advance_rules=True, rule_events=rules)[0][:-1] == [
        (120, 0, 655360), (121, 440092, 655360),
    ]
    assert rules == [(374556, 782791, 409599, 65536)]


def test_bare_math_hrule_fails():
    with pytest.raises(EngineError):
        _run(r"$x\hrule height2pt y$")


@pytest.mark.parametrize("kind", ["leaders", "cleaders", "xleaders"])
@pytest.mark.parametrize("context", [
    r"\noindent $xBODY y$\par", r"$$xBODY y$$",
    r"\hbox{$xBODY y$}", r"\hbox\bgroup$xBODY y$\egroup",
    r"\vbox{\noindent $xBODY y$\par}", r"\hbox{$a^{xBODY y}b$}",
])
def test_math_leaders_glyph_advance(kind, context):
    body = context.replace("BODY", "\\" + kind + r"\hrule\hskip10pt")
    data = _compile(body, DviDevice())
    rules = []
    glyphs = walk_chars_with_positions(data, _tfm_width(), advance_rules=True, rule_events=rules)[0][:-1]
    x, y = next(g for g in glyphs if g[0] == 120), next(g for g in glyphs if g[0] == 121)
    # Text or script x widths, freshly measured reference contexts.
    assert y[1] - x[1] == (952548 if "a^{" in context else 1029916)
    assert len(rules) == 1
    assert rules[0][3] == 655360


@pytest.mark.parametrize("payload", [r"\hrule height30pt", r"\hbox{\vrule height30pt}"])
def test_leader_payload_does_not_size_delimiters(payload):
    body = r"\left(x\leaders" + payload + r"\hskip10pt y\right)"
    box = _run(r"\setbox0\hbox{$" + body + "$}")._box_regs.getbox(0)
    assert (box.width, box.height, box.depth) == (1884466, 1966080, 163840)


def test_leader_alias_relax_and_tail():
    box = _run(r"\let\L=\leaders\let\R=\hrule\let\S=\hskip"
               r"\setbox0\hbox{$x\L\relax\R\relax\S10pt\unskip y$}")._box_regs.getbox(0)
    assert box.width == 719380


@pytest.mark.parametrize("body", [r"\leaders\hrule\vskip10pt", r"\leaders\hrule y", r"\leaders z"])
def test_invalid_math_leaders_fail(body):
    with pytest.raises(EngineError):
        _run("$x" + body + "$")


@pytest.mark.parametrize("value", [0, 7, -50, 10000, 20000])
def test_explicit_penalty_owner_and_suppression(value):
    body = rf"$a=\penalty{value} b$"
    items = _paragraph_items(body)
    assert _penalties_after_chars(items) == [("=", value)]
    assert [n.penalty for n in _hbox_items(body) if isinstance(n, PenaltyNode)] == [value]
    box = _run(r"\setbox0\vbox{\noindent " + body + r"\par}")._box_regs.getbox(0)
    assert not any(isinstance(n, PenaltyNode) for n in box.list)


def test_explicit_nobreak_and_penalty_positions():
    assert _penalties_after_chars(_paragraph_items(r"$a=\nobreak b$ $a+\penalty7 b$")) == [("=", 10000), ("+", 7)]


@pytest.mark.parametrize("material", [r"\vrule", r"\hskip1pt", r"\kern1pt", r"\textstyle"])
def test_penalty_suppression_requires_immediate_carrier(material):
    items = _paragraph_items(r"$a=" + material + r"\penalty7 b$")
    assert [n.penalty for n in items if isinstance(n, PenaltyNode)][:2] == [500, 7]


def test_nested_penalties_keep_selected_list():
    box = _run(r"\setbox0\hbox{$a^{x\penalty7 y}{b\penalty-2 c}"
               r"\mathchoice{\penalty1}{\penalty2}{\penalty3}{\penalty4}$}")._box_regs.getbox(0)
    def penalties(node):
        return ([node.penalty] if isinstance(node, PenaltyNode) else
                [p for n in getattr(node, "list", []) for p in penalties(n)])
    assert penalties(box) == [7, -2, 2]


_EVENTS = json.loads((Path(__file__).parents[1] / "testdata/reference/math_brace_leaders/events.json").read_text())
_EVENTS.update({"origin_" + name: row for name, row in json.loads(
    (Path(__file__).parents[1] / "testdata/reference/math_brace_leaders/origin_reference.json").read_text()).items()})


@pytest.mark.parametrize("name", _EVENTS)
@pytest.mark.parametrize("backend", ["dvi", "svg", "pdf"])
def test_fresh_miktex_events_all_outputs(name, backend, monkeypatch):
    row = _EVENTS[name]
    pdf_glyphs = []
    if backend == "pdf":
        from aspose_tex._output.pdf_writer import PdfWriter
        original = PdfWriter._flush_text_run

        def capture(writer):
            if writer._run_font is not None:
                h, v = writer._run_h_sp, writer._run_v_sp
                for c in writer._run_chars:
                    pdf_glyphs.append((c, h, v))
                    h += writer._run_font.metrics.char_metrics(c).width
            original(writer)

        monkeypatch.setattr(PdfWriter, "_flush_text_run", capture)
    device = {"dvi": DviDevice, "svg": SvgDevice, "pdf": PdfDevice}[backend]()
    data = _compile(r"\nopagenumbers " + row["tex"], device)
    glyphs = [tuple(g) for page in row["glyphs"] for g in page]
    rules = [tuple(r) for r in row["rules"]]
    if backend == "dvi":
        actual_rules = []
        actual = walk_chars_with_positions(data, _tfm_width(), advance_rules=True, rule_events=actual_rules)
        assert [g for page in actual for g in page] == glyphs
        assert actual_rules == rules
    elif backend == "svg":
        writer = device._backend
        assert [(c, h, v) for _, c, h, v in writer._char_placements] == glyphs
        assert writer._rule_placements == [(h, v-height, width, height) for h, v, height, width in rules]
    else:
        writer = device._backend
        assert pdf_glyphs == glyphs
        streams = re.findall(rb"stream\n(.*?)endstream", data, re.S)
        paints = b"\n".join(streams)
        rectangles = re.findall(rb"([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) re\s+f", paints)
        assert [tuple(round(float(n), 4) for n in rect) for rect in rectangles] == [
            (round(72+h/_SP_PER_BP, 4), round(writer._page_height_pt-72-v/_SP_PER_BP, 4),
             round(width/_SP_PER_BP, 4), round(height/_SP_PER_BP, 4)) for h, v, height, width in rules]


def test_physical_math_tails_and_restored_parent():
    read = r"\message{[\the\lastskip/\the\lastkern/\the\lastpenalty]}"
    assert _messages(r"\noindent o\penalty19$\leaders\hrule\hskip10pt" + read
                     + r"{\penalty7" + read + r"\unpenalty" + read + "}" + read
                     + r"\vrule" + read + r"\unskip" + read + r"\penalty-4" + read
                     + r"\unpenalty" + read + "$" + read) == [
        "[10.0pt/0.0pt/0]", "[0.0pt/0.0pt/7]", "[0.0pt/0.0pt/0]",
        "[0.0pt/0.0pt/0]", "[0.0pt/0.0pt/0]", "[0.0pt/0.0pt/0]",
        "[0.0pt/0.0pt/-4]", "[0.0pt/0.0pt/0]", "[0.0pt/0.0pt/0]",
    ]


@pytest.mark.parametrize("command,retained", [("box", False), ("copy", True)])
def test_failed_leader_scan_keeps_extraction_ownership(command, retained, monkeypatch):
    from aspose_tex import StringInputSource
    from aspose_tex._engine import leaders
    from aspose_tex._engine.interpreter import TeXInterpreter
    interp = TeXInterpreter(load_format="plain")
    parse = leaders.parse_leaders
    observed = []

    def failing_scan(*args, **kwargs):
        with pytest.raises(EngineError):
            parse(*args, **kwargs)
        assert all(n.kind.name != "GLUE" for n in interp._math_builder.mlist)
        assert not any(isinstance(n, (RuleNode, PenaltyNode)) for n in interp._par_list.nodes)
        observed.append(True)
        raise EngineError("expected wrong-axis leader glue")

    monkeypatch.setattr(leaders, "parse_leaders", failing_scan)
    with pytest.raises(EngineError):
        interp.run_with_device(StringInputSource(r"\setbox1\hbox{A}\noindent $x\leaders"
                                                + "\\" + command + r"1\vskip10pt$"), DviDevice())
    assert (interp._box_regs.copybox(1) is not None) == retained
    assert observed == [True]


def test_raw_collection_stays_in_math_owner(monkeypatch):
    from aspose_tex import StringInputSource
    from aspose_tex._engine.interpreter import TeXInterpreter
    from aspose_tex._engine.math_list import MathListBuilder
    from aspose_tex._engine.nodes import LeadersNode
    interp = TeXInterpreter(load_format="plain")
    seen = []
    for name in ("add_rule", "add_leaders", "add_penalty"):
        original = getattr(MathListBuilder, name)

        def capture(builder, payload, original=original, name=name):
            assert not any(isinstance(n, (RuleNode, LeadersNode, PenaltyNode)) for n in interp._par_list.nodes)
            assert not any(isinstance(n, (RuleNode, LeadersNode, PenaltyNode))
                           for n in [*interp._page_builder._mvl, *interp._page_builder._contrib])
            original(builder, payload)
            seen.append(name)

        monkeypatch.setattr(MathListBuilder, name, capture)
    source = StringInputSource(r"\noindent $x\vrule\leaders\hrule\hskip10pt\penalty7 y$\par\end")
    interp.run_with_device(source, DviDevice())
    assert seen == ["add_rule", "add_leaders", "add_penalty"]


def test_display_explicit_penalty_survives_disabled_automatic_penalties():
    box = _run(r"\setbox0\vbox{$$a=\penalty7 b$$}")._box_regs.getbox(0)
    def penalties(node):
        return ([node.penalty] if isinstance(node, PenaltyNode) else
                [p for n in getattr(node, "list", []) for p in penalties(n)])
    assert [p for n in box.list for p in penalties(n) if p == 7] == [7]
    assert not any(isinstance(n, PenaltyNode) and n.penalty == 7 for n in box.list)


def test_repeated_translation_preserves_raw_carriers(monkeypatch):
    from aspose_tex._engine.box_builder import _measure_hlist
    from aspose_tex._engine.interpreter import TeXInterpreter
    original = TeXInterpreter._translate_mlist
    checked = []

    def twice(interp, mlist, **kwargs):
        before = repr(mlist)
        first = original(interp, mlist, **kwargs)
        measured = _measure_hlist(first, interp._font_manager)
        second = original(interp, mlist, **kwargs)
        assert first == second
        assert measured == _measure_hlist(second, interp._font_manager)
        assert repr(mlist) == before
        checked.append(True)
        return second

    monkeypatch.setattr(TeXInterpreter, "_translate_mlist", twice)
    _run(r"\setbox0\hbox{$x\vrule\leaders\hrule\hskip10pt\penalty7 y$}")
    assert checked
