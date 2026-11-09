"""interword space after an inline ``$…$`` formula.

The space *after* the closing ``$`` of an inline formula was dropped whenever a
space also *preceded* the opening ``$``: ``_handle_space``'s ``_after_space``
collapse guard is cleared only by ``_handle_char``, and an inline formula never
routes through it, so the flag survived the formula and the trailing space was
early-returned away (TeX:The Program §1196 ``after_math``).

These tests drive the public DVI API on minimal ``word $x$ word`` sources and
assert, via the per-glyph position walker, that the interword glue after the
formula is present when a space precedes ``$`` (the fixed case) and that the
no-space-before / no-space-after shapes are unchanged (no-regression).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from aspose_tex import DviDevice, StringInputSource, TeXJob, TeXOptions

# Load the DVI position walker the e2e suite uses (shared verification helper).
_WALKER_PATH = Path(__file__).parent / "_verification" / "dvi_walker.py"
_spec = importlib.util.spec_from_file_location("_dvi_walker_trailing_space", _WALKER_PATH)
assert _spec and _spec.loader
_dvi_walker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dvi_walker)
walk_chars_with_positions = _dvi_walker.walk_chars_with_positions

# cmr10 interword space (\fontdimen2) — 3.33333 pt in sp; the amount the
# post-formula word shifts right when the trailing space is (correctly) emitted.
_CMR10_SPACE_SP = 218453
_TOL_SP = 200  # generous: distinguishes "space present" from "space dropped"


def _positions(body: str) -> list[tuple[int, int, int]]:
    """Compile ``\\noindent <body>\\par\\bye`` and return page-1 (code, h, v)."""
    src = f"\\hsize=6.5in\n\\nopagenumbers\n\\noindent\n{body}\n\\par\n\\bye"
    job = TeXJob(
        StringInputSource(src),
        DviDevice(),
        options=TeXOptions(load_format="plain"),
    )
    dvi = job.run()
    assert dvi is not None
    pages = walk_chars_with_positions(dvi)
    assert pages, "no page produced"
    return pages[0]


def _h_after_last(glyphs: list[tuple[int, int, int]], marker: str, follow: str) -> tuple[int, int]:
    """Return ``(h_of_last_marker, h_of_next_follow_glyph)``.

    Locates the last ``marker`` glyph (the formula's typeset char) and the very
    next ``follow`` glyph after it *by list order* — the position walker reports
    abutting glyphs at the same reference h, so an h-threshold filter is unsafe;
    list order is the reliable "what comes after the formula" signal.
    """
    m_code, f_code = ord(marker), ord(follow)
    last_marker_idx = max(i for i, (c, _h, _v) in enumerate(glyphs) if c == m_code)
    marker_h = glyphs[last_marker_idx][1]
    for c, h, _v in glyphs[last_marker_idx + 1:]:
        if c == f_code:
            return marker_h, h
    raise AssertionError(f"glyph {follow!r} not found after last {marker!r}")


class TestInlineMathTrailingSpace:
    """AC-1/AC-4: the trailing space is emitted iff the input has one."""

    def test_space_before_and_after_dollar_keeps_trailing_space(self) -> None:
        """Space before AND after ``$x$`` → the word after ``$`` is one space right.

        The originally-dropped case: compare ``a $x$ bb`` against the
        no-space-before control ``a$x$ bb`` — both have a trailing space, so the
        ``b`` after the formula must land at the *same* h in both.  Before the
        fix the space-before variant lost the trailing glue and ``b`` sat one
        cmr10 space left.
        """
        x_with, b_with = _h_after_last(_positions(r"a $x$ bb"), "x", "b")
        x_no, b_no = _h_after_last(_positions(r"a$x$ bb"), "x", "b")

        # Both inputs have a trailing space, so the gap from the formula 'x' to
        # the following 'b' must match: the space-before variant must not lose
        # the trailing glue (the bug shrank its gap by one cmr10 space).
        gap_with = b_with - x_with
        gap_no = b_no - x_no
        assert abs(gap_with - gap_no) <= _TOL_SP, (
            f"trailing-space gap differs: space-before={gap_with} sp "
            f"vs no-space-before={gap_no} sp (the dropped-space bug)"
        )
        # And the gap is a real interword space, not zero (glyphs abutting).
        assert gap_with >= _CMR10_SPACE_SP - _TOL_SP, (
            f"trailing space missing: gap={gap_with} sp < one cmr10 space"
        )

    def test_no_space_after_dollar_emits_no_glue(self) -> None:
        """``a $x$bb`` (no space after ``$``) → ``bb`` abuts the formula.

        No spurious trailing glue may be injected: the ``b`` after the formula
        starts within an italic-correction kern of the formula, not a full
        interword space away.
        """
        x_h, b_h = _h_after_last(_positions(r"a $x$bb"), "x", "b")
        gap = b_h - x_h
        assert gap < _CMR10_SPACE_SP - _TOL_SP, (
            f"spurious interword glue after '$' with no source space: gap={gap} sp"
        )

    def test_two_inline_formulae_each_keep_trailing_space(self) -> None:
        """Cumulative case: two ``$…$`` each followed by a space (math_inline shape).

        Both trailing spaces must be emitted, so the word after the second
        formula is two interword spaces further right than if both were dropped.
        """
        y_h, c_h = _h_after_last(_positions(r"aa $x$ bb $y$ cc"), "y", "c")
        assert c_h - y_h >= _CMR10_SPACE_SP - _TOL_SP, (
            f"trailing space after second formula dropped: gap={c_h - y_h} sp"
        )
