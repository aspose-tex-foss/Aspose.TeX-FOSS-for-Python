r"""Tests for language whatsits and ``\setlanguage`` (§7, FR-7, AC-5).

Every expected list and message is MiKTeX 24.4 (``tex``, plain, nonstopmode,
2026-10-21), read from ``\showbox`` of the same material.  Lists are written
compactly: a letter is a ``\tenrm`` character, ``[ffi]`` a ligature with its
source characters, ``<L1 2,3>`` a language whatsit (``\setlanguage1
(hyphenmin 2,3)``), ``{pre|post|nobreak}`` a discretionary, ``[box:…]`` an
hbox; glue, kerns and penalties are left out.
"""
from __future__ import annotations

import warnings

import pytest

import aspose_tex._engine.interpreter as interpreter_module
from aspose_tex._engine.hyph_pass import HyphenationContext
from aspose_tex._engine.hyphenation import LanguageWhatsit
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode, DiscretionaryNode, HlistNode, WhatsitNode
from aspose_tex._input.reader import StringInputSource
from aspose_tex._output.pdf_writer import PdfWriter
from aspose_tex.presentation import DviDevice, PdfDevice, SvgDevice, TeXJob, TeXOptions

_PROBE_MACRO = (
    "\\def\\probe#1{\\setbox1\\vbox{\\hsize=\\maxdimen \\pretolerance=-1 \\tolerance=10000\n"
    "  \\parfillskip=0pt plus 1fil \\tenrm #1}}\n"
)


def _show(nodes) -> list[str]:
    out: list[str] = []
    for node in nodes:
        if isinstance(node, CharNode):
            out.append(f"[{''.join(map(chr, node.source))}]" if node.source else chr(node.char))
        elif isinstance(node, WhatsitNode) and isinstance(node.data, LanguageWhatsit):
            out.append(f"<L{node.data.language} {node.data.left_min},{node.data.right_min}>")
        elif isinstance(node, DiscretionaryNode):
            out.append("{" + " ".join(_show(node.pre)) + "|" + " ".join(_show(node.post))
                       + "|" + " ".join(_show(node.nobreak)) + "}")
        elif isinstance(node, HlistNode):
            out.append("[box:" + " ".join(_show(node.list)) + "]")
    return out


def _paragraphs(source: str, monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], list[str], list[str]]:
    """Run *source* under plain.

    Returns each paragraph's list as line breaking received it, each
    hyphenation result, and the job messages.
    """
    paragraphs: list[str] = []
    hyphenated: list[str] = []
    real_par = interpreter_module.exec_par
    real_hyph = interpreter_module.hyphenate_paragraph

    def spy_par(par_list, *args, **kwargs):
        paragraphs.append(" ".join(_show(par_list.nodes)))
        return real_par(par_list, *args, **kwargs)

    def spy_hyph(nodes: list, ctx: HyphenationContext) -> list:
        result = real_hyph(nodes, ctx)
        hyphenated.append(" ".join(_show(result)))
        return result

    monkeypatch.setattr(interpreter_module, "exec_par", spy_par)
    monkeypatch.setattr(interpreter_module, "hyphenate_paragraph", spy_hyph)
    messages: list[str] = []
    interp = TeXInterpreter(load_format="plain", messages=messages)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(StringInputSource(source), DviDevice())
    return paragraphs, hyphenated, messages


class TestWhatsitProducers:
    """§1034/§1376 ``fix_language`` and §1377 ``\\setlanguage`` build MiKTeX's lists."""

    def test_p4_restricted_hbox_records_no_language_change(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r"""P4: ``\setbox2\hbox{\language=1 x}`` shows ``\tenrm x`` only."""
        paragraphs, _, _ = _paragraphs(
            "\\setbox2\\hbox{\\language=1 x}\\noindent\\box2\\par\\bye\n", monkeypatch)
        assert paragraphs == ["[box:x]"]

    def test_setlanguage_in_restricted_hbox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r"""``\hbox{\setlanguage5 x\language=1 y}``: ``\setlanguage5 (hyphenmin 2,3)``, x, y."""
        paragraphs, _, _ = _paragraphs(
            "\\setbox2\\hbox{\\setlanguage5 x\\language=1 y}\\noindent\\box2\\par\\bye\n", monkeypatch)
        assert paragraphs == ["[box:<L5 2,3> x y]"]

    def test_p5_paragraph_sequence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r"""P5: ``a\language=1 b\setlanguage5 c`` gives whatsits 1, 5, 1."""
        paragraphs, _, _ = _paragraphs(
            _PROBE_MACRO + "\\probe{\\noindent a\\language=1 b\\setlanguage5 c}\\bye\n", monkeypatch)
        assert paragraphs == ["a <L1 2,3> b <L5 2,3> <L1 2,3> c"]

    def test_language_numbers_outside_1_to_255_become_0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r"""``\hbox{\setlanguage300 x}`` shows ``\setlanguage0 (hyphenmin 2,3)``."""
        paragraphs, _, _ = _paragraphs(
            "\\setbox2\\hbox{\\setlanguage300 x}\\noindent\\box2\\par\\bye\n", monkeypatch)
        assert paragraphs == ["[box:<L0 2,3> x]"]

    def test_unchanged_language_inserts_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r"""``\language=1 \language=0`` between two characters leaves no whatsit."""
        paragraphs, _, _ = _paragraphs(
            _PROBE_MACRO + "\\probe{\\noindent a\\language=1 \\language=0 b}\\bye\n", monkeypatch)
        assert paragraphs == ["a b"]

    def test_display_resume_records_the_language_anew(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r"""§1200: after ``a\language=1 b$$ $$`` the resumed paragraph starts in language 1.

        MiKTeX: ``a \setlanguage1 b`` before the display, ``c \setlanguage0 d``
        after it for ``c\language=0 d``.
        """
        paragraphs, _, _ = _paragraphs(
            _PROBE_MACRO + "\\probe{\\noindent a\\language=1 b$$ $$c\\language=0 d}\\bye\n", monkeypatch)
        assert paragraphs == ["a <L1 2,3> b", "c <L0 2,3> d"]


class TestIllegalModes:
    """§1377 ``report_illegal_case``: the message, and the number stays in the input."""

    @pytest.mark.parametrize(("source", "message"), [
        ("\\setlanguage7 \\par", "! You can't use `\\setlanguage' in vertical mode."),
        ("\\setbox0\\vbox{\\setlanguage7}", "! You can't use `\\setlanguage' in internal vertical mode."),
        ("\\noindent$\\setlanguage7 x$\\par", "! You can't use `\\setlanguage' in math mode."),
        ("\\noindent x$$\\setlanguage7 $$\\par", "! You can't use `\\setlanguage' in display math mode."),
    ], ids=["vertical", "internal-vertical", "math", "display-math"])
    def test_message(self, monkeypatch: pytest.MonkeyPatch, source: str, message: str) -> None:
        _, _, messages = _paragraphs(source + "\\bye\n", monkeypatch)
        assert messages[-1] == message

    def test_number_is_not_scanned_in_vertical_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r"""MiKTeX typesets the ``7`` after ``\setlanguage`` in vertical mode."""
        paragraphs, _, _ = _paragraphs("\\noindent\\setlanguage7\\par\\setlanguage7\\par\\bye\n",
                                       monkeypatch)
        assert paragraphs == ["<L7 2,3>", "[box:] 7"]


class TestHyphenationFollowsWhatsits:
    """ AC-5: each case is MiKTeX's ``\\showbox`` of the probe body."""

    _DIFFICULTIES = "d i {f -|[fi]|[ffi]} {-||} c u l {-||} t i e s"
    _PLAIN = "d i [ffi] c u l t i e s"

    def test_language_without_patterns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, hyphenated, _ = _paragraphs(
            _PROBE_MACRO + "\\probe{\\language=2 \\noindent\\hskip0pt teapot difficulties}\\bye\n",
            monkeypatch)
        assert hyphenated == ["t e a p o t " + self._PLAIN]

    def test_mid_paragraph_language_change(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, hyphenated, _ = _paragraphs(
            _PROBE_MACRO + "\\probe{\\noindent\\hskip0pt difficulties \\language=1 difficulties "
            "\\language=0 difficulties}\\bye\n", monkeypatch)
        assert hyphenated == [f"{self._DIFFICULTIES} <L1 2,3> {self._PLAIN} <L0 2,3> {self._DIFFICULTIES}"]

    def test_setlanguage_lasts_until_the_next_character(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r"""``\setlanguage1`` is undone by ``fix_language`` at once, as ``\language`` is still 0."""
        _, hyphenated, _ = _paragraphs(
            _PROBE_MACRO + "\\probe{\\noindent\\hskip0pt difficulties \\setlanguage1 difficulties "
            "difficulties}\\bye\n", monkeypatch)
        assert hyphenated == [f"{self._DIFFICULTIES} <L1 2,3> <L0 2,3> {self._DIFFICULTIES} "
                              f"{self._DIFFICULTIES}"]

    def test_minima_carried_by_a_whatsit_apply_to_following_words(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, hyphenated, _ = _paragraphs(
            _PROBE_MACRO + "\\probe{\\noindent\\hskip0pt difficulties \\lefthyphenmin=4 "
            "\\righthyphenmin=4 \\setlanguage0 difficulties}\\bye\n", monkeypatch)
        assert hyphenated == [f"{self._DIFFICULTIES} <L0 4,4> d i [ffi] {{-||}} c u l {{-||}} t i e s"]


class TestOutput:
    """Language whatsits change no output byte and raise no warning."""

    @pytest.mark.parametrize("device", [DviDevice, PdfDevice, SvgDevice], ids=["dvi", "pdf", "svg"])
    def test_bytes_unchanged_and_no_warning(self, device, monkeypatch: pytest.MonkeyPatch) -> None:
        # The PDF /CreationDate (and the /ID derived from it) follows the clock.
        monkeypatch.setattr(PdfWriter, "_now_pdf_date", lambda self: b"D:20260101000000Z")

        def run(body: str) -> tuple[bytes, list[str]]:
            job = TeXJob(StringInputSource(body + "\\bye\n"), device(), options=TeXOptions())
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                data = job.run()
            return data, [str(w.message) for w in caught]

        with_whatsits, caught = run("\\noindent a\\language=1 b\\setlanguage5 c\\par")
        without, _ = run("\\noindent a\\relax b\\relax c\\par")
        assert with_whatsits == without
        assert caught == []
