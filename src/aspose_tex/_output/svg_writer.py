"""SVG 1.1 output backend.

Implements the SVG writer specified in and.  Receives
completed page boxes from the page builder via the ShipoutBackend protocol
and emits standalone SVG 1.1 documents with embedded glyph outlines as
``<path>`` elements.

See for full design rationale, coordinate system, and glyph
embedding approach.
"""
from __future__ import annotations

import dataclasses
import io
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from aspose_tex._engine.hyphenation import LanguageWhatsit
from aspose_tex._engine.leaders import leader_positions
from aspose_tex._engine.nodes import (
    RUNNING_DIMEN,
    CharNode,
    GlueNode,
    HlistNode,
    InsertNode,
    KernNode,
    LeadersNode,
    MathNode,
    PenaltyNode,
    RuleNode,
    VlistNode,
    WhatsitNode,
    iter_nobreak_nodes,
)
from aspose_tex._fonts.type1_outlines import GlyphOutline, extract_glyph_outlines
from aspose_tex._output.glue_setter import GlueSetter
from aspose_tex.exceptions import FontError

if TYPE_CHECKING:
    from aspose_tex._fonts.font_manager import FontManager
    from aspose_tex._fonts.font_metrics import FontMetrics


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SVG_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg"'
    ' xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1"\n'
    '     width="{w}pt" height="{h}pt"\n'
    '     viewBox="{vx} {vy} {vw} {vh}">\n'
)
_SVG_FOOTER = "</svg>\n"

_DEFAULT_PAGE_WIDTH_PT = 612
_DEFAULT_PAGE_HEIGHT_PT = 792

_ORIGIN_X_PT = 72
_ORIGIN_Y_PT = 72

# Output space is PostScript big points (1in = 72bp), as in pdftex,
# dvipdfmx and dvisvgm; TeX's pt is 1/72.27in, so 1bp = 72.27/72 pt.
_SP_PER_BP = 65536 * 72.27 / 72


def _sp_per_bp(mag: int) -> float:
    """Return the sp in one output bp under *mag*; the 1in origin stays physical."""
    return _SP_PER_BP if mag == 1000 else _SP_PER_BP * 1000 / mag
_COORD_PRECISION = 4


def _glyph_id(tfm_name: str, at_size_sp: int, code: int) -> str:
    """Build the ``<defs>`` glyph id / ``xlink:href`` target for one glyph.

    The id encodes the at-size so the same TFM loaded at multiple sizes does
    not collide on a single ``<path id>``.  Once every document used
    cmr10 at exactly one size and the old ``g-{tfm}-{code}`` scheme sufficed;
    plain.tex routinely selects e.g. cmr10 at 7pt (``\\sevenrm``) or 5pt
    (``\\fiverm``), where the un-sized scheme would let whichever font emitted
    last overwrite the other's outline in ``<defs>``.

    The at-size component is the **exact** size in sp (not a rounded pt value):
    Fractional / magnified sizes are reachable (``\\font\\x=cmr10 at
    10.95pt``, ``scaled \\magstephalf``), so two distinct sizes that round to
    the same integer pt — e.g. 10.3pt and 10.4pt — would re-collide under the
    old ``round(pt)`` scheme (§G FR-10).  Encoding sp keeps the
    id collision-free for every distinct at-size.

    Args:
        tfm_name:    TFM stem, e.g. ``"cmr10"``.
        at_size_sp:  Requested font size in sp (exact; e.g. ``655360`` for
                     10pt, ``458752`` for 7pt).
        code:        Character code.

    Returns:
        Glyph id string ``g-{tfm_name}-{at_size_sp}-{code}``, e.g.
        ``"g-cmr10-458752-49"`` for cmr10@7pt char 49.
    """
    return f"g-{tfm_name}-{at_size_sp}-{code}"


# Padding (in pt) added around the content bounding box when emitting a
# content-tight viewBox.  Chrome 147 silently drops glyph
# placements that fall too close to the bottom edge of an SVG that exactly
# fills the layout viewport.  dvisvgm uses a comparable margin around its
# content-tight box; we add a small constant rather than computing exact
# glyph extents to keep the bbox calculation cheap.
_CONTENT_BBOX_PADDING_PT = 2.0
_CONTENT_BBOX_BOTTOM_PADDING_PT = 4.0


def _rule_paints(width: int, height: int, depth: int) -> bool:
    """Whether a rule actually paints, per TeX:The Program §622 / §634.

    A rule is rendered only when both its total height (``height + depth``) and
    its ``width`` are positive. A non-painting rule (e.g. a zero-width
    ``\\strut``) advances the reference point but emits no placement.
    Dimensions are in sp and must already be RUNNING_DIMEN-resolved
    
    """
    return width > 0 and (height + depth) > 0


# ---------------------------------------------------------------------------
# Path-data pre-scaling
# ---------------------------------------------------------------------------

def _fmt_path_num(x: float) -> str:
    """Format a path coordinate with up to ``_COORD_PRECISION`` decimals.

    Mirrors :py:meth:`SvgWriter._fmt_num` but lives at module scope so that
    the pre-scaling helper can be exercised independently in unit tests.
    Strips trailing zeros and a trailing decimal point so the emitted
    path strings stay compact (e.g. ``2.94`` rather than ``2.9400``).
    """
    if x == int(x):
        return str(int(x))
    s = f"{x:.{_COORD_PRECISION}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s == "" or s == "-":
        s = "0"
    return s


def _scale_path_d(d: str, scale: float) -> str:
    """Return *d* with every coordinate scaled by ``scale`` (x) and ``-scale`` (y).

    The y-flip is folded in to convert TeX's "y-up" glyph outline into
    SVG's "y-down" user-coordinate system without an emit-time
    ``transform="scale(s,-s)"``.  See for the Chromium rendering
    issue that motivated this transform-folding.

    Only the four path commands produced by
    :func:`aspose_tex._fonts.type1_outlines._path_to_svg` are accepted:
    ``M``, ``L``, ``C``, ``Z`` (single-letter, whitespace-separated, integer
    operands).  Any other token raises :class:`ValueError` rather than
    silently corrupting the path.

    Args:
        d:     Source ``d`` attribute string (font-design units, y-up).
        scale: Multiplicative factor applied to x; ``-scale`` is applied
               to y.

    Returns:
        Pre-scaled ``d`` string in user (point) units, y-down.
    """
    if not d:
        return d
    tokens = d.split()
    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        cmd = tokens[i]
        if cmd == "Z":
            out.append("Z")
            i += 1
        elif cmd == "M" or cmd == "L":
            x = float(tokens[i + 1]) * scale
            y = float(tokens[i + 2]) * -scale
            out.append(cmd)
            out.append(_fmt_path_num(x))
            out.append(_fmt_path_num(y))
            i += 3
        elif cmd == "C":
            out.append("C")
            for j in range(3):
                x = float(tokens[i + 1 + 2 * j]) * scale
                y = float(tokens[i + 2 + 2 * j]) * -scale
                out.append(_fmt_path_num(x))
                out.append(_fmt_path_num(y))
            i += 7
        else:
            raise ValueError(f"unexpected SVG path token {cmd!r} in {d!r}")
    return " ".join(out)


# ---------------------------------------------------------------------------
# _SvgFontRecord (internal)
# ---------------------------------------------------------------------------

@dataclasses.dataclass(slots=True)
class _SvgFontRecord:
    """Internal bookkeeping for one loaded font in the SVG writer.

    Attributes:
        cs_name:        TeX control-sequence name (e.g. ``"tenrm"``).
        tfm_name:       TFM stem (e.g. ``"cmr10"``).
        at_size_sp:     Requested font size in sp.
        at_size_pt:     Requested font size in output bp, magnified.
        design_size_sp: Design size in sp (from FontMetrics).
        metrics:        FontMetrics reference for width lookups.
        outlines:       Extracted glyph outlines: code -> GlyphOutline.
        scaled_d:       Lazily populated glyph ``d`` strings pre-scaled into
                        user-units:
                        ``x'`` = ``x * at_size_pt/1000`` and
                        ``y'`` = ``-y * at_size_pt/1000`` (TeX-up to
                        SVG-down y-flip is folded in).  Empty string when
                        the glyph has no outline.  This
                        replaces an emit-time ``transform="translate(...)
                        scale(0.01,-0.01)"`` on every ``<use>`` so glyph
                        placements use bare ``x`` / ``y`` attributes
                        (dvisvgm-style), which Chromium browsers paint
                        reliably when our equivalent transform-based form
                        was silently dropped for the page-folio glyph.
                        keeps this cache demand-filled so font loading does
                        not scale glyphs that are never emitted.
    """

    cs_name: str
    tfm_name: str
    at_size_sp: int
    at_size_pt: float
    design_size_sp: int
    metrics: FontMetrics
    outlines: dict[int, GlyphOutline]
    scaled_d: dict[int, str]


# ---------------------------------------------------------------------------
# SvgWriter
# ---------------------------------------------------------------------------

class SvgWriter:
    """Writes SVG 1.1 output; implements ``ShipoutBackend``.

    Each ``shipout()`` call produces one standalone SVG document.
    ``finalize()`` writes all pages to files or keeps them in memory.

    Usage (in-memory)::

        import io
        buf = io.BytesIO()
        writer = SvgWriter(buf, font_manager=mgr)
        page_builder = PageBuilder(config, backend=writer, ...)
        # ... feed content to page_builder ...
        page_builder.end_of_document()
        writer.finalize()
        svg_bytes = writer.get_bytes()       # first page
        all_pages = writer.get_all_pages()   # all pages

    With file output::

        writer = SvgWriter(Path("output/hello"), font_manager=mgr)
        # ... use writer as backend ...
        writer.finalize()
        # writes hello.svg (single page) or hello-1.svg, hello-2.svg (multi)
    """

    def __init__(
        self,
        destination: Path | io.BytesIO,
        font_manager: FontManager,
        *,
        mag: int = 1000,
        page_width_pt: float = _DEFAULT_PAGE_WIDTH_PT,
        page_height_pt: float = _DEFAULT_PAGE_HEIGHT_PT,
    ) -> None:
        """Initialise the SVG writer.

        Args:
            destination:    ``pathlib.Path`` base path for file output (pages
                            written as ``base.svg`` or ``base-N.svg``), or
                            ``io.BytesIO`` for in-memory output.
            font_manager:   Used to load TFM metrics and PFB data on demand.
            mag:            TeX magnification * 1000 (default 1000 = 1x).
            page_width_pt:  Page width in points (default 612 = US Letter).
            page_height_pt: Page height in points (default 792).
        """
        self._destination = destination
        self._font_manager = font_manager
        self._mag = mag
        self._mag_source: Callable[[], int] | None = None
        self._mag_fixed = False
        self._sp_per_bp = _sp_per_bp(mag)
        self._page_width_pt = float(page_width_pt)
        self._page_height_pt = float(page_height_pt)

        self._fonts: dict[str, _SvgFontRecord] = {}
        self._resource_names: dict[str, str] = {}
        self._pages: list[bytes] = []
        self._finalized = False

        # Per-page accumulators (reset in shipout)
        self._char_placements: list[tuple[_SvgFontRecord, int, int, int]] = []
        self._rule_placements: list[tuple[int, int, int, int]] = []
        self._specials_warned: set[str] = set()
        self._missing_glyph_warned: set[tuple[str, int]] = set()

    # ------------------------------------------------------------------
    # ShipoutBackend interface
    # ------------------------------------------------------------------

    def set_mag_source(self, source: Callable[[], int] | None) -> None:
        r"""Take the job's magnification from *source* at the first shipout.

        TeX §617 fixes ``\mag`` when the first page goes out, so the value
        passed to the constructor stands only until then.

        Args:
            source: Callable returning the magnification * 1000, or ``None``.

        Example::

            writer.set_mag_source(lambda: named_params.get_int("mag"))
        """
        self._mag_source = source

    def shipout(self, page_number: int, box: VlistNode) -> None:
        """Receive one completed page and generate an SVG document.

        Args:
            page_number: Value of ``\\pageno`` at the time of shipout.
            box:         Finalised page VlistNode from PlainOutputRoutine.

        Raises:
            RuntimeError: If ``finalize()`` has already been called.
            FontError:    If a CharNode references a font whose PFB cannot
                          be loaded.
        """
        if self._finalized:
            raise RuntimeError("SvgWriter.shipout() called after finalize()")
        if not self._mag_fixed:
            self._mag_fixed = True
            if self._mag_source is not None:
                self._mag = self._mag_source()
                self._sp_per_bp = _sp_per_bp(self._mag)

        # Reset per-page state
        self._char_placements = []
        self._rule_placements = []

        # Traverse the page box to collect placements
        self._traverse_vlist(box.list, box, h_ref=0, v_ref=0)

        # Build SVG document
        svg_bytes = self._build_svg_page()
        self._pages.append(svg_bytes)

    # ------------------------------------------------------------------
    # Finalisation
    # ------------------------------------------------------------------

    def finalize(self) -> None:
        """Write all SVG pages to the destination.

        For file destination (Path):
          - Single page: writes ``{base}.svg``
          - Multi-page: writes ``{base}-1.svg``, ``{base}-2.svg``, etc.

        For memory destination (BytesIO):
          - No-op (pages are already stored in ``_pages``).

        Raises:
            RuntimeError: If called more than once.
        """
        if self._finalized:
            raise RuntimeError("SvgWriter.finalize() already called")
        self._finalized = True

        if isinstance(self._destination, Path):
            # Derive base path — strip .svg extension if present
            base = self._destination
            if base.suffix.lower() == ".svg":
                base = base.with_suffix("")

            base.parent.mkdir(parents=True, exist_ok=True)

            if len(self._pages) == 1:
                path = base.with_suffix(".svg")
                path.write_bytes(self._pages[0])
            else:
                for i, page_bytes in enumerate(self._pages, 1):
                    path = base.parent / f"{base.name}-{i}.svg"
                    path.write_bytes(page_bytes)

    def get_bytes(self) -> bytes:
        """Return the first page's SVG as bytes.

        Raises:
            RuntimeError: If ``finalize()`` not called, no pages, or
                          destination is a file path.
        """
        if not self._finalized:
            raise RuntimeError("SvgWriter.finalize() must be called first")
        if isinstance(self._destination, Path):
            raise RuntimeError("get_bytes() is only for in-memory output")
        if not self._pages:
            raise RuntimeError("SvgWriter: no pages to return")
        return self._pages[0]

    def get_all_pages(self) -> list[bytes]:
        """Return all pages as a list of SVG byte strings.

        Raises:
            RuntimeError: If ``finalize()`` not called or destination is
                          a file path.
        """
        if not self._finalized:
            raise RuntimeError("SvgWriter.finalize() must be called first")
        if isinstance(self._destination, Path):
            raise RuntimeError("get_all_pages() is only for in-memory output")
        return list(self._pages)

    # ------------------------------------------------------------------
    # Font handling
    # ------------------------------------------------------------------

    def _ensure_font(self, cs_name: str) -> _SvgFontRecord:
        """Return the font record for *cs_name*, loading outlines if new."""
        rec = self._fonts.get(cs_name)
        if rec is not None:
            return rec

        info = self._font_manager.font_def_info(cs_name)
        if info is None:
            name = cs_name if not cs_name.startswith(chr(0)) else 'unknown identifier'
            raise FontError(f"SVG: font '{name}' not loaded")
        tfm_name, _checksum, design_size_sp, at_size_sp = info

        pfb = self._font_manager.load_pfb(cs_name)
        if pfb is None:
            raise FontError(f"SVG: no PFB for '{tfm_name}'")

        outlines = extract_glyph_outlines(pfb)
        metrics = self._font_manager.get_metrics(cs_name)
        assert metrics is not None  # font_def_info succeeded

        at_size_pt = at_size_sp / self._sp_per_bp

        rec = _SvgFontRecord(
            cs_name=cs_name,
            tfm_name=tfm_name,
            at_size_sp=at_size_sp,
            at_size_pt=at_size_pt,
            design_size_sp=design_size_sp,
            metrics=metrics,
            outlines=outlines,
            scaled_d={},
        )
        # Keep familiar safe SVG names; distinguish separate resolved sources.
        resource = tfm_name
        if any(r.tfm_name == tfm_name and r.at_size_sp == at_size_sp
               for r in self._fonts.values()):
            resource += f"-f{len(self._fonts)}"
        self._resource_names[cs_name] = resource
        self._fonts[cs_name] = rec
        return rec

    def _scaled_glyph_path_d(self, rec: _SvgFontRecord, code: int) -> str:
        """Return and cache the pre-scaled SVG path for one glyph code.

        keeps ``_ensure_font`` cheap by deferring the path
        scaling work until a glyph is actually referenced by bbox, defs, or
        emission code.  The cache hit path returns the stored string directly;
        missing-outline entries are cached as ``""`` so repeated references do
        not redo the outline lookup.
        """
        cached = rec.scaled_d.get(code)
        if cached is not None:
            return cached

        outline = rec.outlines.get(code)
        if outline is None:
            rec.scaled_d[code] = ""
            return ""

        d = _scale_path_d(outline.svg_path, rec.at_size_pt / 1000.0)
        rec.scaled_d[code] = d
        return d

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def _traverse_vlist(
        self, nodes: list, parent: VlistNode, h_ref: int, v_ref: int,
    ) -> None:
        """Vertical traversal — same logic as DviWriter/PdfWriter."""
        setter = GlueSetter.for_box(parent)
        v_cursor = v_ref
        for node in nodes:
            if isinstance(node, HlistNode):
                v_cursor += node.height
                self._traverse_hlist(
                    node.list, node,
                    h_ref=h_ref + node.shift_amount,
                    v_ref=v_cursor,
                )
                v_cursor += node.depth
            elif isinstance(node, VlistNode):
                v_cursor += node.height
                self._traverse_vlist(
                    node.list, node,
                    h_ref=h_ref + node.shift_amount,
                    v_ref=v_cursor - node.height,
                )
                v_cursor += node.depth
            elif isinstance(node, LeadersNode):
                span = setter.set_size(node.glue)
                self._paint_leaders(node, parent, h_ref, v_cursor, span, vertical=True, origin=v_ref)
                v_cursor += span
            elif isinstance(node, GlueNode):
                v_cursor += setter.set_size(node.glue)
            elif isinstance(node, KernNode):
                v_cursor += node.width
            elif isinstance(node, (PenaltyNode, InsertNode)):
                pass
            elif isinstance(node, RuleNode):
                width = node.width if node.width != RUNNING_DIMEN else parent.width
                height = node.height if node.height != RUNNING_DIMEN else parent.height
                depth = node.depth if node.depth != RUNNING_DIMEN else parent.depth
                # TeX §634: place the rule only when it paints; the reference
                # point advances by height+depth either way.
                v_cursor += height
                if _rule_paints(width, height, depth):
                    self._rule_placements.append(
                        (h_ref, v_cursor - height, width, height + depth)
                    )
                v_cursor += depth
            elif isinstance(node, WhatsitNode):
                self._warn_whatsit(node)

    def _traverse_hlist(
        self, nodes: list, parent: HlistNode, h_ref: int, v_ref: int,
    ) -> None:
        """Horizontal traversal."""
        setter = GlueSetter.for_box(parent)
        h_cursor = h_ref
        for node in iter_nobreak_nodes(nodes):
            if isinstance(node, CharNode):
                rec = self._ensure_font(node.font_name)
                self._char_placements.append(
                    (rec, node.char, h_cursor, v_ref)
                )
                if rec.metrics.has_char(node.char):
                    h_cursor += rec.metrics.char_metrics(node.char).width

            elif isinstance(node, (KernNode, MathNode)):
                h_cursor += node.width

            elif isinstance(node, LeadersNode):
                span = setter.set_size(node.glue)
                self._paint_leaders(node, parent, h_cursor, v_ref, span, vertical=False, origin=h_ref)
                h_cursor += span

            elif isinstance(node, GlueNode):
                h_cursor += setter.set_size(node.glue)

            elif isinstance(node, (PenaltyNode, InsertNode)):
                pass

            elif isinstance(node, RuleNode):
                width = node.width if node.width != RUNNING_DIMEN else parent.width
                height = node.height if node.height != RUNNING_DIMEN else parent.height
                depth = node.depth if node.depth != RUNNING_DIMEN else parent.depth
                # TeX §622: place the rule only when it paints; the reference
                # point advances by width either way.
                if _rule_paints(width, height, depth):
                    self._rule_placements.append(
                        (h_cursor, v_ref - height, width, height + depth)
                    )
                h_cursor += width

            elif isinstance(node, HlistNode):
                self._traverse_hlist(
                    node.list, node,
                    h_ref=h_cursor,
                    v_ref=v_ref - node.shift_amount,
                )
                h_cursor += node.width

            elif isinstance(node, VlistNode):
                self._traverse_vlist(
                    node.list, node,
                    h_ref=h_cursor,
                    v_ref=v_ref - node.height - node.shift_amount,
                )
                h_cursor += node.width

            elif isinstance(node, WhatsitNode):
                self._warn_whatsit(node)

    def _paint_leaders(self, node, parent, h, v, span, *, vertical, origin):
        """Paint a leader payload using the containing list's axis and grid."""
        payload = node.payload
        if isinstance(payload, RuleNode):
            width = payload.width if payload.width != RUNNING_DIMEN else parent.width
            height = payload.height if payload.height != RUNNING_DIMEN else parent.height
            depth = payload.depth if payload.depth != RUNNING_DIMEN else parent.depth
            if vertical:
                height, depth = span, 0
            else:
                width = span
                v -= height
            height += depth
            if width > 0 and height > 0:
                self._rule_placements.append((h, v, width, height))
            return
        extent = payload.height + payload.depth if vertical else payload.width
        start = v if vertical else h
        previous = getattr(self, "_doing_leaders", False)
        self._doing_leaders = True
        try:
            for edge in leader_positions(node.kind, start=start, span=span, extent=extent, origin=origin):
                x = h + payload.shift_amount if vertical else edge
                baseline = edge + payload.height if vertical else v - payload.shift_amount
                if isinstance(payload, HlistNode):
                    self._traverse_hlist(payload.list, payload, h_ref=x, v_ref=baseline)
                else:
                    self._traverse_vlist(payload.list, payload, h_ref=x, v_ref=baseline-payload.height)

        finally:
            self._doing_leaders = previous

    def _warn_whatsit(self, node: WhatsitNode) -> None:
        if isinstance(node.data, LanguageWhatsit):
            return  # no output and nothing to report (§7)
        key = repr(node.data)
        if key in self._specials_warned:
            return
        self._specials_warned.add(key)
        warnings.warn(
            f"SVG: \\special/whatsit ignored: {node.data!r}",
            stacklevel=2,
        )

    # ------------------------------------------------------------------
    # SVG generation
    # ------------------------------------------------------------------

    def _compute_content_bbox(self) -> tuple[float, float, float, float] | None:
        """Return the content bounding box ``(x_min, y_min, x_max, y_max)`` in pt.

        Returns ``None`` when the page has no painted placements.  Char
        extents come from ``FontMetrics`` (width/height/depth in sp);
        rule extents are taken directly from the placement record.  All
        coordinates are in user (point) units after the same origin
        offset applied by ``_build_char_use`` / ``_build_rule_rect`` so
        the bbox can be plugged straight into the SVG header.

        this is the data feeding the content-tight viewBox that
        replaces the page-sized one.  Empty pages return ``None``; the
        caller falls back to the configured page dimensions.
        """
        if not self._char_placements and not self._rule_placements:
            return None

        x_min = float("inf")
        y_min = float("inf")
        x_max = float("-inf")
        y_max = float("-inf")

        for rec, code, h_sp, v_sp in self._char_placements:
            if not self._scaled_glyph_path_d(rec, code):
                # Skipped at emit time (no outline) — also exclude from bbox.
                continue
            x = self._sp_to_pt_x(h_sp)
            y = self._sp_to_pt_y(v_sp)
            if rec.metrics.has_char(code):
                cm = rec.metrics.char_metrics(code)
                w_pt = cm.width / self._sp_per_bp
                h_pt = cm.height / self._sp_per_bp
                d_pt = cm.depth / self._sp_per_bp
            else:
                w_pt = h_pt = d_pt = 0.0
            if x < x_min:
                x_min = x
            if x + w_pt > x_max:
                x_max = x + w_pt
            if y - h_pt < y_min:
                y_min = y - h_pt
            if y + d_pt > y_max:
                y_max = y + d_pt

        for h_sp, v_sp, w_sp, h_total_sp in self._rule_placements:
            x = self._sp_to_pt_x(h_sp)
            y = self._sp_to_pt_y(v_sp)
            w_pt = w_sp / self._sp_per_bp
            h_pt = h_total_sp / self._sp_per_bp
            if x < x_min:
                x_min = x
            if x + w_pt > x_max:
                x_max = x + w_pt
            if y < y_min:
                y_min = y
            if y + h_pt > y_max:
                y_max = y + h_pt

        if x_min == float("inf"):
            # Every char placement was skipped (missing outlines) and
            # there are no rules — treat as empty for the caller.
            return None

        return (x_min, y_min, x_max, y_max)

    def _build_svg_page(self) -> bytes:
        """Build a complete SVG document for one page.

        The SVG header uses a content-tight ``viewBox`` and matching
        ``width`` / ``height``.  Empty pages fall back to the
        configured page dimensions (preserves the FR-10 default
        for the no-content edge case).  See ``_compute_content_bbox``
        for the bounding-box calculation and the padding note above for the
        Chromium rendering quirk that motivated the switch from a
        page-sized viewBox.
        """
        bbox = self._compute_content_bbox()
        if bbox is None:
            # Empty page — fall back to full page dimensions so the SVG
            # still has a sensible layout box.
            vx_f, vy_f = 0.0, 0.0
            vw_f, vh_f = self._page_width_pt, self._page_height_pt
        else:
            x_min, y_min, x_max, y_max = bbox
            vx_f = max(0.0, x_min - _CONTENT_BBOX_PADDING_PT)
            vy_f = max(0.0, y_min - _CONTENT_BBOX_PADDING_PT)
            vw_f = (x_max - vx_f) + _CONTENT_BBOX_PADDING_PT
            vh_f = (y_max - vy_f) + _CONTENT_BBOX_BOTTOM_PADDING_PT

        vx = self._fmt_num(vx_f)
        vy = self._fmt_num(vy_f)
        vw = self._fmt_num(vw_f)
        vh = self._fmt_num(vh_f)

        parts: list[str] = []
        parts.append(_SVG_HEADER.format(w=vw, h=vh, vx=vx, vy=vy, vw=vw, vh=vh))

        # Collect unique glyphs used on this page.  Keyed by
        # (tfm_name, at_size_sp, code) so the same TFM at distinct sizes
        # produces distinct <defs> entries; the exact-sp at-size keeps
        # fractional sizes that round to the same int pt from colliding
        # (§G FR-10).  The record is carried alongside so
        # _build_defs can scale through the right font.
        used_glyphs: dict[tuple[str, int, int], _SvgFontRecord] = {}
        for rec, code, _h, _v in self._char_placements:
            used_glyphs.setdefault((rec.cs_name, rec.at_size_sp, code), rec)

        # Build <defs>
        parts.append(self._build_defs(used_glyphs))

        # Keep the per-page `<g id="pageN">...</g>` wrapper from the
        # rev. 1 dvisvgm-shape work. It is harmless/cosmetic:
        # rev. 2 bisection showed this wrapper alone did not make
        # Chromium paint the folio (REPORT.md § B). The load-bearing fix
        # is the content-tight viewBox emitted above (REPORT.md § F).
        parts.append(f'<g id="page{len(self._pages) + 1}">\n')

        # Build <use> elements for characters
        for rec, code, h_sp, v_sp in self._char_placements:
            if not self._scaled_glyph_path_d(rec, code):
                key = (rec.tfm_name, code)
                if key not in self._missing_glyph_warned:
                    self._missing_glyph_warned.add(key)
                    warnings.warn(
                        f"SVG: no outline for char code {code} in {rec.tfm_name}",
                        stacklevel=2,
                    )
                continue
            parts.append(self._build_char_use(rec, code, h_sp, v_sp))

        # Build <rect> elements for rules
        for h_sp, v_sp, w_sp, h_total_sp in self._rule_placements:
            parts.append(self._build_rule_rect(h_sp, v_sp, w_sp, h_total_sp))

        parts.append("</g>\n")
        parts.append(_SVG_FOOTER)
        return "".join(parts).encode("utf-8")

    def _build_defs(
        self, used_glyphs: dict[tuple[str, int, int], _SvgFontRecord],
    ) -> str:
        """Build the <defs> block with pre-scaled glyph path definitions.

        Path data is emitted in user (point) units with the TeX-up→SVG-down
        y-flip already folded in (see ``_ensure_font``), so each ``<use>``
        can place the glyph with bare ``x``/``y`` attributes rather than a
        compound ``transform="translate(...) scale(s,-s)"``.

        ``used_glyphs`` maps ``(tfm_name, at_size_sp, code)`` to the font
        record that owns the outline, so a TFM loaded at multiple sizes
        emits one ``<path>`` per (size, code) pair with exact-sp size-encoded
        ids.
        """
        if not used_glyphs:
            return ""
        lines: list[str] = ["<defs>\n"]
        # Sort by (tfm_name, at_size_sp, code) for deterministic output.
        for (key, at_size_sp, code) in sorted(
                used_glyphs, key=lambda k: (self._resource_names[k[0]], k[1], k[2])):
            rec = used_glyphs[(key, at_size_sp, code)]
            d = self._scaled_glyph_path_d(rec, code)
            if not d:
                continue
            glyph_id = _glyph_id(self._resource_names[rec.cs_name], at_size_sp, code)
            lines.append(f'<path id="{glyph_id}" d="{d}"/>\n')
        lines.append("</defs>\n")
        return "".join(lines)

    def _build_char_use(
        self, rec: _SvgFontRecord, char_code: int, h_sp: int, v_sp: int,
    ) -> str:
        """Build a ``<use>`` element for one character placement.

        Emits the dvisvgm-style ``<use x="…" y="…" xlink:href="#…"/>`` form
        (no ``transform`` attribute).  See: the previous
        ``transform="translate(...) scale(0.01,-0.01)"`` form was silently
        dropped by Chromium browsers for the page-folio glyph at
        ``translate(304.38, 739.20)`` while painting body text glyphs at
        the same scale; pre-scaled paths + bare placement attrs render
        consistently across Chrome, Edge, Firefox, and Inkscape.
        """
        x = self._sp_to_pt_x(h_sp)
        y = self._sp_to_pt_y(v_sp)
        glyph_id = _glyph_id(self._resource_names[rec.cs_name], rec.at_size_sp, char_code)
        return (
            f'<use x="{self._fmt_num(x)}" y="{self._fmt_num(y)}"'
            f' xlink:href="#{glyph_id}"/>\n'
        )

    def _build_rule_rect(
        self, h_sp: int, v_sp: int, w_sp: int, h_total_sp: int,
    ) -> str:
        """Build a <rect> element for a rule."""
        x = self._fmt_num(self._sp_to_pt_x(h_sp))
        y = self._fmt_num(self._sp_to_pt_y(v_sp))
        w = self._fmt_num(w_sp / self._sp_per_bp)
        h = self._fmt_num(h_total_sp / self._sp_per_bp)
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="black"/>\n'

    # ------------------------------------------------------------------
    # Coordinate conversion & formatting
    # ------------------------------------------------------------------

    def _sp_to_pt_x(self, h_sp: int) -> float:
        """TeX h (sp) -> SVG x (pt), applying origin offset."""
        return _ORIGIN_X_PT + h_sp / self._sp_per_bp

    def _sp_to_pt_y(self, v_sp: int) -> float:
        """TeX v (sp) -> SVG y (pt), applying origin offset."""
        return _ORIGIN_Y_PT + v_sp / self._sp_per_bp

    def _fmt_num(self, x: float) -> str:
        """Format a float with at most _COORD_PRECISION decimals, no trailing zeros."""
        if x == int(x):
            return str(int(x))
        s = f"{x:.{_COORD_PRECISION}f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        if s in ("", "-", "-0"):
            s = "0"
        return s
