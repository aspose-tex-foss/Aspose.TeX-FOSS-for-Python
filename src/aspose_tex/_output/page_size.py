"""Shared page-size resolver for the PDF and SVG output backends.

This module owns the single source of truth for named paper-size presets and
the ``page_size`` argument validation shared by :class:`PdfDevice` and
:class:`SvgDevice`.  Keeping it here (rather than in either writer) gives both
backends one preset table and one error contract.

See.  Private module — not part of the public import
surface.
"""
from __future__ import annotations

from typing import Union

__all__ = ["PAGE_SIZE_PRESETS", "PageSize", "resolve_page_size"]

# A page_size argument: a preset name, an explicit (width_pt, height_pt) pair,
# or None (=> the Letter default).
PageSize = Union[str, "tuple[float, float]", "list[float]", None]

# Named presets, keyed by lowercase name, portrait dimensions in PDF points
# (1 pt = 1/72 in).  Values are floats so callers get a uniform type.
PAGE_SIZE_PRESETS: dict[str, tuple[float, float]] = {
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
    "a3": (841.89, 1190.55),
    "a4": (595.276, 841.89),
    "a5": (419.528, 595.276),
}

# The default paper size when page_size is omitted ( FR-8).  Kept as a
# name so the default and the "letter" preset can never drift apart.
_DEFAULT_PRESET = "letter"


def _valid_presets_msg() -> str:
    """Return a stable, sorted listing of preset names for error messages."""
    return ", ".join(sorted(PAGE_SIZE_PRESETS))


def resolve_page_size(page_size: PageSize) -> tuple[float, float]:
    """Resolve a ``page_size`` argument to ``(width_pt, height_pt)``.

    Args:
        page_size: One of:

            * ``None`` — the US Letter default ``(612.0, 792.0)``.
            * A **named preset** (case-insensitive, surrounding whitespace
              ignored): ``"letter"``, ``"legal"``, ``"a3"``, ``"a4"``,
              ``"a5"``.
            * An explicit ``(width_pt, height_pt)`` pair (a ``tuple`` or
              ``list`` of two positive real numbers) in PDF points.

    Returns:
        The resolved ``(width_pt, height_pt)`` as a pair of ``float``.

    Raises:
        ValueError: If *page_size* is an unknown preset name, a sequence of the
            wrong length, contains a non-numeric or non-positive dimension, or
            is of an unsupported type.  The message names the offending value
            and, for unknown presets, lists the valid preset names.
    """
    if page_size is None:
        return PAGE_SIZE_PRESETS[_DEFAULT_PRESET]

    if isinstance(page_size, str):
        key = page_size.strip().lower()
        if key not in PAGE_SIZE_PRESETS:
            raise ValueError(
                f"unknown page size preset {page_size!r}; "
                f"valid presets: {_valid_presets_msg()}"
            )
        return PAGE_SIZE_PRESETS[key]

    # Explicit size: accept a tuple or list of two numbers (reject str/bytes,
    # which are sequences but handled above / never a valid size).
    if isinstance(page_size, (tuple, list)):
        if len(page_size) != 2:
            raise ValueError(
                f"invalid explicit page size {page_size!r}: expected a "
                f"(width_pt, height_pt) pair of two positive numbers"
            )
        dims: list[float] = []
        for value in page_size:
            # bool is an int subclass but is not a meaningful dimension.
            if isinstance(value, bool):
                raise ValueError(
                    f"invalid explicit page size {page_size!r}: "
                    f"dimensions must be positive numbers"
                )
            try:
                dims.append(float(value))
            except (TypeError, ValueError):
                raise ValueError(
                    f"invalid explicit page size {page_size!r}: "
                    f"dimensions must be positive numbers"
                ) from None
        if dims[0] <= 0 or dims[1] <= 0:
            raise ValueError(
                f"invalid explicit page size {page_size!r}: "
                f"dimensions must be positive numbers"
            )
        return (dims[0], dims[1])

    raise ValueError(
        f"invalid page_size {page_size!r}: expected a preset name "
        f"({_valid_presets_msg()}) or a (width_pt, height_pt) pair"
    )
