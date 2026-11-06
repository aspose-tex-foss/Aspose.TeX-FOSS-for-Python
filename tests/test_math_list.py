"""Tests for the noad data model + mlist builder ( / §A/§B/§F).

Covers the cascade #1 acceptance criteria:
  AC-1 (FR-1, AC-5)  \\mathcode routing + class-7 \\fam resolution
  AC-2 (FR-2)        \\mathchar / \\mathchardef → symbol noad
  AC-3 (FR-3)        \\mathord… class routing
  AC-4 (FR-4)        scan_math_field: char vs {<mlist>}; absent → error
  AC-5 (FR-5)        \\fam selects family for class-7 atoms
  AC-6 (FR-8)        noad field set complete for
  AC-7               scripts parse+attach; double-script error
  AC-8               \\left/\\right depth contract preserved

The builder is exercised through the full interpreter main loop; the finished
mlist is captured at ``$``-close (it is otherwise discarded until cascade #2).
"""

from __future__ import annotations

import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.math_list import (
    MathChar,
    MathClass,
    MathList,
    MathListBuilder,
    Noad,
    NoadKind,
)
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError


def capture_mlist(source: str) -> list[Noad]:
    """Run *source* and return the noad mlist of its first ``$…$`` formula.

    Wraps ``_close_math_builder`` to snapshot the finished mlist before it is
    discarded (cascade #2 wires the translation; cascade #1 only builds).
    """
    captured: list[list[Noad]] = []
    interp = TeXInterpreter()
    original = interp._close_math_builder

    def _capture() -> None:
        builder = interp._math_builder
        if builder is not None:
            captured.append(list(builder.mlist))
        original()

    interp._close_math_builder = _capture  # type: ignore[method-assign]
    interp.run(StringInputSource(source))
    assert captured, "no math formula was closed"
    return captured[0]


def _run(source: str) -> TeXInterpreter:
    interp = TeXInterpreter()
    interp.run(StringInputSource(source))
    return interp


# ---------------------------------------------------------------------------
# AC-1 / AC-5 — \mathcode routing + class-7 \fam resolution
# ---------------------------------------------------------------------------


class TestMathcodeRouting:
    def test_letter_is_class7_ord_family1(self) -> None:
        # IniTeX default \mathcode for letters is 0x71xx → class 7 (var) → Ord,
        # family 1 (math italic) when \fam is out of range.
        mlist = capture_mlist(r"$x$\bye")
        assert len(mlist) == 1
        noad = mlist[0]
        assert noad.kind == NoadKind.ATOM
        assert noad.math_class == MathClass.ORD
        assert isinstance(noad.nucleus, MathChar)
        assert noad.nucleus.fam == 1
        assert noad.nucleus.position == ord("x")

    def test_digit_is_class7_ord_family0(self) -> None:
        # Digits default to 0x70xx → class 7 → Ord, family 0.
        mlist = capture_mlist(r"$5$\bye")
        assert mlist[0].nucleus.fam == 0
        assert mlist[0].nucleus.position == ord("5")

    def test_explicit_mathcode_class_and_family(self) -> None:
        # \mathcode`\+ = "2203 → class 2 (Bin), family 2, position 0x03.
        mlist = capture_mlist(r'\mathcode`\+="2203 $+$\bye')
        noad = mlist[0]
        assert noad.math_class == MathClass.BIN
        assert noad.nucleus.fam == 2
        assert noad.nucleus.position == 0x03

    def test_class7_uses_fam_when_in_range(self) -> None:
        # AC-5: inside \fam0, a class-7 letter resolves to family 0 (roman),
        # not the default math-italic family 1.
        mlist = capture_mlist(r"$\fam0 A$\bye")
        assert mlist[0].nucleus.fam == 0
        assert mlist[0].nucleus.position == ord("A")

    def test_class7_ignores_fam_out_of_range(self) -> None:
        mlist = capture_mlist(r"$\fam-1 A$\bye")
        # \fam = -1 (out of 0..15) → keep the code's family (1).
        assert mlist[0].nucleus.fam == 1


# ---------------------------------------------------------------------------
# AC-2 — \mathchar / \mathchardef
# ---------------------------------------------------------------------------


class TestMathchar:
    def test_mathchar_decodes_class_family_position(self) -> None:
        # \mathchar"2603 → class 2 (Bin), family 6, position 0x03.
        mlist = capture_mlist(r'$\mathchar"2603 $\bye')
        noad = mlist[0]
        assert noad.math_class == MathClass.BIN
        assert noad.nucleus.fam == 6
        assert noad.nucleus.position == 0x03

    def test_mathchardef_symbol_builds_noad(self) -> None:
        # \mathchardef\alpha="010B → class 0 (Ord), family 1, position 0x0B.
        mlist = capture_mlist(r'\mathchardef\alpha="010B $\alpha$\bye')
        noad = mlist[0]
        assert noad.math_class == MathClass.ORD
        assert noad.nucleus.fam == 1
        assert noad.nucleus.position == 0x0B

    def test_two_mathchardef_symbols(self) -> None:
        mlist = capture_mlist(
            r'\mathchardef\alpha="010B \mathchardef\beta="010C $\alpha\beta$\bye'
        )
        assert len(mlist) == 2
        assert mlist[0].nucleus.position == 0x0B
        assert mlist[1].nucleus.position == 0x0C


# ---------------------------------------------------------------------------
# AC-3 — class-routing primitives
# ---------------------------------------------------------------------------


class TestClassPrimitives:
    @pytest.mark.parametrize(
        ("prim", "expected"),
        [
            ("mathord", MathClass.ORD),
            ("mathop", MathClass.OP),
            ("mathbin", MathClass.BIN),
            ("mathrel", MathClass.REL),
            ("mathopen", MathClass.OPEN),
            ("mathclose", MathClass.CLOSE),
            ("mathpunct", MathClass.PUNCT),
            ("mathinner", MathClass.INNER),
        ],
    )
    def test_class_primitive_forces_class(self, prim: str, expected: MathClass) -> None:
        mlist = capture_mlist(rf"$\{prim}{{x}}$\bye")
        assert mlist[0].math_class == expected
        # TeX §1186: the {x} group is one script-less Ord, so its char is the
        # nucleus itself ( amendment,)
        assert isinstance(mlist[0].nucleus, MathChar)

    def test_group_of_two_atoms_stays_a_sub_mlist(self) -> None:
        mlist = capture_mlist(r"$\mathop{xy}$\bye")
        assert mlist[0].math_class == MathClass.OP
        assert isinstance(mlist[0].nucleus, MathList)

    def test_group_with_a_scripted_atom_stays_a_sub_mlist(self) -> None:
        # §1186 collapses only a script-less Ord noad
        mlist = capture_mlist(r"$\mathop{x^2}$\bye")
        assert isinstance(mlist[0].nucleus, MathList)

    def test_bare_group_of_one_char_has_the_char_as_nucleus(self) -> None:
        mlist = capture_mlist(r"${x}$\bye")
        assert mlist[0].math_class == MathClass.ORD
        assert isinstance(mlist[0].nucleus, MathChar)

    def test_mathop_vs_mathbin_distinct_class(self) -> None:
        # AC-4 structure: forced classes differ → drive different spacing in #2.
        op = capture_mlist(r"$\mathop{x}$\bye")[0]
        binn = capture_mlist(r"$\mathbin{x}$\bye")[0]
        assert op.math_class == MathClass.OP
        assert binn.math_class == MathClass.BIN


# ---------------------------------------------------------------------------
# AC-4 — scan_math_field
# ---------------------------------------------------------------------------


class TestScanMathField:
    def test_single_char_field(self) -> None:
        mlist = capture_mlist(r"$\mathord x$\bye")
        assert isinstance(mlist[0].nucleus, MathChar)
        assert mlist[0].nucleus.position == ord("x")

    def test_group_field_is_sub_mlist(self) -> None:
        mlist = capture_mlist(r"$\mathord{xy}$\bye")
        nucleus = mlist[0].nucleus
        assert isinstance(nucleus, MathList)
        assert len(nucleus.noads) == 2
        assert nucleus.noads[0].nucleus.position == ord("x")
        assert nucleus.noads[1].nucleus.position == ord("y")

    def test_absent_field_raises(self) -> None:
        with pytest.raises(EngineError, match="math field expected"):
            _run(r"$\mathord")


# ---------------------------------------------------------------------------
# AC-6 (FR-8) — noad field set complete for
# ---------------------------------------------------------------------------


class TestNoadStructureComplete:
    def test_subscript_superscript_fields_populated(self) -> None:
        mlist = capture_mlist(r"$x^a_b$\bye")
        noad = mlist[0]
        assert isinstance(noad.supscr, MathChar)
        assert noad.supscr.position == ord("a")
        assert isinstance(noad.subscr, MathChar)
        assert noad.subscr.position == ord("b")

    def test_fraction_numerator_denominator_thickness(self) -> None:
        mlist = capture_mlist(r"$a\over b$\bye")
        assert len(mlist) == 1
        frac = mlist[0]
        assert frac.kind == NoadKind.FRACTION
        assert isinstance(frac.numerator, MathList)
        assert frac.numerator.noads[0].nucleus.position == ord("a")
        assert isinstance(frac.denominator, MathList)
        assert frac.denominator.noads[0].nucleus.position == ord("b")
        # \over → DEFAULT_FRACTION_THICKNESS sentinel (resolved in).
        assert frac.thickness is not None

    def test_atop_has_none_thickness(self) -> None:
        frac = capture_mlist(r"$a\atop b$\bye")[0]
        assert frac.kind == NoadKind.FRACTION
        assert frac.thickness is None

    def test_above_thickness_is_dimen(self) -> None:
        frac = capture_mlist(r"$a\above2pt b$\bye")[0]
        assert frac.kind == NoadKind.FRACTION
        assert frac.thickness == 2 * 65536

    def test_mathaccent_fields_populated(self) -> None:
        mlist = capture_mlist(r'$\mathaccent"7013 a$\bye')
        noad = mlist[0]
        assert noad.math_class == MathClass.ACCENT
        assert noad.accent_fam == 0
        assert noad.accent_pos == 0x13
        assert isinstance(noad.nucleus, MathChar)

    def test_radical_left_delim_populated(self) -> None:
        mlist = capture_mlist(r'$\radical"270370 x$\bye')
        noad = mlist[0]
        assert noad.math_class == MathClass.RADICAL
        assert noad.left_delim is not None

    def test_boundary_delims_populated(self) -> None:
        # §C: \left … \right collapses into one INNER atom (TeX §1191)
        # whose nucleus is the inner sub-mlist.  (Delcodes are INITEX defaults
        # here — no plain.tex — so the `(`/`)` delimiters decode to None; the
        # populated-delcode path is covered by the delimiter tests.)
        mlist = capture_mlist(r"$\left(x\right)$\bye")
        assert len(mlist) == 1
        inner = mlist[0]
        assert inner.kind == NoadKind.ATOM
        assert inner.math_class == MathClass.INNER
        # the inner span (the `x`) is the nucleus sub-mlist.
        assert isinstance(inner.nucleus, MathList)
        assert len(inner.nucleus.noads) == 1

    def test_mathchoice_four_sublists(self) -> None:
        mlist = capture_mlist(r"$\mathchoice{d}{t}{s}{ss}$\bye")
        noad = mlist[0]
        assert noad.kind == NoadKind.CHOICE
        assert noad.choices is not None
        assert len(noad.choices) == 4
        assert all(isinstance(c, MathList) for c in noad.choices)

    def test_mathchoice_branches_execute_through_main_loop(self) -> None:
        #: the four branches build through the main loop's
        # begin_group/end_group (full dispatch), not the old symbol-only
        # _scan_choice_group.  Each branch mlist holds its own atoms.
        mlist = capture_mlist(r"$\mathchoice{a}{bb}{ccc}{dddd}$\bye")
        noad = mlist[0]
        assert noad.kind == NoadKind.CHOICE
        assert [len(c.noads) for c in noad.choices] == [1, 2, 3, 4]

    def test_mathchoice_incomplete_raises(self) -> None:
        #: an armed capture that never sees four {…} branches is a
        # runaway \mathchoice (TeX §1174) — take_mlist guards it.
        with pytest.raises(EngineError, match="four"):
            capture_mlist(r"$\mathchoice{a}{b}$\bye")

    def test_overline_underline_class(self) -> None:
        over = capture_mlist(r"$\overline x$\bye")[0]
        under = capture_mlist(r"$\underline y$\bye")[0]
        assert over.math_class == MathClass.OVER
        assert under.math_class == MathClass.UNDER

    def test_mskip_mkern_carriers(self) -> None:
        mlist = capture_mlist(r"$x\mskip9mu y\mkern3mu z$\bye")
        glues = [n for n in mlist if n.kind == NoadKind.GLUE]
        kerns = [n for n in mlist if n.kind == NoadKind.KERN]
        assert glues and glues[0].mu_glue
        assert kerns and kerns[0].mu_glue

    def test_style_noad(self) -> None:
        mlist = capture_mlist(r"$\scriptstyle x$\bye")
        styles = [n for n in mlist if n.kind == NoadKind.STYLE]
        assert styles and styles[0].style == "script"

    def test_nonscript_marker(self) -> None:
        mlist = capture_mlist(r"$x\nonscript y$\bye")
        glues = [n for n in mlist if n.kind == NoadKind.GLUE]
        assert any(g.nonscript for g in glues)


# ---------------------------------------------------------------------------
# AC-7 — scripts attach; double-script error
# ---------------------------------------------------------------------------


class TestScripts:
    def test_superscript_attaches_to_last_atom(self) -> None:
        mlist = capture_mlist(r"$x^2$\bye")
        assert isinstance(mlist[0].supscr, MathChar)
        assert mlist[0].supscr.position == ord("2")

    def test_group_superscript(self) -> None:
        mlist = capture_mlist(r"$x^{ab}$\bye")
        assert isinstance(mlist[0].supscr, MathList)
        assert len(mlist[0].supscr.noads) == 2

    def test_double_superscript_raises(self) -> None:
        with pytest.raises(EngineError, match="double superscript"):
            _run(r"$x^a^b$\bye")

    def test_double_subscript_raises(self) -> None:
        with pytest.raises(EngineError, match="double subscript"):
            _run(r"$x_a_b$\bye")

    def test_script_without_atom_creates_empty_ord(self) -> None:
        # A leading ^ attaches to a freshly-created empty Ord (TeX §1176).
        mlist = capture_mlist(r"$^a$\bye")
        assert mlist[0].kind == NoadKind.ATOM
        assert mlist[0].nucleus is None
        assert isinstance(mlist[0].supscr, MathChar)

    def test_subscript_at_eof_raises(self) -> None:
        with pytest.raises(EngineError, match="math field expected"):
            _run(r"$x_")


# ---------------------------------------------------------------------------
# AC-8 — \left/\right depth contract preserved
# ---------------------------------------------------------------------------


class TestLeftRightDepth:
    def test_balanced_left_right_ok(self) -> None:
        _run(r"$\left(x\right)$\bye")

    def test_right_without_left_raises(self) -> None:
        with pytest.raises(EngineError, match=r"\\right without \\left"):
            _run(r"$\right)$\bye")

    def test_left_without_right_raises(self) -> None:
        with pytest.raises(EngineError, match=r"missing \\right"):
            _run(r"$\left(x$\bye")


# ---------------------------------------------------------------------------
# Unit-level builder construction (no interpreter)
# ---------------------------------------------------------------------------


class TestBuilderUnit:
    def test_take_mlist_resets(self) -> None:
        # A direct builder over a trivial expander; take_mlist resets state.
        from aspose_tex._engine.code_arrays import CodeArrays
        from aspose_tex._engine.expansion import Expander
        from aspose_tex._engine.group import GroupStack
        from aspose_tex._engine.registers import RegisterSet
        from aspose_tex._fonts.font_manager import FontManager
        from aspose_tex._fonts.math_family_registry import MathFamilyRegistry
        from aspose_tex._input.catcode import CatcodeTable
        from aspose_tex._input.reader import InputReader
        from aspose_tex._input.tokenizer import Tokenizer

        groups = GroupStack()
        src = StringInputSource("")
        reader = InputReader(src)
        catcodes = CatcodeTable()
        tok = Tokenizer(reader, catcodes)
        expander = Expander(reader, tok, catcodes)
        fonts = FontManager(group_stack=groups)
        registry = MathFamilyRegistry(groups, fonts)
        registers = RegisterSet(group_stack=groups)
        code_arrays = CodeArrays(group_stack=groups)
        builder = MathListBuilder(expander, code_arrays, registry, registers)

        builder.add_mathchar(0x010B)
        assert len(builder.mlist) == 1
        taken = builder.take_mlist()
        assert len(taken) == 1
        assert builder.mlist == []


def _bare_builder(source: str = "") -> MathListBuilder:
    """Construct a MathListBuilder over *source* with no format loaded."""
    from aspose_tex._engine.code_arrays import CodeArrays
    from aspose_tex._engine.expansion import Expander
    from aspose_tex._engine.group import GroupStack
    from aspose_tex._engine.registers import RegisterSet
    from aspose_tex._fonts.font_manager import FontManager
    from aspose_tex._fonts.math_family_registry import MathFamilyRegistry
    from aspose_tex._input.catcode import CatcodeTable
    from aspose_tex._input.reader import InputReader
    from aspose_tex._input.tokenizer import Tokenizer

    groups = GroupStack()
    reader = InputReader(StringInputSource(source))
    catcodes = CatcodeTable()
    tok = Tokenizer(reader, catcodes)
    expander = Expander(reader, tok, catcodes)
    fonts = FontManager(group_stack=groups)
    registry = MathFamilyRegistry(groups, fonts)
    registers = RegisterSet(group_stack=groups)
    code_arrays = CodeArrays(group_stack=groups)
    return MathListBuilder(expander, code_arrays, registry, registers)


class TestPendingClass:
    """§A — the deferred forced-class group lifecycle."""

    def test_class_primitive_on_brace_sets_pending_and_pushes_back(self) -> None:
        # `\mathopen{` peeks a `{`, sets _pending_class, and pushes the `{` back
        # (does NOT scan the field): the main loop will build the group.
        builder = _bare_builder("{x}")
        builder.add_class_primitive("mathopen")
        assert builder._pending_class is MathClass.OPEN
        assert builder.mlist == [], "the field must NOT have been scanned eagerly"
        # the `{` was pushed back onto the expander for the main loop.
        nxt = builder._expander.peek_raw()
        from aspose_tex._input.catcode import Catcode
        from aspose_tex._input.token import CharToken
        assert isinstance(nxt, CharToken) and nxt.catcode == Catcode.BEGIN_GROUP

    def test_begin_group_binds_pending_class_to_its_frame(self) -> None:
        # begin_group moves the pending class onto the group's frame; only that
        # group's end_group applies it, so a {…} nested in the argument stays an
        # Ord.
        builder = _bare_builder()
        builder._pending_class = MathClass.CLOSE
        builder.begin_group()
        assert builder._pending_class is None, "the frame owns the class now"
        builder.begin_group()  # a nested {…} inside the argument
        builder.add_char(ord("y"))
        builder.end_group()
        builder.add_char(ord("x"))
        builder.end_group()
        assert [n.math_class for n in builder.mlist] == [MathClass.CLOSE]
        assert [n.math_class for n in builder.mlist[0].nucleus.noads] == [
            MathClass.ORD, MathClass.ORD,
        ]

    def test_end_group_applies_pending_class(self) -> None:
        builder = _bare_builder()
        builder._pending_class = MathClass.CLOSE
        builder.begin_group()
        builder.add_char(ord("x"))
        builder.end_group()
        assert builder.mlist[0].math_class is MathClass.CLOSE
        # one script-less Ord in the group: its char is the nucleus (§1186)
        assert isinstance(builder.mlist[0].nucleus, MathChar)


class TestChoiceCapture:
    """ — the deferred four-group \\mathchoice capture lifecycle."""

    def test_add_mathchoice_arms_capture_without_scanning(self) -> None:
        # add_mathchoice sets _choice_capture = [] and does NOT consume the
        # branches — the four `{` are left for the main loop.
        builder = _bare_builder("{a}{b}{c}{d}")
        builder.add_mathchoice()
        assert builder._choice_stack == [(0, [])]
        assert builder.mlist == [], "the branches must NOT have been scanned eagerly"

    def test_end_group_diverts_branches_until_fourth(self) -> None:
        # Each branch end_group collects; only the fourth appends the CHOICE noad.
        builder = _bare_builder()
        builder.add_mathchoice()
        for i in range(3):
            builder.begin_group()
            builder.add_char(ord("x"))
            builder.end_group()
            assert len(builder._choice_stack) == 1
            assert len(builder._choice_stack[0][1]) == i + 1
            assert builder.mlist == [], "no CHOICE noad before the fourth branch"
        builder.begin_group()
        builder.add_char(ord("y"))
        builder.end_group()
        assert builder._choice_stack == [], "the capture disarms on the fourth branch"
        assert len(builder.mlist) == 1
        assert builder.mlist[0].kind is NoadKind.CHOICE
        assert len(builder.mlist[0].choices) == 4

    def test_group_inside_a_branch_is_not_a_branch(self) -> None:
        #: only a group closing back to the armed depth is a branch;
        # the {x} inside the first branch stays an atom of that branch.
        builder = _bare_builder()
        builder.add_mathchoice()
        builder.begin_group()              # branch 1
        builder.begin_group()              # {x} inside it
        builder.add_char(ord("x"))
        builder.end_group()
        assert builder._choice_stack[0][1] == [], "the inner group is no branch"
        builder.end_group()                # closes branch 1
        for _ in range(3):
            builder.begin_group()
            builder.add_char(ord("y"))
            builder.end_group()
        choice = builder.mlist[0]
        assert choice.kind is NoadKind.CHOICE
        first = choice.choices[0].noads
        assert len(first) == 1 and first[0].kind is NoadKind.ATOM

    def test_nested_mathchoice_keeps_its_own_capture(self) -> None:
        #: a \mathchoice inside a branch pushes its own entry and does
        # not clobber the outer branches collected so far.
        builder = _bare_builder()
        builder.add_mathchoice()
        builder.begin_group()              # outer branch 1
        builder.add_mathchoice()
        assert [d for d, _ in builder._choice_stack] == [0, 1]
        for _ in range(4):                 # the inner four branches
            builder.begin_group()
            builder.add_char(ord("x"))
            builder.end_group()
        assert len(builder._choice_stack) == 1
        builder.end_group()                # outer branch 1 holds the inner CHOICE
        for _ in range(3):
            builder.begin_group()
            builder.add_char(ord("y"))
            builder.end_group()
        outer = builder.mlist[0]
        assert outer.kind is NoadKind.CHOICE
        assert outer.choices[0].noads[0].kind is NoadKind.CHOICE
        assert builder._choice_stack == []

    def test_take_mlist_on_incomplete_capture_raises(self) -> None:
        builder = _bare_builder()
        builder.add_mathchoice()
        builder.begin_group()
        builder.end_group()  # only one branch
        with pytest.raises(EngineError, match="four"):
            builder.take_mlist()

    def test_bare_group_without_class_is_ord(self) -> None:
        # A bare {…} group (no class primitive) keeps the default Ord class.
        builder = _bare_builder()
        builder.begin_group()
        builder.add_char(ord("y"))
        builder.end_group()
        assert builder.mlist[0].math_class is MathClass.ORD

    def test_class_primitive_on_symbol_does_not_set_pending(self) -> None:
        # A single-symbol field keeps the eager path; _pending_class stays None.
        builder = _bare_builder("x")
        builder.add_class_primitive("mathord")
        assert builder._pending_class is None
        assert len(builder.mlist) == 1
        assert builder.mlist[0].math_class is MathClass.ORD
        assert isinstance(builder.mlist[0].nucleus, MathChar)

    def test_add_box_appends_ord_atom_with_box_nucleus(self) -> None:
        from aspose_tex._engine.nodes import GlueSign, HlistNode
        from aspose_tex._engine.registers import GlueOrder

        builder = _bare_builder()
        box = HlistNode(
            list=[], width=0, height=0, depth=0, shift_amount=0,
            glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
        )
        builder.add_box(box)
        assert len(builder.mlist) == 1
        assert builder.mlist[0].kind is NoadKind.ATOM
        assert builder.mlist[0].math_class is MathClass.ORD
        assert builder.mlist[0].nucleus is box


class TestOrdinaryGlueCarrier:
    r""" — \hfil and friends enter the mlist as an ordinary glue noad."""

    def test_add_glue_appends_ordinary_glue_noad(self) -> None:
        from aspose_tex._engine.registers import Glue, GlueOrder

        builder = _bare_builder()
        hfil = Glue(0, 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL)
        builder.add_glue(hfil)

        assert len(builder.mlist) == 1
        noad = builder.mlist[0]
        assert noad.kind is NoadKind.GLUE
        assert noad.glue is hfil
        # The mu payload stays untouched, so the translator takes the ordinary
        # arm rather than converting a mu value per style.
        assert noad.mu_glue is False
        assert noad.glue_value == 0

    def test_mskip_carries_a_full_mu_glue(self) -> None:
        #: \mskip scans a whole <muglue> (§1060) into `glue`, and
        # `mu_glue` marks it as mu so the translator still scales it per style.
        from aspose_tex._engine.registers import Glue, GlueOrder

        builder = _bare_builder("3mu plus 1mu minus 2fil ")
        builder.add_mskip()

        assert len(builder.mlist) == 1
        noad = builder.mlist[0]
        assert noad.kind is NoadKind.GLUE
        assert noad.mu_glue is True
        assert noad.glue == Glue(196608, 65536, GlueOrder.NORMAL, 131072, GlueOrder.FIL)

    def test_nonscript_keeps_the_mu_payload_and_no_ordinary_glue(self) -> None:
        builder = _bare_builder()
        builder.add_nonscript()

        noad = builder.mlist[0]
        assert noad.nonscript is True
        assert noad.mu_glue is True
        assert noad.glue is None


# ---------------------------------------------------------------------------
# — a `{…}` math field runs through the main loop (TeX §1151/§1186)
# ---------------------------------------------------------------------------


def _kinds(field: MathList) -> list[NoadKind]:
    return [n.kind for n in field.noads]


class TestFieldGroupsExecute:
    r"""A script, radicand or accentee written as ``{…}`` is built by the main loop.

    The old symbol-only field scanner dropped every control sequence that was
    not a ``\mathchardef`` and read the rest as letters, so ``\mkern3mu`` in a
    superscript became the atoms ``3``, ``m``, ``u``.
    """

    @pytest.mark.parametrize(
        ("source", "kind"),
        [
            (r"$x^{a\mskip3mu b}$\bye", NoadKind.GLUE),
            (r"$x^{a\mkern3mu b}$\bye", NoadKind.KERN),
            (r"$x^{a\hskip1pt b}$\bye", NoadKind.GLUE),
            (r"$x^{a\kern1pt b}$\bye", NoadKind.KERN),
        ],
    )
    def test_spacing_primitive_in_superscript_becomes_a_noad(
        self, source: str, kind: NoadKind
    ) -> None:
        field = capture_mlist(source)[0].supscr
        assert isinstance(field, MathList)
        assert _kinds(field) == [NoadKind.ATOM, kind, NoadKind.ATOM]

    def test_subscript_group_executes(self) -> None:
        field = capture_mlist(r"$x_{a\mkern3mu b}$\bye")[0].subscr
        assert _kinds(field) == [NoadKind.ATOM, NoadKind.KERN, NoadKind.ATOM]
        assert field.noads[1].width == 3 * 65536

    def test_radicand_group_executes(self) -> None:
        noad = capture_mlist(r'$\radical"270370 {a\mkern3mu b}$\bye')[0]
        assert noad.math_class == MathClass.RADICAL
        assert _kinds(noad.nucleus) == [NoadKind.ATOM, NoadKind.KERN, NoadKind.ATOM]

    @pytest.mark.parametrize(
        ("source", "math_class"),
        [
            (r'$\mathaccent"7013 {a\mskip3mu b}$\bye', MathClass.ACCENT),
            (r"$\overline{a\mskip3mu b}$\bye", MathClass.OVER),
            (r"$\underline{a\mskip3mu b}$\bye", MathClass.UNDER),
        ],
    )
    def test_nucleus_group_executes(self, source: str, math_class: MathClass) -> None:
        noad = capture_mlist(source)[0]
        assert noad.math_class == math_class
        assert _kinds(noad.nucleus) == [NoadKind.ATOM, NoadKind.GLUE, NoadKind.ATOM]

    def test_fraction_inside_a_script_is_built(self) -> None:
        field = capture_mlist(r"$x^{a\over b}$\bye")[0].supscr
        assert _kinds(field) == [NoadKind.FRACTION]

    def test_script_after_a_radical_attaches_to_it(self) -> None:
        # The radical noad is on the list before its `{…}` field is built, so a
        # following ^ attaches to the radical, not to a fresh empty Ord.
        mlist = capture_mlist(r'$\radical"270370 {x}^2$\bye')
        assert len(mlist) == 1
        assert mlist[0].math_class == MathClass.RADICAL
        assert isinstance(mlist[0].supscr, MathChar)

    def test_nested_script_groups_fill_their_own_fields(self) -> None:
        outer = capture_mlist(r"$x^{a^{b\mkern1mu c}}$\bye")[0].supscr
        assert _kinds(outer) == [NoadKind.ATOM]
        inner = outer.noads[0].supscr
        assert _kinds(inner) == [NoadKind.ATOM, NoadKind.KERN, NoadKind.ATOM]

    def test_assignment_in_a_script_is_local_to_its_group(self) -> None:
        # The field is a real TeX group: \fam0 inside it is undone at the `}`.
        mlist = capture_mlist(r"$x^{\fam0 a}b$\bye")
        assert mlist[0].supscr == MathChar(0, ord("a"))  # one-Ord field, §1186
        assert mlist[1].nucleus == MathChar(1, ord("b"))

    def test_script_group_inside_a_mathchoice_branch_is_not_a_branch(self) -> None:
        noad = capture_mlist(r"$\mathchoice{x^{a}}{b}{c}{d}$\bye")[0]
        assert noad.kind == NoadKind.CHOICE
        first = noad.choices[0].noads
        assert len(first) == 1
        assert first[0].supscr == MathChar(1, ord("a"))

    def test_double_superscript_after_a_group_still_raises(self) -> None:
        with pytest.raises(EngineError, match="double superscript"):
            _run(r"$x^{a}^b$\bye")


class TestKernInMath:
    r"""``\kern`` in math mode joins the math list in place (TeX §1061)."""

    def test_kern_is_a_noad_between_the_atoms(self) -> None:
        mlist = capture_mlist(r"$a\kern1pt b$\bye")
        assert [n.kind for n in mlist] == [NoadKind.ATOM, NoadKind.KERN, NoadKind.ATOM]
        assert mlist[1].width == 65536
        # sp, not mu: the translator must not convert it per style.
        assert mlist[1].mu_glue is False

    def test_add_kern_appends_sp_kern_noad(self) -> None:
        builder = _bare_builder()
        builder.add_kern(-32768)
        noad = builder.mlist[0]
        assert noad.kind is NoadKind.KERN
        assert noad.width == -32768
        assert noad.mu_glue is False
