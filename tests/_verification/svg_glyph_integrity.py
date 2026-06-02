"""SVG glyph path integrity check ( FR-4a).

Scans an SVG file emitted by :class:`aspose_tex._output.svg_writer.SvgWriter`,
walks every ``<path id="g-*" d="...">`` node, and reports every path whose
``M`` / ``Z`` command counts are imbalanced. The failure threshold
(``M_count - Z_count >= 2``) is the structural signature of the 
Type 1 Flex defect class: a single orphan ``M`` can occur for open
subpaths the renderer still closes visually, but two or more indicates an
interpreter error.

This module is the canonical helper that FR-6 reviewer replay
re-runs. It is stdlib-only (``re``, ``pathlib``, ``warnings``) so that
the same module can be invoked from tests, verification scripts, and
inline task notes without dragging dependencies or side effects.
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

_PATH_RE = re.compile(r'<path\s+id="(g-[^"]+)"\s+d="([^"]*)"')
_MISSING_OUTLINE_RE = re.compile(
 r"SVG:\s*no outline for char code\s*(\d+)", re.IGNORECASE
)


@dataclass(frozen=True)
class PathReport:
 """Integrity row for one ``<path id="g-*">`` element.

 Attributes:
 path_id: Value of the ``id`` attribute (e.g. ``g-cmr10-10-65``;
 encodes the at-size between the TFM stem and the code).
 m_count: Number of ``M``/``m`` (moveto) commands in the path ``d`` data.
 z_count: Number of ``Z``/``z`` (closepath) commands in the path ``d`` data.
 """

 path_id: str
 m_count: int
 z_count: int

 @property
 def imbalance(self) -> int:
 """``m_count - z_count``. ``>= 2`` is the FR-4a failure threshold."""
 return self.m_count - self.z_count


def scan_svg(svg_path: Path) -> list[PathReport]:
 """Return an integrity report for every ``g-*`` path in *svg_path*.

 Args:
 svg_path: Path to an SVG document written by ``SvgWriter``.

 Returns:
 One :class:`PathReport` per ``<path id="g-*">`` element, in document
 order. Paths without the ``g-`` id prefix (e.g. ``<path class="rule">``
 for ``\\hrule``) are skipped — they have no glyph-outline contract.
 """
 text = svg_path.read_text(encoding="utf-8", errors="replace")
 reports: list[PathReport] = []
 for pid, d in _PATH_RE.findall(text):
 m = d.count("M") + d.count("m")
 z = d.count("Z") + d.count("z")
 reports.append(PathReport(pid, m, z))
 return reports


def orphan_movetos(reports: list[PathReport]) -> list[PathReport]:
 """Subset of *reports* where ``m_count - z_count >= 2``.

 This is the FR-4a failure threshold. A single orphan ``M``
 can occur for open subpaths the renderer still closes visually, but
 two or more is the Type 1 Flex signature.
 """
 return [r for r in reports if r.imbalance >= 2]


def scan_svg_path_integrity(path: Path) -> list[tuple[str, str]]:
 """ FR-4a canonical entry point.

 Runs :func:`scan_svg` on *path* and returns only the offending rows as
 ``(path_id, issue)`` tuples, where ``issue`` is a short human-readable
 diagnostic suitable for pasting into a verification report.

 Args:
 path: SVG document produced by ``SvgWriter``.

 Returns:
 Empty list when every ``g-*`` path balances its ``M`` and ``Z``
 commands within the FR-4a tolerance. Non-empty when the document
 would FAIL FR-4a — one tuple per offending path.
 """
 issues: list[tuple[str, str]] = []
 for rep in orphan_movetos(scan_svg(path)):
 issues.append(
 (
 rep.path_id,
 f"M={rep.m_count} Z={rep.z_count} "
 f"(imbalance={rep.imbalance}, expected <= 1)",
 )
 )
 return issues


def scan_warnings_for_missing_outlines(warnings_text: str) -> list[int]:
 """Return char codes flagged by ``SVG: no outline for char code N`` warnings.

 FR-4a promotes *any* ``UserWarning: SVG: no outline for char
 code N`` emitted during SVG generation (for a code present in the
 source text) from caveat to FAIL. Callers capture the warning stream
 via :func:`warnings.catch_warnings` around the render call and pass
 the collected text here.

 Args:
 warnings_text: Concatenated warning messages captured during SVG
 generation. ``str(w.message)`` or the full ``warnings`` text
 dump both work — the regex only matches the literal prefix.

 Returns:
 List of char codes (as ints) extracted from matching warnings, in
 order of appearance. Duplicates are preserved so callers can see
 the frequency.
 """
 return [int(m.group(1)) for m in _MISSING_OUTLINE_RE.finditer(warnings_text)]


def collect_warning_messages(
 captured: list[warnings.WarningMessage],
) -> str:
 """Concatenate messages captured by :func:`warnings.catch_warnings`.

 Helper for callers who have a ``list[warnings.WarningMessage]`` from
 ``warnings.catch_warnings(record=True)``. Returns a newline-joined
 string suitable for feeding into
 :func:`scan_warnings_for_missing_outlines`.
 """
 return "\n".join(str(w.message) for w in captured)
