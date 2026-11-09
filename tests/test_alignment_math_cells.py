r"""`\endv` v-template injection for math `\halign` cells.

The real-TeX `\endv` model (TeX:The Program §324/§789/§1131) for math
``\halign`` cells built inside a math ``\vcenter`` body
(``build_math_vcenter_box``).  Two gaps closed:

* **Gap A** — a *bare* math cell (``\matrix``'s strut row ``\mathstrut\crcr``,
  no ``$`` of its own) must scan so ``\mathstrut``→``\mathchoice`` is a legal
  math atom, not ``EngineError: Unexpected token in hbox: \mathchoice``.
* **Gap B** — a u/v template that straddles ``$`` *and* an open ``{`` across the
  cell terminator (``\eqalign``'s ``$\displaystyle{##}$``) must terminate the
  cell at the top-level ``&``/``\cr`` (the v-template ``}$`` injected ahead of
  the terminator), not ``EngineError: alignment tab outside \halign/\valign``.

These assert grid *structure* (rows x cells via the contributed ``\vcenter``
vlist); the MiKTeX glyph-position byte-compare lands downstream.
"""
from __future__ import annotations

import aspose_tex._engine.interpreter as interpreter_mod
from aspose_tex import DviDevice, TeXJob, TeXOptions, create_input_source
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import HlistNode, VlistNode
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice as _DviDevice


def _run_plain(src: str) -> bytes:
    """Compile *src* with plain.tex loaded; return the DVI bytes."""
    dev = DviDevice()
    job = TeXJob(create_input_source(src), dev, TeXOptions(load_format="plain"))
    job.run()
    return dev.get_bytes() or b""


def _vcenter_boxes(src: str) -> list[VlistNode | HlistNode]:
    """Compile *src*, capturing every math ``\\vcenter`` box that gets built.

    The ``\\matrix``/``\\eqalign``/… family wraps its grid in
    ``\\vcenter{\\ialign{…}}``; intercepting ``build_math_vcenter_box`` exposes
    the finished alignment box so a test can assert its row/column structure.
    """
    captured: list = []
    original = TeXInterpreter.build_math_vcenter_box

    def patched(self):
        box = original(self)
        captured.append(box)
        return box

    interpreter_mod.TeXInterpreter.build_math_vcenter_box = patched
    try:
        dev = _DviDevice()
        job = TeXJob(
            create_input_source(src), dev, TeXOptions(load_format="plain"),
        )
        job.run()
    finally:
        interpreter_mod.TeXInterpreter.build_math_vcenter_box = original
    return captured


def _row_hlists(box: VlistNode) -> list[HlistNode]:
    return [n for n in box.list if isinstance(n, HlistNode)]


# ---------------------------------------------------------------------------
# Gap A — bare-math cell (\matrix strut row \mathstrut\crcr)
# ---------------------------------------------------------------------------

class TestGapABareMathCell:
    def test_matrix_builds_no_mathchoice_error(self) -> None:
        # The very repro that raised `Unexpected token in hbox: \mathchoice`
        # (the strut row's bare \mathstrut) now compiles end-to-end.
        assert _run_plain(r"$\matrix{a&b\cr c&d\cr}$\bye")

    def test_matrix_builds_real_2x2_grid(self) -> None:
        # AC #5: the body rows are distinct from the strut rows (different
        # natural width), proving two real grid rows x two columns — not one
        # flat run.  The two `a&b` / `c&d` rows share a width that differs from
        # the zero-content strut rows.
        boxes = _vcenter_boxes(r"$\matrix{a&b\cr c&d\cr}$\bye")
        assert boxes, "no \\vcenter box was built for \\matrix"
        vlist = next(b for b in boxes if isinstance(b, VlistNode))
        rows = _row_hlists(vlist)
        # plain.tex \matrix brackets the body with two \mathstrut strut rows.
        widths = [r.width for r in rows]
        body_width = max(widths)
        body_rows = [w for w in widths if w == body_width]
        assert len(body_rows) >= 2, (
            f"expected >=2 equal-width body rows, got widths {widths}"
        )
        assert body_width > 0


# ---------------------------------------------------------------------------
# Gap B — $/{ straddle (\eqalign template $\displaystyle{##}$)
# ---------------------------------------------------------------------------

class TestGapBStraddleTemplate:
    def test_eqalign_one_row_no_alignment_tab_error(self) -> None:
        # The repro that raised `alignment tab outside \halign/\valign` (the
        # user's `&` arriving while the u-template's `{` is still open).
        assert _run_plain(r"$\eqalign{x&=y\cr}$\bye")

    def test_eqalign_two_rows_build(self) -> None:
        boxes = _vcenter_boxes(r"$\eqalign{x&=y+z\cr a&=b\cr}$\bye")
        assert boxes, "no \\vcenter box was built for \\eqalign"
        vlist = next(b for b in boxes if isinstance(b, VlistNode))
        rows = _row_hlists(vlist)
        # Two equation rows (each a `lhs & = rhs` cell pair).
        assert len(rows) >= 2


# ---------------------------------------------------------------------------
# The \vcenter math corpus builds grids (AC #5)
# ---------------------------------------------------------------------------

class TestVcenterMathCorpus:
    def test_pmatrix_builds(self) -> None:
        # \pmatrix = \left(\matrix{…}\right): each cell is its own \left/\right
        # scope, so the outer \left must not trip "missing \right".
        assert _run_plain(r"$\pmatrix{a&b\cr c&d\cr}$\bye")

    def test_cases_builds(self) -> None:
        assert _run_plain(r"$\cases{a&b\cr c&d\cr}$\bye")

    def test_single_row_matrix_builds(self) -> None:
        assert _run_plain(r"$\matrix{x\cr}$\bye")


# ---------------------------------------------------------------------------
# Floor / non-regression — the simple cell + \big-family stay intact
# ---------------------------------------------------------------------------

class TestNonRegression:
    def test_simple_math_cell_still_builds(self) -> None:
        # The landed floor: a simple non-straddling `$#$` math cell with
        # an empty-v close-at-terminator (no injection).  Must still build.
        interp = TeXInterpreter()
        interp.run_with_device(
            StringInputSource(
                r"\font\tenrm=cmr10 \tenrm "
                r"\setbox0=\vbox{\halign{$#$&$#$\cr a&b\cr}}\bye"
            ),
            DviDevice(),
        )
        box = interp._box_regs.getbox(0)
        assert isinstance(box, VlistNode)

    def test_big_family_inline_math_in_hbox_unaffected(self) -> None:
        # The \big-family $-in-\hbox path runs at _alignment_cell_depth
        # 0, so the v-template injection branch is never taken — it must remain
        # intact.  `\bigl`/`\bigr` are plain.tex macros expanding to the
        # \hbox{$\left…$} barrier the pump owns.  A smoke check it still builds.
        assert _run_plain(r"$\bigl(x\bigr)$\bye")


# ---------------------------------------------------------------------------
# the preamble `$`-test raises _alignment_math_context off the
# \vcenter path (regression pin for first_column_is_math).
# ---------------------------------------------------------------------------

class TestPreambleMathSignal:
    def test_math_first_column_signals_math_context(self) -> None:
        from aspose_tex._engine.alignment import (
            _AlignmentState,
            _ColumnTemplate,
            first_column_is_math,
        )
        from aspose_tex._input.catcode import Catcode
        from aspose_tex._input.token import CharToken

        math_u = _ColumnTemplate(
            u_tokens=[CharToken("$", Catcode.MATH_SHIFT)], v_tokens=[],
        )
        state = _AlignmentState(
            templates=[math_u], tabskip=[], rows=[], column_width=[],
            vertical=False,
        )
        assert first_column_is_math(state) is True

    def test_text_first_column_is_not_math(self) -> None:
        from aspose_tex._engine.alignment import (
            _AlignmentState,
            _ColumnTemplate,
            first_column_is_math,
        )
        from aspose_tex._input.catcode import Catcode
        from aspose_tex._input.token import CharToken

        text_u = _ColumnTemplate(
            u_tokens=[CharToken("x", Catcode.LETTER)], v_tokens=[],
        )
        state = _AlignmentState(
            templates=[text_u], tabskip=[], rows=[], column_width=[],
            vertical=False,
        )
        assert first_column_is_math(state) is False
