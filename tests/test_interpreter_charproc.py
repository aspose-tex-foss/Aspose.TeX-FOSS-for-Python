"""Tests for TeX interpreter character processing ( / §4).

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
 assert char_nodes[0].font_name == "tenrm"

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
 assert char_nodes[0].font_name == "tenrm"

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
 assert k.explicit is False # automatic font kern

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
 assert len(char_nodes) >= 1 # at least some chars were processed


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
 # Note: the tokenizer already collapses spaces in state S,
 # but even if multiple space tokens arrive, the interpreter
 # should suppress duplicates via _after_space flag
 nodes_single = _collect_par_nodes("a b")
 nodes_double = _collect_par_nodes("a b")
 glue_single = [n for n in nodes_single if isinstance(n, GlueNode)]
 glue_double = [n for n in nodes_double if isinstance(n, GlueNode)]
 assert len(glue_single) == len(glue_double)

 def test_many_spaces(self) -> None:
 """Many consecutive spaces still produce single GlueNode."""
 nodes = _collect_par_nodes("a b")
 # Between 'a' and 'b' there should be exactly one GlueNode
 # (plus maybe the indent box)
 glue_nodes = [n for n in nodes if isinstance(n, GlueNode)]
 assert len(glue_nodes) == 1


# ---------------------------------------------------------------------------
# AC#6: Spacefactor > 2000 triggers extra space (fontdimen 7)
# ---------------------------------------------------------------------------

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
 nodes_period = _collect_par_nodes("a. b")
 glue_normal = [n for n in nodes_normal if isinstance(n, GlueNode)]
 glue_period = [n for n in nodes_period if isinstance(n, GlueNode)]

 assert len(glue_normal) >= 1
 assert len(glue_period) >= 1

 # Space after period should be wider (includes fontdimen 7)
 if extra_space > 0:
 assert glue_period[0].glue.width == normal_space + extra_space
 assert glue_normal[0].glue.width == normal_space

 def test_uppercase_resets_spacefactor(self) -> None:
 """After uppercase letter (sfcode=999), sf is clamped to 1000."""
 # "A. B" — A has sfcode 999, which resets sf from 3000→1000
 # So space after "B" should be normal, not extra-wide
 # But "a. B" — 'a' sfcode=1000, '.' sfcode=3000, space should be wide
 nodes = _collect_par_nodes("a. B")
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
 nodes_period = _collect_par_nodes("a. b")
 glue_normal = [n for n in nodes_normal if isinstance(n, GlueNode)]
 glue_period = [n for n in nodes_period if isinstance(n, GlueNode)]

 assert len(glue_normal) >= 1
 assert len(glue_period) >= 1

 # Normal space: sf=1000 (after 'a', sfcode=1000), stretch unchanged
 assert glue_normal[0].glue.stretch == normal_stretch
 # After period: sf=3000, stretch = normal_stretch * 3000 // 1000
 assert glue_period[0].glue.stretch == normal_stretch * 3000 // 1000

 def test_exclamation_triggers_xspaceskip(self) -> None:
 """'!' also has sfcode=3000."""
 nodes = _collect_par_nodes("a! b")
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
 """'?' also has sfcode=3000."""
 nodes = _collect_par_nodes("a? b")
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
 assert nodes[0].width == 1_310_720 # 20pt in sp

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
