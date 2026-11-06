r""" scanner boundaries; dimensions measured by MiKTeX 24.4."""

import pytest

from aspose_tex import DviDevice, StringInputSource
from aspose_tex._engine.code_arrays import CodeArrays
from aspose_tex._engine.group import GroupStack
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.macro import PrimitiveMeaning
from aspose_tex._engine.math_shell import MathShellRegistry
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._fonts.math_family_registry import MathFamilyRegistry
from aspose_tex.exceptions import EngineError
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_expansion_completeness import _make_expander
from tests.test_plain_tie import _glyph_h, _messages, _run, _tfm_width


@pytest.mark.parametrize("template", [r"\hbox{#}", r"{\hbox{#}}", r"\hbox{{#}}"])
def test_text_box_template_owns_closing_groups(template: str) -> None:
    body = (r"\setbox0\vbox{\halign{#\hfil&" + template
            + r"\cr A&B\cr C&D\cr}}\message{[R:\number\wd0;\number\ht0;\number\dp0]}")
    assert _messages(body) == ["[R:992144;1234260;0]"]


def test_text_template_retains_following_cells_rows_and_scope() -> None:
    body = (r"\count200=7 \halign{\hbox{#}&\hbox{#}&\hbox{#}\cr"
            r"\count200=8 A&B&C\cr D&E&F\cr}\message{[\the\count200]}")
    assert [code for code, _ in _glyph_h(body)] == [65, 66, 67, 68, 69, 70]
    assert _messages(body) == ["[7]"]


@pytest.mark.parametrize(("wrapper", "measured"), [
    ("{}", [(97, 0)]),
    (r"\noindent x{}y", [(120, 0), (97, 345886), (121, 673567)]),
    (r"\hbox{x{}y}", [(120, 0), (97, 345886), (121, 673567)]),
    (r"\halign{#\cr x{}y\cr}", [(120, 0), (97, 345886), (121, 673567)]),
    (r"\noindent$x\hbox{{}}y$", [(120, 0), (97, 374556), (121, 702237)]),
])
def test_eager_valign_uses_receiving_list(wrapper: str, measured: list) -> None:
    assert _glyph_h(wrapper.replace("{}", r"\hbox{\valign{#\cr\hbox{a}\cr}}")) == measured


def test_eager_valign_negative_kern_has_zero_extent() -> None:
    assert _messages(r"\setbox0\hbox{\valign{#\cr\kern-5pt\cr}}"
                     r"\message{[\number\ht0,\number\wd0]}") == ["[0,0]"]


def test_eager_valign_witness_has_exact_miktex_baseline() -> None:
    dvi = _run(r"\hbox{\valign{#\cr\hbox{a}\cr}}")._dvi
    assert walk_chars_with_positions(dvi, _tfm_width())[0][:-1] == [(97, 0, 655360)]


@pytest.mark.parametrize(("setup", "gap"), [
    ("", " "), ("", r"\relax "),
    (r"\let\blank=\space", r"\blank "),
    (r"\let\r=\relax\def\relax{z}", r"\r "),
    (r"\def\r{\relax}", r"\r "),
])
@pytest.mark.parametrize(("command", "expected"), [
    (r"\message@{[ok]}", ["[ok]"]),
    (r"\uppercase@{\message{[ok]}}", ["[OK]"]),
    (r"\lowercase@{\message{[OK]}}", ["[ok]"]),
    (r"\mark@{x}\message{[ok]}", ["[ok]"]),
    (r"\halign@{#\cr x\cr}\message{[ok]}", ["[ok]"]),
    (r"\halign{#\cr x\cr\noalign@{\kern2pt}y\cr}\message{[ok]}", ["[ok]"]),
    (r"\noindent$x\vcenter@{\hbox{a}}y$\message{[ok]}", ["[ok]"]),
    (r"\toks0=@{\X}\message{[\the\toks0]}", [r"[\X ]"]),
    (r"\hyphenation@{hy-phen}\message{[ok]}", ["[ok]"]),
    (r"\noindent$x\mathchoice@{a}@{b}@{c}@{d}y$\message{[ok]}", ["[ok]"]),
])
def test_balanced_reader_skips_relax_meanings(setup, gap, command, expected) -> None:
    assert _messages(setup + command.replace("@", gap)) == expected


@pytest.mark.parametrize("command", [
    r"\message", r"\uppercase", r"\lowercase", r"\mark", r"\halign",
    r"\toks0=", r"\hyphenation", r"$\vcenter",
    r"\halign{#\cr x\cr\noalign",
])
@pytest.mark.parametrize("assignment", [r"\count200=9", r"\def\newmacro{x}"])
def test_bad_brace_prefix_does_not_execute_assignment(command, assignment) -> None:
    interp = TeXInterpreter()
    with pytest.raises(EngineError):
        interp.run_with_device(StringInputSource(r"\count200=7 " + command + assignment + "{x}"), DviDevice())
    assert interp._register_set.get_count(200) == 7
    assert "newmacro" not in interp._expander.macros


def test_case_body_stays_raw_until_converted() -> None:
    assert _messages(r"\def\q{low}\uppercase\relax{\message{[\q]}}") == ["[low]"]


def test_toks_body_retains_unexpanded_tokens() -> None:
    interp = TeXInterpreter()
    interp.run_with_device(StringInputSource(r"\def\q{expanded}\toks0=\relax{\q\noexpand\X}"), DviDevice())
    assert [token.name for token in interp._register_set.get_toks(0)] == ["q", "noexpand", "X"]


@pytest.mark.parametrize("gap", [" ", r"\relax ", r"\r "])
def test_math_shell_four_balanced_bodies_stay_raw(gap) -> None:
    setup = r"\let\r=\relax\def\relax{z}" if gap == r"\r " else ""
    expander = _make_expander(setup + r"\start"
                              + (gap + r"{\undefinedbody}") * 4 + "Q")
    expander.define("relax", PrimitiveMeaning("relax"))
    assert expander._next_unexpandable().name == "start"
    shell = MathShellRegistry(expander, CodeArrays(), MathFamilyRegistry(GroupStack(), FontManager()))
    assert shell.dispatch_if_known("mathchoice")
    assert expander._next_raw().char == "Q"


@pytest.mark.parametrize("form", [("{", "}"), (r"\bgroup", r"\egroup")])
def test_boxmaxdepth_is_read_before_box_group_restore(form) -> None:
    opening, closing = form
    body = (r"\boxmaxdepth=9pt\setbox0\vbox" + opening
            + r"\boxmaxdepth=2pt \hbox{\vrule depth5pt height1pt}" + closing
            + r"\message{[\the\ht0,\the\dp0,\the\boxmaxdepth]}")
    assert _messages(body) == ["[4.0pt,2.0pt,9.0pt]"]


def test_nested_open_vbox_reads_each_local_boxmaxdepth() -> None:
    body = (r"\boxmaxdepth=9pt\setbox0\vbox\bgroup\boxmaxdepth=2pt"
            r"\setbox1\vbox\bgroup\boxmaxdepth=1pt\hbox{\vrule depth5pt height1pt}"
            r"\egroup\message{[\the\ht1,\the\dp1,\the\boxmaxdepth]}"
            r"\hbox{\vrule depth5pt height1pt}\egroup"
            r"\message{[\the\ht0,\the\dp0,\the\boxmaxdepth]}")
    assert _messages(body) == ["[5.0pt,1.0pt,2.0pt]", "[4.0pt,2.0pt,9.0pt]"]


@pytest.mark.parametrize("template", [r"\hbox{#}", "{#}", r"\hbox{{#}}", r"{\hbox{#}}"])
@pytest.mark.parametrize(("setup", "row"), [
    (r"\def\endrow{\cr}", r"A&B\endrow C&D\cr"),
    (r"\def\endrow{\cr C}", r"A&B\endrow&D\cr"),
    (r"\let\stop=\cr\def\endrow{\stop}", r"A&B\endrow C&D\cr"),
])
def test_macro_row_end_closes_owning_text_template(template, setup, row) -> None:
    body = setup + r"\halign{" + template + "&" + template + r"\cr " + row + "}"
    dvi = _run(body)._dvi
    assert walk_chars_with_positions(dvi, _tfm_width())[0][:-1] == [
        (65, 0, 655360), (66, 491521, 655360),
        (67, 0, 1441792), (68, 491521, 1441792),
    ]


def test_u_template_definitions_govern_macro_row_end() -> None:
    body = (r"\def\endrow{Z}\halign{\hbox{\def\endrow{\csname cr\endcsname}#}"
            r"&\hbox{\def\endrow{\csname cr\endcsname}#}\cr A&B\endrow C&D\cr}"
            r"\message{[\endrow]}")
    assert _messages(body) == ["[Z]"]
    dvi = _run(body)._dvi
    assert walk_chars_with_positions(dvi, _tfm_width())[0][:-1] == [
        (65, 0, 655360), (66, 491521, 655360),
        (67, 0, 1441792), (68, 491521, 1441792),
    ]


def test_raw_body_waits_for_u_template_local_definition() -> None:
    body = (r"\def\word{Z}\halign{\hbox{\def\word{A}#}&\hbox{#}\cr "
            r"x\word&B\cr C&D\cr}\message{[\word]}")
    assert _messages(body) == ["[Z]"]
    assert [code for code, _ in _glyph_h(body)] == [120, 65, 66, 67, 68]


@pytest.mark.parametrize("template", [r"\hbox{#}", "{#}"])
def test_invalid_body_group_does_not_inject_template_close(template) -> None:
    interp = TeXInterpreter()
    body = (r"\def\endrow{\cr}\count200=7\halign{" + template
            + r"\cr A{\count200=9\aftergroup Q\endrow}B\cr}")
    with pytest.raises(EngineError):
        interp.run_with_device(StringInputSource(body), DviDevice())
    assert interp._alignment_cell_assembled_close == []
    assert interp._alignment_cell_vtemplate == []
    assert interp._alignment_cell_pushed_v == []


def test_macro_text_template_row_end_inside_vcenter_retains_math_owner() -> None:
    body = (r"\def\endrow{\cr}\noindent$x\vcenter{\halign{\hbox{#}&\hbox{#}\cr"
            r" A&B\endrow C&D\cr}}y$")
    dvi = _run(body)._dvi
    assert walk_chars_with_positions(dvi, _tfm_width())[0][:-1] == [
        (120, 0, 780970), (65, 374556, 447828), (66, 866077, 447828),
        (67, 374556, 1234260), (68, 866077, 1234260), (121, 1366700, 780970),
    ]


def test_nested_assembled_cell_restores_outer_boundary() -> None:
    body = (r"\def\endrow{\cr}\halign{\hbox{#}&\hbox{#}\cr A&"
            r"\vbox{\halign{\hbox{#}\cr B\endrow C\cr}}\endrow D&E\cr}")
    dvi = _run(body)._dvi
    assert walk_chars_with_positions(dvi, _tfm_width())[0][:-1] == [
        (65, 0, 1234260), (66, 500623, 447828), (67, 500623, 1234260),
        (68, 0, 2020692), (69, 500623, 2020692),
    ]
    interp = TeXInterpreter()
    interp.run_with_device(StringInputSource(body), DviDevice())
    assert interp._alignment_cell_assembled_close == []
    assert interp._alignment_cell_vtemplate == []


@pytest.mark.parametrize("body", [
    r"\begingroup\count200=9\aftergroup Q}",
    r"\count200=9\aftergroup Q\endgroup",
])
def test_mismatched_assembled_group_close_clears_cell_metadata(body) -> None:
    interp = TeXInterpreter()
    source = r"\count200=7\halign{\hbox{#}\cr " + body + r"\cr}"
    with pytest.raises(EngineError, match="cannot close"):
        interp.run_with_device(StringInputSource(source), DviDevice())
    assert interp._alignment_cell_assembled_close == []
    assert interp._alignment_cell_vtemplate == []
    assert interp._alignment_cell_pushed_v == []
