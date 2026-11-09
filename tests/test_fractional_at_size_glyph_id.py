"""Regression tests for exact fractional ``at_size_sp``.

Covers §G — fractional / magnified font sizes (reachable via
``\\font\\x=cmr10 at 10.95pt`` and ``scaled \\magstephalf``):

- **AC-5a (FR-9):** ``\\font\\x=cmr10 at 10.95pt`` emits the *exact* ``at_size_sp``
  in the DVI ``fnt_def`` — no ``round(pt)`` step between the engine and the DVI
  writer.  This is a verification + regression guard; the path is already exact.
- **AC-5b (FR-10, closes):** two distinct fractional sizes that round to
  the *same* integer pt (10.3pt = 675020 sp and 10.4pt = 681574 sp, both round to
  10pt) must emit **distinct** SVG ``<path>`` ids with per-size ``<use>``
  resolution.  Under the old ``g-{tfm}-{round(pt)}-{code}`` scheme both collapsed
  onto ``g-cmr10-10-72`` and the later font silently overwrote the earlier
  outline (re-opened for fractional sizes).
"""
from __future__ import annotations

import io
import warnings
import xml.etree.ElementTree as ET

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import CharNode, GlueSign, HlistNode, VlistNode
from aspose_tex._engine.registers import GlueOrder
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._input.reader import StringInputSource
from aspose_tex._output.dvi_writer import DviWriter
from aspose_tex._output.svg_writer import SvgWriter

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
_NS = f"{{{SVG_NS}}}"
_XLINK_HREF = f"{{{XLINK_NS}}}href"

# cmr10 design size = 10pt = 655360 sp.  TeX parses ``at <dimen>`` to exact sp:
#   10.95pt -> 717619 sp   (collision-free anchor for FR-9)
#   10.3pt  -> 675020 sp ┐ both round to 10pt under the old round(pt) scheme,
#   10.4pt  -> 681574 sp ┘ so they collided on g-cmr10-10-<code> (FR-10 bug).
_AT_10_95_SP = 717_619
_AT_10_3_SP = 675_020
_AT_10_4_SP = 681_574


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hbox(nodes: list) -> HlistNode:
    return HlistNode(
        list=nodes, width=0, height=0, depth=0, shift_amount=0,
        glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
    )


def _page(children: list) -> VlistNode:
    return VlistNode(
        list=children, width=0, height=0, depth=0, shift_amount=0,
        glue_sign=GlueSign.NORMAL, glue_order=GlueOrder.NORMAL, glue_set=0.0,
    )


def _fnt_def_scaled_sizes(dvi: bytes) -> dict[bytes, int]:
    """Return ``{tfm_name_bytes: scaled_size_sp}`` for every ``fnt_def`` in *dvi*.

    Walks the DVI byte stream and decodes the ``scaled_size_sp`` 4-byte field of
    each ``fnt_def1..fnt_def4`` (opcodes 243..246), keyed by the TFM file name.
    """
    sizes: dict[bytes, int] = {}
    i = 0
    n = len(dvi)
    while i < n:
        op = dvi[i]
        if 243 <= op <= 246:  # fnt_def1..fnt_def4
            fn_bytes = op - 242
            base = i + 1 + fn_bytes
            # font_num (fn_bytes) | checksum (4) | scaled (4) | design (4)
            scaled = int.from_bytes(dvi[base + 4 : base + 8], "big")
            area_len = dvi[base + 12]
            name_len = dvi[base + 13]
            name = bytes(dvi[base + 14 + area_len : base + 14 + area_len + name_len])
            sizes[name] = scaled
            i = base + 14 + area_len + name_len
        else:  # pragma: no cover - this test only reaches the preamble + fnt_def
            i += 1
    return sizes


def _render_svg(mgr: FontManager, page: VlistNode) -> ET.Element:
    buf = io.BytesIO()
    writer = SvgWriter(buf, font_manager=mgr)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        writer.shipout(1, page)
        writer.finalize()
    return ET.fromstring(writer.get_bytes())


# ---------------------------------------------------------------------------
# AC-5a (FR-9): exact at_size_sp through DVI fnt_def
# ---------------------------------------------------------------------------

class TestDviExactAtSize:
    """``\\font\\x=cmr10 at 10.95pt`` reaches the DVI ``fnt_def`` un-rounded."""

    def test_engine_parses_exact_sp(self) -> None:
        """The engine stores the exact sp for a fractional ``at`` size."""
        interp = TeXInterpreter()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            interp.run(StringInputSource(r"\font\x=cmr10 at 10.95pt \bye"))
        info = interp._font_manager.font_def_info("x")
        assert info is not None
        _tfm, _cs, _design, at_size = info
        assert at_size == _AT_10_95_SP  # 10.95pt, exact — not round(11pt)

    def test_dvi_fnt_def_carries_exact_sp(self) -> None:
        """The DVI ``fnt_def`` scaled-size field is the exact sp, no pt rounding.

        Drives ``DviWriter`` directly with a CharNode in the fractional-size
        font so the ``fnt_def`` is emitted, then decodes the scaled-size field
        straight out of the DVI bytes.
        """
        mgr = FontManager()
        mgr.load_font("x", "cmr10", at_sp=_AT_10_95_SP)
        buf = io.BytesIO()
        writer = DviWriter(buf, font_manager=mgr)
        writer.shipout(1, _page([_hbox([CharNode(char=72, font_name="x")])]))
        writer.finalize()

        sizes = _fnt_def_scaled_sizes(writer.get_bytes())
        assert sizes.get(b"cmr10") == _AT_10_95_SP


# ---------------------------------------------------------------------------
# AC-5b (FR-10): collision-free SVG glyph ids for fractional sizes
# ---------------------------------------------------------------------------

class TestFractionalGlyphIdCollision:
    """Two sizes rounding to the same int pt emit distinct ``<path>`` ids."""

    def test_same_round_pt_distinct_path_ids(self) -> None:
        """10.3pt and 10.4pt (both round to 10pt) yield distinct id sets.

        the old ``round(pt)`` id scheme collapsed both onto
        ``g-cmr10-10-72``; the exact-sp scheme keeps them separate.
        """
        mgr = FontManager()
        mgr.load_font("small", "cmr10", at_sp=_AT_10_3_SP)  # 10.3pt
        mgr.load_font("big", "cmr10", at_sp=_AT_10_4_SP)    # 10.4pt
        page = _page([_hbox([
            CharNode(char=72, font_name="small"),  # H @ 10.3pt
            CharNode(char=72, font_name="big"),     # H @ 10.4pt
        ])])
        root = _render_svg(mgr, page)

        defs = root.find(f"{_NS}defs")
        assert defs is not None
        ids = [p.get("id") for p in defs.findall(f"{_NS}path")]

        # Distinct, exact-sp-encoded ids — no collapse onto g-cmr10-10-72.
        assert f"g-cmr10-{_AT_10_3_SP}-72" in ids
        assert f"g-cmr10-{_AT_10_4_SP}-72" in ids
        assert len(ids) == 2
        assert len(ids) == len(set(ids)), f"duplicate path ids: {ids}"

    def test_per_size_use_resolution(self) -> None:
        """each ``<use>`` resolves to the path for its own size."""
        mgr = FontManager()
        mgr.load_font("small", "cmr10", at_sp=_AT_10_3_SP)
        mgr.load_font("big", "cmr10", at_sp=_AT_10_4_SP)
        page = _page([_hbox([
            CharNode(char=72, font_name="small"),
            CharNode(char=72, font_name="big"),
        ])])
        root = _render_svg(mgr, page)

        defs = root.find(f"{_NS}defs")
        defined = {p.get("id") for p in defs.findall(f"{_NS}path")}
        hrefs = [u.get(_XLINK_HREF) for u in root.findall(f".//{_NS}use")]

        assert f"#g-cmr10-{_AT_10_3_SP}-72" in hrefs
        assert f"#g-cmr10-{_AT_10_4_SP}-72" in hrefs
        for href in hrefs:
            assert href[1:] in defined, f"dangling href {href!r}"

        # Outlines differ in scale — proving they are not one shared definition.
        d_small = next(
            p.get("d") for p in defs.findall(f"{_NS}path")
            if p.get("id") == f"g-cmr10-{_AT_10_3_SP}-72"
        )
        d_big = next(
            p.get("d") for p in defs.findall(f"{_NS}path")
            if p.get("id") == f"g-cmr10-{_AT_10_4_SP}-72"
        )
        assert d_small != d_big
