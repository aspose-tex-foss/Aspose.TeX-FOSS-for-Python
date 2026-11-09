"""unit tests for the per-glyph position comparator.

Covers the comparator contract directly (tolerance edges, shape mismatches,
truncation) plus the AC-4 proof that it catches a synthetic missing-interword-
space regression the pre-existing E2E checks cannot see.
"""
from __future__ import annotations

import pytest

dvi_walker = pytest.importorskip("tests._verification.dvi_walker")
position_compare = pytest.importorskip("tests._verification.position_compare")

compare_glyph_positions = position_compare.compare_glyph_positions
walk_chars_with_positions = dvi_walker.walk_chars_with_positions
collect_chars_per_page = dvi_walker.collect_chars_per_page
walk_line_starts = dvi_walker.walk_line_starts

_SP_PER_PT = 65_536
_TENTH_PT_SP = 6_554  # ±0.1 pt horizontal bound.
_HALF_PT_SP = 32_768  # ±0.5 pt vertical bound.

#: One cmr10 interword space (\fontdimen2 = 3.33333 pt) in scaled points —
#: the exact magnitude of the dropped-space defect.
_CMR10_SPACE_SP = 218_453


def _glyph_stream(pages) -> list[list[int]]:
    """Per page, the glyph-code stream — what ``collect_chars_per_page`` records."""
    return [[code for code, _h, _v in page] for page in pages]


def _line_starts(pages) -> list[list[tuple[int, int]]]:
    """Per page, the ``(v, code)`` of the first glyph at each new v.

    Mirrors what ``walk_line_starts`` records, derived from a position stream
    so the same mutation can be applied to it.
    """
    out: list[list[tuple[int, int]]] = []
    for page in pages:
        starts: list[tuple[int, int]] = []
        last_v: int | None = None
        for code, _h, v in page:
            if v != last_v:
                starts.append((v, code))
                last_v = v
        out.append(starts)
    return out


def _page(*glyphs: tuple[int, int, int]) -> list[list[tuple[int, int, int]]]:
    """Wrap ``(code, h, v)`` triples as a single-page glyph stream."""
    return [list(glyphs)]


def _compare(ours, ref, **kwargs):
    """Run the comparator at the tolerances."""
    kwargs.setdefault("h_tol_sp", _TENTH_PT_SP)
    kwargs.setdefault("v_tol_sp", _HALF_PT_SP)
    return compare_glyph_positions(ours, ref, **kwargs)


class TestComparatorContract:
    """The comparator reports divergences and never raises on shape mismatch."""

    def test_identical_streams_report_nothing(self) -> None:
        stream = _page((65, 0, 0), (66, 100_000, 0), (67, 200_000, 0))
        assert _compare(stream, stream) == []

    def test_h_divergence_beyond_tolerance_reported(self) -> None:
        ref = _page((65, 0, 0), (66, 100_000, 0))
        ours = _page((65, 0, 0), (66, 100_000 + _TENTH_PT_SP + 1, 0))
        diagnostics = _compare(ours, ref)
        assert len(diagnostics) == 1
        assert "glyph 1" in diagnostics[0]
        assert "h ours=" in diagnostics[0]

    def test_h_divergence_within_tolerance_ignored(self) -> None:
        """Exactly at the bound is tolerated — the check is ``> tol``."""
        ref = _page((65, 0, 0), (66, 100_000, 0))
        ours = _page((65, 0, 0), (66, 100_000 + _TENTH_PT_SP, 0))
        assert _compare(ours, ref) == []

    def test_v_divergence_beyond_tolerance_reported(self) -> None:
        ref = _page((65, 0, 0))
        ours = _page((65, 0, _HALF_PT_SP + 1))
        diagnostics = _compare(ours, ref)
        assert len(diagnostics) == 1
        assert "v ours=" in diagnostics[0]

    def test_page_count_mismatch_short_circuits(self) -> None:
        """A page-count mismatch yields one diagnostic and no per-glyph noise."""
        ours = _page((65, 0, 0))
        ref = [[(65, 0, 0)], [(66, 999_999, 0)]]
        diagnostics = _compare(ours, ref)
        assert diagnostics == ["page count ours=1 != MiKTeX=2"]

    def test_glyph_count_mismatch_reported_per_page(self) -> None:
        ours = _page((65, 0, 0), (66, 100_000, 0))
        ref = _page((65, 0, 0))
        diagnostics = _compare(ours, ref)
        assert len(diagnostics) == 1
        assert "glyph count ours=2 != MiKTeX=1" in diagnostics[0]

    def test_glyph_code_mismatch_stops_that_page(self) -> None:
        """Positions past a stream divergence are meaningless, so stop there."""
        ours = _page((65, 0, 0), (67, 999_999, 0), (68, 999_999, 0))
        ref = _page((65, 0, 0), (66, 100_000, 0), (68, 200_000, 0))
        diagnostics = _compare(ours, ref)
        assert len(diagnostics) == 1
        assert "code ours=67 != MiKTeX=66" in diagnostics[0]

    def test_report_is_truncated_with_more_marker(self) -> None:
        ref = _page(*((65, i * 100_000, 0) for i in range(20)))
        ours = _page(*((65, i * 100_000 + _CMR10_SPACE_SP, 0) for i in range(20)))
        diagnostics = _compare(ours, ref, max_report=8)
        assert len(diagnostics) == 9
        assert diagnostics[-1] == "... and 12 more"


class TestSyntheticMissingSpaceRegression:
    """AC-4 — prove the check catches the missing-interword-space defect class.

    Mutates a real, currently-clean fixture's glyph walk exactly the way the
    defect deforms output (every glyph from a mid-line point onward
    shifted left by one cmr10 interword space) and asserts the new comparator
    catches it *while the pre-existing checks do not* — so the check closes a
    genuine hole rather than duplicating cover.
    """

    FIXTURE = "paragraph"
    MUTATION_INDEX = 20

    @pytest.fixture(scope="class")
    def baseline_dvi(self) -> bytes:
        e2e = pytest.importorskip("tests.test_e2e_dvi_baseline")
        return e2e._baseline(self.FIXTURE)

    def _mutate(self, pages):
        """Drop one interword space from ``MUTATION_INDEX`` onward on page 1."""
        mutated = [list(page) for page in pages]
        for idx in range(self.MUTATION_INDEX, len(mutated[0])):
            code, h, v = mutated[0][idx]
            mutated[0][idx] = (code, h - _CMR10_SPACE_SP, v)
        return mutated

    def test_synthetic_missing_interword_space_is_caught(self, baseline_dvi) -> None:
        clean = walk_chars_with_positions(baseline_dvi)
        assert len(clean[0]) > self.MUTATION_INDEX, "fixture too short to mutate"

        diagnostics = _compare(self._mutate(clean), clean)

        assert diagnostics, "the comparator missed a full interword space drop"
        assert f"glyph {self.MUTATION_INDEX}" in diagnostics[0], (
            f"first diagnostic should name the mutation point, got: {diagnostics[0]}"
        )
        assert "-3.333 pt" in diagnostics[0], (
            f"expected the cmr10 space magnitude, got: {diagnostics[0]}"
        )

    def test_preexisting_checks_would_miss_it(self, baseline_dvi) -> None:
        """The glyph stream and line starts are blind to this mutation.

        This is the whole justification: a horizontal-only defect
        leaves both pre-existing signals untouched, which is why fixtures could
        be called "byte-exact vs MiKTeX" while carrying one.

        Both signals are derived here from the position stream in the same
        shape the real walkers produce, and each derivation is pinned against
        its walker on the unmutated DVI first — so this test cannot drift into
        asserting something weaker than the checks it stands in for.
        """
        clean = walk_chars_with_positions(baseline_dvi)
        mutated = self._mutate(clean)

        # Pin both derivations against the real walkers before relying on them.
        assert _glyph_stream(clean) == collect_chars_per_page(baseline_dvi), (
            "glyph-stream derivation must match collect_chars_per_page"
        )
        assert _line_starts(clean) == walk_line_starts(baseline_dvi), (
            "line-start derivation must match walk_line_starts"
        )

        assert _glyph_stream(mutated) == _glyph_stream(clean), (
            "mutation must leave the glyph-code stream untouched — this is why "
            "collect_chars_per_page cannot see a horizontal-only defect"
        )
        assert _line_starts(mutated) == _line_starts(clean), (
            "mutation must leave every line-start (v, code) untouched — this is "
            "why walk_line_starts cannot see a horizontal-only defect"
        )

        assert _compare(mutated, clean), (
            "sanity: the mid-line check must still catch what the others miss"
        )
