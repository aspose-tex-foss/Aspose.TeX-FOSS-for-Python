"""Tests for the ``\\/`` italic-correction primitive.

Implements TeX:The Program §1112 (``ital_corr``).  Every expected width in
this module is ground truth measured from MiKTeX etex 24.4 by differencing
``\\hbox`` widths with and without ``\\/``::

    \\hbox{\\ti f\\/} - \\hbox{\\ti f}  =  2.11945pt   (cmti10 f)
    \\hbox{\\ti l\\/} - \\hbox{\\ti l}  =  1.03334pt   (cmti10 l)
    \\hbox{\\rm f\\/} - \\hbox{\\rm f}  =  0.77779pt   (cmr10  f)
    \\/ at list start / after kern / after box / after glue / in math  =  0pt

Covers:
- AC#1: ``\\/`` after a char node emits the italic-correction kern
- AC#2: ``\\/`` at list start or after a non-char node is a no-op
- AC#3: ``\\/`` inside math mode is a no-op
"""
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode, GlueNode, HlistNode, KernNode
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._input.reader import StringInputSource

# Italic corrections in sp, taken from our TFM reader and cross-checked against
# the MiKTeX hbox-difference measurements above: each value below formats to
# exactly the pt figure MiKTeX printed (sp / 65536, 5 decimal places).
CMR10_F_IC = 50973      # 0.77779pt
CMTI10_F_IC = 138900    # 2.11945pt
CMTI10_L_IC = 67721     # 1.03334pt


def _collect_par_nodes(tex_source: str) -> list:
    """Run TeX source and return the paragraph node list before line-breaking."""
    captured: list = []

    class _CapturingInterpreter(TeXInterpreter):
        def _end_paragraph(self, **kwargs) -> None:
            if self._par_list is not None:
                captured.extend(self._par_list.nodes)
            super()._end_paragraph(**kwargs)

    interp = _CapturingInterpreter()
    interp.run(StringInputSource(tex_source + r"\par\bye"))
    return captured


def _ic_kerns(nodes: list) -> list[KernNode]:
    """Return only the italic-correction kerns from a node list."""
    return [n for n in nodes
            if isinstance(n, KernNode) and n.italic_correction]


# ---------------------------------------------------------------------------
# Reference values — our TFM must agree with MiKTeX before anything else
# ---------------------------------------------------------------------------

class TestReferenceMetrics:
    """The TFM italic table matches the MiKTeX-measured corrections."""

    def test_tfm_italics_match_miktex(self) -> None:
        mgr = FontManager()
        mgr.load_font("rm", "cmr10")
        mgr.load_font("ti", "cmti10")
        rm = mgr.get_metrics("rm")
        ti = mgr.get_metrics("ti")
        assert rm.char_metrics(ord("f")).italic == CMR10_F_IC
        assert ti.char_metrics(ord("f")).italic == CMTI10_F_IC
        assert ti.char_metrics(ord("l")).italic == CMTI10_L_IC

    def test_constants_round_trip_to_miktex_printed_widths(self) -> None:
        """Each sp constant formats to the pt figure MiKTeX printed."""
        assert f"{CMR10_F_IC / 65536:.5f}pt" == "0.77779pt"
        assert f"{CMTI10_F_IC / 65536:.5f}pt" == "2.11945pt"
        assert f"{CMTI10_L_IC / 65536:.5f}pt" == "1.03334pt"

    def test_italic_correction_is_not_fontdimen1(self) -> None:
        """Guards the defect's AC-1 wording would have introduced.

        ``\\fontdimen1`` is a font-wide slant ratio, not a kern width: it is
        identical for every glyph of a font and zero for all of cmr10, whereas
        the real correction differs per glyph.
        """
        mgr = FontManager()
        mgr.load_font("ti", "cmti10")
        ti = mgr.get_metrics("ti")
        assert CMTI10_F_IC != CMTI10_L_IC          # per-glyph, not per-font
        assert ti.char_metrics(ord("f")).italic != ti.fontdimen(1)


# ---------------------------------------------------------------------------
# AC#1 — \/ after a char node emits the correct kern
# ---------------------------------------------------------------------------

class TestItalicCorrectionAfterChar:
    """``\\/`` following a character appends that character's correction."""

    def test_after_cmr10_f_emits_kern(self) -> None:
        kerns = _ic_kerns(_collect_par_nodes(r"f\/"))
        assert len(kerns) == 1
        assert kerns[0].width == CMR10_F_IC

    def test_kern_is_marked_and_not_explicit(self) -> None:
        """AC#4: the kern is flagged as an italic correction, not a \\kern."""
        kern = _ic_kerns(_collect_par_nodes(r"f\/"))[0]
        assert kern.italic_correction is True
        assert kern.explicit is False

    def test_zero_correction_char_still_emits_kern(self) -> None:
        """cmr10 ``l`` has no correction — TeX still appends a 0pt kern."""
        kerns = _ic_kerns(_collect_par_nodes(r"l\/"))
        assert len(kerns) == 1
        assert kerns[0].width == 0

    def test_kern_follows_the_char_node(self) -> None:
        nodes = _collect_par_nodes(r"f\/")
        idx = next(i for i, n in enumerate(nodes)
                   if isinstance(n, CharNode) and n.char == ord("f"))
        assert isinstance(nodes[idx + 1], KernNode)
        assert nodes[idx + 1].italic_correction

    def test_italic_font_correction_differs_per_glyph(self) -> None:
        """The whole point of §1112: the width comes from the glyph, not the font."""
        f_kerns = _ic_kerns(_collect_par_nodes(r"\font\ti=cmti10 \ti f\/"))
        l_kerns = _ic_kerns(_collect_par_nodes(r"\font\ti=cmti10 \ti l\/"))
        assert f_kerns[0].width == CMTI10_F_IC
        assert l_kerns[0].width == CMTI10_L_IC

    def test_after_ligature_uses_ligature_glyph(self) -> None:
        """``ff\\/`` corrects the ff-ligature glyph, matching MiKTeX's 2.11945pt."""
        nodes = _collect_par_nodes(r"\font\ti=cmti10 \ti ff\/")
        chars = [n for n in nodes if isinstance(n, CharNode)]
        assert len(chars) == 1                     # ff collapsed to one ligature
        kerns = _ic_kerns(nodes)
        assert len(kerns) == 1
        assert kerns[0].width == CMTI10_F_IC

    def test_inside_hbox(self) -> None:
        """Restricted horizontal mode uses the same tail lookup."""
        nodes = _collect_par_nodes(r"a\hbox{f\/}b")
        boxes = [n for n in nodes if isinstance(n, HlistNode) and n.list]
        inner = [n for b in boxes for n in b.list
                 if isinstance(n, KernNode) and n.italic_correction]
        assert len(inner) == 1
        assert inner[0].width == CMR10_F_IC


# ---------------------------------------------------------------------------
# AC#2 — no-op at list start and after non-char nodes
# ---------------------------------------------------------------------------

class TestItalicCorrectionNoOp:
    """``\\/`` emits nothing unless a char node precedes it."""

    def test_start_of_paragraph_is_noop(self) -> None:
        assert _ic_kerns(_collect_par_nodes(r"\/f")) == []

    def test_after_kern_is_noop(self) -> None:
        assert _ic_kerns(_collect_par_nodes(r"f\kern1pt\/")) == []

    def test_after_glue_is_noop(self) -> None:
        nodes = _collect_par_nodes(r"f \/")
        assert any(isinstance(n, GlueNode) for n in nodes)
        assert _ic_kerns(nodes) == []

    def test_after_box_is_noop(self) -> None:
        assert _ic_kerns(_collect_par_nodes(r"f\hbox{}\/")) == []

    def test_outer_vertical_mode_emits_nothing(self) -> None:
        """``\\/`` in vertical mode contributes no kern and does not start a par.

        Real TeX raises ``You can't use `\\/' in vertical mode`` here and then
        *ignores* the command; we ignore it silently.  The typeset result is the
        same — this asserts the observable half.  ``\\/`` notably does NOT start
        a paragraph, unlike most horizontal commands (verified against MiKTeX
        etex 24.4), so the following text keeps its normal ``\\parindent``.
        """
        nodes = _collect_par_nodes(r"\/f\/")
        kerns = _ic_kerns(nodes)
        # Only the second \/ (which follows the char f) contributes.
        assert len(kerns) == 1
        assert kerns[0].width == CMR10_F_IC


# ---------------------------------------------------------------------------
# AC#3 — no-op in math mode
# ---------------------------------------------------------------------------

class TestItalicCorrectionInMath:
    """Math mode inserts its own italic corrections; ``\\/`` is a no-op there."""

    def test_inline_math_is_noop(self) -> None:
        nodes = _collect_par_nodes(r"$f\/$")
        assert _ic_kerns(nodes) == []

    def test_display_math_is_noop(self) -> None:
        nodes = _collect_par_nodes(r"a$$f\/$$")
        assert _ic_kerns(nodes) == []

    def test_still_works_after_leaving_math(self) -> None:
        """The math no-op must not disable the primitive afterwards."""
        kerns = _ic_kerns(_collect_par_nodes(r"$x$f\/"))
        assert len(kerns) == 1
        assert kerns[0].width == CMR10_F_IC


# ---------------------------------------------------------------------------
# Regression — \/ must not disturb documents that do not use it
# ---------------------------------------------------------------------------

class TestNoCollateralChange:
    """Ordinary kerns stay unmarked so existing behaviour is unchanged."""

    def test_lig_kern_table_kerns_are_not_italic_corrections(self) -> None:
        nodes = _collect_par_nodes("AV")
        kerns = [n for n in nodes if isinstance(n, KernNode)]
        assert kerns                                # cmr10 A-V pair kerns
        assert all(not k.italic_correction for k in kerns)

    def test_explicit_kern_is_not_an_italic_correction(self) -> None:
        nodes = _collect_par_nodes(r"a\kern3pt b")
        kerns = [n for n in nodes if isinstance(n, KernNode)]
        assert kerns
        assert all(not k.italic_correction for k in kerns)
