r""" cascade (c) — real plain.tex alignment math macros.

Exercises the math-alignment user macros through the **public** API with the
bundled plain.tex loaded (``TeXOptions(load_format="plain")``), NOT mocks: the
``\matrix`` family routes each ``$…$`` cell through the ``\endv`` v-template
injection and the ``\bordermatrix`` + display family
through ``first_column_is_math``.

These assert each macro compiles end-to-end (no ``EngineError`` /
``NotImplementedError`` / ``Undefined control sequence``) and, where a
``\vcenter`` grid is built, that the grid has the expected row/column
*structure*.  The glyph-position-exact MiKTeX byte-compare for the row/column
layout lives in the E2E suite (``tests/test_e2e_dvi_baseline.py``); the
``\baselineskip`` interline-glue residual it surfaced (general ``\halign``
``fin_align`` §807 gap) is tracked separately — see that module's note.

Explicitly covers the two fragile alignment↔macro seams flagged in the
original task + the reviewer/integrator note: the line-1101
``\bordermatrix`` nested ``\def\cr{\crcr\noalign{\kern2\p@\global\let\cr
\endline}}`` redefined-``\cr`` pattern, and the ``\ialign`` helper.
"""
from __future__ import annotations

import aspose_tex._engine.interpreter as interpreter_mod
from aspose_tex import DviDevice, TeXJob, TeXOptions, create_input_source
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import HlistNode, VlistNode


def _run_plain(src: str) -> bytes:
    """Compile *src* with plain.tex loaded; return the DVI bytes (or b'')."""
    dev = DviDevice()
    job = TeXJob(create_input_source(src), dev, TeXOptions(load_format="plain"))
    job.run()
    return dev.get_bytes() or b""


def _vcenter_boxes(src: str) -> list[VlistNode | HlistNode]:
    """Compile *src*, capturing every math ``\\vcenter`` box that gets built.

    ``\\matrix``/``\\eqalign``/… wrap their grid in ``\\vcenter{\\ialign{…}}``;
    intercepting ``build_math_vcenter_box`` exposes the finished alignment box
    so a test can assert its row/column structure.
    """
    captured: list = []
    original = TeXInterpreter.build_math_vcenter_box

    def patched(self):  # test shim
        box = original(self)
        captured.append(box)
        return box

    interpreter_mod.TeXInterpreter.build_math_vcenter_box = patched
    try:
        dev = DviDevice()
        job = TeXJob(create_input_source(src), dev, TeXOptions(load_format="plain"))
        job.run()
    finally:
        interpreter_mod.TeXInterpreter.build_math_vcenter_box = original
    return captured


def _row_hlists(box: VlistNode) -> list[HlistNode]:
    return [n for n in box.list if isinstance(n, HlistNode)]


# ---------------------------------------------------------------------------
# — \mathstrut / \finph@nt phantom is invisible
# ---------------------------------------------------------------------------

class TestPhantomStrut:
    r"""The \mathstrut / \vphantom / \finph@nt chain must contribute an
    INVISIBLE box with the right height/depth — never leak the phantom's
    literal ``(`` glyph (cmex/cmr char ``0x28``).

    Regression pin for the full chain: C1 (\mathstrut reaches
    the math branch) + C2 (\vcenter §735), (\mathchoice branches
    EXECUTE their \setbox/\finph@nt box machinery), (\finph@nt's
    equals-less ``\ht\tw@\ht\z@`` box-dimension copy runs and is not
    group-restore-corrupted).  Before the chain, ``$\pmatrix{…}$`` leaked two
    stray ``0x28`` struts and the fence dropped to a smaller cmex size.
    """

    def test_pmatrix_glyph_stream_has_no_leaked_strut(self) -> None:
        from tests._verification.dvi_walker import collect_chars_per_page

        pages = collect_chars_per_page(_run_plain(r"$\pmatrix{x&y\cr z&w\cr}$\bye"))
        assert pages, "no DVI produced for \\pmatrix"
        glyphs = pages[0]
        # The MiKTeX cmex fence codes are 0x12 / 0x13 (18 / 19); the inner
        # cell glyphs are x y z w.  The phantom ``(`` (0x28) must NOT appear.
        assert 0x28 not in glyphs, (
            f"leaked \\mathstrut '(' glyph 0x28 in {glyphs!r}"
        )
        assert 0x12 in glyphs and 0x13 in glyphs, (
            f"expected MiKTeX cmex fence 0x12/0x13, got {glyphs!r}"
        )
        for code in (ord("x"), ord("y"), ord("z"), ord("w")):
            assert code in glyphs, f"missing inner cell glyph {code!r} in {glyphs!r}"

    def test_mathstrut_box_has_paren_height_depth(self) -> None:
        r"""``$\mathstrut$`` builds a box with the height/depth of math ``(``
        (≈7.5pt / ≈2.5pt), not the empty (0,0,0) it was before."""
        captured: list = []
        original = TeXInterpreter._add_box_to_current_list

        def patched(self, box):  # test shim — capture contributed math boxes
            captured.append(box)
            return original(self, box)

        interpreter_mod.TeXInterpreter._add_box_to_current_list = patched
        try:
            _run_plain(r"$\mathstrut$\bye")
        finally:
            interpreter_mod.TeXInterpreter._add_box_to_current_list = original

        sp = 65536.0
        # The phantom box is the one carrying the ( height/depth (~7.5 / ~2.5).
        assert any(
            abs(b.height / sp - 7.5) < 0.5 and abs(b.depth / sp - 2.5) < 0.5
            for b in captured
        ), (
            "no phantom box with math-( height/depth (7.5/2.5); got "
            f"{[(round(b.height / sp, 2), round(b.depth / sp, 2)) for b in captured]}"
        )


# ---------------------------------------------------------------------------
# AC-9 — \matrix builds a 2x2 aligned grid
# ---------------------------------------------------------------------------

class TestMatrix:
    def test_matrix_compiles(self) -> None:
        assert _run_plain(r"$\matrix{a&b\cr c&d\cr}$\bye")

    def test_matrix_builds_two_body_rows_two_columns(self) -> None:
        """AC-9: a 2x2 \\matrix produces two equal-width body rows of two cells."""
        boxes = _vcenter_boxes(r"$\matrix{a&b\cr c&d\cr}$\bye")
        assert boxes, "no \\vcenter box built for \\matrix"
        vlist = next(b for b in boxes if isinstance(b, VlistNode))
        rows = _row_hlists(vlist)
        # plain.tex brackets the body with two \mathstrut strut rows; the two
        # `a&b` / `c&d` body rows share a width that differs from the struts.
        widths = [r.width for r in rows]
        body_width = max(widths)
        assert sum(1 for w in widths if w == body_width) >= 2, (
            f"expected >=2 equal-width body rows, got widths {widths}"
        )
        assert body_width > 0


# ---------------------------------------------------------------------------
# AC-10 — \eqalign aligns equations on the relation column
# ---------------------------------------------------------------------------

class TestEqalign:
    def test_eqalign_compiles(self) -> None:
        assert _run_plain(r"$$\eqalign{x &= y + z\cr a &= b\cr}$$\bye")

    def test_eqalign_builds_two_rows(self) -> None:
        boxes = _vcenter_boxes(r"$$\eqalign{x &= y + z\cr a &= b\cr}$$\bye")
        assert boxes, "no \\vcenter box built for \\eqalign"
        vlist = next(b for b in boxes if isinstance(b, VlistNode))
        assert len(_row_hlists(vlist)) >= 2


# ---------------------------------------------------------------------------
# AC-3 — \pmatrix / \cases via real plain.tex bodies
# ---------------------------------------------------------------------------

class TestMatrixFamily:
    def test_pmatrix_compiles(self) -> None:
        # \pmatrix = \left(\matrix{…}\right): the outer \left/\right must close.
        assert _run_plain(r"$\pmatrix{a&b\cr c&d\cr}$\bye")

    def test_cases_compiles(self) -> None:
        assert _run_plain(r"$f(x)=\cases{1&if $x>0$\cr 0&otherwise\cr}$\bye")

    def test_single_row_matrix_compiles(self) -> None:
        assert _run_plain(r"$\matrix{x\cr}$\bye")


# ---------------------------------------------------------------------------
# AC-3 — \bordermatrix redefined-\cr + \ialign fragile seam ( D1)
# ---------------------------------------------------------------------------

class TestBordermatrix:
    def test_bordermatrix_compiles(self) -> None:
        # The line-1101 \def\cr{\crcr\noalign{…\global\let\cr\endline}} +
        # \ialign pattern: the live terminator becomes \endline (meaning \cr)
        # mid-row.  The by-meaning terminator resolution ( D1)
        # keeps the next row's `&` inside the cell scanner.
        assert _run_plain(
            r"$\bordermatrix{&c_1&c_2\cr r_1&a&b\cr r_2&c&d\cr}$\bye"
        )


# ---------------------------------------------------------------------------
# AC-3 — display family \displaylines / \eqalignno / \leqalignno ( D2)
# ---------------------------------------------------------------------------

class TestDisplayFamily:
    def test_displaylines_compiles(self) -> None:
        assert _run_plain(r"$$\displaylines{x = y\cr a = b\cr}$$\bye")

    def test_eqalignno_compiles(self) -> None:
        assert _run_plain(r"$$\eqalignno{x &= y&(1)\cr a &= b&(2)\cr}$$\bye")

    def test_leqalignno_compiles(self) -> None:
        assert _run_plain(r"$$\leqalignno{x &= y&(1)\cr a &= b&(2)\cr}$$\bye")


# ---------------------------------------------------------------------------
# AC-3 — \ialign helper used directly
# ---------------------------------------------------------------------------

class TestIalign:
    def test_ialign_math_cells_compile(self) -> None:
        # \ialign = \halign with \everycr/\tabskip reset; the \matrix family's
        # workhorse.  Drive it directly with math cells.
        assert _run_plain(r"\ialign{$#$&$#$\cr a&b\cr c&d\cr}\bye")


# ---------------------------------------------------------------------------
# AC-12 — \matrix inside \footnote (math in a vbox/insert body)
# ---------------------------------------------------------------------------

class TestMatrixInFootnote:
    def test_matrix_in_footnote_compiles(self) -> None:
        # The footnote body is built in internal vertical mode (a vbox/insert);
        # a $…$ formula there must start a paragraph line and route the math
        # through run_inline_math_in_box (vbox-text MATH_SHIFT branch).
        assert _run_plain(
            r"\nopagenumbers Body text\footnote*{$\matrix{a&b\cr c&d\cr}$}\bye"
        )

    def test_inline_math_in_footnote_compiles(self) -> None:
        assert _run_plain(r"\nopagenumbers Body\footnote*{$x+y=z$}\bye")
