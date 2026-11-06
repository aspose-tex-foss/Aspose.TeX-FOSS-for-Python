r"""Tests for the hyphenation step of the second pass (§4-§6,).

Every expected node sequence is MiKTeX 24.4 (``tex``, plain, nonstopmode,
2026-10-21): each probe body ran as

    \setbox1\vbox{\hsize=\maxdimen \pretolerance=-1 \tolerance=10000
      \parfillskip=0pt plus 1fil \tenrm \global\hyphenchar\tenrm=`- <body>}
    \showbox1

and the ``\showbox`` line is written here in a compact notation: a letter is
a ``\tenrm`` character, ``[14/ffi]`` a ligature with its source characters,
``<k-0.27779>`` a kern in pt, ``{pre|post|nobreak}`` a discretionary,
``[box]``/``[rule]`` a box/rule, ``font:code`` a character of another font;
glue and the paragraph-end penalties are left out.
"""
from __future__ import annotations

import warnings

import pytest

import aspose_tex._engine.interpreter as interpreter_module
from aspose_tex._engine.hyph_pass import HyphenationContext, hyphenate_paragraph
from aspose_tex._engine.hyphenation import HyphenationStore, LanguageWhatsit
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.linebreak import LinebreakParams, break_paragraph
from aspose_tex._engine.nodes import (
    CharNode,
    DiscretionaryNode,
    GlueNode,
    HlistNode,
    KernNode,
    LeadersNode,
    MathNode,
    PenaltyNode,
    RuleNode,
    WhatsitNode,
)
from aspose_tex._engine.par_primitives import ParagraphList
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice
from tests._font_keys import font_key

_PROBE_MACRO = (
    "\\def\\probe#1{\\setbox1\\vbox{\\hsize=\\maxdimen \\pretolerance=-1 \\tolerance=10000\n"
    "  \\parfillskip=0pt plus 1fil \\tenrm \\global\\hyphenchar\\tenrm=`- #1}}\n"
)

# (name, body, MiKTeX's line). Bodies start with \noindent\hskip0pt so the
# word follows a glue node, the only place TeX tries a word (§866).
_PROBES: list[tuple[str, str, str]] = [
    # P2: the disc around ffi/ffl, the next disc after the ligature,
    # the n-t kern kept.
    ("p2", r"\noindent\hskip0pt difficulties affluent office",
     "d i {f -|[12/fi]|[14/ffi]} {-||} c u l {-||} t i e s "
     "a {f -|[13/fl]|[15/ffl]} u {-||} e n <k-0.27779> t "
     "o {f -|[12/fi]|[14/ffi]} c e"),
    # §866: only a word after glue is tried, so not the first after the indent.
    ("first-word", r"\indent difficulties difficulties",
     "[box] d i [14/ffi] c u l t i e s d i {f -|[12/fi]|[14/ffi]} {-||} c u l {-||} t i e s"),
    # §896: a non-letter prefix is skipped; a same-font one is hu[0] (§903).
    ("paren", r"\noindent\hskip0pt (difficulties)",
     "( d i {f -|[12/fi]|[14/ffi]} {-||} c u l {-||} t i e s )"),
    ("quotes", r"\noindent\hskip0pt ``difficulties''",
     "[92/``] d i {f -|[12/fi]|[14/ffi]} {-||} c u l {-||} t i e s [34/'']"),
    # §896: an uppercase start needs \uchyph > 0.
    ("uchyph-1", r"\noindent\hskip0pt Difficulties",
     "D i {f -|[12/fi]|[14/ffi]} {-||} c u l {-||} t i e s"),
    ("uchyph-0", r"\uchyph=0 \noindent\hskip0pt Difficulties",
     "D i [14/ffi] c u l t i e s"),
    # §897: one font across the word; a same-font group does not split it.
    ("mixed-font", r"\noindent\hskip0pt diffi{\it culties} difficul{\tenrm ties}",
     "d i [14/ffi] tenit:99 tenit:117 tenit:108 tenit:116 tenit:105 tenit:101 tenit:115 "
     "d i {f -|[12/fi]|[14/ffi]} {-||} c u l {-||} t i e s"),
    # §899: box, rule, math and discretionary reject; penalty, explicit kern
    # and a same-font character accept.
    ("followers",
     r"\noindent\hskip0pt difficulties\hbox{} difficulties\vrule\ difficulties$x$ "
     r"difficulties\- difficulties\penalty0 difficulties\kern1pt\ difficulties.",
     "d i [14/ffi] c u l t i e s [box] d i [14/ffi] c u l t i e s [rule] "
     "d i [14/ffi] c u l t i e s mathon teni:120 mathoff d i [14/ffi] c u l t i e s {-||} "
     "d i {f -|[12/fi]|[14/ffi]} {-||} c u l {-||} t i e s <p0> "
     "d i [14/ffi] c u l t i e s <k1.0> d i {f -|[12/fi]|[14/ffi]} {-||} c u l {-||} t i e s ."),
    # done2: \hyphenchar outside 0..255 leaves the word alone.
    ("hyphenchar-neg", r"\hyphenchar\tenrm=-1 \noindent\hskip0pt difficulties",
     "d i [14/ffi] c u l t i e s"),
    ("hyphenchar-256", r"\hyphenchar\tenrm=256 \noindent\hskip0pt difficulties",
     "d i [14/ffi] c u l t i e s"),
    # §866: no word is tried inside a formula.
    ("math", r"\noindent\hskip0pt $\hbox{}\ \rm difficulties$",
     "mathon [box] d i tenrm:14 c u l t i e s mathoff"),
    # §897: a word is cut at 63 letters; only those are hyphenated.
    ("cap-63",
     r"\noindent\hskip0pt difficultiesdifficultiesdifficultiesdifficulties"
     r"difficultiesdifficultiesdiff",
     " ".join(["d i {f -|[12/fi]|[14/ffi]} {-||} c u l {-||} t i e s {-||}"]
              + ["d {-||} i {f -|[12/fi]|[14/ffi]} {-||} c u l {-||} t i e s {-||}"] * 3
              + ["d {-||} i {f -|[12/fi]|[14/ffi]} {-||} c u l {-||} t i e s",
                 "d i [14/ffi] c u l t i e s d i [11/ff]"])),
    # §909: a font kern at a hyphen position becomes the replaced material.
    ("kern-at-break", r"\noindent\hskip0pt environmental",
     "e {n -||n <k-0.27779>} v i {-||} r o n {-||} m e {n -||n <k-0.27779>} t a l"),
    # §915: the hyphen character kerns with the letter before it (o-y).
    ("hyphen-kern", r"\hyphenchar\tenrm=`y \hyphenation{co-vo-vo}\noindent\hskip0pt covovo",
     "c {o <k-0.27779> y||o <k-0.27779>} v <k-0.27779> o <k-0.27779> v <k-0.27779> o"),
    # TeX's leaders are glue nodes: the word after them is tried.
    ("after-leaders", r"\noindent\leaders\hrule\hskip1pt difficulties",
     "d i {f -|[12/fi]|[14/ffi]} {-||} c u l {-||} t i e s"),
    # §896: a font kern in the prefix is skipped, an explicit one stops it.
    ("prefix-explicit-kern", r"\noindent\hskip0pt\kern1pt difficulties",
     "<k1.0> d i [14/ffi] c u l t i e s"),
    # §1091: the minima recorded at the paragraph start apply.
    ("minima", r"\lefthyphenmin=4 \righthyphenmin=4 \noindent\hskip0pt difficulties",
     "d i [14/ffi] {-||} c u l {-||} t i e s"),
    # AC-4: exceptions of language 1, and a language with no data.
    ("language-1", r"\language=1 \hyphenation{tea-pot}\noindent\hskip0pt teapot",
     "t e a {-||} p <k0.27779> o t"),
    ("language-empty", r"\language=2 \noindent\hskip0pt teapot difficulties",
     "t e a p <k0.27779> o t d i [14/ffi] c u l t i e s"),
    ("language-1-patterns", r"\language=1 \noindent\hskip0pt difficulties",
     "d i [14/ffi] c u l t i e s"),
]


def _show(nodes) -> list[str]:
    out: list[str] = []
    for node in nodes:
        if isinstance(node, CharNode):
            if node.source:
                out.append(f"[{node.char}/{''.join(map(chr, node.source))}]")
            elif node.font_name in ("tenrm", font_key("tenrm", plain=True)) and 32 < node.char < 127:
                out.append(chr(node.char))
            else:
                name = next((n for n in ("tenit", "teni", "tenrm")
                             if node.font_name == font_key(n, plain=True)), node.font_name)
                out.append(f"{name}:{node.char}")
        elif isinstance(node, DiscretionaryNode):
            out.append("{" + " ".join(_show(node.pre)) + "|" + " ".join(_show(node.post))
                       + "|" + " ".join(_show(node.nobreak)) + "}")
        elif isinstance(node, KernNode):
            out.append(f"<k{round(node.width / 65536, 5)}>")
        elif isinstance(node, PenaltyNode):
            if abs(node.penalty) != 10000:
                out.append(f"<p{node.penalty}>")
        elif isinstance(node, HlistNode):
            out.append("[box]")
        elif isinstance(node, RuleNode):
            out.append("[rule]")
        elif isinstance(node, MathNode):
            out.append("mathoff" if node.after else "mathon")
        elif not isinstance(node, (GlueNode, LeadersNode)):
            out.append(type(node).__name__)
    return out


def _run_plain(source: str, monkeypatch: pytest.MonkeyPatch) -> tuple[TeXInterpreter, list]:
    """Run *source* under plain; return the interpreter and each hyphenation result."""
    calls: list = []
    real = interpreter_module.hyphenate_paragraph

    def spy(nodes: list, ctx: HyphenationContext) -> list:
        result = real(nodes, ctx)
        calls.append((nodes, result))
        return result

    monkeypatch.setattr(interpreter_module, "hyphenate_paragraph", spy)
    interp = TeXInterpreter(load_format="plain", messages=[])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(StringInputSource(source), DviDevice())
    return interp, calls


@pytest.fixture(scope="module")
def probe_results() -> dict[str, str]:
    """One plain job running every probe; each enters the second pass once."""
    monkeypatch = pytest.MonkeyPatch()
    try:
        source = _PROBE_MACRO + "".join(f"\\probe{{{body}}}\n" for _, body, _ in _PROBES) + "\\bye\n"
        _, calls = _run_plain(source, monkeypatch)
    finally:
        monkeypatch.undo()
    assert len(calls) == len(_PROBES)
    return {name: " ".join(_show(result)) for (name, _, _), (_, result) in zip(_PROBES, calls, strict=True)}


class TestMiKTeXStructures:
    """§894-§918 eligibility and reconstitution against MiKTeX's ``\\showbox``."""

    @pytest.mark.parametrize(("name", "expected"), [(n, e) for n, _, e in _PROBES],
                             ids=[n for n, _, _ in _PROBES])
    def test_probe_matches_miktex(self, probe_results: dict[str, str], name: str,
                                  expected: str) -> None:
        assert probe_results[name] == expected

    def test_display_resume_records_the_language(self, monkeypatch: pytest.MonkeyPatch) -> None:
        r"""§1200 records the language anew when the paragraph resumes after a display.

        MiKTeX: ``\language=1 \hyphenation{pro-ject}\language=0`` then, in the
        probe box, ``\noindent\hskip0pt project $$\global\language=1 $$
        \hskip0pt project``: the first line keeps ``p r o <k0.55554> j e c t``
        (Knuth's exception), the resumed one breaks as
        ``p r {o -||o <k0.55554>} j e c t``.
        """
        source = (_PROBE_MACRO + "\\language=1 \\hyphenation{pro-ject}\\language=0\n"
                  "\\probe{\\noindent\\hskip0pt project $$\\global\\language=1 $$ \\hskip0pt project}\n"
                  "\\bye\n")
        _, calls = _run_plain(source, monkeypatch)
        assert [" ".join(_show(result)) for _, result in calls] == [
            "p r o <k0.55554> j e c t",
            "p r {o -||o <k0.55554>} j e c t",
        ]


def _context(store: HyphenationStore, interp: TeXInterpreter, **overrides) -> HyphenationContext:
    fields = dict(store=store, font_manager=interp._font_manager,
                  lccode=interp._code_arrays.get_lccode, uchyph=1, language=0,
                  left_min=2, right_min=3, missing_character=lambda font, code: None)
    fields.update(overrides)
    return HyphenationContext(**fields)


@pytest.fixture(scope="module")
def plain_interp() -> TeXInterpreter:
    interp = TeXInterpreter(load_format="plain", messages=[])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(StringInputSource("\\relax"), DviDevice())
    return interp


def _word(text: str, font: str = "tenrm") -> list:
    return [CharNode(char=ord(c), font_name=font) for c in text]


_SPACE = GlueNode(glue=Glue(218453, 109226, GlueOrder.NORMAL, 72818, GlueOrder.NORMAL))


class TestHyphenateParagraph:
    """``hyphenate_paragraph`` contract on hand-built lists."""

    def test_input_untouched_and_other_nodes_shared(self, plain_interp: TeXInterpreter) -> None:
        nodes = [*_word("xx"), _SPACE, *_word("table"), _SPACE, *_word("yy")]
        before = list(nodes)
        result = hyphenate_paragraph(nodes, _context(plain_interp._hyphenation, plain_interp))
        assert nodes == before
        assert _show(result) == ["x", "x", "t", "a", "{-||}", "b", "l", "e", "y", "y"]
        assert result[0] is nodes[0] and result[2] is nodes[2] and result[-1] is nodes[-1]

    def test_nothing_to_hyphenate_returns_an_equal_copy(self, plain_interp: TeXInterpreter) -> None:
        nodes = [*_word("ab"), _SPACE, *_word("cd")]
        result = hyphenate_paragraph(nodes, _context(plain_interp._hyphenation, plain_interp))
        assert result == nodes and result is not nodes

    def test_language_whatsit_switches_language_and_minima(self, plain_interp: TeXInterpreter) -> None:
        store = HyphenationStore()
        store.add_exception(1, tuple(map(ord, "table")), frozenset({2}))
        switch = WhatsitNode(data=LanguageWhatsit(language=1, left_min=1, right_min=1))
        nodes = [*_word("x"), _SPACE, *_word("table"), switch, _SPACE, *_word("table"),
                 _SPACE, switch, *_word("table")]
        result = hyphenate_paragraph(nodes, _context(store, plain_interp))
        assert " ".join(_show(result)) == (
            "x t a b l e WhatsitNode t a {-||} b l e WhatsitNode t a {-||} b l e"
        )

    def test_missing_hyphen_glyph_is_reported_and_omitted(self, plain_interp: TeXInterpreter) -> None:
        missing: list[tuple[str, int]] = []
        fm = plain_interp._font_manager
        fm.set_hyphenchar("tenrm", 200)
        try:
            result = hyphenate_paragraph(
                [*_word("x"), _SPACE, *_word("table")],
                _context(plain_interp._hyphenation, plain_interp,
                         missing_character=lambda font, code: missing.append((font, code))),
            )
        finally:
            fm.set_hyphenchar("tenrm", ord("-"))
        assert _show(result) == ["x", "t", "a", "{||}", "b", "l", "e"]
        assert missing == [("tenrm", 200)]


class TestCharNodeSource:
    """§4: ligatures keep their source characters."""

    def test_ligature_source_and_unchanged_equality(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, calls = _run_plain(_PROBE_MACRO + "\\probe{\\noindent\\hskip0pt office ``q}\n\\bye\n",
                              monkeypatch)
        chars = [n for n in calls[0][0] if isinstance(n, CharNode)]
        assert [(n.char, n.source) for n in chars] == [
            (ord("o"), ()), (14, (102, 102, 105)), (ord("c"), ()), (ord("e"), ()),
            (92, (96, 96)), (ord("q"), ()),
        ]
        assert chars[1] == CharNode(char=14, font_name=font_key("tenrm", plain=True))
        assert hash(chars[1]) == hash(CharNode(char=14, font_name=font_key("tenrm", plain=True)))


def _params(**overrides) -> LinebreakParams:
    zero = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)
    fields = dict(hsize=300 * 65536, tolerance=10000, pretolerance=100, linepenalty=10,
                  adjdemerits=10000, leftskip=zero, rightskip=zero,
                  parfillskip=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL))
    fields.update(overrides)
    return LinebreakParams(**fields)


class TestSecondPassHook:
    """§6: the step runs once, and only on entering the second pass."""

    @staticmethod
    def _paragraph() -> list:
        return [*_word("ab"), _SPACE, *_word("cd"), PenaltyNode(10000),
                GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
                PenaltyNode(-10000)]

    def _break(self, plain_interp: TeXInterpreter, **overrides) -> tuple[list, list]:
        calls: list = []

        def hyphenate(nodes: list) -> list:
            calls.append(nodes)
            return list(nodes)

        lines = break_paragraph(self._paragraph(), _params(**overrides),
                                plain_interp._font_manager, hyphenate=hyphenate)
        return lines, calls

    def test_first_pass_success_skips_the_step(self, plain_interp: TeXInterpreter) -> None:
        lines, calls = self._break(plain_interp)
        assert calls == []
        plain = break_paragraph(self._paragraph(), _params(), plain_interp._font_manager)
        assert lines == plain

    def test_negative_pretolerance_runs_it_once(self, plain_interp: TeXInterpreter) -> None:
        _, calls = self._break(plain_interp, pretolerance=-1)
        assert len(calls) == 1

    def test_failed_first_pass_runs_it_once(self, plain_interp: TeXInterpreter) -> None:
        # 20pt cannot hold "ab cd" at badness <= 100 in one line, so pass 1 fails.
        _, calls = self._break(plain_interp, hsize=12 * 65536)
        assert len(calls) == 1

    def test_second_pass_uses_the_returned_list(self, plain_interp: TeXInterpreter) -> None:
        marker = RuleNode(width=65536, height=0, depth=0)

        def hyphenate(nodes: list) -> list:
            return [marker, *nodes]

        lines = break_paragraph(self._paragraph(), _params(pretolerance=-1),
                                plain_interp._font_manager, hyphenate=hyphenate)
        assert lines[0].list[0] is marker

    @pytest.mark.parametrize(("hyphenpenalty", "broken"), [(50, True), (10000, False)])
    def test_infinite_hyphenpenalty_is_no_breakpoint(
        self, plain_interp: TeXInterpreter, hyphenpenalty: int, broken: bool,
    ) -> None:
        """§859 try_break returns at once for pi >= 10000, so the disc is never taken."""
        disc = DiscretionaryNode(pre=tuple(_word("-")), post=(), nobreak=())
        nodes = [*_word("aaaa"), disc, *_word("bbbb"), PenaltyNode(10000),
                 GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)),
                 PenaltyNode(-10000)]
        disc_breaks: list[bool] = []
        break_paragraph(nodes, _params(hsize=25 * 65536, hyphenpenalty=hyphenpenalty),
                        plain_interp._font_manager, disc_breaks=disc_breaks)
        assert (True in disc_breaks) is broken

    def test_plain_paragraph_set_by_first_pass_is_never_hyphenated(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, calls = _run_plain("difficulties affluent office\\par\\bye\n", monkeypatch)
        assert calls == []


def _formatless(source: str) -> list[str]:
    messages: list[str] = []
    interp = TeXInterpreter(load_format=False, messages=messages)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(StringInputSource(source), DviDevice())
    return messages


class TestPatternFreeze:
    r"""P6/P7: ``\patterns`` closes when a paragraph enters the second pass."""

    _PREAMBLE = "\\catcode`\\{=1 \\catcode`\\}=2 \\hsize=100pt\n"

    def test_first_pass_paragraph_keeps_patterns_open(self) -> None:
        messages = _formatless(self._PREAMBLE
                               + "\\pretolerance=100 \\noindent\\hbox{}\\par \\patterns{1b}\n\\end\n")
        assert not any("Too late" in m for m in messages)

    def test_second_pass_paragraph_closes_patterns(self) -> None:
        messages = _formatless(self._PREAMBLE
                               + "\\pretolerance=-1 \\noindent\\hbox{}\\par \\patterns{1c{d}e}\n\\end\n")
        assert "! Too late for \\patterns." in messages


class TestParagraphList:
    """§1091: the paragraph records its language and minima."""

    def test_defaults(self) -> None:
        pl = ParagraphList()
        assert (pl.language, pl.left_min, pl.right_min) == (0, 1, 1)

    def test_recorded_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorded: list[tuple[int, int, int]] = []
        real = interpreter_module.hyphenate_paragraph

        def spy(nodes: list, ctx: HyphenationContext) -> list:
            recorded.append((ctx.language, ctx.left_min, ctx.right_min))
            return real(nodes, ctx)

        monkeypatch.setattr(interpreter_module, "hyphenate_paragraph", spy)
        interp = TeXInterpreter(load_format="plain", messages=[])
        source = (_PROBE_MACRO + "\\probe{\\language=300 \\lefthyphenmin=0 \\righthyphenmin=99 "
                  "\\noindent x\\language=5 \\lefthyphenmin=2}\n\\bye\n")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            interp.run_with_device(StringInputSource(source), DviDevice())
        assert recorded == [(0, 1, 63)]
