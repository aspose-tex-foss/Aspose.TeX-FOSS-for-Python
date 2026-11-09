r"""Tests for ``short_display`` and paragraph-line reports (§8).

Every expected message is MiKTeX 24.4 (``tex``, plain, nonstopmode,
2026-10-21) on the same source, copied verbatim from its log.  TeX follows
each pair with a box display line (``\hbox(…)x…, glue set … []``), which the
engine does not produce (§8 known gap).
"""
from __future__ import annotations

import warnings

import pytest

from aspose_tex._engine.box_builder import short_display
from aspose_tex._engine.box_primitives import OverfullBoxWarning, UnderfullBoxWarning
from aspose_tex._engine.hyphenation import LanguageWhatsit
from aspose_tex._engine.linebreak import LinebreakParams, break_paragraph
from aspose_tex._engine.nodes import (
    AdjustNode,
    CharNode,
    DiscretionaryNode,
    GlueNode,
    GlueSign,
    HlistNode,
    InsertNode,
    KernNode,
    LeadersKind,
    LeadersNode,
    MarkNode,
    MathNode,
    PenaltyNode,
    RuleNode,
    VlistNode,
    WhatsitNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

_ZERO = Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)


def test_shared_key_uses_latest_font_id_text_in_report():
    assert _messages(r'\hbadness=-1 \parfillskip=0pt plus1000pt \hsize=100pt '
                     r'\let\x=\tenrm \font\y=cmr10 \noindent\x ab\y cd\par')[-1] == r'\y abcd '


def test_short_display_aliases_distinct_sizes_and_recursive_key_state():
    from aspose_tex._fonts.font_manager import FontManager
    fonts = FontManager()
    fonts.load_font('a', 'cmr10')
    fonts.load_font('b', 'cmr10')
    fonts.load_font('large', 'cmr10', scaled=1200)
    key = fonts.font_id('a')
    large = fonts.font_id('large')
    disc = DiscretionaryNode(pre=(CharNode(char=ord('b'), font_name=key),),
                             post=(CharNode(char=ord('c'), font_name=large),), nobreak=())
    nodes = [CharNode(char=ord('a'), font_name=key), disc, CharNode(char=ord('d'), font_name=large)]
    assert short_display(nodes, fonts) == r'\b ab\large cd'


def test_local_font_id_text_survives_binding_restoration():
    from aspose_tex._engine.group import GroupKind, GroupStack
    from aspose_tex._fonts.font_manager import FontManager
    groups = GroupStack()
    fonts = FontManager(group_stack=groups)
    fonts.load_font('a', 'cmr10')
    key = fonts.font_id('a')
    nodes = [CharNode(char=ord('a'), font_name=key)]
    groups.open_group(GroupKind.BRACE)
    fonts.load_font('local', 'cmr10')
    groups.close_group()
    assert not fonts.is_font('local')
    assert short_display(nodes, fonts) == r'\local a'


def test_no_manager_cannot_leak_an_opaque_key():
    with pytest.raises(ValueError, match='requires a font manager'):
        short_display([CharNode(char=65, font_name='\x00font:1')])
_PLAIN_PROGRESS = (
    "Preloading the plain format: codes,", "registers,", "parameters,", "fonts,",
    "more fonts,", "macros,", "math definitions,", "output routines,", "hyphenation",
)


def _rm(text: str) -> list[CharNode]:
    return [CharNode(char=ord(c), font_name="tenrm") for c in text]


def _box() -> HlistNode:
    return HlistNode(list=[], width=0, height=0, depth=0, shift_amount=0,
                     glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0)


class TestShortDisplay:
    """§174-§175 per node kind."""

    def test_font_switches_print_the_identifier_once_per_change(self) -> None:
        nodes = [*_rm("ab"), CharNode(char=ord("c"), font_name="tenit"), *_rm("d")]
        assert short_display(nodes) == "\\tenrm ab\\tenit c\\tenrm d"

    def test_ligature_prints_its_source_characters(self) -> None:
        nodes = [CharNode(char=14, font_name="tenrm", source=(102, 102, 105)), *_rm("x")]
        assert short_display(nodes) == "\\tenrm ffix"

    def test_discretionary_prints_pre_then_post_never_nobreak(self) -> None:
        disc = DiscretionaryNode(pre=tuple(_rm("f-")),
                                 post=(CharNode(char=12, font_name="tenrm", source=(102, 105)),),
                                 nobreak=(CharNode(char=14, font_name="tenrm", source=(102, 102, 105)),))
        assert short_display([*_rm("di"), disc, *_rm("c")]) == "\\tenrm dif-fic"

    def test_discretionary_switches_font_inside_its_branches(self) -> None:
        disc = DiscretionaryNode(pre=(CharNode(char=ord("x"), font_name="tenit"),), post=(), nobreak=())
        assert short_display([*_rm("a"), disc, *_rm("b")]) == "\\tenrm a\\tenit x\\tenrm b"

    @pytest.mark.parametrize(("code", "text"), [
        (1, "^^A"), (30, "^^^"), (32, " "), (126, "~"), (127, "^^?"), (200, "^^c8"),
    ])
    def test_caret_notation(self, code: int, text: str) -> None:
        assert short_display([CharNode(char=code, font_name="f")]) == f"\\f {text}"

    def test_boxes_inserts_marks_adjusts_and_whatsits_print_brackets(self) -> None:
        vbox = VlistNode(list=[], width=0, height=0, depth=0, shift_amount=0,
                         glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0)
        nodes = [_box(), vbox, InsertNode(class_=100, vlist=(), height=0, depth=0, floating_penalty=0,
                                          split_top_skip=_ZERO, split_max_depth=0),
                 MarkNode(tokens=()), AdjustNode(list=[]),
                 WhatsitNode(data=LanguageWhatsit(language=1, left_min=2, right_min=3)),
                 WhatsitNode(data=b"special")]
        assert short_display(nodes) == "[]" * 7

    def test_rule_math_glue_kern_penalty(self) -> None:
        space = Glue(218453, 109226, GlueOrder.NORMAL, 72818, GlueOrder.NORMAL)
        nodes = [*_rm("a"), RuleNode(width=1, height=1, depth=0), MathNode(width=0, after=False),
                 MathNode(width=0, after=True), GlueNode(glue=space), KernNode(width=65536, explicit=True),
                 PenaltyNode(penalty=5), GlueNode(glue=_ZERO),
                 GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)), *_rm("b")]
        assert short_display(nodes) == "\\tenrm a|$$  b"

    def test_leaders_print_like_their_glue(self) -> None:
        rule = RuleNode(width=0, height=0, depth=0)
        nodes = [LeadersNode(kind=LeadersKind.NORMAL, payload=rule,
                             glue=Glue(2 * 65536, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL)),
                 LeadersNode(kind=LeadersKind.NORMAL, payload=rule, glue=_ZERO)]
        assert short_display(nodes) == " "

    def test_nested_boxes_are_not_entered(self) -> None:
        box = _box()
        box.list.extend(_rm("hidden"))
        assert short_display([box, *_rm("x")]) == "[]\\tenrm x"


def _messages(source: str) -> list[str]:
    job = TeXJob(StringInputSource(source + "\\bye\n"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job.run()
    return [m for m in job.messages if m not in _PLAIN_PROGRESS]


class TestParagraphLineReports:
    """§663/§666: header and short display of each reported paragraph line."""

    def test_ac7_showhyphens_difficulties(self) -> None:
        assert _messages("\\showhyphens{difficulties}\n") == [
            "Underfull \\hbox (badness 10000) in paragraph at lines 1--1",
            "[] \\tenrm dif-fi-cul-ties",
        ]

    def test_p1_three_words(self) -> None:
        assert _messages("\n\\showhyphens{difficulties affluent office}\n") == [
            "Underfull \\hbox (badness 10000) in paragraph at lines 2--2",
            "[] \\tenrm dif-fi-cul-ties af-flu-ent of-fice",
        ]

    def test_overfull_lines_with_rule_and_broken_discretionaries(self) -> None:
        r"""Each line ends at a discretionary or the paragraph end; ``|`` is the overfull rule.

        MiKTeX starts the first line with `` \tenrm``: its ``\hskip0pt`` is
        not ``zero_glue`` (a known gap), so the
        engine's copy of that probe leaves the glue out.
        """
        assert _messages("{\\hsize=10pt \\noindent\\hskip0pt difficulties\\par}\n") == [
            "Overfull \\hbox (4.72226pt too wide) in paragraph at lines 1--1",
            "\\tenrm dif-|",
            "Overfull \\hbox (11.6667pt too wide) in paragraph at lines 1--1",
            "\\tenrm fi-cul-|",
            "Overfull \\hbox (5.05557pt too wide) in paragraph at lines 1--1",
            "\\tenrm ties |",
        ]

    def test_overfull_first_word(self) -> None:
        assert _messages("{\\hsize=10pt \\noindent difficulties\\par}\n") == [
            "Overfull \\hbox (34.50009pt too wide) in paragraph at lines 1--1",
            "\\tenrm difficulties |",
        ]

    _LOOSE = "\\hbadness=-1 \\parfillskip=0pt plus 1000pt \\hsize=300pt\n"

    def test_node_kinds_in_a_line(self) -> None:
        r"""Marks, inserts and adjusts are moved out of the line before the report (§655)."""
        source = (self._LOOSE + "\\noindent ab{\\it cd}\\char'177\\char1 \\kern1pt$x$\\vrule\\penalty5 "
                  "\\hskip0pt plus1pt\\hbox{}\\discretionary{x}{y}{z}\\mark{m}\\vadjust{}\\insert100{} "
                  "fi ``q\\par\n")
        assert _messages(source) == [
            "Loose \\hbox (badness 1) in paragraph at lines 2--2",
            "\\tenrm ab\\tenit cd\\tenrm ^^?^^A$\\teni x$| []\\tenrm xy fi ``q ",
        ]

    def test_leaders_whatsit_and_caret(self) -> None:
        source = (self._LOOSE + "\\noindent A\\hskip 0pt plus 1pt\\leaders\\hrule\\hskip 2pt"
                  "\\setlanguage3 q\\char'036 r\\par\n")
        assert _messages(source) == [
            "Loose \\hbox (badness 2) in paragraph at lines 2--2",
            "\\tenrm A  [][]q^^^r ",
        ]

    def test_language_whatsits_in_a_line(self) -> None:
        source = (self._LOOSE.replace("300pt", "100pt")
                  + "\\noindent a\\language=1 b\\setlanguage3 c\\par\n")
        assert _messages(source) == [
            "Loose \\hbox (badness 0) in paragraph at lines 2--2",
            "\\tenrm a[]b[][]c ",
        ]

    def test_line_range_spans_the_paragraph_input(self) -> None:
        source = self._LOOSE + "\\noindent\nfirst line\nsecond line\nthird\\par\n"
        assert _messages(source) == [
            "Loose \\hbox (badness 1) in paragraph at lines 2--5",
            "\\tenrm first line second line third ",
        ]

    def test_display_resume_starts_a_new_range(self) -> None:
        source = self._LOOSE + "\\noindent x\n$$ $$\ny\nz\\par\n"
        assert _messages(source) == [
            "Loose \\hbox (badness 3) in paragraph at lines 2--3",
            "\\tenrm x ",
            "Loose \\hbox (badness 2) in paragraph at lines 3--5",
            "\\tenrm y z ",
        ]

    def test_python_warnings_keep_their_text(self) -> None:
        job = TeXJob(StringInputSource("{\\hsize=10pt \\noindent difficulties\\par}\\bye\n"),
                     DviDevice(), options=TeXOptions())
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            job.run()
        overfull = [w for w in caught if issubclass(w.category, (OverfullBoxWarning, UnderfullBoxWarning))]
        assert [str(w.message) for w in overfull] == ["Overfull \\hbox (badness 1000000)"]


class TestBreakParagraphReports:
    """``line_reports`` of :func:`break_paragraph` on a hand-built list."""

    def test_no_report_without_the_out_parameter_or_a_bad_line(self, plain_font_manager) -> None:
        params = LinebreakParams(
            hsize=300 * 65536, tolerance=10000, pretolerance=100, linepenalty=10,
            adjdemerits=10000, leftskip=_ZERO, rightskip=_ZERO,
            parfillskip=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL),
        )
        nodes = [*_rm("ab"), PenaltyNode(10000),
                 GlueNode(glue=Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)), PenaltyNode(-10000)]
        reports: list = []
        break_paragraph(nodes, params, plain_font_manager, line_reports=reports)
        assert reports == []


@pytest.fixture(scope="module")
def plain_font_manager():
    from aspose_tex._engine.interpreter import TeXInterpreter

    interp = TeXInterpreter(load_format="plain", messages=[])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        interp.run_with_device(StringInputSource("\\relax"), DviDevice())
    return interp._font_manager
