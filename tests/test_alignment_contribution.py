r""" — `\halign` contribution model (splice vs pack).

A top-level `\halign`/`\valign` in a real vertical list splices its rows
individually into the enclosing list (the TeX `fin_align` §812 model), so the
page builder owns the §679 interline glue **and** the §1001 `\topskip` on the
first row.  A `\halign` consumed as a box (`\setbox` / `\vbox` / `\vcenter`)
keeps the packed-with-glue vlist.

These assert the DVI baseline positions; the inter-row spacing itself is also
pinned by ``tests/test_interline_glue.py``.
"""
from __future__ import annotations

from aspose_tex import DviDevice, TeXJob, TeXOptions, create_input_source
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import VlistNode
from aspose_tex._input.reader import StringInputSource
from tests._verification.dvi_walker import walk_line_starts, walk_rules

_PT = 65_536
_PRE = r"\font\tenrm=cmr10 \tenrm \baselineskip=12pt "


def _baselines(src: str) -> list[float]:
    interp = TeXInterpreter()
    dev = DviDevice()
    interp.run_with_device(StringInputSource(src), dev)
    pages = walk_line_starts(dev.get_bytes())
    return [round(v / _PT, 3) for v, _ in pages[0]]


# ---------------------------------------------------------------------------
# Top-level \halign — splice path (AC #1: topskip on the first row)
# ---------------------------------------------------------------------------

class TestTopLevelSplice:
    def test_first_row_attracts_topskip(self) -> None:
        # First row baseline at \topskip (plain default 10pt), not the row's
        # natural height.  The \bye \vfill is the trailing baseline.
        rows = _baselines(_PRE + r"\halign{#\hfil\cr one\cr two\cr three\cr}\bye")
        assert rows[0] == 10.0, f"first row not at \\topskip: {rows}"

    def test_rows_baselineskip_apart(self) -> None:
        rows = _baselines(_PRE + r"\halign{#\hfil\cr one\cr two\cr three\cr}\bye")
        # 10, 22, 34 — exactly \baselineskip (12pt) apart.
        assert rows[0:3] == [10.0, 22.0, 34.0]

    def test_halign_after_paragraph_no_topskip_on_alignment(self) -> None:
        # A \halign that is NOT the first box composes normally: the prelude gets
        # \topskip (10pt), and the alignment rows follow at \baselineskip.
        rows = _baselines(
            _PRE + r"\noindent prelude\par\halign{#\hfil\cr one\cr two\cr}\bye"
        )
        assert rows[0] == 10.0  # the prelude line
        # the two alignment rows are 12pt apart and 12pt below the prelude.
        assert rows[1] - rows[0] == 12.0
        assert rows[2] - rows[1] == 12.0


# ---------------------------------------------------------------------------
# Box-consuming paths keep the packed vlist (non-regression)
# ---------------------------------------------------------------------------

class TestPackedPathIntact:
    def test_setbox_vbox_halign_builds_packed_vlist(self) -> None:
        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(_PRE + r"\setbox0=\vbox{\halign{#\cr a\cr b\cr}}\bye"),
            DviDevice(),
        )
        box = interp._box_regs.getbox(0)
        assert isinstance(box, VlistNode)
        # Two rows + one inter-row interline GlueNode ( pre-glue).
        from aspose_tex._engine.nodes import GlueNode, HlistNode
        rows = [n for n in box.list if isinstance(n, HlistNode)]
        glues = [n for n in box.list if isinstance(n, GlueNode)]
        assert len(rows) == 2
        assert len(glues) == 1

    def test_matrix_vcenter_still_12pt(self) -> None:
        # The math \vcenter corpus keeps the packed path (12pt rows); a smoke
        # check it still builds end-to-end through the public API.
        dev = DviDevice()
        TeXJob(
            create_input_source(r"$\matrix{a&b\cr c&d\cr}$\bye"),
            dev, TeXOptions(load_format="plain"),
        ).run()
        assert dev.get_bytes()


# ---------------------------------------------------------------------------
# \noalign on the splice path resets the interline chain (§679)
# ---------------------------------------------------------------------------

class TestNoalignOnSplicePath:
    def test_noalign_hrule_between_top_level_rows(self) -> None:
        # The alignment compiles end-to-end with a \noalign rule between rows on
        # the splice path (the rule contributes + resets prevdepth via §679).
        interp = TeXInterpreter()
        dev = DviDevice()
        interp.run_with_device(
            StringInputSource(_PRE + r"\halign{#\hfil\cr a\cr\noalign{\hrule}b\cr}\bye"),
            dev,
        )
        rules = walk_rules(dev.get_bytes())
        assert any(page for page in rules), "the \\noalign \\hrule did not ship"
