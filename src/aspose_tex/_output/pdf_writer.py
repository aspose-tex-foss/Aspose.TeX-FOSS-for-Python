"""PDF 1.4 output backend.

Implements the PDF writer specified (FR-1..FR-4, FR-7..FR-11) and
Receives completed page boxes from the page builder via the
ShipoutBackend protocol and emits a valid, self-contained PDF file with
embedded Type 1 Computer Modern fonts.

See for full design rationale, object layout, and PDF operator reference.
"""
from __future__ import annotations

import dataclasses
import datetime
import hashlib
import io
import re
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
from aspose_tex._output.glue_setter import GlueSetter
from aspose_tex.exceptions import FontError

if TYPE_CHECKING:
    from aspose_tex._fonts.encoding import FontEncoding
    from aspose_tex._fonts.font_manager import FontManager
    from aspose_tex._fonts.font_metrics import FontMetrics
    from aspose_tex._fonts.pfb_parser import PfbData


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PDF_HEADER = b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n"

_DEFAULT_PAGE_WIDTH_PT = 612
_DEFAULT_PAGE_HEIGHT_PT = 792

_ORIGIN_X_PT = 72
_ORIGIN_Y_FROM_TOP_PT = 72

# Output space is PostScript big points (1in = 72bp), as in pdftex,
# dvipdfmx and dvisvgm; TeX's pt is 1/72.27in, so 1bp = 72.27/72 pt.
_SP_PER_BP = 65536 * 72.27 / 72


def _sp_per_bp(mag: int) -> float:
    """Return the sp in one output bp under *mag*; the 1in origin stays physical."""
    return _SP_PER_BP if mag == 1000 else _SP_PER_BP * 1000 / mag
_WIDTH_SCALE = 1000
_COORD_PRECISION = 4

_DEFAULT_FONTBBOX = (-40, -250, 1009, 750)

_RE_FONTBBOX = re.compile(
    rb"/FontBBox\s*\{\s*(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s*\}"
)
_RE_ITALIC_ANGLE = re.compile(rb"/ItalicAngle\s+(-?[\d.]+)\s+def")


def _rule_paints(width: int, height: int, depth: int) -> bool:
    """Whether a rule actually paints, per TeX:The Program §622 / §634.

    A rule is drawn only when both its total height (``height + depth``) and
    its ``width`` are positive. A non-painting rule (e.g. a zero-width
    ``\\strut``) advances the reference point but emits no rectangle.
    Dimensions are in sp and must already be RUNNING_DIMEN-resolved
    
    """
    return width > 0 and (height + depth) > 0


# ---------------------------------------------------------------------------
# _PdfFontRecord (internal)
# ---------------------------------------------------------------------------

@dataclasses.dataclass(slots=True)
class _PdfFontRecord:
    """Internal bookkeeping for one embedded font.

    Attributes:
        cs_name:            TeX control-sequence name (e.g. ``"tenrm"``).
        tfm_name:           TFM stem (e.g. ``"cmr10"``).
        resource_name:      Name used in the Resources dict (e.g. ``"F1"``).
        at_size_sp:         Requested font size in sp.
        design_size_sp:     Design size in sp.
        metrics:            FontMetrics reference.
        encoding:           FontEncoding from PFB data.
        pfb_data:           Parsed PfbData for embedding.
        font_obj_id:        Object id of the /Font dictionary.
        descriptor_obj_id:  Object id of the /FontDescriptor dict.
        fontfile_obj_id:    Object id of the /FontFile stream.
        encoding_obj_id:    Object id of the /Encoding dict.
        widths_obj_id:      Object id of the /Widths array object.
    """

    cs_name: str
    tfm_name: str
    resource_name: str
    at_size_sp: int
    design_size_sp: int
    metrics: FontMetrics
    encoding: FontEncoding
    pfb_data: PfbData
    font_obj_id: int
    descriptor_obj_id: int
    fontfile_obj_id: int
    encoding_obj_id: int
    widths_obj_id: int


# ---------------------------------------------------------------------------
# PdfWriter
# ---------------------------------------------------------------------------

class PdfWriter:
    """Writes a PDF 1.4 file; implements ``ShipoutBackend``.

    Usage (in-memory)::

        import io
        buf = io.BytesIO()
        writer = PdfWriter(buf, font_manager=mgr)
        page_builder = PageBuilder(config, backend=writer, ...)
        # ... feed content to page_builder ...
        page_builder.end_of_document()
        writer.finalize()
        pdf_bytes = writer.get_bytes()

    With file output::

        writer = PdfWriter(Path("output.pdf"), font_manager=mgr)
        # ... use writer as backend ...
        writer.finalize()
    """

    def __init__(
        self,
        destination: Path | io.BytesIO | io.BufferedWriter,
        font_manager: FontManager,
        *,
        mag: int = 1000,
        page_width_pt: float = _DEFAULT_PAGE_WIDTH_PT,
        page_height_pt: float = _DEFAULT_PAGE_HEIGHT_PT,
        producer: str = "aspose_tex",
    ) -> None:
        """Initialise the PDF writer.

        Args:
            destination:    ``pathlib.Path`` for file output, or ``io.BytesIO``
                            for in-memory output.
            font_manager:   Used to load TFM metrics and PFB data on demand.
            mag:            TeX magnification * 1000 (default 1000 = 1x).
            page_width_pt:  Page width in PDF points (default 612 = US Letter).
            page_height_pt: Page height in PDF points (default 792).
            producer:       String placed in /Info /Producer.
        """
        self._font_manager = font_manager
        self._mag = mag
        self._mag_source: Callable[[], int] | None = None
        self._mag_fixed = False
        self._sp_per_bp = _sp_per_bp(mag)
        self._page_width_pt = float(page_width_pt)
        self._page_height_pt = float(page_height_pt)
        self._producer = producer

        self._is_memory = not isinstance(destination, Path)
        self._owns_file = False
        if isinstance(destination, Path):
            self._stream: io.BufferedWriter | io.BytesIO = destination.open("wb")
            self._owns_file = True
        else:
            self._stream = destination  # type: ignore[assignment]

        self._next_object_id = 1
        self._xref_offsets: dict[int, int] = {}
        self._page_ids: list[int] = []
        self._fonts: dict[str, _PdfFontRecord] = {}
        self._next_resource_num = 1
        self._finalized = False

        self._content_buf: io.BytesIO = io.BytesIO()
        self._run_font: _PdfFontRecord | None = None
        self._run_chars: list[int] = []
        self._run_h_sp: int = 0
        self._run_v_sp: int = 0
        self._specials_warned: set[bytes] = set()
        self._missing_glyph_warned: set[tuple[str, int]] = set()

        self._creation_date = self._now_pdf_date()

        # Reserve object id 1 for Pages root so Page objects written during
        # shipout() can reference /Parent N 0 R immediately.
        self._pages_obj_id = self._allocate_object()

        self._stream.write(_PDF_HEADER)

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
        """Receive one completed page and append a Page object to the PDF.

        Args:
            page_number: Value of ``\\pageno`` at shipout time.
            box:         Finalised page VlistNode.

        Raises:
            RuntimeError: If ``finalize()`` has already been called.
            FontError:    If a CharNode references a font without a loadable PFB.
        """
        if self._finalized:
            raise RuntimeError("PdfWriter.shipout() called after finalize()")
        if not self._mag_fixed:
            self._mag_fixed = True
            if self._mag_source is not None:
                self._mag = self._mag_source()
                self._sp_per_bp = _sp_per_bp(self._mag)

        # Reset per-page state.
        self._content_buf = io.BytesIO()
        self._run_font = None
        self._run_chars = []
        self._run_h_sp = 0
        self._run_v_sp = 0

        # Ensure all referenced fonts are loaded.
        for cs_name in self._collect_fonts(box):
            self._ensure_font(cs_name)

        # Traverse the page box.
        self._traverse_vlist(box.list, box, h_ref=0, v_ref=0)
        self._flush_text_run()

        content_bytes = self._content_buf.getvalue()

        # Write content stream object.
        stream_id = self._allocate_object()
        self._write_stream_object(stream_id, b"", content_bytes)

        # Write Page object referencing the content and the (reserved) Pages root.
        page_id = self._allocate_object()
        body = (
            b"<< /Type /Page /Parent "
            + str(self._pages_obj_id).encode("ascii")
            + b" 0 R /Contents "
            + str(stream_id).encode("ascii")
            + b" 0 R >>"
        )
        self._write_object(page_id, body)
        self._page_ids.append(page_id)

    # ------------------------------------------------------------------
    # Finalisation
    # ------------------------------------------------------------------

    def finalize(self) -> None:
        """Write font objects, Pages root, Catalog, Info, xref and trailer.

        Raises:
            RuntimeError: If called more than once.
        """
        if self._finalized:
            raise RuntimeError("PdfWriter.finalize() already called")
        self._finalized = True

        self._write_font_objects()
        self._write_pages_root()
        catalog_id = self._write_catalog(self._pages_obj_id)
        info_id = self._write_info()
        self._write_xref_and_trailer(catalog_id, info_id)

        if self._owns_file:
            self._stream.close()
        elif hasattr(self._stream, "flush"):
            self._stream.flush()

    def get_bytes(self) -> bytes:
        """Return the full PDF content as bytes.

        Valid only after ``finalize()`` and only when destination is a
        ``BytesIO`` (or similar in-memory buffer).

        Raises:
            RuntimeError: If ``finalize()`` has not been called or destination
                          is a file path.
        """
        if not self._finalized:
            raise RuntimeError("PdfWriter.finalize() must be called before get_bytes()")
        if not self._is_memory:
            raise RuntimeError("get_bytes() is only available for in-memory destinations")
        return self._stream.getvalue()  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Object allocation and emission
    # ------------------------------------------------------------------

    def _allocate_object(self) -> int:
        obj_id = self._next_object_id
        self._next_object_id += 1
        return obj_id

    def _write_object(self, obj_id: int, body: bytes) -> None:
        """Emit ``obj_id 0 obj\\n<body>\\nendobj\\n``; record xref offset."""
        self._xref_offsets[obj_id] = self._stream.tell()
        self._stream.write(str(obj_id).encode("ascii"))
        self._stream.write(b" 0 obj\n")
        self._stream.write(body)
        self._stream.write(b"\nendobj\n")

    def _write_stream_object(
        self,
        obj_id: int,
        dict_entries: bytes,
        stream_bytes: bytes,
    ) -> None:
        """Emit a stream object with ``/Length`` set from ``stream_bytes``."""
        self._xref_offsets[obj_id] = self._stream.tell()
        self._stream.write(str(obj_id).encode("ascii"))
        self._stream.write(b" 0 obj\n<<")
        if dict_entries:
            self._stream.write(b" ")
            self._stream.write(dict_entries)
        self._stream.write(b" /Length ")
        self._stream.write(str(len(stream_bytes)).encode("ascii"))
        self._stream.write(b" >>\nstream\n")
        self._stream.write(stream_bytes)
        self._stream.write(b"\nendstream\nendobj\n")

    # ------------------------------------------------------------------
    # Font handling
    # ------------------------------------------------------------------

    def _collect_fonts(self, node: object) -> list[str]:
        """Depth-first collection of CharNode.font_name values (deduped)."""
        seen: set[str] = set()
        result: list[str] = []

        def _walk(n: object) -> None:
            if isinstance(n, CharNode):
                if n.font_name not in seen:
                    seen.add(n.font_name)
                    result.append(n.font_name)
            elif isinstance(n, LeadersNode):
                _walk(n.payload)
            elif isinstance(n, (HlistNode, VlistNode)):
                for child in iter_nobreak_nodes(n.list):
                    _walk(child)

        _walk(node)
        return result

    def _ensure_font(self, cs_name: str) -> _PdfFontRecord:
        rec = self._fonts.get(cs_name)
        if rec is not None:
            return rec

        info = self._font_manager.font_def_info(cs_name)
        if info is None:
            name = cs_name if not cs_name.startswith(chr(0)) else 'unknown identifier'
            raise FontError(f"PDF: font '{name}' not loaded")
        tfm_name, _checksum, design_size_sp, at_size_sp = info

        pfb = self._font_manager.load_pfb(cs_name)
        if pfb is None:
            raise FontError(f"PDF: no PFB for '{tfm_name}'")

        from aspose_tex._fonts.encoding import FontEncoding

        encoding = FontEncoding(pfb)
        metrics = self._font_manager.get_metrics(cs_name)
        assert metrics is not None  # font_def_info succeeded

        resource_name = f"F{self._next_resource_num}"
        self._next_resource_num += 1

        widths_id = self._allocate_object()
        encoding_id = self._allocate_object()
        fontfile_id = self._allocate_object()
        descriptor_id = self._allocate_object()
        font_id = self._allocate_object()

        rec = _PdfFontRecord(
            cs_name=cs_name,
            tfm_name=tfm_name,
            resource_name=resource_name,
            at_size_sp=at_size_sp,
            design_size_sp=design_size_sp,
            metrics=metrics,
            encoding=encoding,
            pfb_data=pfb,
            font_obj_id=font_id,
            descriptor_obj_id=descriptor_id,
            fontfile_obj_id=fontfile_id,
            encoding_obj_id=encoding_id,
            widths_obj_id=widths_id,
        )
        self._fonts[cs_name] = rec
        return rec

    # ------------------------------------------------------------------
    # Traversal
    # ------------------------------------------------------------------

    def _traverse_vlist(
        self, nodes: list, parent: VlistNode, h_ref: int, v_ref: int,
    ) -> None:
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
                # TeX §634: emit the rect only when the rule paints; the
                # reference point advances by height+depth either way.
                v_cursor += height
                if _rule_paints(width, height, depth):
                    self._emit_rect(h_ref, v_cursor - height, width, height + depth)
                v_cursor += depth
            elif isinstance(node, WhatsitNode):
                self._warn_whatsit(node)

    def _traverse_hlist(
        self, nodes: list, parent: HlistNode, h_ref: int, v_ref: int,
    ) -> None:
        # Each HlistNode is a distinct baseline. Flush any text run carried
        # over from the previous hlist so its (_run_h_sp, _run_v_sp) is not
        # reused for characters belonging to this line. See.
        self._flush_text_run()
        setter = GlueSetter.for_box(parent)
        h_cursor = h_ref
        for node in iter_nobreak_nodes(nodes):
            if isinstance(node, CharNode):
                rec = self._ensure_font(node.font_name)

                if not rec.encoding.has_code(node.char):
                    key = (rec.tfm_name, node.char)
                    if key not in self._missing_glyph_warned:
                        self._missing_glyph_warned.add(key)
                        warnings.warn(
                            f"PDF: char code {node.char} missing from "
                            f"{rec.tfm_name} encoding; skipping",
                            stacklevel=2,
                        )
                    # Still advance by TFM width (consistent with DVI which
                    # emits the char regardless).
                    if rec.metrics.has_char(node.char):
                        h_cursor += rec.metrics.char_metrics(node.char).width
                    continue

                # Open or continue run.
                if (self._run_font is None or self._run_font is not rec
                        or self._run_v_sp != v_ref):
                    self._flush_text_run()
                    self._run_font = rec
                    self._run_h_sp = h_cursor
                    self._run_v_sp = v_ref
                    self._run_chars = []

                self._run_chars.append(node.char)
                if rec.metrics.has_char(node.char):
                    h_cursor += rec.metrics.char_metrics(node.char).width

            elif isinstance(node, KernNode):
                self._flush_text_run()
                h_cursor += node.width

            elif isinstance(node, MathNode):
                # A zero-width formula boundary must not split the text run.
                if node.width:
                    self._flush_text_run()
                    h_cursor += node.width

            elif isinstance(node, LeadersNode):
                span = setter.set_size(node.glue)
                self._paint_leaders(node, parent, h_cursor, v_ref, span, vertical=False, origin=h_ref)
                h_cursor += span

            elif isinstance(node, GlueNode):
                self._flush_text_run()
                h_cursor += setter.set_size(node.glue)

            elif isinstance(node, (PenaltyNode, InsertNode)):
                pass

            elif isinstance(node, RuleNode):
                self._flush_text_run()
                width = node.width if node.width != RUNNING_DIMEN else parent.width
                height = node.height if node.height != RUNNING_DIMEN else parent.height
                depth = node.depth if node.depth != RUNNING_DIMEN else parent.depth
                # TeX §622: emit the rect only when the rule paints; the
                # reference point advances by width either way.
                if _rule_paints(width, height, depth):
                    self._emit_rect(h_cursor, v_ref - height, width, height + depth)
                h_cursor += width

            elif isinstance(node, HlistNode):
                self._flush_text_run()
                self._traverse_hlist(
                    node.list, node,
                    h_ref=h_cursor,
                    v_ref=v_ref - node.shift_amount,
                )
                h_cursor += node.width

            elif isinstance(node, VlistNode):
                self._flush_text_run()
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
        self._flush_text_run()
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
                self._emit_rect(h, v, width, height)
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
            self._flush_text_run()
        finally:
            self._doing_leaders = previous

    def _warn_whatsit(self, node: WhatsitNode) -> None:
        if isinstance(node.data, LanguageWhatsit):
            return  # no output and nothing to report (§7)
        key = repr(node.data).encode("utf-8", errors="replace")
        if key in self._specials_warned:
            return
        self._specials_warned.add(key)
        warnings.warn(
            f"PDF: \\special/whatsit ignored: {node.data!r}",
            stacklevel=2,
        )

    # ------------------------------------------------------------------
    # Text run emission
    # ------------------------------------------------------------------

    def _flush_text_run(self) -> None:
        if self._run_font is None or not self._run_chars:
            self._run_font = None
            self._run_chars = []
            return

        rec = self._run_font
        size_pt = rec.at_size_sp / self._sp_per_bp
        x_pt = self._sp_to_pt_x(self._run_h_sp)
        y_pt = self._sp_to_pt_y(self._run_v_sp)

        buf = self._content_buf
        buf.write(b"BT\n")
        buf.write(b"/")
        buf.write(rec.resource_name.encode("ascii"))
        buf.write(b" ")
        buf.write(self._fmt_num(size_pt))
        buf.write(b" Tf\n")
        buf.write(self._fmt_num(x_pt))
        buf.write(b" ")
        buf.write(self._fmt_num(y_pt))
        buf.write(b" Td\n")
        buf.write(b"(")
        buf.write(self._escape_pdf_string(self._run_chars))
        buf.write(b") Tj\n")
        buf.write(b"ET\n")

        self._run_font = None
        self._run_chars = []

    def _emit_rect(
        self, h_sp: int, v_sp_top: int, w_sp: int, h_sp_total: int,
    ) -> None:
        self._flush_text_run()
        x = self._sp_to_pt_x(h_sp)
        y = self._sp_to_pt_y(v_sp_top + h_sp_total)  # PDF: bottom edge
        w = self._sp_to_pt_delta(w_sp)
        h = self._sp_to_pt_delta(h_sp_total)
        buf = self._content_buf
        buf.write(self._fmt_num(x))
        buf.write(b" ")
        buf.write(self._fmt_num(y))
        buf.write(b" ")
        buf.write(self._fmt_num(w))
        buf.write(b" ")
        buf.write(self._fmt_num(h))
        buf.write(b" re\nf\n")

    # ------------------------------------------------------------------
    # Coordinate conversion & formatting
    # ------------------------------------------------------------------

    def _sp_to_pt_x(self, h_sp: int) -> float:
        return _ORIGIN_X_PT + h_sp / self._sp_per_bp

    def _sp_to_pt_y(self, v_sp: int) -> float:
        return self._page_height_pt - _ORIGIN_Y_FROM_TOP_PT - v_sp / self._sp_per_bp

    def _sp_to_pt_delta(self, sp: int) -> float:
        return sp / self._sp_per_bp

    def _fmt_num(self, x: float) -> bytes:
        if x == int(x):
            return str(int(x)).encode("ascii")
        s = f"{x:.{_COORD_PRECISION}f}"
        # Strip trailing zeros and dangling decimal point.
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        if s in ("", "-", "-0"):
            s = "0"
        return s.encode("ascii")

    def _escape_pdf_string(self, char_codes: list[int]) -> bytes:
        out = bytearray()
        for code in char_codes:
            if code == 0x28:      # '('
                out.extend(b"\\(")
            elif code == 0x29:    # ')'
                out.extend(b"\\)")
            elif code == 0x5C:    # '\'
                out.extend(b"\\\\")
            elif 0x20 <= code <= 0x7E:
                out.append(code)
            else:
                out.extend(f"\\{code:03o}".encode("ascii"))
        return bytes(out)

    # ------------------------------------------------------------------
    # Font-object emission (in finalize)
    # ------------------------------------------------------------------

    def _write_font_objects(self) -> None:
        for rec in self._fonts.values():
            self._write_widths_object(rec)
            self._write_encoding_object(rec)
            self._write_fontfile_object(rec)
            self._write_fontdescriptor_object(rec)
            self._write_font_dict_object(rec)

    def _write_widths_object(self, rec: _PdfFontRecord) -> None:
        widths: list[int] = []
        for code in range(256):
            if rec.metrics.has_char(code):
                # The TFM width is already scaled to the at size, so glyph
                # space (1/1000 em) divides by the at size, not the design
                # size: every instance of one TFM gets the same /Widths.
                w_sp = rec.metrics.char_metrics(code).width
                widths.append(
                    round(w_sp * _WIDTH_SCALE / rec.at_size_sp)
                )
            else:
                widths.append(0)
        body = b"[" + b" ".join(str(w).encode("ascii") for w in widths) + b"]"
        self._write_object(rec.widths_obj_id, body)

    def _write_encoding_object(self, rec: _PdfFontRecord) -> None:
        diffs = rec.encoding.differences()
        parts = [b"<< /Type /Encoding /Differences ["]
        last_code = -2
        for code, name in diffs:
            if code != last_code + 1:
                parts.append(b" ")
                parts.append(str(code).encode("ascii"))
            parts.append(b" /")
            parts.append(name.encode("ascii"))
            last_code = code
        parts.append(b" ] >>")
        self._write_object(rec.encoding_obj_id, b"".join(parts))

    def _write_fontfile_object(self, rec: _PdfFontRecord) -> None:
        pfb = rec.pfb_data
        length1 = len(pfb.ascii_header)
        length2 = len(pfb.binary_body)
        length3 = len(pfb.ascii_trailer)
        dict_entries = (
            b"/Length1 " + str(length1).encode("ascii")
            + b" /Length2 " + str(length2).encode("ascii")
            + b" /Length3 " + str(length3).encode("ascii")
        )
        stream_bytes = pfb.ascii_header + pfb.binary_body + pfb.ascii_trailer
        self._write_stream_object(rec.fontfile_obj_id, dict_entries, stream_bytes)

    def _write_fontdescriptor_object(self, rec: _PdfFontRecord) -> None:
        bbox = self._parse_pfb_fontbbox(rec.pfb_data)
        italic_angle = self._parse_pfb_italic_angle(rec.pfb_data)
        ascent = bbox[3]
        descent = bbox[1]
        cap_height = ascent
        flags = self._font_flags(rec.tfm_name, italic_angle)

        font_name = rec.pfb_data.font_name or rec.tfm_name.upper()

        body = (
            b"<< /Type /FontDescriptor"
            + b" /FontName /" + font_name.encode("ascii")
            + b" /Flags " + str(flags).encode("ascii")
            + b" /FontBBox [" + b" ".join(
                str(v).encode("ascii") for v in bbox
            ) + b"]"
            + b" /ItalicAngle " + self._fmt_num(italic_angle)
            + b" /Ascent " + str(ascent).encode("ascii")
            + b" /Descent " + str(descent).encode("ascii")
            + b" /CapHeight " + str(cap_height).encode("ascii")
            + b" /StemV 70"
            + b" /FontFile " + str(rec.fontfile_obj_id).encode("ascii") + b" 0 R"
            + b" >>"
        )
        self._write_object(rec.descriptor_obj_id, body)

    def _write_font_dict_object(self, rec: _PdfFontRecord) -> None:
        font_name = rec.pfb_data.font_name or rec.tfm_name.upper()
        body = (
            b"<< /Type /Font /Subtype /Type1"
            + b" /BaseFont /" + font_name.encode("ascii")
            + b" /FirstChar 0 /LastChar 255"
            + b" /Widths " + str(rec.widths_obj_id).encode("ascii") + b" 0 R"
            + b" /FontDescriptor " + str(rec.descriptor_obj_id).encode("ascii") + b" 0 R"
            + b" /Encoding " + str(rec.encoding_obj_id).encode("ascii") + b" 0 R"
            + b" >>"
        )
        self._write_object(rec.font_obj_id, body)

    def _parse_pfb_fontbbox(self, pfb: PfbData) -> tuple[int, int, int, int]:
        m = _RE_FONTBBOX.search(pfb.ascii_header)
        if m is None:
            return _DEFAULT_FONTBBOX
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))

    def _parse_pfb_italic_angle(self, pfb: PfbData) -> float:
        m = _RE_ITALIC_ANGLE.search(pfb.ascii_header)
        if m is None:
            return 0.0
        return float(m.group(1))

    def _font_flags(self, tfm_name: str, italic_angle: float) -> int:
        flags = 4 | 2  # Symbolic + Serif (baseline for CM)
        name = tfm_name.lower()
        if (name.startswith("cmtt")
                or name.startswith("cmitt")
                or name.startswith("cmsltt")
                or name.startswith("cmvtt")):
            flags |= 1  # FixedPitch
        if italic_angle != 0:
            flags |= 64  # Italic
        return flags

    # ------------------------------------------------------------------
    # Pages root, Catalog, Info
    # ------------------------------------------------------------------

    def _write_pages_root(self) -> None:
        kids = b" ".join(
            str(pid).encode("ascii") + b" 0 R" for pid in self._page_ids
        )
        mediabox = (
            b"[0 0 "
            + self._fmt_num(self._page_width_pt) + b" "
            + self._fmt_num(self._page_height_pt) + b"]"
        )

        if self._fonts:
            font_entries = b" ".join(
                b"/" + rec.resource_name.encode("ascii")
                + b" " + str(rec.font_obj_id).encode("ascii") + b" 0 R"
                for rec in self._fonts.values()
            )
            resources = b" /Resources << /Font << " + font_entries + b" >> >>"
        else:
            resources = b" /Resources << >>"

        body = (
            b"<< /Type /Pages /Kids [" + kids + b"]"
            + b" /Count " + str(len(self._page_ids)).encode("ascii")
            + b" /MediaBox " + mediabox
            + resources
            + b" >>"
        )
        self._write_object(self._pages_obj_id, body)

    def _write_catalog(self, pages_obj_id: int) -> int:
        cid = self._allocate_object()
        body = (
            b"<< /Type /Catalog /Pages "
            + str(pages_obj_id).encode("ascii") + b" 0 R >>"
        )
        self._write_object(cid, body)
        return cid

    def _write_info(self) -> int:
        iid = self._allocate_object()
        producer = self._producer.encode("ascii", errors="replace")
        body = (
            b"<< /Producer (" + producer + b")"
            + b" /Creator (aspose_tex)"
            + b" /CreationDate (" + self._creation_date + b")"
            + b" >>"
        )
        self._write_object(iid, body)
        return iid

    # ------------------------------------------------------------------
    # xref + trailer
    # ------------------------------------------------------------------

    def _write_xref_and_trailer(
        self, root_obj_id: int, info_obj_id: int,
    ) -> None:
        xref_offset = self._stream.tell()
        n_objects = self._next_object_id - 1
        size = n_objects + 1

        self._stream.write(b"xref\n")
        self._stream.write(b"0 ")
        self._stream.write(str(size).encode("ascii"))
        self._stream.write(b"\n")
        self._stream.write(b"0000000000 65535 f \n")
        for obj_id in range(1, n_objects + 1):
            offset = self._xref_offsets.get(obj_id, 0)
            self._stream.write(
                f"{offset:010d} 00000 n \n".encode("ascii")
            )

        # ID: MD5 of producer + creation_date + page_count, same in both slots.
        h = hashlib.md5()
        h.update(self._producer.encode("utf-8", errors="replace"))
        h.update(self._creation_date)
        h.update(str(len(self._page_ids)).encode("ascii"))
        id_hex = h.hexdigest().encode("ascii")

        self._stream.write(b"trailer\n")
        self._stream.write(
            b"<< /Size " + str(size).encode("ascii")
            + b" /Root " + str(root_obj_id).encode("ascii") + b" 0 R"
            + b" /Info " + str(info_obj_id).encode("ascii") + b" 0 R"
            + b" /ID [<" + id_hex + b"> <" + id_hex + b">] >>\n"
        )
        self._stream.write(b"startxref\n")
        self._stream.write(str(xref_offset).encode("ascii"))
        self._stream.write(b"\n%%EOF\n")

    def _now_pdf_date(self) -> bytes:
        now = datetime.datetime.now(datetime.timezone.utc)
        return now.strftime("D:%Y%m%d%H%M%SZ").encode("ascii")
