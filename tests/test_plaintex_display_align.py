r""" — non-``\vcenter`` math ``\halign`` end-to-end.

The two macro families carved out (their ``\halign`` runs WITHOUT a
math ``\vcenter``, so ``_alignment_math_context == 0``):

* **``\bordermatrix``** — eager ``\setbox\z@\vbox{…\ialign{$##$…}}`` plus the
  pre-existing ``\let``-alias ``\cr`` self-cycle (C1) + the eager-path math-cell
  signal (C2/C3 via the preamble ``$``-test).
* **display family** ``\displaylines`` / ``\eqalignno`` / ``\leqalignno`` — a
  top-level display ``\halign`` whose cells wrap the math in an ``\hbox``
  (C4 cross-scanner terminator propagation) or a ``\rlap`` macro-arg brace
  (C5 raw cell-body assembly).

These assert end-to-end build + grid/glyph structure via the DVI walker; the
MiKTeX glyph-position byte-compare lands downstream in.
"""
from __future__ import annotations

from aspose_tex import DviDevice, TeXJob, TeXOptions, create_input_source
from tests._verification.dvi_walker import walk_chars_with_positions


def _run_plain(src: str) -> bytes:
    dev = DviDevice()
    job = TeXJob(create_input_source(src), dev, TeXOptions(load_format="plain"))
    job.run()
    return dev.get_bytes() or b""


def _chars(dvi: bytes) -> list[tuple[int, int, int]]:
    """All ``(char_code, h, v)`` across pages."""
    out: list[tuple[int, int, int]] = []
    for page in walk_chars_with_positions(dvi):
        out.extend(page)
    return out


class TestBorderMatrix:
    def test_no_hang_and_builds(self) -> None:
        # AC #1: the pre-existing \cr-self-cycle hang is gone and the eager
        # \setbox\vbox math \halign builds (C1 + C2/C3).  A bounded run is the
        # hang regression guard (pytest would otherwise never return).
        dvi = _run_plain(r"$\bordermatrix{&1\cr a&x\cr}$\bye")
        assert dvi

    def test_builds_a_grid(self) -> None:
        # AC #1/#2: the $##$ cells terminate at \cr (no "alignment tab outside"
        # / "display math not allowed") and a real grid is built — the border
        # label `1`, the row label `a`, and the body `x` occupy distinct rows.
        dvi = _run_plain(r"$\bordermatrix{&1\cr a&x\cr}$\bye")
        chars = _chars(dvi)
        assert chars, "no glyphs shipped for \\bordermatrix"
        vs = {v for _c, _h, v in chars}
        assert len(vs) >= 2, f"expected >=2 distinct row baselines, got {sorted(vs)}"


class TestDisplaylines:
    def test_builds_two_centred_lines(self) -> None:
        # AC #3/#4: the \hbox-cell straddle (`\hbox to\displaywidth{$…$}`)
        # terminates at the top-level \cr (C4) — two display lines.
        dvi = _run_plain(r"$$\displaylines{x=y\cr a=b\cr}$$\bye")
        chars = _chars(dvi)
        assert chars
        vs = sorted({v for _c, _h, v in chars})
        assert len(vs) >= 2, f"expected >=2 display lines, got baselines {vs}"
        codes = {c for c, _h, _v in chars}
        # both lines' content present: x,y (line 1) and a,b (line 2).
        assert {ord("x"), ord("y"), ord("a"), ord("b")} <= codes


class TestEqAlignNo:
    def test_eqalignno_builds_with_number_column(self) -> None:
        # AC #4: \eqalignno's \llap{$\@lign##$} equation-number column builds
        # and the number `(1)` ships.
        dvi = _run_plain(r"$$\eqalignno{x&=y&(1)\cr}$$\bye")
        codes = {c for c, _h, _v in _chars(dvi)}
        assert {ord("x"), ord("y"), ord("("), ord("1"), ord(")")} <= codes

    def test_leqalignno_builds_with_number_column(self) -> None:
        # AC #4: \leqalignno's \kern-\displaywidth\rlap{$\@lign##$} number
        # column is the C5 macro-arg straddle (the \rlap macro grabs `{…}`
        # across the cell terminator); it must build with the number shipped.
        dvi = _run_plain(r"$$\leqalignno{x&=y&(1)\cr}$$\bye")
        codes = {c for c, _h, _v in _chars(dvi)}
        assert {ord("x"), ord("y"), ord("("), ord("1"), ord(")")} <= codes


class TestNoRegressionHbox:
    def test_single_line_displaylines_terminates(self) -> None:
        # AC #3 minimal: a one-line \displaylines whose only cell is the bare
        # `\hbox to\displaywidth{$…$}` terminates at the top-level \cr with no
        # "unexpected }" (the C4 cross-scanner propagation).  Uses the real
        # macro so the `@`-letter internals are loaded by plain.tex.
        dvi = _run_plain(r"$$\displaylines{a=b\cr}$$\bye")
        assert dvi


class TestDisplaylinesHorizontalCentring:
    r""" — a ``\displaylines`` row is centred once, not twice.

    The cell template is ``\hbox to\displaywidth{$\@lign\hfil\displaystyle##\hfil$}``
    (plain.tex:1127) — one ``\hfil`` on each side of the formula.  Both live
    *inside* the ``$…$``, so before both were appended to the enclosing
    hlist ahead of the formula, giving two adjacent leading fils: the row's
    glyphs landed at twice their correct offset (431.111 pt vs MiKTeX's
    215.556 pt).
    """

    # The reproducer verbatim.  Deliberately no \vsize: forcing a page
    # break through \plainoutput trips a pre-existing, unrelated
    # "\prevdepth only valid in vertical mode" ( AC-6).
    _SRC = (
        "\\nopagenumbers\n"
        "\\noindent\n"
        "lead\n"
        "$$\\displaylines{r = s + t\\cr m = n\\cr}$$\n"
        "tail\n"
        "\\par\n"
        "\\bye\n"
    )

    def test_row_glyphs_match_miktex_horizontally(self) -> None:
        # MiKTeX 24.4 dvitype on this exact source: 'r' at 215.556 pt, 'm' at
        # 220.820 pt.  The pre- engine gave 431.111 / 441.639.
        chars = _chars(_run_plain(self._SRC))
        by_code = {c: h for c, h, _v in chars}
        assert round(by_code[ord("r")] / 65536, 3) == 215.556
        assert round(by_code[ord("m")] / 65536, 3) == 220.820

    def test_cell_has_one_fil_on_each_side_of_the_formula(self) -> None:
        # The structural statement of the fix, independent of TFM arithmetic:
        # the centring glue is balanced rather than both on the leading side.
        from aspose_tex._engine import alignment
        from aspose_tex._engine.nodes import CharNode, GlueNode

        rows: list = []
        original = alignment._emit_row

        def _cap(state, row):
            box = original(state, row)
            rows.append(box)
            return box

        alignment._emit_row = _cap  # type: ignore[assignment]
        try:
            _run_plain(self._SRC)
        finally:
            alignment._emit_row = original  # type: ignore[assignment]

        assert rows, r"no \displaylines rows were emitted"

        def innermost(node):
            """Descend to the hbox that directly holds the row's glyphs."""
            kids = getattr(node, "list", []) or []
            for child in kids:
                found = innermost(child)
                if found is not None:
                    return found
            if any(isinstance(k, CharNode) for k in kids):
                return node
            return None

        cell = innermost(rows[0])
        assert cell is not None, "no glyph-bearing hbox inside the row"
        kinds = [
            "char" if isinstance(n, CharNode)
            else "fil" if isinstance(n, GlueNode) and n.glue.stretch_order == 1
            else None
            for n in cell.list
        ]
        kinds = [k for k in kinds if k is not None]
        assert kinds[0] == "fil", rf"no leading \hfil: {kinds}"
        assert kinds[-1] == "fil", rf"no trailing \hfil: {kinds}"
        assert kinds.count("fil") == 2, f"expected exactly two fils: {kinds}"


class TestEqalignnoStaysExact:
    r""" AC-4 — ``\eqalignno``'s ``\hfil``s are OUTSIDE the ``$``.

    They are handled by the alignment cell's hbox scanner in written order and
    never reach the math list, which is why the family was already horizontally
    exact (``\eqno`` column dH -0.0001 pt) and must not move.
    """

    def test_eqno_column_is_flush_right(self) -> None:
        src = (
            "\\hsize=6.5in\n"
            "\\nopagenumbers\n"
            "\\noindent\n"
            "lead\n"
            "$$\\eqalignno{u &= v + w&(1)\\cr p &= q&(2)\\cr}$$\n"
            "tail\n"
            "\\par\n"
            "\\bye\n"
        )
        chars = _chars(_run_plain(src))
        opens = [h for c, h, _v in chars if c == ord("(")]
        assert opens, "no equation-number parenthesis shipped"
        # MiKTeX puts the '(' of (1) at 456.9772 pt; we are within the
        # +/-0.1 pt H bound of it.
        assert abs(opens[0] / 65536 - 456.9772) < 0.1
