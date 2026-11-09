r"""box/group boundaries, measured with MiKTeX 24.4.

Expected values come from tex + tests._verification.dvi_walker on the
identical sources (a reference probe), with the folio excluded.
"""

import pytest

from aspose_tex import DviDevice, StringInputSource
from aspose_tex._engine.group import GroupKind
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex.exceptions import EngineError
from tests.test_plain_tie import _glyph_h, _messages


@pytest.mark.parametrize("wrapper", ["{}", r"\edef\x{{{}}}\message{{\x}}"])
def test_box_dimension_expansion(wrapper: str) -> None:
    values = r"[\the\wd1][\the\ht1][\the\dp1][\the\wd2][\the\ht2][\the\dp2]"
    body = r"\setbox1\hbox{oo}"
    body += r"\message{" + values + "}" if wrapper == "{}" else wrapper.format(values)
    assert _messages(body) == ["[10.27782pt][4.30554pt][0.0pt][0.0pt][0.0pt][0.0pt]"]


@pytest.mark.parametrize(
    ("body", "measured"),
    [
        (r"\noindent\hbox{a\begingroup b\endgroup c}", [(97, 0), (98, 327681), (99, 691771)]),
        (r"\noindent$\hbox{a\begingroup b\endgroup c}$", [(97, 0), (98, 327681), (99, 691771)]),
        (r"\halign{#\cr a\begingroup b\endgroup c\cr}", [(97, 0), (98, 327681), (99, 691771)]),
        (r"\noindent\hbox{o\begingroup{f}\begingroup i\endgroup\endgroup o}",
         [(111, 0), (102, 327681), (105, 527931), (111, 709976)]),
        (r"\noindent\hbox{a\begingroup\aftergroup b\endgroup c}",
         [(97, 0), (98, 327681), (99, 709976)]),
    ],
)
def test_semisimple_group_positions(body: str, measured: list) -> None:
    assert _glyph_h(body) == measured


def test_semisimple_group_restores_assignments() -> None:
    body = (r"\count0=7 \noindent\hbox{a\begingroup\count0=8 "
            r"\message{[\the\count0]}\endgroup\message{[\the\count0]}c}")
    assert _messages(body) == ["[8]", "[7]"]
    assert _glyph_h(body) == [(97, 0), (99, 327681)]


@pytest.mark.parametrize("body", [
    r"\begingroup\noindent\hbox{a\endgroup b}\endgroup",
    r"\noindent\hbox{a{\endgroup}b}",
    r"\noindent\hbox{a\begingroup b}",
])
def test_semisimple_group_rejects_wrong_owner(body: str) -> None:
    with pytest.raises(EngineError):
        _glyph_h(body)


@pytest.mark.parametrize("command", [
    r"\setbox0\hbox{}", r"\wd0=0pt ", r"\ht0=0pt ", r"\dp0=0pt ",
])
def test_cell_delegated_command_breaks_run(command: str) -> None:
    assert _glyph_h(r"\halign{#\cr o" + command + r"o\cr}") == [(111, 0), (111, 327681)]


@pytest.mark.parametrize("kind", ["vbox", "vtop"])
@pytest.mark.parametrize("wrapper", [r"\noindent {}", r"\halign{{#\cr {}\cr}}",
                                     r"\noindent\hbox\bgroup {}\egroup"])
def test_vertical_frame_restores_spacefactor(kind: str, wrapper: str) -> None:
    content = rf"x.\setbox0\{kind}\bgroup\noindent y\egroup{{}} o"
    assert _glyph_h(wrapper.format(content)) == [(120, 0), (46, 345886), (111, 819202)]


@pytest.mark.parametrize(
    ("content", "measured"),
    [
        (r"x\setbox0\hbox\bgroup y\egroup\box0", [(120, 0), (121, 345886)]),
        (r"x.\setbox0\hbox\bgroup y\egroup{} o", [(120, 0), (46, 345886), (111, 819202)]),
        (r"x.\setbox0\vbox\bgroup\noindent y\egroup{} o",
         [(120, 0), (46, 345886), (111, 819202)]),
        (r"x.\setbox0\vtop\bgroup\noindent y\egroup{} o",
         [(120, 0), (46, 345886), (111, 819202)]),
        (r"x\setbox0\hbox\bgroup a\setbox1\hbox\bgroup b\egroup\box1 c\egroup\box0 z",
         [(120, 0), (97, 345886), (98, 673567), (99, 1037657), (122, 1328928)]),
    ],
)
def test_eager_hbox_drains_deferred_frames(content: str, measured: list) -> None:
    assert _glyph_h(r"\noindent\hbox{" + content + "}") == measured


def test_eager_hbox_drains_macro_opened_frame() -> None:
    body = (r"\let\sb=\setbox\def\start{\sb0\hbox\bgroup}\def\stop{\egroup\box0}"
            r"\noindent\hbox{x\start y\stop z}")
    assert _glyph_h(body) == [(120, 0), (121, 345886), (122, 691772)]


@pytest.mark.parametrize("closing", ["}", r"\endgroup"])
@pytest.mark.parametrize("kind", ["hbox", "vbox", "vtop"])
def test_deferred_close_preserves_group_owners_on_rejection(closing: str, kind: str) -> None:
    """MiKTeX rejects mismatched closes; no save frame may be consumed first."""
    interp = TeXInterpreter()
    prefix = (r"\let\bgroup={\let\egroup=}\font\tenrm=cmr10\tenrm"
              r"\begingroup\count200=8 \noindent\hbox{x\setbox0")
    group = r"\begingroup" if closing == "}" else ""
    start = r"\noindent" if kind != "hbox" else ""
    body = (prefix + "\\" + kind + r"\bgroup" + start + group
            + r"\count200=9 \aftergroup Q y" + closing + r"\egroup\box0}\endgroup")
    with pytest.raises(EngineError, match="cannot close"):
        interp.run_with_device(StringInputSource(body), DviDevice())
    expected = [GroupKind.SEMI_SIMPLE, GroupKind.BRACE, GroupKind.BRACE]
    if closing == "}":
        expected.append(GroupKind.SEMI_SIMPLE)
    assert [frame.kind for frame in interp._group_stack._frames] == expected
    assert interp._register_set.get_count(200) == 9
    assert interp._box_regs.peekbox(0) is None
    assert len(interp._group_stack._frames[-1].aftergroup) == 1


def test_reviewed_deferred_brace_rejects_semisimple_close() -> None:
    # MiKTeX 24.4: exit 1, "Extra }, or forgotten \endgroup.", no page.
    with pytest.raises(EngineError, match="cannot close"):
        _glyph_h(r"\noindent\hbox{x\setbox0\hbox\bgroup\begingroup y}\egroup\box0}")


@pytest.mark.parametrize("content", [r"\begingroup{y}\endgroup", r"\begingroup\aftergroup y\endgroup"])
def test_deferred_matching_group_closes_continue_outer_hbox(content: str) -> None:
    body = r"\noindent\hbox{x\setbox0\hbox\bgroup" + content + r"\egroup\box0 z}"
    assert _glyph_h(body) == [(120, 0), (121, 345886), (122, 691772)]
