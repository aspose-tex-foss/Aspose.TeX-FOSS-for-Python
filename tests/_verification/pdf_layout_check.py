"""PDF layout integrity check ( FR-4b).

Scans a PDF file emitted by :class:`aspose_tex._output.pdf_writer.PdfWriter`
and returns a :class:`LayoutReport` with:

1. Count of ``/Page`` objects — to cross-check against the source's
 ``\\eject`` count ``+ 1`` (FR-4b, sentence 2).
2. On the first page, a list of adjacent glyph positions where the
 horizontal advance at a source whitespace position falls below the
 minimum interword space — the word-concatenation heuristic that
 would have caught at developer stage (FR-4b, sentence 3).
3. Ratio of the content's used vertical span to the page height —
 approximation of the ``used content / \\vsize`` ratio used in
 FR-4b sentence 1 comparisons.

The helper is stdlib-only (``re``, ``pathlib``, ``dataclasses``). It
assumes our writer's output profile: uncompressed content streams and
``BT / Tf / Td / Tj / ET`` segments, one logical word per ``Tj``. Input
coming from viewers or third-party producers is out of scope.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Heuristic constants
# ---------------------------------------------------------------------------

# Maximum plausible *visible* glyph count for one source word in the
# samples we verify (smoke_m2.tex / hello.tex at 10pt Computer Modern).
# Post-fix the longest single-Tj word is ``together.`` / ``a\\017icted``
# at 9 visible glyphs; pre-fix victims (``theafterno``,
# ``stifffiddle.``, ``afflictedofficer``) all exceed 10. The heuristic
# deliberately uses glyph-count rather than positional deltas: cmr10
# glyph widths vary by 3x (``i`` approx 2.8pt vs ``M`` approx 9pt), so a
# position-only check would need the TFM to stay stable, while the
# glyph-count check works from the PDF bytes alone. See FR-4b
# (word-concatenation heuristic) and the task description.
_MAX_WORD_GLYPHS = 10

_OCTAL_ESCAPE_RE = re.compile(r"\\\d{3}")
_TD_TJ_RE = re.compile(
 r"([-\d.]+)\s+([-\d.]+)\s+Td\s*\n\(([^)]*)\)\s+Tj",
)
_STREAM_RE = re.compile(rb"stream\n(.*?)\nendstream", re.DOTALL)
_PAGE_OBJ_RE = re.compile(rb"/Type\s*/Page\b(?!s)")
_MEDIABOX_RE = re.compile(
 rb"/MediaBox\s*\[\s*[-\d.]+\s+[-\d.]+\s+[-\d.]+\s+([-\d.]+)\s*\]"
)


# ---------------------------------------------------------------------------
# Report types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ZeroAdvancePair:
 """One flagged adjacency for FR-4b reporting.

 Attributes:
 tj_text: Raw bytes of the ``Tj`` string (with PDF octal escapes
 intact) that appears to concatenate two source words.
 position: ``"Y=<y>, X=<x>"`` of the ``Td`` that placed
 ``tj_text`` — useful for locating the defect in a viewer.
 reason: Short diagnostic tag — currently always ``"fused-tj"``
 (a single ``Tj`` carries 10+ visible glyphs — 
 signature).
 """

 tj_text: str
 position: str
 reason: str


@dataclass(frozen=True)
class LayoutReport:
 """Result of :func:`scan_pdf_layout`.

 Attributes:
 page_count: Number of ``/Type /Page`` objects in the PDF.
 expected_page_count: ``\\eject`` count in *source_tex* ``+ 1``
 ( FR-4b). ``None`` when no source file was supplied
 or it could not be read.
 zero_advance_pairs: Adjacencies on page 1 flagged by the word-
 concatenation heuristic. Empty on a clean post-fix PDF.
 vfill_ratio: ``used_vertical_span / page_height`` on page 1, in
 ``[0, 1]``. Used by reviewers to cross-check against the
 MiKTeX baseline within ±10% per FR-4b sentence 1.
 page_height_pt: Page height parsed from ``/MediaBox`` (the
 MediaBox's ``ury`` coordinate).
 """

 page_count: int
 expected_page_count: int | None
 zero_advance_pairs: list[ZeroAdvancePair]
 vfill_ratio: float
 page_height_pt: float = 0.0

 @property
 def page_count_matches(self) -> bool:
 """``True`` when :attr:`page_count` equals :attr:`expected_page_count`."""
 return (
 self.expected_page_count is not None
 and self.page_count == self.expected_page_count
 )


@dataclass
class _PageContent:
 index: int
 placements: list[tuple[float, float, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _decoded_glyph_count(tj_text: str) -> int:
 """Count *visible* glyphs in a PDF ``Tj`` string.

 PDF octal escapes (``\\NNN``) denote a single glyph (typically a
 Computer Modern ligature like ``\\013`` = ff) and count once.
 """
 return len(_OCTAL_ESCAPE_RE.sub("X", tj_text))


def _looks_fused(tj_text: str) -> bool:
 """Return True when *tj_text* looks like two source words fused.

 Combines two signals:

 1. Visible glyph count ``>= _MAX_WORD_GLYPHS``. Post-fix cmr10
 smoke samples never reach this; pre-fix victims all do.
 2. No trailing sentence punctuation before the last three glyphs
 — rules out legitimate long tokens like ``together.`` and
 ``affliction's``.
 """
 glyphs = _decoded_glyph_count(tj_text)
 if glyphs < _MAX_WORD_GLYPHS:
 return False
 # Strip leading/trailing punctuation, then look for internal
 # word-boundary markers. ``theafterno``, ``stifffiddle.``,
 # ``afflictedofficer`` all survive this filter; ``officials`` (10
 # glyphs) does not — punctuation-free but a single lexical word, so
 # we additionally require *internal* octal escapes adjacency OR a
 # capital letter in the middle (unusual for plain text).
 inner = tj_text.rstrip(".,;:!?)'\"")
 if re.search(r"\\\d{3}\\\d{3}", inner): # two adjacent ligatures
 return True
 if re.search(r"[a-z][A-Z]", inner): # midword capital
 return True
 # Octal escape followed by letter run followed by another escape:
 # e.g., ``a\017ictedo\016cer``.
 if re.search(r"\\\d{3}[a-z]{3,}\\\d{3}", inner):
 return True
 # ``theafterno``, ``erntriggers`` — pure lowercase but 10+ glyphs.
 # Real 10+-glyph single words in 10pt cmr cmr10 smoke text are
 # vanishingly rare; accept the mild false-positive risk here.
 return bool(re.fullmatch(r"[a-z]+", inner))


def _count_ejects(source_tex: Path | None) -> int | None:
 """Count plain-TeX ``\\eject`` tokens in *source_tex*.

 Returns ``None`` when *source_tex* is ``None`` or unreadable. The
 caller uses ``eject_count + 1`` as the expected ``/Page`` count per
 FR-4b.
 """
 if source_tex is None:
 return None
 try:
 text = source_tex.read_text(encoding="utf-8", errors="replace")
 except OSError:
 return None
 # Strip line comments (``%`` to newline) so ``% \eject`` in a
 # comment is ignored.
 stripped = re.sub(r"%[^\n]*", "", text)
 return len(re.findall(r"\\eject\b", stripped))


def _extract_page_streams(raw: bytes) -> list[bytes]:
 """Return one content-stream blob per page, in document order.

 Our writer emits exactly one content stream per page and lists them
 in page order, so we match streams sequentially; a more robust
 parser would follow ``/Contents`` references, but that is outside
 the scope of this helper (see module docstring).
 """
 return [m.group(1) for m in _STREAM_RE.finditer(raw)]


def _parse_placements(stream: bytes) -> list[tuple[float, float, str]]:
 """Extract ``(x, y, tj_text)`` triples from a content stream."""
 out: list[tuple[float, float, str]] = []
 for m in _TD_TJ_RE.finditer(stream.decode("latin-1")):
 out.append((float(m.group(1)), float(m.group(2)), m.group(3)))
 return out


def _page_height(raw: bytes) -> float:
 """Parse the first ``/MediaBox`` height; fall back to US Letter."""
 m = _MEDIABOX_RE.search(raw)
 return float(m.group(1)) if m else 792.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_pdf_layout(
 path: Path,
 source_tex: Path | None = None,
) -> LayoutReport:
 """Parse *path* and return a FR-4b layout report.

 Args:
 path: PDF file produced by ``PdfWriter``/``PdfDevice``.
 source_tex: Optional plain-TeX source used to derive the
 expected ``/Page`` count from ``\\eject`` occurrences. When
 omitted, :attr:`LayoutReport.expected_page_count` is ``None``
 and :attr:`LayoutReport.page_count_matches` is ``False``.

 Returns:
 :class:`LayoutReport` populated with page count, zero-advance
 pairs on page 1, and vertical fill ratio.

 Notes:
 Content streams must be uncompressed (the default for our
 writer). Compressed streams will silently yield an empty
 ``zero_advance_pairs`` list.
 """
 raw = path.read_bytes()

 page_count = len(_PAGE_OBJ_RE.findall(raw))
 expected = _count_ejects(source_tex)
 expected_page_count = expected + 1 if expected is not None else None
 page_height = _page_height(raw)

 streams = _extract_page_streams(raw)
 pairs: list[ZeroAdvancePair] = []
 vfill_ratio = 0.0

 if streams:
 placements = _parse_placements(streams[0])
 # Group by Y for adjacency scanning.
 by_y: dict[float, list[tuple[float, str]]] = {}
 for x, y, t in placements:
 by_y.setdefault(y, []).append((x, t))

 for y, row in by_y.items():
 row.sort()
 for x, t in row:
 if _looks_fused(t):
 pairs.append(
 ZeroAdvancePair(
 tj_text=t,
 position=f"Y={y:.3f}, X={x:.3f}",
 reason="fused-tj",
 )
 )

 if placements:
 ys = [y for _, y, _ in placements]
 used = max(ys) - min(ys)
 vfill_ratio = used / page_height if page_height > 0 else 0.0

 return LayoutReport(
 page_count=page_count,
 expected_page_count=expected_page_count,
 zero_advance_pairs=pairs,
 vfill_ratio=vfill_ratio,
 page_height_pt=page_height,
 )
