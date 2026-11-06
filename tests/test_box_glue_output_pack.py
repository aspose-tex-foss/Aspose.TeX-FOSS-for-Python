r""" regressions, expected values measured with MiKTeX 24.4 tex."""

import re
import warnings
import xml.etree.ElementTree as ET

import pytest

from aspose_tex import PdfDevice, StringInputSource, SvgDevice, TeXJob
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _glyph_h, _messages, _run, _tfm_width

# PDF/SVG write big points; a TeX pt is 72.27/72 bp smaller.
_SP_PER_BP = 65536 * 72.27 / 72


@pytest.mark.parametrize(
    "content,expected",
    [
        (r"\relax", "[ok]"),
        (r"\relax\hrule", "[ok]"),
        (r"\hrule\relax", "[ok]"),
        (r"\csname zzq\endcsname", "[undefined]"),
    ],
)
def test_relax_is_noop_in_eager_vbox(content, expected):
    report = r"\meaning\zzq" if expected == "[undefined]" else "ok"
    assert _messages(r"\setbox0\vbox{" + content + r"}\message{[" + report + "]}") == [expected]


def test_relax_alias_and_nested_vbox():
    assert _messages(r"\let\noop\relax\setbox0\vbox{\noop\vbox{\noop}}\message{[ok]}") == ["[ok]"]


@pytest.mark.parametrize("open,close", [(r"\vbox{", "}"), (r"\vbox\bgroup", r"\egroup")])
def test_vfilneg_and_removal(open, close):
    body = (
        r"\setbox0" + open + r"\vfill\message{[\the\lastskip]}"
        r"\vfilneg\message{[\the\lastskip]}\unskip\message{[\the\lastskip]}" + close
    )
    assert _messages(body) == ["[0.0pt plus 1.0fill]", "[0.0pt plus -1.0fil]", "[0.0pt plus 1.0fill]"]


def test_vfilneg_outer_quantity():
    assert _messages(r"\hbox{o}\vfilneg\message{[\the\lastskip]}") == ["[0.0pt plus -1.0fil]"]


# A lone \vfilneg selects its -1fil total; \vfill outranks it.
@pytest.mark.parametrize(
    "glue,last_v",
    [(r"\vfil", 1068600), (r"\vskip0pt plus2fil", 1966080), ("", 1966080), (r"\vfill", 1966080)],
)
def test_vfilneg_cancels_stretch_instead_of_supplying_shrink(glue, last_v):
    job = _run(r"\noindent\vbox to30pt{\hbox{a}" + glue + r"\vfilneg\hbox{b}}")
    assert walk_chars_with_positions(job._dvi, _tfm_width())[0][:-1] == [(97, 0, 282168), (98, 0, last_v)]


@pytest.mark.parametrize(
    "body,expected",
    [
        (r"\noindent\hbox{\spaceskip=7pt x.\hbox{o} o}", [(120, 0), (46, 345886), (111, 527931), (111, 1314364)]),
        (
            r"\noindent\vbox{\noindent\spaceskip=7pt x.\hbox{o} o}",
            [(120, 0), (46, 345886), (111, 527931), (111, 1314364)],
        ),
        (r"\noindent\hbox{\spaceskip=7pt x.\ o}", [(120, 0), (46, 345886), (111, 986683)]),
        (r"\noindent\hbox{x. o}", [(120, 0), (46, 345886), (111, 819202)]),
        (r"\noindent\hbox{\xspaceskip=9pt x. o}", [(120, 0), (46, 345886), (111, 1117755)]),
        (r"\noindent\hbox{\spaceskip=7pt x. $a$ o}", [(120, 0), (46, 345886), (97, 1059501), (111, 1864669)]),
        (r"\noindent\hbox{x.\hbox{o} o}", [(120, 0), (46, 345886), (111, 527931), (111, 1074065)]),
        (r"\noindent\hbox{x.{} o}", [(120, 0), (46, 345886), (111, 819202)]),
        (r"\noindent\hbox{x.\setbox0\hbox{o} o}", [(120, 0), (46, 345886), (111, 819202)]),
        (r"\noindent\hbox{X. o}", [(88, 0), (46, 491521), (111, 892019)]),
        (r"\noindent\hbox{\sfcode`x=500 x o}", [(120, 0), (111, 564339)]),
        (r"\halign{#\cr x. o\cr}", [(120, 0), (46, 345886), (111, 819202)]),
        (r"\noindent\hbox{o\spacefactor=2000\message{[\the\spacefactor]} o}", [(111, 0), (111, 618952)]),
    ],
)
def test_eager_interword_spacing_at_miktex_positions(body, expected):
    assert _glyph_h(body) == expected


@pytest.mark.parametrize(
    "body,expected",
    [
        (
            r"\setbox0\hbox{\spaceskip=7pt plus2fil minus3pt x. \message{[\the\lastskip]}}",
            "[8.11111pt plus 6.0fil minus 1.0pt]",
        ),
        (
            r"\setbox0\hbox{\xspaceskip=9pt plus2fill minus3fil x. \message{[\the\lastskip]}}",
            "[9.0pt plus 2.0fill minus 3.0fil]",
        ),
        (r"\setbox0\hbox{x\char46\relax\message{[\the\spacefactor]} o}", "[3000]"),
        (r"\noindent x.\setbox0\hbox{o}\message{[\the\spacefactor]} o", "[3000]"),
    ],
)
def test_eager_spacefactor_and_glue_quantities(body, expected):
    assert _messages(body) == [expected]


@pytest.mark.parametrize(
    "body",
    [
        r"\noindent\hbox{x.\accent19 o o}",
        r"\halign{#\cr x.\accent19 o o\cr}",
        r"\noindent\vbox{\hbox{x.\accent19 o o}}",
        r"\noindent x.\accent19 o o",
        r"\noindent $\hbox{x.\accent19 o o}$",
        r"\noindent\hbox{\xspaceskip=9pt x.\accent19 o o}",
        r"\edef\a{\accent19 o}\noindent\hbox{x.\a\message{[\the\spacefactor]} o}",
    ],
)
def test_accent_resets_sentence_spacing_at_miktex_positions(body):
    # MiKTeX 24.4, including the accent and base at the same h coordinate.
    # The pre-existing accent height discrepancy is outside.
    assert _glyph_h(body) == [(120, 0), (46, 345886), (19, 527931), (111, 527931), (111, 1074065)]


def test_accent_resets_inner_spacefactor_and_preserves_enclosing_list():
    body = (
        r"\noindent\hbox{x.\setbox0\hbox{x.\accent19 o"
        r"\message{[inner\the\spacefactor]}}"
        r"\message{[outer\the\spacefactor]} o}"
    )
    assert _messages(body) == ["[inner1000]", "[outer3000]"]
    assert _glyph_h(body) == [(120, 0), (46, 345886), (111, 819202)]


def test_accent_resets_spacefactor_even_for_sentence_punctuation():
    assert _messages(r"\setbox0\hbox{x.\accent19 .\message{[\the\spacefactor]}}") == ["[1000]"]


def test_eager_horizontal_state_restores_after_error():
    from aspose_tex import DviDevice, StringInputSource
    from aspose_tex._engine.box_builder import HBoxBuilder
    from aspose_tex._engine.box_primitives import _list_tail_scope
    from aspose_tex._engine.interpreter import ModeKind, TeXInterpreter

    interp = TeXInterpreter()
    interp.run_with_device(StringInputSource(r"\relax"), DviDevice())
    interp._spacefactor = 3000
    initial_mode = interp._mode_stack.current
    builder = HBoxBuilder(interp._font_manager)
    with pytest.raises(ValueError), _list_tail_scope(interp._expander, builder):
        assert interp._mode_stack.current == ModeKind.RESTRICTED_HORIZONTAL
        assert interp._spacefactor == 1000
        raise ValueError("scanner failure")
    assert interp._spacefactor == 3000
    assert interp._mode_stack.current == initial_mode
    assert not interp._tail_providers


@pytest.mark.parametrize(
    "operand,v",
    [
        (r"\raise3pt\vbox{\hbox{a}}", 458752),
        (r"\lower1pt\vbox{\hbox{a}}", 720896),
        (r"\raise3pt\hbox{a}", 458752),
        (r"\lower1pt\hbox{a}", 720896),
        (r"\vbox{\hbox{a}}", 655360),
        (r"\raise3pt\vbox{\hbox{\lower1pt\vbox{\hbox{a}}}}", 524288),
    ],
)
def test_shifted_box_glyph_positions_in_all_backends(operand, v):
    body = r"\noindent o" + operand + "o"
    dvi = _run(body)._dvi
    assert walk_chars_with_positions(dvi, _tfm_width())[0][:-1] == [
        (111, 0, 655360),
        (97, 327681, v),
        (111, 655362, 655360),
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pdf = TeXJob(StringInputSource(body + r"\bye"), PdfDevice()).run()
        svg = TeXJob(StringInputSource(body + r"\bye"), SvgDevice()).run()
    # Conversion of measured MiKTeX sp coordinates into each backend's
    # existing origin/axis convention, at its serialized 4-place precision.
    pdf_a = re.search(rb"([\d.-]+) ([\d.-]+) Td\n\(ao?\) Tj", pdf)
    assert pdf_a is not None
    assert (float(pdf_a[1]), float(pdf_a[2])) == (round(72 + 327681 / _SP_PER_BP, 4), round(720 - v / _SP_PER_BP, 4))
    if v != 655360:
        pdf_o = re.findall(rb"([\d.-]+) ([\d.-]+) Td\n\(o\) Tj", pdf)
        assert (float(pdf_o[1][0]), float(pdf_o[1][1])) == (
            round(72 + 655362 / _SP_PER_BP, 4), round(720 - 655360 / _SP_PER_BP, 4))
    uses = ET.fromstring(svg).findall(".//{http://www.w3.org/2000/svg}use")
    assert (float(uses[1].get("x")), float(uses[1].get("y"))) == (
        round(72 + 327681 / _SP_PER_BP, 4),
        round(72 + v / _SP_PER_BP, 4),
    )
