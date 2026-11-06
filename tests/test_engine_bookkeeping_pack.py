r""" regressions. Expectations measured by MiKTeX in a reference probe"""

import warnings

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob, TeXOptions
from aspose_tex._engine.box_builder import VBoxBuilder
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import GlueOrder, GlueSign, HlistNode
from aspose_tex._engine.registers import Glue
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex.exceptions import EngineError
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _tfm_width


def _run(body):
    job = TeXJob(StringInputSource(body + "\n\\bye\n"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = job.run()
    return job, dvi


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("\\def\\q{m}{\\chardef\\q=65 \\global\\countdef\\q=5 }\\message{[\\meaning\\q]}", ["[\\count5]"]),
        (
            "\\noindent x \\def\\q{m}{\\chardef\\q=65 \\global\\countdef\\q=5 }\\message{[\\meaning\\q]} y\\par",
            ["[\\count5]"],
        ),
        (
            "\\setbox0\\hbox{\\def\\q{m}{\\chardef\\q=65 \\global\\countdef\\q=5 }\\message{[\\meaning\\q]}}",
            ["[\\count5]"],
        ),
        (
            "\\setbox0\\vbox{\\def\\q{m}{\\chardef\\q=65 \\global\\countdef\\q=5 }\\message{[\\meaning\\q]}}",
            ["[\\count5]"],
        ),
        ("\\setbox0\\hbox{{$x$}}", []),
        (
            "\\def\\q{m}{\\chardef\\q=65 {\\global\\countdef\\q=5 }}\\edef\\z{\\meaning\\q}\\message{[\\z]}",
            ["[\\count5]"],
        ),
        ("\\def\\q{m}{\\chardef\\q=65 }\\message{[\\meaning\\q]}", ["[macro:->m]"]),
        ("\\countdef\\q=7 {\\def\\q{l}\\global\\chardef\\q=66 }\\message{[\\meaning\\q]}", ['[\\char"42]']),
        (
            "\\noindent x \\countdef\\q=7 {\\def\\q{l}\\global\\chardef\\q=66 }\\message{[\\meaning\\q]} y\\par",
            ['[\\char"42]'],
        ),
        (
            "\\setbox0\\hbox{\\countdef\\q=7 {\\def\\q{l}\\global\\chardef\\q=66 }\\message{[\\meaning\\q]}}",
            ['[\\char"42]'],
        ),
        (
            "\\setbox0\\vbox{\\countdef\\q=7 {\\def\\q{l}\\global\\chardef\\q=66 }\\message{[\\meaning\\q]}}",
            ['[\\char"42]'],
        ),
        ("\\setbox0\\hbox{{$x$}}", []),
        (
            "\\countdef\\q=7 {\\def\\q{l}{\\global\\chardef\\q=66 }}\\edef\\z{\\meaning\\q}\\message{[\\z]}",
            ['[\\char"42]'],
        ),
        ("\\countdef\\q=7 {\\def\\q{l}}\\message{[\\meaning\\q]}", ["[\\count7]"]),
        ("\\chardef\\q=67 {\\countdef\\q=8 \\global\\def\\q{g}}\\message{[\\meaning\\q]}", ["[macro:->g]"]),
        (
            "\\noindent x \\chardef\\q=67 {\\countdef\\q=8 \\global\\def\\q{g}}\\message{[\\meaning\\q]} y\\par",
            ["[macro:->g]"],
        ),
        (
            "\\setbox0\\hbox{\\chardef\\q=67 {\\countdef\\q=8 \\global\\def\\q{g}}\\message{[\\meaning\\q]}}",
            ["[macro:->g]"],
        ),
        (
            "\\setbox0\\vbox{\\chardef\\q=67 {\\countdef\\q=8 \\global\\def\\q{g}}\\message{[\\meaning\\q]}}",
            ["[macro:->g]"],
        ),
        ("\\setbox0\\hbox{{$x$}}", []),
        (
            "\\chardef\\q=67 {\\countdef\\q=8 {\\global\\def\\q{g}}}\\edef\\z{\\meaning\\q}\\message{[\\z]}",
            ["[macro:->g]"],
        ),
        ("\\chardef\\q=67 {\\countdef\\q=8 }\\message{[\\meaning\\q]}", ['[\\char"43]']),
        ("\\font\\q=cmr10 {\\chardef\\q=65 \\global\\countdef\\q=5 }\\message{[\\meaning\\q]}", ["[\\count5]"]),
        (
            "\\noindent x \\font\\q=cmr10 {\\chardef\\q=65 \\global\\countdef\\q=5 }\\message{[\\meaning\\q]} y\\par",
            ["[\\count5]"],
        ),
        (
            "\\setbox0\\hbox{\\font\\q=cmr10 {\\chardef\\q=65 \\global\\countdef\\q=5 }\\message{[\\meaning\\q]}}",
            ["[\\count5]"],
        ),
        (
            "\\setbox0\\vbox{\\font\\q=cmr10 {\\chardef\\q=65 \\global\\countdef\\q=5 }\\message{[\\meaning\\q]}}",
            ["[\\count5]"],
        ),
        ("\\setbox0\\hbox{{$x$}}", []),
        (
            "\\font\\q=cmr10 {\\chardef\\q=65 {\\global\\countdef\\q=5 }}\\edef\\z{\\meaning\\q}\\message{[\\z]}",
            ["[\\count5]"],
        ),
        ("\\font\\q=cmr10 {\\chardef\\q=65 }\\message{[\\meaning\\q]}", ["[select font cmr10]"]),
    ],
)
def test_cross_kind_global_release(body, expected):
    job, _ = _run(body)
    assert [m for m in job.messages if m.startswith("[")] == expected


@pytest.mark.parametrize("assignment", [r"\global\countdef\q=5 ", r"\global\def\q{g}"])
def test_previously_hidden_font_stays_hidden_after_global_release(assignment):
    interp = TeXInterpreter(load_format="plain")
    interp.run_with_device(StringInputSource(r"\font\q=cmr10 {\chardef\q=65 " + assignment + r"}\bye"), DviDevice())
    assert not interp._font_manager.is_font("q")
    # Previously emitted nodes still have access to the retained font record.
    key = interp._font_manager.font_id("tenrm")  # q shared this persistent record.
    assert interp._font_manager.get_metrics("q") is None
    assert interp._font_manager.get_metrics(key).tfm_name == "cmr10"


@pytest.mark.parametrize("box", ["hbox", "vbox"])
def test_box_brace_does_not_execute_an_unexpandable_assignment(box):
    interp = TeXInterpreter(load_format="plain")
    with pytest.raises(EngineError, match=r"Expected.*open"):
        interp.run_with_device(StringInputSource("\\" + box + r"\def\q{wrong}{x}"), DviDevice())
    assert "q" not in interp._expander.macros


def test_box_brace_checks_meaning_of_a_redefined_relax():
    with pytest.raises(EngineError, match=r"Expected.*open"):
        _run(r"\def\relax{z}\setbox0\hbox\relax{x}")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("\\setbox0\\hbox\\relax{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}", ["[5.2778pt,4.30554pt,0.0pt]"]),
        (
            "\\let\\r=\\relax \\setbox0\\hbox\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.2778pt,4.30554pt,0.0pt]"],
        ),
        (
            "\\def\\r{\\relax}\\setbox0\\hbox\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.2778pt,4.30554pt,0.0pt]"],
        ),
        (
            "\\setbox0\\hbox to 10pt\\relax{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[10.0pt,4.30554pt,0.0pt]"],
        ),
        (
            "\\let\\r=\\relax \\setbox0\\hbox to 10pt\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[10.0pt,4.30554pt,0.0pt]"],
        ),
        (
            "\\def\\r{\\relax}\\setbox0\\hbox to 10pt\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[10.0pt,4.30554pt,0.0pt]"],
        ),
        (
            "\\setbox0\\hbox spread 2pt\\relax{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[7.2778pt,4.30554pt,0.0pt]"],
        ),
        (
            "\\let\\r=\\relax \\setbox0\\hbox spread 2pt\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[7.2778pt,4.30554pt,0.0pt]"],
        ),
        (
            "\\def\\r{\\relax}\\setbox0\\hbox spread 2pt\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[7.2778pt,4.30554pt,0.0pt]"],
        ),
        ("\\noindent a \\hbox\\relax{x} b\\par\\message{[ok]}", ["[ok]"]),
        ("\\setbox1\\hbox{\\hbox\\relax{x}}\\message{[ok]}", ["[ok]"]),
        ("\\setbox1\\vbox{\\hbox\\relax{x}}\\message{[ok]}", ["[ok]"]),
        ("\\setbox1\\hbox{{$ \\hbox\\relax{x} $}}\\message{[ok]}", ["[ok]"]),
        ("\\edef\\z{\\hbox\\relax{x}}\\setbox1\\hbox{\\z}\\message{[ok]}", ["[ok]"]),
        ("\\setbox0\\vbox\\relax{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}", ["[469.75499pt,4.30554pt,0.0pt]"]),
        (
            "\\let\\r=\\relax \\setbox0\\vbox\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,4.30554pt,0.0pt]"],
        ),
        (
            "\\def\\r{\\relax}\\setbox0\\vbox\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,4.30554pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox to 10pt\\relax{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,10.0pt,0.0pt]"],
        ),
        (
            "\\let\\r=\\relax \\setbox0\\vbox to 10pt\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,10.0pt,0.0pt]"],
        ),
        (
            "\\def\\r{\\relax}\\setbox0\\vbox to 10pt\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,10.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox spread 2pt\\relax{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,6.30554pt,0.0pt]"],
        ),
        (
            "\\let\\r=\\relax \\setbox0\\vbox spread 2pt\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,6.30554pt,0.0pt]"],
        ),
        (
            "\\def\\r{\\relax}\\setbox0\\vbox spread 2pt\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,6.30554pt,0.0pt]"],
        ),
        ("\\noindent a \\vbox\\relax{x} b\\par\\message{[ok]}", ["[ok]"]),
        ("\\setbox1\\hbox{\\vbox\\relax{x}}\\message{[ok]}", ["[ok]"]),
        ("\\setbox1\\vbox{\\vbox\\relax{x}}\\message{[ok]}", ["[ok]"]),
        ("\\setbox1\\hbox{{$ \\vbox\\relax{x} $}}\\message{[ok]}", ["[ok]"]),
        ("\\edef\\z{\\vbox\\relax{x}}\\setbox1\\hbox{\\z}\\message{[ok]}", ["[ok]"]),
        ("\\setbox0\\vtop\\relax{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}", ["[469.75499pt,4.30554pt,0.0pt]"]),
        (
            "\\let\\r=\\relax \\setbox0\\vtop\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,4.30554pt,0.0pt]"],
        ),
        (
            "\\def\\r{\\relax}\\setbox0\\vtop\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,4.30554pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vtop to 10pt\\relax{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,4.30554pt,5.69446pt]"],
        ),
        (
            "\\let\\r=\\relax \\setbox0\\vtop to 10pt\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,4.30554pt,5.69446pt]"],
        ),
        (
            "\\def\\r{\\relax}\\setbox0\\vtop to 10pt\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,4.30554pt,5.69446pt]"],
        ),
        (
            "\\setbox0\\vtop spread 2pt\\relax{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,4.30554pt,2.0pt]"],
        ),
        (
            "\\let\\r=\\relax \\setbox0\\vtop spread 2pt\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,4.30554pt,2.0pt]"],
        ),
        (
            "\\def\\r{\\relax}\\setbox0\\vtop spread 2pt\\r{x}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[469.75499pt,4.30554pt,2.0pt]"],
        ),
        ("\\noindent a \\vtop\\relax{x} b\\par\\message{[ok]}", ["[ok]"]),
        ("\\setbox1\\hbox{\\vtop\\relax{x}}\\message{[ok]}", ["[ok]"]),
        ("\\setbox1\\vbox{\\vtop\\relax{x}}\\message{[ok]}", ["[ok]"]),
        ("\\setbox1\\hbox{{$ \\vtop\\relax{x} $}}\\message{[ok]}", ["[ok]"]),
        ("\\edef\\z{\\vtop\\relax{x}}\\setbox1\\hbox{\\z}\\message{[ok]}", ["[ok]"]),
    ],
)
def test_box_brace_relax(body, expected):
    job, _ = _run(body)
    assert [m for m in job.messages if m.startswith("[")] == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("\\setbox0\\hbox\\relax\\relax\\bgroup x\\egroup\\message{[\\the\\wd0]}", ["[5.2778pt]"]),
        ("\\setbox0\\vbox\\relax\\bgroup\\hbox{x}\\egroup\\message{[\\the\\ht0]}", ["[4.30554pt]"]),
        ("\\let\\r=\\relax\\def\\relax{z}\\setbox0\\hbox\\r{x}\\message{[\\the\\wd0]}", ["[5.2778pt]"]),
        ("\\setbox0\\hbox{a\\discretionary\\relax{b}\\relax{c}\\relax{d}e}\\message{[\\the\\wd0]}", ["[15.00003pt]"]),
        ("\\noindent x\\insert\\footins\\relax{\\hbox{a}}y\\message{[ok]}", ["[ok]"]),
        ("\\noindent x\\vadjust\\relax{\\kern2pt}y\\message{[ok]}", ["[ok]"]),
    ],
)
def test_box_brace_related_scanners(body, expected):
    job, _ = _run(body)
    assert [m for m in job.messages if m.startswith("[")] == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "\\setbox0\\vbox{\\hbox{\\strut a}\\kern2pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,14.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox to 20pt{\\hbox{\\strut a}\\kern2pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,20.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox spread 2pt{\\hbox{\\strut a}\\kern2pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,16.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vtop{\\hbox{\\strut a}\\kern2pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,8.5pt,5.5pt]"],
        ),
        (
            "\\setbox0\\vbox{\\hbox{\\strut a}\\vskip2pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,14.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox to 20pt{\\hbox{\\strut a}\\vskip2pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,20.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox spread 2pt{\\hbox{\\strut a}\\vskip2pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,16.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vtop{\\hbox{\\strut a}\\vskip2pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,8.5pt,5.5pt]"],
        ),
        (
            "\\setbox0\\vbox{\\hbox{\\strut a}\\kern-2pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,10.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox to 20pt{\\hbox{\\strut a}\\kern-2pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,20.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox spread 2pt{\\hbox{\\strut a}\\kern-2pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,12.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vtop{\\hbox{\\strut a}\\kern-2pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,8.5pt,1.5pt]"],
        ),
        (
            "\\setbox0\\vbox{\\hbox{\\strut a}\\kern0pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,12.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox to 20pt{\\hbox{\\strut a}\\kern0pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,20.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox spread 2pt{\\hbox{\\strut a}\\kern0pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,14.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vtop{\\hbox{\\strut a}\\kern0pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,8.5pt,3.5pt]"],
        ),
        (
            "\\setbox0\\vbox{\\hbox{\\strut a}\\penalty7}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,8.5pt,3.5pt]"],
        ),
        (
            "\\setbox0\\vbox to 20pt{\\hbox{\\strut a}\\penalty7}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,20.0pt,3.5pt]"],
        ),
        (
            "\\setbox0\\vbox spread 2pt{\\hbox{\\strut a}\\penalty7}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,10.5pt,3.5pt]"],
        ),
        (
            "\\setbox0\\vtop{\\hbox{\\strut a}\\penalty7}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,8.5pt,3.5pt]"],
        ),
        (
            "\\setbox0\\vbox{\\hbox{\\strut a}\\kern2pt\\penalty7}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,14.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox to 20pt{\\hbox{\\strut a}\\kern2pt\\penalty7}"
            "\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,20.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox spread 2pt{\\hbox{\\strut a}\\kern2pt\\penalty7}"
            "\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,16.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vtop{\\hbox{\\strut a}\\kern2pt\\penalty7}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,8.5pt,5.5pt]"],
        ),
        (
            "\\setbox0\\vbox{\\hbox{\\strut a}\\vskip2pt\\kern3pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,17.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox to 20pt{\\hbox{\\strut a}\\vskip2pt\\kern3pt}"
            "\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,20.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vbox spread 2pt{\\hbox{\\strut a}\\vskip2pt\\kern3pt}"
            "\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,19.0pt,0.0pt]"],
        ),
        (
            "\\setbox0\\vtop{\\hbox{\\strut a}\\vskip2pt\\kern3pt}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,8.5pt,8.5pt]"],
        ),
        (
            "\\setbox0\\vbox{\\hbox{\\strut a}\\kern2pt\\hbox{g}}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,22.5pt,1.94444pt]"],
        ),
        (
            "\\setbox0\\vbox to 20pt{\\hbox{\\strut a}\\kern2pt\\hbox{g}}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,20.0pt,1.94444pt]"],
        ),
        (
            "\\setbox0\\vbox spread 2pt{\\hbox{\\strut a}\\kern2pt\\hbox{g}}"
            "\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,24.5pt,1.94444pt]"],
        ),
        (
            "\\setbox0\\vtop{\\hbox{\\strut a}\\kern2pt\\hbox{g}}\\message{[\\the\\wd0,\\the\\ht0,\\the\\dp0]}",
            ["[5.00002pt,8.5pt,15.94444pt]"],
        ),
    ],
)
def test_vertical_pack_final_depth(body, expected):
    job, _ = _run(body)
    assert [m for m in job.messages if m.startswith("[")] == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "\\noindent x\\insert\\footins{\\hbox{\\strut a}\\kern2pt} y",
            [[120, 0, 655360], [121, 564339, 655360], [97, 0, 41792475], [49, 15229091, 43725786]],
        ),
        (
            "\\noindent x\\hbox{\\vbox{\\hbox{\\strut a}\\kern2pt}} y",
            [[120, 0, 917504], [97, 345886, 557056], [121, 892020, 917504], [49, 15229091, 43725786]],
        ),
        (
            "\\noindent x$\\vcenter{\\hbox{\\strut a}\\kern2pt}$y",
            [[120, 0, 655360], [97, 345886, 589824], [121, 673567, 655360], [49, 15229091, 43725786]],
        ),
        (
            "\\noindent x\\insert\\footins{\\hbox{\\strut a}\\vskip2pt} y",
            [[120, 0, 655360], [121, 564339, 655360], [97, 0, 41792475], [49, 15229091, 43725786]],
        ),
        (
            "\\noindent x\\hbox{\\vbox{\\hbox{\\strut a}\\vskip2pt}} y",
            [[120, 0, 917504], [97, 345886, 557056], [121, 892020, 917504], [49, 15229091, 43725786]],
        ),
        (
            "\\noindent x$\\vcenter{\\hbox{\\strut a}\\vskip2pt}$y",
            [[120, 0, 655360], [97, 345886, 589824], [121, 673567, 655360], [49, 15229091, 43725786]],
        ),
    ],
)
def test_insertion_depth_and_nested_glyphs(body, expected):
    _, dvi = _run(body)
    actual = walk_chars_with_positions(dvi, _tfm_width())
    assert [list(g) for g in actual[0]] == expected


@pytest.mark.parametrize("tail", [r"\kern2pt", r"\vskip2pt"])
def test_insertion_depth_contribution_matches_miktex_exactly(tail):
    # MiKTeX: control a v=42152923, trailing-strut a v=41792475.
    _, control = _run(r"\noindent x\insert\footins{\hbox{a}} y")
    _, changed = _run(r"\noindent x\insert\footins{\hbox{\strut a}" + tail + "} y")
    control_a = walk_chars_with_positions(control, _tfm_width())[0][2]
    changed_a = walk_chars_with_positions(changed, _tfm_width())[0][2]
    assert control_a[2] - changed_a[2] == 360448


@pytest.mark.parametrize(
    ("tail", "width", "expected"),
    [
        ("kern", 131072, (917504, 0)),
        ("glue", 131072, (917504, 0)),
        ("kern", 0, (786432, 0)),
        ("kern", -131072, (655360, 0)),
        ("penalty", 7, (557056, 229376)),
    ],
)
def test_vertical_pack_builder_pending_depth(tail, width, expected):
    # Dimensions and tail outcomes of the measured \hbox{\strut a} witnesses.
    builder = VBoxBuilder(FontManager())
    builder.add_hbox(
        HlistNode(
            list=[],
            width=327681,
            height=557056,
            depth=229376,
            shift_amount=0,
            glue_sign=GlueSign.NORMAL,
            glue_order=GlueOrder.NORMAL,
            glue_set=0.0,
        )
    )
    if tail == "kern":
        builder.add_kern(width)
    elif tail == "glue":
        builder.add_glue(Glue(width, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL))
    else:
        builder.add_penalty(width)
    result = builder.build()
    assert (result.height, result.depth) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "\\vsize=640pt\\noindent x\\insert\\footins{\\hbox{\\strut a}\\kern2pt} y",
            [[(120, 0, 655360), (121, 564339, 655360), (97, 0, 41582591), (49, 15229091, 43515904)]],
        ),
        (
            "\\noindent x\\insert\\footins{\\hbox{a}} y",
            [[(120, 0, 655360), (121, 564339, 655360), (97, 0, 42152923), (49, 15229091, 43725786)]],
        ),
        ("\\shipout\\hbox to 39666195sp{a\\hskip0pt plus1fil b}", [[(97, 0, 455111), (98, 39302105, 455111)]]),
        ("\\shipout\\hbox to 39666195sp{a\\hskip0pt plus-1fil b}", [[(97, 0, 455111), (98, 39302105, 455111)]]),
        ("\\shipout\\hbox to 1pt{a\\hskip0pt minus1fil b}", [[(97, 0, 455111), (98, -298554, 455111)]]),
        ("\\shipout\\hbox to 1pt{a\\hskip0pt minus-1fil b}", [[(97, 0, 455111), (98, -298554, 455111)]]),
        (
            "\\shipout\\vbox to 39666195sp{\\hbox{a}\\vskip0pt plus1fil\\hbox{b}}",
            [[(97, 0, 282168), (98, 0, 39666196)]],
        ),
        (
            "\\shipout\\vbox to 39666195sp{\\hbox{a}\\vskip0pt plus-1fil\\hbox{b}}",
            [[(97, 0, 282168), (98, 0, 39666196)]],
        ),
        ("\\shipout\\hbox to 10pt{a\\hskip3pt minus1pt b}", [[(97, 0, 455111), (98, 458753, 455111)]]),
        ("\\shipout\\hbox to 20pt{a\\hskip3pt plus1pt b}", [[(97, 0, 455111), (98, 946630, 455111)]]),
    ],
)
def test_packed_glue_precision_matches_miktex(body, expected):
    _, dvi = _run(body)
    actual = walk_chars_with_positions(dvi, _tfm_width())
    assert actual == expected
