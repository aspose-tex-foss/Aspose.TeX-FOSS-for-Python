""" active-character dispatch tests."""
from __future__ import annotations

import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice


class _CaptureParagraphInterpreter(TeXInterpreter):
    def __init__(self) -> None:
        super().__init__()
        self.captured_paragraphs: list[list] = []

    def _end_paragraph(self) -> None:
        if self._par_list is not None:
            self.captured_paragraphs.append(self._par_list.nodes)
        super()._end_paragraph()


def _run_capture(tex: str) -> _CaptureParagraphInterpreter:
    interp = _CaptureParagraphInterpreter()
    interp.run_with_device(StringInputSource(tex), DviDevice())
    return interp


def _paragraph_text(interp: _CaptureParagraphInterpreter, idx: int = 0) -> str:
    return "".join(
        chr(node.char)
        for node in interp.captured_paragraphs[idx]
        if isinstance(node, CharNode)
    )


class TestActiveCharBasic:
    def test_active_char_macro_dispatches(self) -> None:
        interp = _run_capture(r"\catcode`\~=13 \def~{X}\noindent~\par\bye")

        assert _paragraph_text(interp) == "X"

    def test_default_catcode_stays_non_active(self) -> None:
        interp = _run_capture(r"\noindent!\par\bye")

        assert _paragraph_text(interp) == "!"


class TestActiveCharCharLet:
    def test_active_char_let_to_control_sequence_dispatches(self) -> None:
        interp = _run_capture(r"\catcode`\~=13 \let~=\par \noindent a~\noindent b\par\bye")

        assert _paragraph_text(interp, 0) == "a"
        assert _paragraph_text(interp, 1) == "b"


class TestActiveCharUndefined:
    def test_undefined_active_char_raises(self) -> None:
        with pytest.raises(EngineError, match="Undefined active character: !"):
            _run_capture(r"\catcode`\!=13 \noindent!\bye")


class TestActiveCharGroupScope:
    def test_active_char_definition_restores_with_group(self) -> None:
        interp = _run_capture(r"{\catcode`\!=13 \def!{X}}\noindent!\par\bye")

        assert _paragraph_text(interp) == "!"


# ---------------------------------------------------------------------------
# own key space, expanded by the expander (plain format).
# Every expected line is MiKTeX 24.4 plain \message output of the same input.
# ---------------------------------------------------------------------------

_ACTIVE = r"\catcode`\!=13 "
_WIDTH = r"\dimen0=\wd0 \message{[\the\dimen0]}"


def _plain_messages(body: str) -> list[str]:
    import warnings

    from aspose_tex import TeXJob, TeXOptions

    job = TeXJob(StringInputSource(_ACTIVE + body + r"\bye"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job.run()
    return [m for m in job.messages if m.startswith("[")]


class TestActiveCharOwnKey:
    r"""An active char and the control symbol of the same char are distinct (§222)."""

    @pytest.mark.parametrize(
        "defs",
        [r"\def!{X}\def\!{Z}", r"\def\!{Z}\def!{X}"],
    )
    def test_active_char_and_control_symbol_are_independent(self, defs: str) -> None:
        # ! typesets X (7.50002pt) whichever is defined last; \! stays Z
        assert _plain_messages(defs + r"\setbox0\hbox{!}" + _WIDTH + r"\message{[\meaning\!]}") == [
            "[7.50002pt]", "[macro:->Z]",
        ]

    def test_local_definition_is_restored_after_group(self) -> None:
        assert _plain_messages(r"\def!{X}{\def!{i}}\setbox0\hbox{!}" + _WIDTH) == ["[7.50002pt]"]

    def test_global_definition_survives_group(self) -> None:
        assert _plain_messages(r"\def!{X}{\gdef!{i}}\setbox0\hbox{!}" + _WIDTH) == ["[2.77779pt]"]


class TestActiveCharExpandedByExpander:
    """The expander expands active chars wherever TeX does (§358)."""

    def test_inside_a_box(self) -> None:
        assert _plain_messages(r"\def!{X}\setbox0\hbox{o!o}" + _WIDTH) == ["[17.50005pt]"]

    def test_arguments_are_scanned(self) -> None:
        assert _plain_messages(r"\def!#1{[#1]}\setbox0\hbox{o!ab}" + _WIDTH) == ["[21.11118pt]"]

    def test_in_edef(self) -> None:
        assert _plain_messages(r"\def!{X}\edef\a{!}\message{[\meaning\a]}") == ["[macro:->X]"]

    def test_in_message(self) -> None:
        assert _plain_messages(r"\def!{X}\message{[!]}") == ["[X]"]

    def test_let_copies_the_current_meaning(self) -> None:
        assert _plain_messages(r"\def!{X}\let\c=!\def!{Y}\message{[\meaning\c]}") == ["[macro:->X]"]


class TestActiveCharMeaning:
    r"""``\meaning`` and ``\ifx`` look an active char up like a control sequence (§296, §507).

    expected lines are MiKTeX 24.4 plain output.
    """

    def test_meaning_of_a_macro(self) -> None:
        assert _plain_messages(r"\def!{X}\message{[\meaning!]}") == ["[macro:->X]"]

    def test_meaning_of_plain_tie(self) -> None:
        # A control word is printed with a space after it (§262).
        assert _plain_messages(r"\message{[\meaning~]}") == [r"[macro:->\penalty \@M \ ]"]

    def test_undefined_is_undefined(self) -> None:
        assert _plain_messages(r"\catcode`\?=13 \message{[\meaning?]}") == ["[undefined]"]

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            (r"\let!=a \message{[\meaning!]}", "[the letter a]"),
            (r"\let!=\relax \message{[\meaning!]}", r"[\relax]"),
            (r"\let!=! \message{[\meaning!]}", "[undefined]"),
        ],
        ids=["let-letter", "let-primitive", "let-itself-undefined"],
    )
    def test_meaning_of_a_let(self, body: str, expected: str) -> None:
        assert _plain_messages(body) == [expected]

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            (r"\def!{X}\def\b{X}\message{[\ifx!\b T\else F\fi]}", "[T]"),
            (r"\def!{X}\def\b{X}\message{[\ifx\b!T\else F\fi]}", "[T]"),
            (r"\catcode`\?=13 \def!{X}\def?{X}\message{[\ifx!?T\else F\fi]}", "[T]"),
            (r"\catcode`\?=13 \def!{X}\def?{Y}\message{[\ifx!?T\else F\fi]}", "[F]"),
            (r"\catcode`\?=13 \message{[\ifx?\undefinedqq T\else F\fi]}", "[T]"),
            (r"\let!=a \message{[\ifx!a T\else F\fi]}", "[ T]"),
            (r"\let!=\relax \message{[\ifx!\relax T\else F\fi]}", "[T]"),
            (r"\def!{X}\message{[\expandafter\ifx\string!!T\else F\fi]}", "[F]"),
            (r"\def!{X}\let\c=! \message{[\ifx\c!T\else F\fi]}", "[T]"),
        ],
        ids=["macro-vs-cs", "cs-vs-macro", "two-active", "two-active-differ",
             "undefined", "let-letter", "let-primitive", "other-catcode", "let-copy"],
    )
    def test_ifx(self, body: str, expected: str) -> None:
        assert _plain_messages(body) == [expected]

    def test_futurelet_copies_the_active_meaning(self) -> None:
        assert _plain_messages(
            r"\def!{X}\def\t{\message{[\meaning\next][\ifx!\next T\else F\fi]}}\futurelet\next\t!"
        ) == ["[macro:->X][T]"]

    @pytest.mark.parametrize(
        "body",
        [
            r"\setbox0\hbox{\def!{X}\message{[\meaning!]}}",
            r"\def!{X}\edef\r{\meaning!}\message{[\r]}",
            r"$\def!{X}\message{[\meaning!]}$",
        ],
        ids=["hbox", "edef", "math"],
    )
    def test_other_contexts(self, body: str) -> None:
        assert _plain_messages(body) == ["[macro:->X]"]


class TestControlSequenceMeaningUndefined:
    """A control sequence without any meaning prints ``undefined`` (§296)."""

    @pytest.mark.parametrize(
        "body",
        [
            r"\message{[\meaning\zzqa]}",
            r"{\def\zzm{1}}\message{[\meaning\zzm]}",
            r"\let\x=\zzqa \message{[\meaning\x]}",
            r"{\csname zzq\endcsname}\message{[\meaning\zzq]}",
        ],
        ids=["never-defined", "group-ended", "let-to-undefined", "csname-group-ended"],
    )
    def test_undefined(self, body: str) -> None:
        assert _plain_messages(body) == ["[undefined]"]

    def test_primitives_keep_their_name(self) -> None:
        assert _plain_messages(
            r"\message{[\meaning\relax][\meaning\count][\meaning\hsize][\meaning\over]"
            r"[\meaning\endcsname][\meaning\pagegoal]}"
        ) == [r"[\relax][\count][\hsize][\over][\endcsname][\pagegoal]"]
