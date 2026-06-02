"""Interpreter-integration tests for output-routine wiring.

Covers:
- \\pageno alias to \\count0 and register-driven advance ( AC-2).
- \\vsize, \\topskip, \\maxdepth assignment handlers ( AC-6).
- \\output CS is undefined in M2 ( AC-1 / error-handling row).
- DVI-regression: folio CharNodes are shipped ( AC-5).
- DVI-regression: \\vfil / \\vsize vertical distribution ( AC-3, AC-4).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.reader import StringInputSource
from tests._verification.dvi_walker import walk_line_starts as _walk_line_starts

# ---------------------------------------------------------------------------
# DVI opcode constants (subset needed for folio scanning)
# ---------------------------------------------------------------------------

_SET_CHAR_MAX = 127
_SET1 = 128
_BOP = 139
_EOP = 140
_PRE = 247
_POST = 248
_POST_POST = 249
_DVI_ID = 2


_DVI_OP_OPERAND_SIZE: dict[int, int] = {
 132: 8, 137: 8, 138: 0, _BOP: 44, _EOP: 0, 141: 0, 142: 0,
 143: 1, 144: 2, 145: 3, 146: 4,
 147: 0, 148: 1, 149: 2, 150: 3, 151: 4,
 152: 0, 153: 1, 154: 2, 155: 3, 156: 4,
 157: 1, 158: 2, 159: 3, 160: 4,
 161: 0, 162: 1, 163: 2, 164: 3, 165: 4,
 166: 0, 167: 1, 168: 2, 169: 3, 170: 4,
 235: 1, 236: 2, 237: 3, 238: 4,
}
for _op in range(171, 235):
 _DVI_OP_OPERAND_SIZE[_op] = 0


def _skip_preamble(dvi: bytes) -> int:
 assert dvi[0] == _PRE and dvi[1] == _DVI_ID
 k = dvi[14]
 return 15 + k


def _collect_chars_per_page(dvi: bytes) -> list[list[int]]:
 """Return a list of char-code lists, one per DVI page (bop..eop)."""
 i = _skip_preamble(dvi)
 n = len(dvi)
 pages: list[list[int]] = []
 current: list[int] | None = None
 while i < n:
 op = dvi[i]
 if op == _POST:
 break
 if op == _BOP:
 current = []
 pages.append(current)
 i += 1 + 44
 continue
 if op == _EOP:
 current = None
 i += 1
 continue
 if current is None:
 i += 1
 continue
 if op <= _SET_CHAR_MAX:
 current.append(op)
 i += 1
 continue
 if op == _SET1:
 current.append(dvi[i + 1])
 i += 2
 continue
 if 243 <= op <= 246:
 fn_bytes = op - 242
 base = i + 1 + fn_bytes + 4 + 4 + 4
 area_len = dvi[base]
 name_len = dvi[base + 1]
 i = base + 2 + area_len + name_len
 continue
 if 239 <= op <= 242:
 kbytes = op - 238
 length = int.from_bytes(dvi[i + 1 : i + 1 + kbytes], "big")
 i += 1 + kbytes + length
 continue
 size = _DVI_OP_OPERAND_SIZE.get(op)
 if size is None:
 break
 i += 1 + size
 return pages


def _run(tex: str) -> bytes:
 from aspose_tex.presentation import DviDevice

 device = DviDevice()
 TeXInterpreter().run_with_device(StringInputSource(tex), device)
 return device.get_bytes()


# ---------------------------------------------------------------------------
# \pageno alias (AC-2)
# ---------------------------------------------------------------------------

class TestPagenoAlias:
 def test_pageno_alias_set_and_advance(self) -> None:
 """Start pageno=7 → footline shows '7'; after shipout count[0]==8."""
 from aspose_tex.presentation import DviDevice

 interp = TeXInterpreter()
 device = DviDevice()
 interp.run_with_device(StringInputSource(r"\pageno=7 Hello\bye"), device)
 dvi = device.get_bytes()
 pages = _collect_chars_per_page(dvi)
 assert len(pages) == 1
 assert ord("7") in pages[0]
 # count[0] was advanced to 8 after the single shipout.
 assert interp._register_set.get_count(0) == 8

 def test_pageno_increments_multipage(self) -> None:
 r"""Three forced pages: folios '1', '2', '3' appear on each page."""
 tex = r"Page one\eject Page two\eject Page three\bye"
 dvi = _run(tex)
 pages = _collect_chars_per_page(dvi)
 assert len(pages) == 3
 assert ord("1") in pages[0]
 assert ord("2") in pages[1]
 assert ord("3") in pages[2]


# ---------------------------------------------------------------------------
# \vsize, \topskip, \maxdepth register-to-config sync (AC-6)
# ---------------------------------------------------------------------------

class TestConfigRegisterSync:
 def _capture_config(self, tex: str):
 from aspose_tex.presentation import DviDevice

 interp = TeXInterpreter()
 device = DviDevice()
 interp.run_with_device(StringInputSource(tex), device)
 cfg = interp._page_builder._config
 return {
 "vsize": cfg.vsize,
 "topskip_width": cfg.topskip.width,
 "max_depth": cfg.max_depth,
 }

 def test_vsize_register_update(self) -> None:
 cap = self._capture_config(r"\vsize=100pt Hello\bye")
 assert cap["vsize"] == 100 * 65536

 def test_topskip_register_update(self) -> None:
 cap = self._capture_config(r"\topskip=30pt Hello\bye")
 assert cap["topskip_width"] == 30 * 65536

 def test_maxdepth_register_update(self) -> None:
 cap = self._capture_config(r"\maxdepth=8pt Hello\bye")
 assert cap["max_depth"] == 8 * 65536


# ---------------------------------------------------------------------------
# \output is registered as a TOKS named parameter in M3 ( / AC-3)
# ---------------------------------------------------------------------------

class TestOutputCsRegistered:
 def test_output_assignment_parses_without_error(self) -> None:
 """``\\output={\\relax}`` parses (consumption is )."""
 # Should run cleanly — no "Undefined control sequence". The token list
 # is stored but not consumed by the page builder yet (that's ).
 _run(r"\output={\relax}\bye")


# ---------------------------------------------------------------------------
# DVI-regression — folio glyphs land in the DVI stream (AC-5)
# ---------------------------------------------------------------------------

class TestFolioInDvi:
 def test_folio_rendered_in_dvi(self) -> None:
 r"""Default \\pageno=1 → '1' appears in the DVI char stream."""
 dvi = _run("Hello\\bye")
 pages = _collect_chars_per_page(dvi)
 assert len(pages) == 1
 assert ord("1") in pages[0]

 def test_folio_not_duplicated(self) -> None:
 r"""Exactly one '1' glyph on a page whose body does not mention '1'."""
 dvi = _run("Hello\\bye")
 pages = _collect_chars_per_page(dvi)
 assert pages[0].count(ord("1")) == 1


# ---------------------------------------------------------------------------
# DVI-regression — \vfil / \vsize vertical distribution ( AC-3, AC-4)
# ---------------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).parent.parent / "testdata" / "fixtures" / "vsize_stretch"
_FIXTURE_TEX = _FIXTURE_DIR / "three_paragraph_vsize_stretch.tex"
_FIXTURE_MIKTEX_DVI = _FIXTURE_DIR / "three_paragraph_vsize_stretch.miktex.dvi"

_TOLERANCE_SP = 65_536 # 1 pt


def _read_paragraph_vs(dvi: bytes, n_paragraphs: int) -> list[int]:
 """Return v-positions of the first char of each of the first n paragraphs on page 1.

 The fixture's body is N short paragraphs (no line wrap), each on its own
 baseline. The folio sits below on a further baseline; we keep only the
 first n_paragraphs lines.
 """
 pages = _walk_line_starts(dvi)
 assert pages, "DVI has no pages"
 lines = pages[0]
 assert len(lines) >= n_paragraphs, f"page 1 has {len(lines)} lines; need {n_paragraphs}"
 return [v for v, _ in lines[:n_paragraphs]]


def _read_folio_v(dvi: bytes) -> int:
 """Return the v-position of the folio glyph on page 1 (the char after the last paragraph)."""
 pages = _walk_line_starts(dvi)
 assert pages, "DVI has no pages"
 lines = pages[0]
 assert len(lines) >= 4, f"page 1 needs 3 paragraphs + folio, got {len(lines)} lines"
 return lines[-1][0]


class TestVfilVsizeDistributesBody:
 def test_vfil_vsize_distributes_body(self) -> None:
 """ AC-3: paragraphs 1..3 land within 1pt of MiKTeX baseline."""
 tex_source = _FIXTURE_TEX.read_text(encoding="utf-8")
 ours_dvi = _run(tex_source)
 miktex_dvi = _FIXTURE_MIKTEX_DVI.read_bytes()

 ours_vs = _read_paragraph_vs(ours_dvi, 3)
 miktex_vs = _read_paragraph_vs(miktex_dvi, 3)

 for idx, (ours_v, ref_v) in enumerate(zip(ours_vs, miktex_vs, strict=True), start=1):
 delta = ours_v - ref_v
 assert abs(delta) <= _TOLERANCE_SP, (
 f"paragraph {idx}: ours v={ours_v / 65536:.3f} pt differs "
 f"from MiKTeX v={ref_v / 65536:.3f} pt by "
 f"{delta / 65536:+.3f} pt (tolerance: 1 pt)"
 )

 def test_vfil_vsize_regression_if_build_pagebody_skipped(
 self, monkeypatch: pytest.MonkeyPatch
 ) -> None:
 """ AC-4: bypassing set_glue_vbox breaks the page layout.

 Pins the architectural claim that the `\\vbox to\\vsize` wrap is
 load-bearing. With content placed from the top of the body vbox
 ( + correct DVI-writer vbox entry), paragraph-1 y stays at
 ``topskip`` regardless of the vbox's total height — so this regression
 guard checks the *folio* position, which shifts whenever the body box
 is not stretched to ``\\vsize``. Skipping set_glue_vbox leaves the
 body at natural height (~34 pt), and the folio drifts from
 ~324 pt to ~58 pt — far outside the 1-pt tolerance.
 """
 from aspose_tex._engine import page_builder as pb
 from aspose_tex._engine.box_builder import _measure_vlist
 from aspose_tex._engine.nodes import GlueSign as _GlueSign
 from aspose_tex._engine.nodes import VlistNode
 from aspose_tex._engine.registers import GlueOrder as _GlueOrder

 def _build_pagebody_no_stretch(self, body_nodes):
 w, h, d = _measure_vlist(body_nodes, self._font_manager)
 return VlistNode(
 list=body_nodes,
 width=w,
 height=h,
 depth=d,
 shift_amount=0,
 glue_sign=_GlueSign.NORMAL,
 glue_order=_GlueOrder.NORMAL,
 glue_set=0.0,
 )

 monkeypatch.setattr(
 pb.PlainOutputRoutine, "_build_pagebody", _build_pagebody_no_stretch
 )

 tex_source = _FIXTURE_TEX.read_text(encoding="utf-8")
 ours_dvi = _run(tex_source)
 miktex_dvi = _FIXTURE_MIKTEX_DVI.read_bytes()

 ours_folio_v = _read_folio_v(ours_dvi)
 miktex_folio_v = _read_folio_v(miktex_dvi)
 assert abs(ours_folio_v - miktex_folio_v) > _TOLERANCE_SP, (
 "expected folio y to drift > 1pt when set_glue_vbox is bypassed, "
 f"but ours v={ours_folio_v / 65536:.3f} pt vs MiKTeX "
 f"{miktex_folio_v / 65536:.3f} pt"
 )
