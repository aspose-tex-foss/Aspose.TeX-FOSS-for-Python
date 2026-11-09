"""Tests for TeX interpreter character processing (§4).

Covers:
- AC#1: Letter token in H mode creates CharNode with correct metrics
- AC#2: fi ligature in cmr10 produces single ligature CharNode
- AC#3: AV in cmr10 produces CharNode(A) + KernNode(-kern) + CharNode(V)
- AC#4: Space token inserts GlueNode with cmr10 fontdimen(2/3/4) values
- AC#5: Consecutive spaces produce single GlueNode
- AC#6: Spacefactor > 2000 before space applies xspaceskip (fontdimen 7)
"""
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode, GlueNode, KernNode
from aspose_tex._engine.registers import GlueOrder
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice
from tests._font_keys import font_key

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_par_nodes(tex_source: str) -> list:
    """Run TeX source that builds a paragraph and return the par_list nodes.

    The source must NOT contain \\par or \\bye — the helper deliberately
    does NOT finalise the paragraph so we can inspect the raw node list.

    We monkey-patch _end_paragraph to capture the nodes before they are
    consumed by the line breaker.
    """
    captured: list = []

    class _CapturingInterpreter(TeXInterpreter):
        def _end_paragraph(self) -> None:
            if self._par_list is not None:
                captured.extend(self._par_list.nodes)
            super()._end_paragraph()

    interp = _CapturingInterpreter()
    # Append \par\bye to finalise; our override captures nodes before consumption
    interp.run(StringInputSource(tex_source + r"\par\bye"))
    return captured


def _run(tex_source: str) -> bytes:
    """Run TeX source through the interpreter and return DVI bytes."""
    interp = TeXInterpreter()
    return interp.run(StringInputSource(tex_source))


# ---------------------------------------------------------------------------
# AC#1: Letter token creates CharNode with correct font metrics
# ---------------------------------------------------------------------------

class TestCharNodeCreation:
    """Letter/other tokens in H mode produce CharNode with correct char code."""

    def test_single_letter_creates_charnode(self) -> None:
        nodes = _collect_par_nodes("A")
        # First node(s) may be indent box; find first CharNode
        char_nodes = [n for n in nodes if isinstance(n, CharNode)]
        assert len(char_nodes) == 1
        assert char_nodes[0].char == ord("A")
        assert char_nodes[0].font_name == font_key("tenrm")

    def test_multiple_letters_create_charnodes(self) -> None:
        nodes = _collect_par_nodes("Hi")
        char_nodes = [n for n in nodes if isinstance(n, CharNode)]
        assert len(char_nodes) == 2
        assert char_nodes[0].char == ord("H")
        assert char_nodes[1].char == ord("i")

    def test_digit_creates_charnode(self) -> None:
        """Digits have catcode OTHER and should also produce CharNode."""
        nodes = _collect_par_nodes("3")
        char_nodes = [n for n in nodes if isinstance(n, CharNode)]
        assert len(char_nodes) == 1
        assert char_nodes[0].char == ord("3")

    def test_charnode_font_metrics_are_positive(self) -> None:
        """Verify that the font has real metrics for the char we emitted."""
        nodes = _collect_par_nodes("A")
        char_nodes = [n for n in nodes if isinstance(n, CharNode)]
        assert len(char_nodes) == 1
        # Load cmr10 to check metrics independently
        from aspose_tex._fonts.font_manager import FontManager
        fm = FontManager()
        fm.load_font("tenrm", "cmr10")
        m = fm.get_metrics("tenrm")
        cm = m.char_metrics(ord("A"))
        assert cm.width > 0
        assert cm.height > 0


# ---------------------------------------------------------------------------
# AC#2: fi ligature in cmr10 produces single CharNode
# ---------------------------------------------------------------------------

class TestLigatures:
    """Ligature processing merges character pairs into ligature CharNode."""

    def test_fi_ligature(self) -> None:
        """cmr10 has an fi ligature; 'fi' should produce one CharNode."""
        nodes = _collect_par_nodes("fi")
        char_nodes = [n for n in nodes if isinstance(n, CharNode)]
        # Without ligature we'd get 2 CharNodes (f, i)
        # With ligature we get 1 CharNode with the ligature char code
        assert len(char_nodes) == 1
        # The ligature char is NOT ord('f') or ord('i')
        assert char_nodes[0].char != ord("f")
        assert char_nodes[0].char != ord("i")
        assert char_nodes[0].font_name == font_key("tenrm")

    def test_fl_ligature(self) -> None:
        """cmr10 also has fl ligature."""
        nodes = _collect_par_nodes("fl")
        char_nodes = [n for n in nodes if isinstance(n, CharNode)]
        assert len(char_nodes) == 1
        assert char_nodes[0].char != ord("f")
        assert char_nodes[0].char != ord("l")

    def test_ff_ligature(self) -> None:
        """cmr10 has ff ligature."""
        nodes = _collect_par_nodes("ff")
        char_nodes = [n for n in nodes if isinstance(n, CharNode)]
        assert len(char_nodes) == 1
        assert char_nodes[0].char != ord("f")

    def test_no_ligature_pair(self) -> None:
        """'ab' in cmr10 has no ligature — two CharNodes expected."""
        nodes = _collect_par_nodes("ab")
        char_nodes = [n for n in nodes if isinstance(n, CharNode)]
        assert len(char_nodes) == 2
        assert char_nodes[0].char == ord("a")
        assert char_nodes[1].char == ord("b")

    def test_chained_ffi_ligature(self) -> None:
        """'ffi' should produce chained ligatures (ff → lig, lig+i → ffi lig)."""
        nodes = _collect_par_nodes("ffi")
        char_nodes = [n for n in nodes if isinstance(n, CharNode)]
        # ffi in cmr10: first f+f→ff lig, then fflig+i→ffi lig
        # Result should be a single CharNode
        assert len(char_nodes) == 1

    def test_ligature_followed_by_nonligature(self) -> None:
        """'fix' — fi ligature consumed, then 'x' is separate."""
        nodes = _collect_par_nodes("fix")
        char_nodes = [n for n in nodes if isinstance(n, CharNode)]
        # fi→ligature + x
        assert len(char_nodes) == 2
        assert char_nodes[1].char == ord("x")


# ---------------------------------------------------------------------------
# AC#3: AV in cmr10 produces CharNode(A) + KernNode + CharNode(V)
# ---------------------------------------------------------------------------

class TestKerning:
    """Automatic kern insertion between character pairs."""

    def test_av_kern(self) -> None:
        """'AV' in cmr10 should insert a KernNode between A and V."""
        nodes = _collect_par_nodes("AV")
        char_nodes = [n for n in nodes if isinstance(n, CharNode)]
        kern_nodes = [n for n in nodes if isinstance(n, KernNode)]
        assert len(char_nodes) == 2
        assert char_nodes[0].char == ord("A")
        assert char_nodes[1].char == ord("V")
        assert len(kern_nodes) >= 1
        # Kern should be negative (pulling A and V closer)
        k = kern_nodes[0]
        assert k.width < 0
        assert k.explicit is False  # automatic font kern

    def test_no_kern_pair(self) -> None:
        """'ab' — no kern expected between a and b in cmr10."""
        nodes = _collect_par_nodes("ab")
        kern_nodes = [n for n in nodes if isinstance(n, KernNode)]
        assert len(kern_nodes) == 0

    def test_kern_and_ligature_coexist(self) -> None:
        """'Affirm' — A+ff ligature possible, kern between A and ff lig?
        At minimum, should not crash and produce valid nodes."""
        nodes = _collect_par_nodes("Affirm")
        char_nodes = [n for n in nodes if isinstance(n, CharNode)]
        assert len(char_nodes) >= 1  # at least some chars were processed


# ---------------------------------------------------------------------------
# AC#4: Space token inserts GlueNode with cmr10 fontdimen values
# ---------------------------------------------------------------------------

class TestSpaceGlue:
    """Space token handling produces correct inter-word glue."""

    def test_space_produces_gluenode(self) -> None:
        """A space between words creates a GlueNode."""
        nodes = _collect_par_nodes("a b")
        glue_nodes = [n for n in nodes if isinstance(n, GlueNode)]
        assert len(glue_nodes) >= 1

    def test_space_glue_matches_fontdimen(self) -> None:
        """GlueNode width matches cmr10 fontdimen(2) (interword space)."""
        nodes = _collect_par_nodes("a b")
        glue_nodes = [n for n in nodes if isinstance(n, GlueNode)]
        assert len(glue_nodes) >= 1
        # Get cmr10 fontdimen values for comparison
        from aspose_tex._fonts.font_manager import FontManager
        fm = FontManager()
        fm.load_font("tenrm", "cmr10")
        space_width = fm.fontdimen("tenrm", 2)
        space_stretch = fm.fontdimen("tenrm", 3)
        space_shrink = fm.fontdimen("tenrm", 4)
        g = glue_nodes[0].glue
        assert g.width == space_width
        assert g.stretch == space_stretch
        assert g.shrink == space_shrink
        assert g.stretch_order == GlueOrder.NORMAL
        assert g.shrink_order == GlueOrder.NORMAL


# ---------------------------------------------------------------------------
# AC#5: Consecutive spaces produce single GlueNode
# ---------------------------------------------------------------------------

class TestConsecutiveSpaces:
    """Consecutive spaces should produce a single GlueNode."""

    def test_double_space(self) -> None:
        """Two consecutive spaces between words → single GlueNode."""
        # The tokenizer collapses the run in state S (TeX §347); the
        # interpreter appends every space token it gets.
        nodes_single = _collect_par_nodes("a b")
        nodes_double = _collect_par_nodes("a  b")
        glue_single = [n for n in nodes_single if isinstance(n, GlueNode)]
        glue_double = [n for n in nodes_double if isinstance(n, GlueNode)]
        assert len(glue_single) == len(glue_double)

    def test_many_spaces(self) -> None:
        """Many consecutive spaces still produce single GlueNode."""
        nodes = _collect_par_nodes("a     b")
        # Between 'a' and 'b' there should be exactly one GlueNode
        # (plus maybe the indent box)
        glue_nodes = [n for n in nodes if isinstance(n, GlueNode)]
        assert len(glue_nodes) == 1


# ---------------------------------------------------------------------------
# AC#6: Spacefactor > 2000 triggers extra space (fontdimen 7)
# ---------------------------------------------------------------------------

# ``_collect_par_nodes`` runs with NO format loaded, so the sfcode table
# holds pure IniTeX defaults: 1000 everywhere except A-Z = 999 (
# FR-4). The sentence-spacing values ``.``/``?``/``!`` = 3000 come from
# plain.tex's ``\nonfrenchspacing`` (line 1238), NOT from IniTeX — verified
# against MiKTeX ``initex``, which reports \sfcode`\. = 1000 with no format.
# Tests that want sentence spacing must therefore assign the sfcode
# themselves, exactly as plain.tex does. Before these tests passed
# without any assignment because the engine read a private 3-entry dict that
# fabricated the plain.tex values under IniTeX conditions.
_NONFRENCH = r"\sfcode`\.=3000 \sfcode`\?=3000 \sfcode`\!=3000 "


class TestSpacefactor:
    """Spacefactor tracking and xspaceskip application."""

    def test_period_sets_high_spacefactor(self) -> None:
        """After '.', spacefactor becomes 3000; space should include extra."""
        from aspose_tex._fonts.font_manager import FontManager
        fm = FontManager()
        fm.load_font("tenrm", "cmr10")
        extra_space = fm.fontdimen("tenrm", 7)
        normal_space = fm.fontdimen("tenrm", 2)

        nodes_normal = _collect_par_nodes("a b")
        nodes_period = _collect_par_nodes(_NONFRENCH + "a. b")
        glue_normal = [n for n in nodes_normal if isinstance(n, GlueNode)]
        glue_period = [n for n in nodes_period if isinstance(n, GlueNode)]

        assert len(glue_normal) >= 1
        assert len(glue_period) >= 1

        # Space after period should be wider (includes fontdimen 7)
        if extra_space > 0:
            assert glue_period[0].glue.width == normal_space + extra_space
            assert glue_normal[0].glue.width == normal_space

    def test_period_is_1000_under_initex_defaults(self) -> None:
        r"""Without a format, ``.`` carries no sentence spacing.

        The complement of the test above, and the direct regression guard for
        ``\nonfrenchspacing`` is a plain.tex macro, so under IniTeX
        defaults ``a. b`` must produce a *plain* interword space. MiKTeX
        ``initex`` reports ``\sfcode`\. = 1000``; the pre- engine
        reported 3000 from a hardcoded dict that no assignment could reach.
        """
        from aspose_tex._fonts.font_manager import FontManager
        fm = FontManager()
        fm.load_font("tenrm", "cmr10")

        glue = [n for n in _collect_par_nodes("a. b") if isinstance(n, GlueNode)]
        assert len(glue) >= 1
        assert glue[0].glue.width == fm.fontdimen("tenrm", 2)
        assert glue[0].glue.stretch == fm.fontdimen("tenrm", 3)
        assert glue[0].glue.shrink == fm.fontdimen("tenrm", 4)

    def test_uppercase_resets_spacefactor(self) -> None:
        """After uppercase letter (sfcode=999), sf is clamped to 1000."""
        # "A. B" — A has sfcode 999, which resets sf from 3000→1000
        # So space after "B" should be normal, not extra-wide
        # But "a. B" — 'a' sfcode=1000, '.' sfcode=3000, space should be wide
        nodes = _collect_par_nodes(_NONFRENCH + "a. B")
        glue_nodes = [n for n in nodes if isinstance(n, GlueNode)]
        assert len(glue_nodes) >= 1
        # After '.', sf=3000, space should be wide
        from aspose_tex._fonts.font_manager import FontManager
        fm = FontManager()
        fm.load_font("tenrm", "cmr10")
        extra_space = fm.fontdimen("tenrm", 7)
        normal_space = fm.fontdimen("tenrm", 2)
        if extra_space > 0:
            assert glue_nodes[0].glue.width == normal_space + extra_space

    def test_spacefactor_stretch_modification(self) -> None:
        """When sf != 1000, stretch is multiplied by sf/1000 (TeX §1042)."""
        # After '.', sf=3000; stretch should be 3x normal
        from aspose_tex._fonts.font_manager import FontManager
        fm = FontManager()
        fm.load_font("tenrm", "cmr10")
        normal_stretch = fm.fontdimen("tenrm", 3)

        nodes_normal = _collect_par_nodes("a b")
        nodes_period = _collect_par_nodes(_NONFRENCH + "a. b")
        glue_normal = [n for n in nodes_normal if isinstance(n, GlueNode)]
        glue_period = [n for n in nodes_period if isinstance(n, GlueNode)]

        assert len(glue_normal) >= 1
        assert len(glue_period) >= 1

        # Normal space: sf=1000 (after 'a', sfcode=1000), stretch unchanged
        assert glue_normal[0].glue.stretch == normal_stretch
        # After period: sf=3000, stretch = normal_stretch * 3000 // 1000
        assert glue_period[0].glue.stretch == normal_stretch * 3000 // 1000

    def test_spacefactor_shrink_modification(self) -> None:
        r"""When sf != 1000, shrink is multiplied by 1000/sf (TeX §1042).

        The counterpart to the stretch modification above: a sentence space
        stretches more readily *and resists shrinking*. Omitting this scaling
        inflated the shrink total of any justified line carrying a sentence
        space, which mis-set every glue node on that line — the /
        ``paragraph_narrow`` drift against MiKTeX.
        """
        from aspose_tex._fonts.font_manager import FontManager
        fm = FontManager()
        fm.load_font("tenrm", "cmr10")
        normal_shrink = fm.fontdimen("tenrm", 4)

        glue_normal = [
            n for n in _collect_par_nodes("a b") if isinstance(n, GlueNode)
        ]
        glue_period = [
            n for n in _collect_par_nodes(_NONFRENCH + "a. b")
            if isinstance(n, GlueNode)
        ]
        assert len(glue_normal) >= 1
        assert len(glue_period) >= 1

        # Normal space: sf=1000, shrink unchanged.
        assert glue_normal[0].glue.shrink == normal_shrink
        # After period: sf=3000, shrink = normal_shrink * 1000 // 3000.
        assert glue_period[0].glue.shrink == normal_shrink * 1000 // 3000
        # Concrete cmr10 values, so a font-metric regression is also caught.
        assert normal_shrink == 72818
        assert glue_period[0].glue.shrink == 24272

    def test_spacefactor_scaling_is_floor_division(self) -> None:
        r"""§1042 scaling truncates like ``xn_over_d``, not round-half.

        Pins the exact integer contract for cmr10 at 10 pt: ``72818 * 1000 //
        3000`` is 24272, whereas rounding the true quotient 24272.666… would
        give 24273. A one-sp difference per space is enough to move a
        shrunken justified line off the MiKTeX baseline.
        """
        assert 72818 * 1000 // 3000 == 24272
        assert round(72818 * 1000 / 3000) == 24273

    def test_spacefactor_below_1000_widens_shrink(self) -> None:
        r"""``sf < 1000`` scales shrink *up* and adds no extra space.

        The two §1042 effects are independent: ``extra_space`` is added only
        when ``sf >= 2000``, while the stretch/shrink scaling applies for any
        ``sf != 1000``. At ``sf=500`` the space must therefore keep the plain
        interword ``width``, halve its stretch and double its shrink — the
        mirror image of the sentence-space case above.

        Uses ``\spacefactor=500{}`` and then a space: ``{}`` ends the number,
        so the space is not absorbed as the assignment's terminator, and it
        leaves the space factor alone.  A control space ``\ `` would not do:
        it ignores the space factor (§1045).  MiKTeX 24.4 gives
        ``3.33333pt plus 0.83333pt minus 2.22223pt`` for this ``\lastskip``.
        """
        from aspose_tex._fonts.font_manager import FontManager
        fm = FontManager()
        fm.load_font("tenrm", "cmr10")
        normal_space = fm.fontdimen("tenrm", 2)
        normal_stretch = fm.fontdimen("tenrm", 3)
        normal_shrink = fm.fontdimen("tenrm", 4)

        nodes = _collect_par_nodes(r"a\spacefactor=500{} b")
        glue = [n for n in nodes if isinstance(n, GlueNode)]
        assert len(glue) >= 1

        assert glue[0].glue.width == normal_space, "sf < 2000 adds no extra_space"
        assert glue[0].glue.stretch == normal_stretch * 500 // 1000
        assert glue[0].glue.shrink == normal_shrink * 1000 // 500
        # Concrete cmr10 values: stretch halved, shrink doubled.
        assert glue[0].glue.stretch == 54613
        assert glue[0].glue.shrink == 145636

    def test_exclamation_triggers_xspaceskip(self) -> None:
        """'!' also gets sfcode=3000 from ``\\nonfrenchspacing``."""
        nodes = _collect_par_nodes(_NONFRENCH + "a! b")
        glue_nodes = [n for n in nodes if isinstance(n, GlueNode)]
        assert len(glue_nodes) >= 1
        from aspose_tex._fonts.font_manager import FontManager
        fm = FontManager()
        fm.load_font("tenrm", "cmr10")
        extra_space = fm.fontdimen("tenrm", 7)
        normal_space = fm.fontdimen("tenrm", 2)
        if extra_space > 0:
            assert glue_nodes[0].glue.width == normal_space + extra_space

    def test_question_triggers_xspaceskip(self) -> None:
        """'?' also gets sfcode=3000 from ``\\nonfrenchspacing``."""
        nodes = _collect_par_nodes(_NONFRENCH + "a? b")
        glue_nodes = [n for n in nodes if isinstance(n, GlueNode)]
        assert len(glue_nodes) >= 1
        from aspose_tex._fonts.font_manager import FontManager
        fm = FontManager()
        fm.load_font("tenrm", "cmr10")
        extra_space = fm.fontdimen("tenrm", 7)
        normal_space = fm.fontdimen("tenrm", 2)
        if extra_space > 0:
            assert glue_nodes[0].glue.width == normal_space + extra_space


# ---------------------------------------------------------------------------
# \sfcode assignment must reach the space factor
# ---------------------------------------------------------------------------

class TestSfcodeAssignmentReachesSpaceFactor:
    r"""``\sfcode`` writes and §1034 reads share one group-scoped store.

    Before ``_exec_sfcode`` wrote ``CodeArrays`` while
    ``_get_sfcode`` read a private ``_sfcodes`` dict, so **no** ``\sfcode``
    assignment — the user's or plain.tex's own ``\nonfrenchspacing`` — ever
    changed the space built after a character.
    """

    @staticmethod
    def _first_glue(tex: str) -> GlueNode:
        glue = [n for n in _collect_par_nodes(tex) if isinstance(n, GlueNode)]
        assert glue, "expected at least one interword GlueNode"
        return glue[0]

    def test_assignment_is_visible_to_get_sfcode(self) -> None:
        r"""AC-1: after ``\sfcode`a=500``, the §1034 lookup returns 500."""
        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(r"\sfcode`\a=500 \bye"), DviDevice(),
        )
        assert interp._get_sfcode(ord("a")) == 500
        assert interp._code_arrays.get_sfcode(ord("a")) == 500

    def test_space_after_assigned_char_uses_1042_scaling(self) -> None:
        r"""AC-2: the space following the char is built with ``sf=500``.

        Concrete cmr10 values, so a font-metric or §1042 regression is caught
        too: width unchanged (extra_space needs ``sf >= 2000``), stretch
        halved, shrink doubled.
        """
        glue = self._first_glue(r"\sfcode`\a=500 a b")
        assert (glue.glue.width, glue.glue.stretch, glue.glue.shrink) == (
            218453, 54613, 145636,
        )

    def test_assignment_is_group_scoped(self) -> None:
        r"""AC-3: a value set inside ``{...}`` is restored on group close."""
        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(r"{\sfcode`\a=500 }\bye"), DviDevice(),
        )
        assert interp._get_sfcode(ord("a")) == 1000

    def test_group_scoped_value_is_live_inside_the_group(self) -> None:
        r"""The restore in AC-3 must not mask the write: 500 applies inside."""
        glue = self._first_glue(r"{\sfcode`\a=500 a b}")
        assert glue.glue.stretch == 54613
        assert glue.glue.shrink == 145636

    def test_the_sfcode_round_trips_assigned_value(self) -> None:
        r"""AC-4: ``\the\sfcode`a`` reads back the assigned value."""
        messages: list[str] = []
        interp = TeXInterpreter(messages=messages)
        interp.run_with_device(
            StringInputSource(
                r"\sfcode`\a=500 \immediate\write16{SF=\the\sfcode`\a}\bye"
            ),
            DviDevice(),
        )
        assert "SF=500" in messages

    def test_uppercase_initex_default_is_999(self) -> None:
        """The IniTeX A-Z = 999 default survives the store unification."""
        interp = TeXInterpreter()
        interp.run_with_device(StringInputSource(r"\bye"), DviDevice())
        assert interp._get_sfcode(ord("A")) == 999
        assert interp._get_sfcode(ord("a")) == 1000

    def test_plain_format_nonfrenchspacing_reaches_space_factor(self) -> None:
        r"""plain.tex's own ``\nonfrenchspacing`` now takes effect.

        The defect was never limited to user assignments: plain.tex line 1238
        calls ``\nonfrenchspacing``, whose ``:``=2000 / ``;``=1500 /
        ``,``=1250 / ``)``=0 values were all dropped along with ``.``=3000.
        Values verified against MiKTeX ``tex`` (``\the\sfcode`\:`` → 2000).
        """
        interp = TeXInterpreter(load_format="plain")
        interp.run_with_device(StringInputSource(r"x\par\bye"), DviDevice())
        assert interp._get_sfcode(ord(".")) == 3000
        assert interp._get_sfcode(ord(":")) == 2000
        assert interp._get_sfcode(ord(";")) == 1500
        assert interp._get_sfcode(ord(",")) == 1250
        assert interp._get_sfcode(ord(")")) == 0


# ---------------------------------------------------------------------------
# Indent / noindent handlers
# ---------------------------------------------------------------------------

class TestIndent:
    """\\indent and \\noindent paragraph-start handlers."""

    def test_default_indent(self) -> None:
        """Default paragraph start has indent box (20pt wide HlistNode)."""
        from aspose_tex._engine.nodes import HlistNode
        nodes = _collect_par_nodes("x")
        # First node should be an indent box (HlistNode with width = parindent)
        assert len(nodes) >= 2
        assert isinstance(nodes[0], HlistNode)
        assert nodes[0].width == 1_310_720  # 20pt in sp

    def test_noindent(self) -> None:
        """\\noindent suppresses the parindent box."""
        from aspose_tex._engine.nodes import HlistNode
        nodes = _collect_par_nodes(r"\noindent x")
        # First node should be CharNode directly (no indent box)
        non_indent = [n for n in nodes if isinstance(n, CharNode)]
        indent_boxes = [n for n in nodes if isinstance(n, HlistNode) and n.width > 0]
        assert len(non_indent) >= 1
        assert len(indent_boxes) == 0


# ---------------------------------------------------------------------------
# Integration: end-to-end DVI output
# ---------------------------------------------------------------------------

class TestCharProcessingIntegration:
    """Integration tests: character processing produces valid DVI output."""

    def test_hello_world_produces_dvi(self) -> None:
        result = _run(r"Hello, world!\bye")
        assert isinstance(result, bytes)
        assert result[0] == 0xF7

    def test_ligature_text_produces_dvi(self) -> None:
        result = _run(r"The official office.\bye")
        assert isinstance(result, bytes)
        assert result[0] == 0xF7

    def test_mixed_text_with_spaces(self) -> None:
        result = _run(r"Hello world. Goodbye world!\bye")
        assert isinstance(result, bytes)
        assert result[0] == 0xF7

    def test_noindent_text(self) -> None:
        result = _run(r"\noindent Hello\bye")
        assert isinstance(result, bytes)
        assert result[0] == 0xF7

    def test_multiple_paragraphs(self) -> None:
        result = _run("First paragraph.\n\nSecond paragraph.\\bye")
        assert isinstance(result, bytes)
        assert result[0] == 0xF7
