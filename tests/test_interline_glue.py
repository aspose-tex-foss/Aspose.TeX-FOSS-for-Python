r""" — §679 interline glue helper + `\halign` inter-row glue.

Unit-tests ``box_builder.compute_interline_glue`` (the four TeX:The Program
§679 branches) and integration-tests that ``\halign`` / ``\valign`` now insert
``\baselineskip`` / ``\lineskip`` interline glue between row boxes (the
``fin_align`` §807 gap's MiKTeX byte-compare surfaced).
"""
from __future__ import annotations

from aspose_tex import DviDevice, TeXJob, TeXOptions, create_input_source
from aspose_tex._engine.box_builder import (
    IGNORE_PREV_DEPTH,
    compute_interline_glue,
)
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import GlueNode, HlistNode, VlistNode
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._input.reader import StringInputSource

_PT = 65_536


def _glue(width_pt: float, stretch_pt: float = 0.0) -> Glue:
    return Glue(
        round(width_pt * _PT),
        round(stretch_pt * _PT), GlueOrder.NORMAL,
        0, GlueOrder.NORMAL,
    )


# ---------------------------------------------------------------------------
# Unit — compute_interline_glue (§679, Component 1)
# ---------------------------------------------------------------------------

class TestComputeInterlineGlue:
    def test_ignore_prev_depth_returns_none(self) -> None:
        assert compute_interline_glue(
            prev_depth=IGNORE_PREV_DEPTH,
            next_height=5 * _PT,
            baselineskip=_glue(12),
            lineskip=_glue(1),
            lineskiplimit=0,
        ) is None

    def test_below_ignore_marker_returns_none(self) -> None:
        assert compute_interline_glue(
            prev_depth=IGNORE_PREV_DEPTH - 1,
            next_height=5 * _PT,
            baselineskip=_glue(12),
            lineskip=_glue(1),
            lineskiplimit=0,
        ) is None

    def test_baselineskip_branch_width_and_flex(self) -> None:
        # ideal = 12 - 2 - 7 = 3pt >= lineskiplimit(0) → baselineskip path.
        g = compute_interline_glue(
            prev_depth=2 * _PT,
            next_height=7 * _PT,
            baselineskip=_glue(12, stretch_pt=3),
            lineskip=_glue(1),
            lineskiplimit=0,
        )
        assert g is not None
        assert g.width == 3 * _PT
        # baselineskip's stretch/shrink are preserved on the interline glue.
        assert g.stretch == 3 * _PT

    def test_lineskip_branch_when_too_close(self) -> None:
        # ideal = 12 - 11 - 5 = -4pt < lineskiplimit(0) → lineskip verbatim.
        lineskip = _glue(1)
        g = compute_interline_glue(
            prev_depth=11 * _PT,
            next_height=5 * _PT,
            baselineskip=_glue(12),
            lineskip=lineskip,
            lineskiplimit=0,
        )
        assert g is lineskip

    def test_boundary_ideal_equals_lineskiplimit_takes_baselineskip(self) -> None:
        # §679 uses strict `<`, so ideal == lineskiplimit → baselineskip path.
        g = compute_interline_glue(
            prev_depth=0,
            next_height=10 * _PT,
            baselineskip=_glue(12),
            lineskip=_glue(1),
            lineskiplimit=2 * _PT,  # ideal = 12 - 0 - 10 = 2 == limit
        )
        assert g is not None
        assert g.width == 2 * _PT


# ---------------------------------------------------------------------------
# Integration — \halign inserts inter-row interline glue (§807)
# ---------------------------------------------------------------------------

def _halign_vlist(prelude: str, body: str) -> VlistNode:
    """Run a \\halign through the box scanner and return its result vlist.

    *prelude* sets the interline parameters (e.g. ``\\baselineskip=12pt``)
    before the alignment; *body* is the ``\\halign{…}`` text.  Uses a bare
    interpreter (no plain.tex) so the parameters are set with primitives.
    """
    interp = TeXInterpreter()
    interp.run_with_device(
        StringInputSource(
            r"\font\tenrm=cmr10 \tenrm " + prelude
            + r"\setbox0=\vbox{" + body + r"}\bye"
        ),
        DviDevice(),
    )
    box = interp._box_regs.getbox(0)
    assert isinstance(box, VlistNode)
    # exec_vbox splices the \halign row hboxes (and their inter-row interline
    # glue) directly into the enclosing \vbox — they are not wrapped in a nested
    # vlist — so the outer box.list IS the row stack.
    return box


_BSK12 = r"\baselineskip=12pt \lineskip=1pt \lineskiplimit=0pt "


class TestInterRowGlue:
    def test_glue_between_text_halign_rows(self) -> None:
        # Two rows at \baselineskip = 12pt get a GlueNode between the row hboxes
        # whose width is the §679 ideal (baselineskip - prev.depth - next.height).
        v = _halign_vlist(_BSK12, r"\halign{#\hfil\cr aa\cr bb\cr}")
        rows = [n for n in v.list if isinstance(n, HlistNode)]
        glues = [n for n in v.list if isinstance(n, GlueNode)]
        assert len(rows) == 2
        # Exactly one interline glue (before the 2nd row; none before the 1st).
        assert len(glues) == 1
        assert 0 < glues[0].glue.width <= 12 * _PT

    def test_no_glue_before_first_row(self) -> None:
        v = _halign_vlist(_BSK12, r"\halign{#\hfil\cr only\cr}")
        # Single row → no interline glue at all.
        assert not any(isinstance(n, GlueNode) for n in v.list)

    def test_offinterlineskip_config_collapses_interline(self) -> None:
        # The \offinterlineskip configuration (\baselineskip=\lineskip=0,
        # \lineskiplimit huge so every gap takes the zero \lineskip): rows touch.
        v = _halign_vlist(
            r"\baselineskip=0pt \lineskip=0pt \lineskiplimit=16383pt ",
            r"\halign{#\hfil\cr aa\cr bb\cr}",
        )
        glues = [n for n in v.list if isinstance(n, GlueNode)]
        assert all(g.glue.width == 0 for g in glues)

    def test_noalign_hrule_resets_interline_chain(self) -> None:
        # A \noalign{\hrule} between rows resets prevdepth (§679): the rule is a
        # non-box discardable.  The vlist still contains the rule.
        from aspose_tex._engine.nodes import RuleNode
        v = _halign_vlist(
            _BSK12, r"\halign{#\hfil\cr aa\cr\noalign{\hrule}bb\cr}"
        )
        assert any(isinstance(n, RuleNode) for n in v.list)


# ---------------------------------------------------------------------------
# \openup reaches the row stack (the in-group capture, Component 2)
# ---------------------------------------------------------------------------

class TestOpenupReachesRowStack:
    def test_interline_tracks_captured_baselineskip(self) -> None:
        # The interline width is driven by the \baselineskip CAPTURED in-group
        # ( C2), so a larger \baselineskip yields proportionally larger
        # interline glue: +6pt of \baselineskip → +6pt of inter-row glue.
        base = _halign_vlist(_BSK12, r"\halign{#\hfil\cr aa\cr bb\cr}")
        bigger = _halign_vlist(
            r"\baselineskip=18pt \lineskip=1pt \lineskiplimit=0pt ",
            r"\halign{#\hfil\cr aa\cr bb\cr}",
        )
        bg = next(n for n in base.list if isinstance(n, GlueNode))
        bigg = next(n for n in bigger.list if isinstance(n, GlueNode))
        assert bigg.glue.width == bg.glue.width + 6 * _PT

    def test_openup_jot_visible_through_plain_eqalign(self) -> None:
        # End-to-end proof that \openup\jot reaches the row stack: \eqalign does
        # \openup\jot inside its \vcenter body group; the resulting display rows
        # are \baselineskip + \jot (12 + 3 = 15pt) apart, not 12pt — captured
        # before the group close rolls the advance back ( C2).
        from tests._verification.dvi_walker import walk_line_starts
        dev = DviDevice()
        TeXJob(
            create_input_source(
                r"\hsize=6.5in\vsize=8.9in\nopagenumbers"
                r"$$\eqalign{x&=y\cr a&=b\cr}$$\bye"
            ),
            dev, TeXOptions(load_format="plain"),
        ).run()
        rows = walk_line_starts(dev.get_bytes())[0]
        # The two \eqalign rows are 15pt apart (\baselineskip 12 + \jot 3).
        deltas = [rows[i + 1][0] - rows[i][0] for i in range(len(rows) - 1)]
        assert any(abs(d - 15 * _PT) <= _PT // 2 for d in deltas), (
            f"expected a 15pt (=baselineskip+jot) inter-row gap, got "
            f"{[round(d / _PT, 3) for d in deltas]} pt"
        )


# ---------------------------------------------------------------------------
# Public-API smoke: the math-alignment macros still compile end-to-end
# ---------------------------------------------------------------------------

def _run_plain(src: str) -> bytes:
    dev = DviDevice()
    TeXJob(create_input_source(src), dev, TeXOptions(load_format="plain")).run()
    return dev.get_bytes() or b""


class TestMacrosStillBuild:
    def test_matrix_and_eqalign_still_build(self) -> None:
        assert _run_plain(r"$\matrix{a&b\cr c&d\cr}$\bye")
        assert _run_plain(r"$$\eqalign{x&=y\cr a&=b\cr}$$\bye")
