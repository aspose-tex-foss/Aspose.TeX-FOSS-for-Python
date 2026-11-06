r""" regressions with expected messages measured by MiKTeX 24.4."""

import warnings
from pathlib import Path

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob
from aspose_tex._engine.interpreter import ModeKind, TeXInterpreter
from aspose_tex.exceptions import EngineError
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _messages, _run, _tfm_width


@pytest.mark.parametrize("scope,expected", [("local", 2), ("global", 9), ("everydisplay", 2)])
def test_nested_display_math_preserves_parent_frame(scope, expected):
    prefix = r"\everydisplay{\count200=9}" if scope == "everydisplay" else ""
    assignment = {"local": r"\count200=9", "global": r"\global\count200=9", "everydisplay": ""}[scope]
    body = (r"\count200=2" + prefix + r"\noindent before $$" + assignment
            + r"\eqalign{a&=b\cr c&=d\cr}$$after"
            + r"\message{[global=\the\count200]}\message{[width=\the\baselineskip]}")
    assert _messages(body) == [f"[global={expected}]", "[width=12.0pt]"]


def test_display_family_prefix_matches_miktex_positions():
    root = Path(__file__).resolve().parents[1]
    source = (root / "testdata/e2e/combined_display_families.tex").read_text()
    job = _run(source)
    actual = walk_chars_with_positions(job._dvi, _tfm_width())[0]
    reference = walk_chars_with_positions(
        (root / "testdata/baselines/combined_display_families.miktex.dvi").read_bytes(),
        _tfm_width(),
    )[0]
    # Prefix ends before the separately tracked cases construct reader seam.
    for ours, measured in zip(actual[:80], reference[:80], strict=True):
        assert ours[0] == measured[0]
        assert abs(ours[1] - measured[1]) <= 1
        assert ours[2] == measured[2]


@pytest.mark.parametrize("breaks,lines,underfull", [(1, 2, 1), (2, 3, 2), (3, 4, 3)])
def test_forced_paragraph_endings(breaks, lines, underfull):
    body = (r"\hsize=25pt\noindent aa\hfil" + r"\break" * breaks
            + r"\par\message{[lines=\the\prevgraf]}\bye")
    job = TeXJob(StringInputSource(body), DviDevice())
    with warnings.catch_warnings(record=True) as diagnostics:
        warnings.simplefilter("always")
        job.run()
    assert [m for m in job.messages if m.startswith("[")] == [f"[lines={lines}]"]
    assert sum(r"Underfull \hbox" in str(w.message) for w in diagnostics) == underfull


@pytest.mark.parametrize("tail,lines,underfull", [
    (r"\penalty0", 3, 2), (r"\penalty-1", 3, 2),
    (r"\penalty10000", 2, 1), (r"\kern4pt", 2, 1),
    (r"\hskip4pt", 2, 1), (r"\hskip3pt\hskip4pt", 2, 1),
    (r"\penalty0 b", 2, 0),
])
def test_forced_ending_discard_run_keeps_ordinary_penalty_candidates(tail, lines, underfull):
    body = (r"\hsize=25pt\noindent aa\hfil\break" + tail
            + r"\par\message{[lines=\the\prevgraf]}\bye")
    job = TeXJob(StringInputSource(body), DviDevice())
    with warnings.catch_warnings(record=True) as diagnostics:
        warnings.simplefilter("always")
        job.run()
    assert [m for m in job.messages if m.startswith("[")] == [f"[lines={lines}]"]
    assert sum(r"Underfull \hbox" in str(w.message) for w in diagnostics) == underfull


@pytest.mark.parametrize("penalty", [0, -1, 10000])
def test_ordinary_ending_penalty_without_forced_break_keeps_one_line(penalty):
    body = (r"\hsize=25pt\noindent aa\penalty" + str(penalty)
            + r"\par\message{[lines=\the\prevgraf]}")
    assert _messages(body) == ["[lines=1]"]


@pytest.mark.parametrize(
    "opening,closing",
    [
        ("{", "}"),
        (r"\begingroup", r"\endgroup"),
        (r"\noindent$", "$"),
        ("$$", "$$"),
        (r"\setbox0\hbox{", "}"),
        (r"\setbox0\vbox{", "}"),
        (r"\setbox0\hbox\bgroup", r"\egroup"),
    ],
)
def test_aftergroup_expands_after_restoration(opening, closing):
    body = r"\def\x{\message{[after=\the\count200]}}\count200=2 " + opening + r"\count200=7\aftergroup\x a" + closing
    assert _messages(body) == ["[after=2]"]


def test_aftergroup_active_macro_order_and_nested_restoration():
    body = (
        r"\def~{\message{[active=\the\count200]}}"
        r"\def\x{\message{[macro=\the\count200]}}\count200=2 "
        r"{\count200=7 {\count200=9\aftergroup~\aftergroup\x}"
        r"\aftergroup~\aftergroup\x}"
    )
    assert _messages(body) == ["[active=7]", "[macro=7]", "[active=2]", "[macro=2]"]


def test_archived_raw_aftergroup_repro():
    job = _run(r"\def\x{\message{MARK:after=\the\count5}}\count5=2 $\count5=7\aftergroup\x a$")
    assert job.messages.count("MARK:after=2") == 1


def test_aftergroup_macro_meaning_is_restored_before_expansion():
    assert _messages(r"\def\x{\message{[outer]}}{\def\x{\message{[inner]}}\aftergroup\x}") == ["[outer]"]


@pytest.mark.parametrize(
    "body,expected",
    [
        ("{\\count200=1\\global\\count200=2 }\\message{[global=\\the\\count200]}", ["[global=2]"]),
        ("\\begingroup\\count200=1\\global\\count200=2 \\endgroup\\message{[global=\\the\\count200]}", ["[global=2]"]),
        ("\\noindent$\\count200=1\\global\\count200=2 $\\message{[global=\\the\\count200]}", ["[global=2]"]),
        ("$$\\count200=1\\global\\count200=2 $$\\message{[global=\\the\\count200]}", ["[global=2]"]),
        ("\\setbox0\\hbox{\\count200=1\\global\\count200=2 }\\message{[global=\\the\\count200]}", ["[global=2]"]),
        ("\\setbox0\\vbox{\\count200=1\\global\\count200=2 }\\message{[global=\\the\\count200]}", ["[global=2]"]),
        (
            "\\setbox0\\hbox\\bgroup\\count200=1\\global\\count200=2 \\egroup\\message{[global=\\the\\count200]}",
            ["[global=2]"],
        ),
        (
            r"\count200=0 {\count200=1 {\count200=3\global\count200=2\count200=4}"
            r"\message{[inner=\the\count200]}\count200=5}\message{[outer=\the\count200]}",
            ["[inner=2]", "[outer=2]"],
        ),
        ("\\count201=9 {\\dimen200=1pt\\global\\dimen200=2pt }\\message{[value=\\the\\dimen200]}", ["[value=2.0pt]"]),
        (
            "\\count201=9 {\\dimen200=1pt\\global\\dimen200=2pt \\dimen200=3pt}\\message{[value=\\the\\dimen200]}",
            ["[value=2.0pt]"],
        ),
        (
            "\\count201=9 {\\skip200=1pt\\global\\skip200=2pt plus1fil }\\message{[value=\\the\\skip200]}",
            ["[value=2.0pt plus 1.0fil]"],
        ),
        (
            "\\count201=9 {\\skip200=1pt\\global\\skip200=2pt plus1fil \\skip200=3pt}\\message{[value=\\the\\skip200]}",
            ["[value=2.0pt plus 1.0fil]"],
        ),
        (
            "\\count201=9 {\\muskip200=1mu\\global\\muskip200=2mu plus1fil }\\message{[value=\\the\\muskip200]}",
            ["[value=2.0mu plus 1.0fil]"],
        ),
        (
            r"\count201=9 {\muskip200=1mu\global\muskip200=2mu plus1fil \muskip200=3mu}"
            r"\message{[value=\the\muskip200]}",
            ["[value=2.0mu plus 1.0fil]"],
        ),
        ("\\count201=9 {\\toks200={one}\\global\\toks200={two} }\\message{[value=\\the\\toks200]}", ["[value=two]"]),
        (
            "\\count201=9 {\\toks200={one}\\global\\toks200={two} \\toks200={three}}\\message{[value=\\the\\toks200]}",
            ["[value=two]"],
        ),
        ("\\count201=9 {\\countdef\\zq=200\\global\\countdef\\zq=201 }\\message{[value=\\the\\zq]}", ["[value=9]"]),
        (
            r"\count201=9 {\countdef\zq=200\global\countdef\zq=201 \countdef\zq=202}"
            r"\message{[value=\the\zq]}",
            ["[value=9]"],
        ),
        ("\\count201=9 {\\chardef\\zq=1\\global\\chardef\\zq=2 }\\message{[value=\\number\\zq]}", ["[value=2]"]),
        (
            "\\count201=9 {\\chardef\\zq=1\\global\\chardef\\zq=2 \\chardef\\zq=3}\\message{[value=\\number\\zq]}",
            ["[value=2]"],
        ),
        ("\\count201=9 {\\catcode64=11\\global\\catcode64=10 }\\message{[value=\\the\\catcode64]}", ["[value=10]"]),
        (
            "\\count201=9 {\\catcode64=11\\global\\catcode64=10 \\catcode64=13}\\message{[value=\\the\\catcode64]}",
            ["[value=10]"],
        ),
        ("\\count201=9 {\\sfcode97=1001\\global\\sfcode97=1002 }\\message{[value=\\the\\sfcode97]}", ["[value=1002]"]),
        (
            "\\count201=9 {\\sfcode97=1001\\global\\sfcode97=1002 \\sfcode97=1003}\\message{[value=\\the\\sfcode97]}",
            ["[value=1002]"],
        ),
        ("\\count201=9 {\\lccode97=98\\global\\lccode97=99 }\\message{[value=\\the\\lccode97]}", ["[value=99]"]),
        (
            "\\count201=9 {\\lccode97=98\\global\\lccode97=99 \\lccode97=100}\\message{[value=\\the\\lccode97]}",
            ["[value=99]"],
        ),
        ("\\count201=9 {\\uccode97=98\\global\\uccode97=99 }\\message{[value=\\the\\uccode97]}", ["[value=99]"]),
        (
            "\\count201=9 {\\uccode97=98\\global\\uccode97=99 \\uccode97=100}\\message{[value=\\the\\uccode97]}",
            ["[value=99]"],
        ),
        ("\\count201=9 {\\mathcode97=1\\global\\mathcode97=2 }\\message{[value=\\the\\mathcode97]}", ["[value=2]"]),
        (
            "\\count201=9 {\\mathcode97=1\\global\\mathcode97=2 \\mathcode97=3}\\message{[value=\\the\\mathcode97]}",
            ["[value=2]"],
        ),
        ("\\count201=9 {\\delcode97=1\\global\\delcode97=2 }\\message{[value=\\the\\delcode97]}", ["[value=2]"]),
        (
            "\\count201=9 {\\delcode97=1\\global\\delcode97=2 \\delcode97=3}\\message{[value=\\the\\delcode97]}",
            ["[value=2]"],
        ),
        ("\\count201=9 {\\hsize=1pt\\global\\hsize=2pt }\\message{[value=\\the\\hsize]}", ["[value=2.0pt]"]),
        ("\\count201=9 {\\hsize=1pt\\global\\hsize=2pt \\hsize=3pt}\\message{[value=\\the\\hsize]}", ["[value=2.0pt]"]),
        (
            r"\count201=9 {\setbox200\hbox to1pt{}\global\setbox200\hbox to2pt{} }"
            r"\dimen200=\wd200 \message{[value=\the\dimen200]}",
            ["[value=2.0pt]"],
        ),
        (
            r"\count201=9 {\setbox200\hbox to1pt{}\global\setbox200\hbox to2pt{} "
            r"\setbox200\hbox to3pt{}}\dimen200=\wd200 \message{[value=\the\dimen200]}",
            ["[value=2.0pt]"],
        ),
    ],
)
def test_global_assignment_retention(body, expected):
    assert _messages(body) == expected


@pytest.mark.parametrize("command,first,global_value,last,expected", [
    ("hangindent", "1pt", "2pt", "3pt", "[0,2.0pt]"),
    ("hangafter", "1", "2", "3", "[0,2]"),
    ("parshape", "1 1pt 10pt", "2 1pt 10pt 2pt 11pt", "3 1pt 10pt 2pt 11pt 3pt 12pt", "[0,2]"),
])
def test_paragraph_shape_state_retention(command, first, global_value, last, expected):
    # The public readers see the live owners since D4.
    body = ("{\\" + command + "=" + first + " \\global\\" + command + "=" + global_value
            + " \\" + command + "=" + last + r" \count200=4}"
            + r"\message{[\the\count200," + "\\the\\" + command + "]}")
    assert _messages(body) == [expected]


@pytest.mark.parametrize("opening,body,closing", [
    ("$", r"\global\fam=1 a", "$"),
    ("$$", r"\global\fam=1 a", "$$"),
    ("{$", r"\global\fam=1\fam=2 a", "$}"),
    ("{$", r"\fam=2\hbox{$\global\fam=1 a$}b", "$}"),
])
def test_math_global_fam_survives_initialization_and_restoration(opening, body, closing):
    assert _messages(r"\fam=0 " + opening + body + closing + r"\message{[fam=\the\fam]}") == ["[fam=1]"]


@pytest.mark.parametrize("body,expected", [
    (r"$\edef\y{\the\fam}\message{[edef=\y]}a$", ["[edef=-1]"]),
    (r"\fam=0 $\ifmmode\message{[fam=\the\fam]}\else\message{[fam=wrong]}\fi a$", ["[fam=-1]"]),
    (r"\count200=2 $\global\count200=7 a$\message{[global=\the\count200]}", ["[global=7]"]),
    (r"$a$$b$\message{[adjacent=ok]}", ["[adjacent=ok]"]),
    (r"\let\dollar=$ \dollar\dollar a\dollar\dollar\message{[adjacent=ok]}", ["[adjacent=ok]"]),
    (r"\count200=2\def\x{\message{[peek=\the\count200]}}$\count200=7 a$\x", ["[peek=2]"]),
    (r"\mathsurround=0pt\setbox0\hbox{$\mathsurround=4pt a$}"
     r"\dimen200=\wd0\message{[width=\number\dimen200]}", ["[width=870704]"]),
    (r"\count200=2\setbox0\vbox{\halign{$# $\cr\count200=3\global\count200=7 a\cr}}"
     r"\message{[global=\the\count200]}", ["[global=7]"]),
])
def test_math_raw_opening_and_live_placement(body, expected):
    assert _messages(body) == expected


@pytest.mark.parametrize("box,close", [(r"\hbox{", "}"), (r"\hbox\bgroup", r"\egroup")])
def test_nested_math_preserves_parent_builder_and_aftergroup_order(box, close):
    body = (r"\def\x{\message{[after=\the\count200]}}\count200=2 $\left(\count200=7"
            + box + r"$\count200=9\aftergroup\x a$" + close + r"\aftergroup\x b\right)$")
    assert _messages(body) == ["[after=7]", "[after=2]"]


@pytest.mark.parametrize("dollar", ["$", "$$"])
def test_missing_font_deletion_restores_scope_and_emits_aftergroup_once(dollar):
    messages = []
    interp = TeXInterpreter(load_format=False, messages=messages)
    body = (r"\def\x{\message{[after=\the\count200]}}\count200=2 "
            + dollar + r"\count200=7\aftergroup\x a" + dollar + r"\message{[restored=\the\count200]}")
    interp.run_with_device(StringInputSource(body), DviDevice())
    assert messages == ["[after=2]", "[restored=2]"]
    assert interp._group_stack.depth == 0
    assert interp._math_builder is None
    assert interp._math_tail_depths == []


@pytest.mark.parametrize("content", [
    r"\left(a$",  # missing right before the close
    "a",  # missing dollar
    "{a$",  # child brace still open at dollar close
    r"\hbox{$\count200=8 a",  # missing nested dollar and box close
    r"\hbox\bgroup$\count200=8 a",  # deferred nested failure
])
@pytest.mark.parametrize("global_assignment,expected", [("", 5), (r"\global\count200=9", 9)])
def test_fatal_math_unwinds_owned_frames_without_popping_parent(content, global_assignment, expected):
    messages = []
    interp = TeXInterpreter(load_format="plain", messages=messages)
    body = (r"\def\x{\message{[aborted]}}{\count200=5 $\count200=7\aftergroup\x "
            + global_assignment + content)
    with pytest.raises(EngineError):
        interp.run_with_device(StringInputSource(body), DviDevice())
    assert "[aborted]" not in messages
    assert interp._group_stack.depth == 1
    assert interp._register_set.get_count(200) == expected
    assert interp._math_group_base is None
    assert interp._math_builder is None
    assert interp._math_tail_depths == []
    assert interp._math_shell._left_right_depth == 0
    assert interp._mode_stack.current == ModeKind.HORIZONTAL


@pytest.mark.parametrize("opening", ["$", "$$", r"$\hbox{$", r"$\hbox\bgroup$"])
@pytest.mark.parametrize("closing", [r"\endgroup", r"\endgroup\endgroup"])
@pytest.mark.parametrize("global_assignment,expected", [("", 5), (r"\global\count200=9", 9)])
def test_endgroup_cannot_pop_math_owner_or_emit_aborted_tokens(opening, closing, global_assignment, expected):
    messages = []
    interp = TeXInterpreter(load_format="plain", messages=messages)
    body = (r"\count200=2\def\x{\message{[aborted]}}{\count200=5 " + opening
            + r"\count200=7\aftergroup\x" + global_assignment + closing + " a$")
    with pytest.raises(EngineError, match="endgroup cannot close the active math group"):
        interp.run_with_device(StringInputSource(body), DviDevice())
    assert "[aborted]" not in messages
    assert interp._group_stack.depth == 1
    assert interp._register_set.get_count(200) == expected
    assert interp._math_group_base is None
    assert interp._math_builder is None
    assert interp._math_tail_depths == []
    assert interp._math_shell._left_right_depth == 0
    #: $$ has already contributed and popped the interrupted paragraph.
    expected_mode = ModeKind.OUTER_VERTICAL if opening == "$$" else ModeKind.HORIZONTAL
    assert interp._mode_stack.current == expected_mode
    if opening == "$$":
        assert interp._par_list is None
        assert interp._display_resume_paragraph is False
        assert interp._pending_display_prev_depth is None


@pytest.mark.parametrize("opening,closing", [
    ("$", "$"), ("$$", "$$"),
    (r"$\hbox{$", "$}a$"), (r"$\hbox\bgroup$", r"$\egroup a$"),
])
def test_explicit_nested_semisimple_group_remains_valid_in_math(opening, closing):
    body = (r"\count200=2\def\x{\message{[after=\the\count200]}}" + opening
            + r"\count200=7\begingroup\count200=8\aftergroup\x\endgroup a" + closing)
    assert _messages(body) == ["[after=7]"]
