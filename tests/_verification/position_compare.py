"""Per-glyph position comparison between two DVI walks.

Pure comparison helper over :func:`tests._verification.dvi_walker.walk_chars_with_positions`
output: it reports *where* two glyph streams disagree horizontally or
vertically, so the E2E MiKTeX suite can assert mid-line horizontal advances
and not just line starts.

Why a differential comparison over the walker's ``h`` is sound
-------------------------------------------------------------
``walk_chars_with_positions`` does **not** add the implicit ``set_char`` glyph
advance to ``h`` — it reports the position reached by *explicit* movement
opcodes only. That is exactly what makes it usable here: the sibling
glyph-stream and ``fnt_def`` metadata tests assert both streams carry the same
glyph codes in the same order from the same fonts *before* this comparison is
meaningful, so the omitted implicit advance is identical in both streams at
every glyph index. The difference ``ours[i].h - ref[i].h`` therefore equals the
true rendered horizontal difference. Do not "fix" the walker to accumulate
glyph widths — it would need TFM access and would not change any delta.
"""
from __future__ import annotations

_SP_PER_PT = 65_536

#: AC-5 horizontal tolerance: ±0.1 pt, in scaled points.
TOL_H_SP = round(0.1 * _SP_PER_PT)

#: AC-5 vertical tolerance: ±0.5 pt, in scaled points.
TOL_V_SP = round(0.5 * _SP_PER_PT)

#: Per page, the ``(char_code, h, v)`` triples returned by the DVI walker.
GlyphPositions = list[list[tuple[int, int, int]]]


def _pt(sp: int) -> str:
    """Format a value in scaled points as a pt string with 3 decimals."""
    return f"{sp / _SP_PER_PT:.3f}"


def _glyph_label(code: int) -> str:
    """Render a glyph code as a printable label for diagnostics."""
    return repr(chr(code)) if 32 <= code < 127 else f"<{code}>"


def compare_glyph_positions(
    ours: GlyphPositions,
    ref: GlyphPositions,
    *,
    h_tol_sp: int,
    v_tol_sp: int,
    max_report: int = 8,
) -> list[str]:
    """Compare two per-page glyph position streams and describe the mismatches.

    Never raises on a shape mismatch — a differing page count, glyph count or
    glyph code is *reported*, because sibling tests in the E2E suite own those
    failures and give better messages. Positions past a glyph-code divergence
    are meaningless, so comparison of that page stops there.

    Args:
        ours: Glyph positions from our engine's DVI, per page.
        ref: Glyph positions from the reference (MiKTeX) DVI, per page.
        h_tol_sp: Maximum tolerated absolute horizontal delta, in scaled points.
        v_tol_sp: Maximum tolerated absolute vertical delta, in scaled points.
        max_report: Maximum number of per-glyph diagnostics to return. When
            more are found, a trailing ``"... and N more"`` line is appended.

    Returns:
        Human-readable diagnostics, ordered by page then glyph index. Empty
        when every glyph is within tolerance.

    Example:
        >>> ours = [[(65, 0, 0), (66, 100_000, 0)]]
        >>> ref = [[(65, 0, 0), (66, 0, 0)]]
        >>> compare_glyph_positions(ours, ref, h_tol_sp=6_554, v_tol_sp=32_768)
        ["page 0 glyph 1 'B': h ours=1.526 pt vs MiKTeX=0.000 pt — Δ=+1.526 pt (tolerance 0.100 pt)"]
    """
    if len(ours) != len(ref):
        return [f"page count ours={len(ours)} != MiKTeX={len(ref)}"]

    diagnostics: list[str] = []
    truncated = 0

    def record(message: str) -> None:
        nonlocal truncated
        if len(diagnostics) < max_report:
            diagnostics.append(message)
        else:
            truncated += 1

    for page_idx, (our_page, ref_page) in enumerate(zip(ours, ref, strict=True)):
        if len(our_page) != len(ref_page):
            record(
                f"page {page_idx} glyph count ours={len(our_page)} "
                f"!= MiKTeX={len(ref_page)}"
            )
            continue
        for glyph_idx, ((oc, oh, ov), (rc, rh, rv)) in enumerate(
            zip(our_page, ref_page, strict=True)
        ):
            if oc != rc:
                record(
                    f"page {page_idx} glyph {glyph_idx} code ours={oc} "
                    f"!= MiKTeX={rc} — positions past a stream divergence are "
                    f"not comparable, skipping the rest of this page"
                )
                break
            for axis, ours_sp, ref_sp, tol_sp in (
                ("h", oh, rh, h_tol_sp),
                ("v", ov, rv, v_tol_sp),
            ):
                delta = ours_sp - ref_sp
                if abs(delta) > tol_sp:
                    record(
                        f"page {page_idx} glyph {glyph_idx} "
                        f"{_glyph_label(oc)}: {axis} ours={_pt(ours_sp)} pt vs "
                        f"MiKTeX={_pt(ref_sp)} pt — "
                        f"Δ={delta / _SP_PER_PT:+.3f} pt "
                        f"(tolerance {_pt(tol_sp)} pt)"
                    )

    if truncated:
        diagnostics.append(f"... and {truncated} more")
    return diagnostics
