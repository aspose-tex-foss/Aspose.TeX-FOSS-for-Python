"""End-to-end integration tests for the TeX interpreter ( / / §5).

Covers acceptance criteria:
- AC#1: "Hello World\\bye" produces valid DVI with one page containing the chars
- AC#2: Blank line between paragraphs produces two separate line groups
- AC#3: \\vskip 12pt in vertical mode inserts GlueNode in the vlist
- AC#4: \\bye triggers document end and DviWriter.finalize() is called exactly once
- AC#5: DVI output passes structural validation (pre/bop/eop/post/post_post)
- AC#6: Multi-page document — \\par after page break lands on page 2

Plus supplementary §§5a-5f coverage: \\hbox in V-mode, \\par no-op in
V-mode, \\hrule, mode-aware \\kern, \\end as alternate terminator.

 / : ``\\eject`` is ``\\par\\penalty-10000`` with no implicit
``\\vfil``; the regression suite at the bottom of this file pins the contract.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from aspose_tex._engine.box_primitives import _PREVDEPTH_SENTINEL
from aspose_tex._engine.interpreter import ModeKind, TeXInterpreter
from aspose_tex._engine.nodes import (
 GlueNode,
 HlistNode,
 KernNode,
 RuleNode,
)
from aspose_tex._engine.registers import GlueOrder
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice
from tests._verification.dvi_walker import (
 collect_chars_per_page,
 walk_line_starts,
 walk_rules,
)

# ---------------------------------------------------------------------------
# DVI opcode constants (mirrored from dvi_writer for test assertions)
# ---------------------------------------------------------------------------

_SET_CHAR_MAX = 127
_SET1 = 128
_BOP = 139
_EOP = 140
_PRE = 247
_POST = 248
_POST_POST = 249
_DVI_ID = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(tex: str) -> bytes:
 """Run TeX source through a fresh interpreter and return DVI bytes."""
 return TeXInterpreter().run(StringInputSource(tex))


def _count_bops(dvi: bytes) -> int:
 """Count BOP opcodes (new page markers) in a DVI byte stream.

 We cannot simply scan for byte value 139 — it can appear inside multi-byte
 operand payloads. Instead, walk the stream structurally: the preamble is
 fixed-length, then each page starts with BOP (44 operand bytes) and ends
 with EOP. After all pages, POST begins. For multi-page counting we rely
 on the ``_page_count`` field written in the postamble.
 """
 # Locate POST opcode: scan from end for 249 (POST_POST), then read the
 # post offset from its i4 operand.
 # Simpler: read the page_count field from POST opcode payload.
 pp_idx = dvi.rfind(bytes([_POST_POST]))
 assert pp_idx > 0, "POST_POST opcode missing"
 post_offset = struct.unpack(">i", dvi[pp_idx + 1 : pp_idx + 5])[0]
 assert dvi[post_offset] == _POST, "POST opcode not at post_offset"
 # POST layout: op(1) + last_bop(4) + num(4) + den(4) + mag(4) +
 # max_height(4) + max_width(4) + max_stack(2) + page_count(2)
 page_count_offset = post_offset + 1 + 4 + 4 + 4 + 4 + 4 + 4 + 2
 (page_count,) = struct.unpack(">H", dvi[page_count_offset : page_count_offset + 2])
 return page_count


def _extract_char_codes(dvi: bytes) -> list[int]:
 """Extract character codes emitted by set_char_i / set1 opcodes.

 Walks the DVI stream opcode-by-opcode starting just after the PRE
 preamble, collecting char codes from set_char_0..127 (opcodes 0-127)
 and set1 (opcode 128, 1-byte operand). Stops at POST (248).
 """
 chars: list[int] = []
 i = _skip_preamble(dvi)
 n = len(dvi)
 while i < n:
 op = dvi[i]
 if op == _POST:
 break
 if op <= _SET_CHAR_MAX:
 chars.append(op)
 i += 1
 continue
 if op == _SET1:
 chars.append(dvi[i + 1])
 i += 2
 continue
 # Variable-length fnt_def1..4 (243..246): skip over payload
 if 243 <= op <= 246:
 fn_bytes = op - 242 # 1..4
 base = i + 1 + fn_bytes + 4 + 4 + 4 # + checksum/scaled/design
 area_len = dvi[base]
 name_len = dvi[base + 1]
 i = base + 2 + area_len + name_len
 continue
 # xxx1..xxx4 (239..242): skip 1-byte length + payload
 if 239 <= op <= 242:
 kbytes = op - 238 # 1..4
 length = int.from_bytes(dvi[i + 1 : i + 1 + kbytes], "big")
 i += 1 + kbytes + length
 continue
 size = _DVI_OP_OPERAND_SIZE.get(op)
 if size is None:
 break
 i += 1 + size
 return chars


# Operand sizes for all DVI opcodes that may appear in our generated output.
# Values are total operand bytes after the 1-byte opcode.
_DVI_OP_OPERAND_SIZE: dict[int, int] = {
 # set_rule
 132: 8,
 # put_rule
 137: 8,
 # nop
 138: 0,
 # bop: 10 * i4 + prev_bop i4 = 44
 _BOP: 44,
 # eop
 _EOP: 0,
 # push/pop
 141: 0,
 142: 0,
 # right1..right4
 143: 1, 144: 2, 145: 3, 146: 4,
 # w0, w1..w4
 147: 0, 148: 1, 149: 2, 150: 3, 151: 4,
 # x0, x1..x4
 152: 0, 153: 1, 154: 2, 155: 3, 156: 4,
 # down1..down4
 157: 1, 158: 2, 159: 3, 160: 4,
 # y0, y1..y4
 161: 0, 162: 1, 163: 2, 164: 3, 165: 4,
 # z0, z1..z4
 166: 0, 167: 1, 168: 2, 169: 3, 170: 4,
 # fnt1..fnt4
 235: 1, 236: 2, 237: 3, 238: 4,
 # xxx1..xxx4 (variable — not emitted by our backend, no size)
 # fnt_def1..fnt_def4 (variable — handled below)
 # pre, post, post_post — scanned implicitly via stream layout
}
# fnt_num_0..fnt_num_63 are opcodes 171..234, all zero-operand.
for _op in range(171, 235):
 _DVI_OP_OPERAND_SIZE[_op] = 0


def _skip_preamble(dvi: bytes) -> int:
 """Return the byte offset of the first opcode after the DVI preamble.

 PRE layout: op(1) + id(1) + num(4) + den(4) + mag(4) + k(1) + comment(k)
 """
 assert dvi[0] == _PRE
 assert dvi[1] == _DVI_ID
 k = dvi[14]
 return 15 + k


def _scan_pages_start(dvi: bytes) -> int:
 """Return offset where the first page (or POST) begins."""
 # After preamble we may have fnt_def opcodes emitted eagerly? No — fnt_def
 # is emitted on first shipout. First opcode is BOP or POST (empty doc).
 return _skip_preamble(dvi)


# ---------------------------------------------------------------------------
# AC#1: Hello World → valid DVI with one page containing the chars
# ---------------------------------------------------------------------------

class TestAcceptanceHelloWorld:
 """ AC#1: StringInputSource('Hello World\\bye') → valid DVI, 1 page."""

 def test_hello_world_produces_valid_dvi(self) -> None:
 dvi = _run("Hello World\\bye")
 assert dvi[0] == _PRE
 assert dvi[1] == _DVI_ID
 assert dvi[-1] == 223 # padding tail

 def test_hello_world_one_page(self) -> None:
 dvi = _run("Hello World\\bye")
 assert _count_bops(dvi) == 1

 def test_hello_world_contains_all_chars(self) -> None:
 """All characters of 'Hello World' are emitted (ligatures/kerns aside).

 adds the plain-TeX footline; the folio glyph '1' follows the
 body chars on page 1.
 """
 dvi = _run("Hello World\\bye")
 chars = _extract_char_codes(dvi)
 # The space between words becomes a right movement, not a char.
 expected = [ord(c) for c in "HelloWorld"] + [ord("1")]
 assert chars == expected

 def test_hello_world_newline_before_bye(self) -> None:
 """AC#1 exact input: literal newline before \\bye still works."""
 dvi = _run("Hello World\n\\bye")
 assert _count_bops(dvi) == 1
 chars = _extract_char_codes(dvi)
 # "Hello World" followed by line-end → trailing space glue; no extra chars.
 # : folio glyph '1' trails the body on page 1.
 assert [ord(c) for c in "HelloWorld"] + [ord("1")] == chars


# ---------------------------------------------------------------------------
# AC#2: Blank line between paragraphs produces two separate line groups
# ---------------------------------------------------------------------------

class TestAcceptanceTwoParagraphs:
 """ AC#2: two paragraphs via \\par or blank line → two line groups."""

 def test_explicit_par_produces_two_paragraph_groups(self) -> None:
 """Capture the hlists contributed to the page builder and assert we see
 two distinct paragraph boundaries."""
 captured: list[tuple[str, object]] = []

 class _Spy(TeXInterpreter):
 def _end_paragraph(self) -> None: # type: ignore[override]
 captured.append(("end_par", None))
 super()._end_paragraph()

 _Spy().run(StringInputSource("Foo\\par Bar\\bye"))
 # Two paragraphs ended (one per \par), not counting the \bye-forced par.
 assert captured.count(("end_par", None)) == 2

 def test_blank_line_between_paragraphs(self) -> None:
 """A blank line in TeX produces a \\par token via the tokenizer."""
 captured_ends = 0

 class _Spy(TeXInterpreter):
 def _end_paragraph(self) -> None: # type: ignore[override]
 nonlocal captured_ends
 captured_ends += 1
 super()._end_paragraph()

 _Spy().run(StringInputSource("Foo\n\nBar\\bye"))
 # One end for the blank-line \par, one for \bye-forced termination.
 assert captured_ends == 2

 def test_two_paragraphs_single_page(self) -> None:
 dvi = _run("Foo\\par Bar\\bye")
 assert _count_bops(dvi) == 1


# ---------------------------------------------------------------------------
# AC#3: \vskip 12pt in vertical mode inserts GlueNode in vlist
# ---------------------------------------------------------------------------

class TestAcceptanceVskip:
 """ AC#3: \\vskip <dimen> contributes a GlueNode to the page vlist."""

 def test_vskip_contributes_gluenode_to_page_builder(self) -> None:
 """\\vskip in V-mode produces a GlueNode with the correct width."""
 captured: list[GlueNode] = []

 class _CapturingVskipInterp(TeXInterpreter):
 def _exec_vskip(self) -> None: # type: ignore[override]
 from aspose_tex._engine.dimparser import parse_glue
 glue = parse_glue(self._expander)
 node = GlueNode(glue=glue)
 captured.append(node)
 self._page_builder.contribute(node)

 _CapturingVskipInterp().run(StringInputSource(r"\vskip 12pt Hello\bye"))
 assert len(captured) == 1
 assert isinstance(captured[0], GlueNode)
 # 12 pt = 12 * 65536 sp = 786432 sp
 assert captured[0].glue.width == 786_432

 def test_vskip_flows_through_to_shipout(self) -> None:
 """End-to-end: \\vskip before text produces valid DVI."""
 dvi = _run(r"\vskip 12pt Hello\bye")
 assert _count_bops(dvi) == 1
 assert dvi[0] == _PRE

 def test_vskip_does_not_switch_to_horizontal(self) -> None:
 """\\vskip in outer-vertical mode stays in vertical mode."""
 observed_modes: list[ModeKind] = []

 class _Spy(TeXInterpreter):
 def _exec_vskip(self) -> None: # type: ignore[override]
 observed_modes.append(self._mode_stack.current)
 super()._exec_vskip()

 _Spy().run(StringInputSource(r"\vskip 12pt \bye"))
 assert observed_modes == [ModeKind.OUTER_VERTICAL]


# ---------------------------------------------------------------------------
# AC#4: \bye triggers document end and finalize() is called exactly once
# ---------------------------------------------------------------------------

class TestAcceptanceBye:
 """ AC#4: \\bye finalises the document exactly once."""

 def test_bye_calls_finalize_once(self) -> None:
 from aspose_tex._output.dvi_writer import DviWriter

 orig_finalize = DviWriter.finalize
 call_count = 0

 def _counting_finalize(self) -> None: # type: ignore[no-untyped-def]
 nonlocal call_count
 call_count += 1
 orig_finalize(self)

 DviWriter.finalize = _counting_finalize # type: ignore[method-assign]
 try:
 TeXInterpreter().run(StringInputSource("Hello\\bye"))
 finally:
 DviWriter.finalize = orig_finalize # type: ignore[method-assign]
 assert call_count == 1

 def test_bye_sets_done_flag(self) -> None:
 """After \\bye the main loop exits and post-\\bye tokens are ignored."""
 # Put garbage after \bye — if \bye sets done and exits the loop,
 # the undefined CS token should never be dispatched.
 dvi = _run(r"Hello\bye\undefined")
 assert _count_bops(dvi) == 1

 def test_end_is_alternate_terminator(self) -> None:
 """\\end also terminates processing (§5f)."""
 dvi = _run(r"Hello\end")
 assert dvi[0] == _PRE
 assert dvi[-1] == 223


# ---------------------------------------------------------------------------
# AC#5: DVI output passes structural validation
# ---------------------------------------------------------------------------

class TestAcceptanceDviStructure:
 """ AC#5: DVI output passes structural validation."""

 def test_preamble_signature(self) -> None:
 dvi = _run("Hello\\bye")
 assert dvi[0] == _PRE
 assert dvi[1] == _DVI_ID

 def test_post_post_signature(self) -> None:
 dvi = _run("Hello\\bye")
 # Find POST_POST (walking from end past padding)
 i = len(dvi) - 1
 while i >= 0 and dvi[i] == 223:
 i -= 1
 # i points at DVI_ID byte, before that is a 4-byte post offset, before that POST_POST
 assert dvi[i] == _DVI_ID
 assert dvi[i - 5] == _POST_POST

 def test_postamble_has_post_opcode(self) -> None:
 dvi = _run("Hello\\bye")
 # POST offset is encoded in POST_POST operand
 pp_idx = dvi.rfind(bytes([_POST_POST]))
 post_offset = struct.unpack(">i", dvi[pp_idx + 1 : pp_idx + 5])[0]
 assert dvi[post_offset] == _POST

 def test_page_count_consistent_with_bops(self) -> None:
 """POST.page_count must match the number of BOP opcodes."""
 dvi = _run("Hello\\bye")
 pp_idx = dvi.rfind(bytes([_POST_POST]))
 post_offset = struct.unpack(">i", dvi[pp_idx + 1 : pp_idx + 5])[0]
 page_count_offset = post_offset + 1 + 4 + 4 + 4 + 4 + 4 + 4 + 2
 (page_count,) = struct.unpack(">H", dvi[page_count_offset : page_count_offset + 2])
 assert page_count == 1

 def test_empty_document_has_no_pages(self) -> None:
 dvi = _run("")
 assert _count_bops(dvi) == 0

 def test_padding_multiple_of_four(self) -> None:
 dvi = _run("Hello\\bye")
 assert len(dvi) % 4 == 0
 # Trailing bytes are 223
 assert dvi[-1] == 223


# ---------------------------------------------------------------------------
# AC#6: Multi-page document
# ---------------------------------------------------------------------------

class TestAcceptanceMultiPage:
 """ AC#6: long document produces 2+ pages."""

 def test_many_paragraphs_produce_multiple_pages(self) -> None:
 # Each paragraph is short (1 line). baselineskip ≈ 12pt, parskip ≈ 0pt plus 1pt.
 # vsize = 8.9in = 640.8 pt. One line pair ≈ 12pt. ~53 lines/page.
 # 200 paragraphs → at least 3 pages.
 body = "Foo\\par " * 200
 dvi = _run(body + "\\bye")
 assert _count_bops(dvi) >= 2

 def test_multi_page_finalizes_once(self) -> None:
 from aspose_tex._output.dvi_writer import DviWriter

 orig_finalize = DviWriter.finalize
 call_count = 0

 def _counting_finalize(self) -> None: # type: ignore[no-untyped-def]
 nonlocal call_count
 call_count += 1
 orig_finalize(self)

 DviWriter.finalize = _counting_finalize # type: ignore[method-assign]
 try:
 TeXInterpreter().run(StringInputSource(("Foo\\par " * 200) + "\\bye"))
 finally:
 DviWriter.finalize = orig_finalize # type: ignore[method-assign]
 assert call_count == 1


# ---------------------------------------------------------------------------
# Supplementary §§5a-5f coverage
# ---------------------------------------------------------------------------

class TestModeTransitions:
 """§5: mode-stack behaviour around paragraph lifecycle."""

 def test_letter_in_outer_vertical_switches_to_horizontal(self) -> None:
 observed: list[ModeKind] = []

 class _Spy(TeXInterpreter):
 def _handle_char(self, token) -> None: # type: ignore[override]
 observed.append(self._mode_stack.current)
 super()._handle_char(token)

 _Spy().run(StringInputSource("A\\bye"))
 assert observed == [ModeKind.HORIZONTAL]

 def test_par_in_vertical_mode_is_noop(self) -> None:
 """\\par in V-mode does not push/pop modes."""
 depths: list[int] = []

 class _Spy(TeXInterpreter):
 def _exec_par_cmd(self) -> None: # type: ignore[override]
 depths.append(len(self._mode_stack._stack)) # type: ignore[attr-defined]
 super()._exec_par_cmd()

 _Spy().run(StringInputSource(r"\par\bye"))
 # \par seen once, in OUTER_VERTICAL → depth 1, no change.
 assert depths == [1]

 def test_horizontal_to_vertical_after_par(self) -> None:
 """After \\par the interpreter returns to OUTER_VERTICAL."""
 observed: list[ModeKind] = []

 class _Spy(TeXInterpreter):
 def _end_paragraph(self) -> None: # type: ignore[override]
 super()._end_paragraph()
 observed.append(self._mode_stack.current)

 _Spy().run(StringInputSource(r"Foo\par\bye"))
 assert observed == [ModeKind.OUTER_VERTICAL]


class TestHboxInVmode:
 """§5e: \\hbox in vertical mode contributes an HlistNode."""

 def test_hbox_in_vmode_contributes_hlist(self) -> None:
 contributed: list = []

 class _Spy(TeXInterpreter):
 def _add_box_to_current_list(self, box) -> None: # type: ignore[override]
 contributed.append(box)
 super()._add_box_to_current_list(box)

 _Spy().run(StringInputSource(r"\hbox{Hi}\bye"))
 assert len(contributed) == 1
 assert isinstance(contributed[0], HlistNode)


class TestKernModeAware:
 """§5d: \\kern is mode-aware."""

 def test_kern_in_vmode_goes_to_page_builder(self) -> None:
 captured: list[tuple[ModeKind, KernNode]] = []

 class _Spy(TeXInterpreter):
 def _exec_kern_cmd(self) -> None: # type: ignore[override]
 mode_before = self._mode_stack.current
 from aspose_tex._engine.dimparser import parse_dimen
 amount = parse_dimen(self._expander)
 node = KernNode(width=amount, explicit=True)
 captured.append((mode_before, node))
 if mode_before in (ModeKind.HORIZONTAL, ModeKind.RESTRICTED_HORIZONTAL):
 self._par_list.append(node) # type: ignore[union-attr]
 else:
 self._page_builder.contribute(node)

 _Spy().run(StringInputSource(r"\kern 3pt \bye"))
 assert len(captured) == 1
 mode, node = captured[0]
 assert mode == ModeKind.OUTER_VERTICAL
 assert node.width == 3 * 65_536 # 3 pt in sp


class TestHrule:
 """§5d: \\hrule contributes a RuleNode."""

 def test_hrule_in_vmode(self) -> None:
 contributed: list = []

 class _Spy(TeXInterpreter):
 def _exec_hrule(self) -> None: # type: ignore[override]
 # Call base and then peek at the last page_builder contribution
 # by wrapping contribute temporarily.
 orig = self._page_builder.contribute

 def _wrap(node): # type: ignore[no-untyped-def]
 contributed.append(node)
 return orig(node)

 self._page_builder.contribute = _wrap # type: ignore[method-assign]
 try:
 super()._exec_hrule()
 finally:
 self._page_builder.contribute = orig # type: ignore[method-assign]

 _Spy().run(StringInputSource(r"\hrule\bye"))
 rules = [n for n in contributed if isinstance(n, RuleNode)]
 assert len(rules) == 1
 # default height 0.4pt = 26214 sp; width runs
 assert rules[0].height == 26_214


# ---------------------------------------------------------------------------
# Sanity: DVI structure on representative outputs
# ---------------------------------------------------------------------------

class TestDviSanity:
 """Cross-cutting DVI structural sanity checks."""

 def test_empty_input_dvi_is_well_formed(self) -> None:
 dvi = _run("")
 assert dvi[0] == _PRE
 assert dvi[1] == _DVI_ID
 pp_idx = dvi.rfind(bytes([_POST_POST]))
 assert pp_idx > 0
 post_offset = struct.unpack(">i", dvi[pp_idx + 1 : pp_idx + 5])[0]
 assert dvi[post_offset] == _POST

 def test_hello_bye_contains_single_page_cycle(self) -> None:
 """BOP and EOP both appear before POST."""
 dvi = _run("A\\bye")
 pp_idx = dvi.rfind(bytes([_POST_POST]))
 post_offset = struct.unpack(">i", dvi[pp_idx + 1 : pp_idx + 5])[0]
 # POST.last_bop_offset operand points at the final BOP
 last_bop_offset = struct.unpack(">i", dvi[post_offset + 1 : post_offset + 5])[0]
 assert dvi[last_bop_offset] == _BOP
 eop_idx = dvi.rfind(bytes([_EOP]), 0, post_offset)
 assert eop_idx > last_bop_offset


# ---------------------------------------------------------------------------
# / : \eject is \par\penalty-10000 (no implicit \vfil)
# ---------------------------------------------------------------------------

_TEX46_FIXTURE_DIR = Path(__file__).parent.parent / "testdata" / "fixtures" / "eject"
_TEX46_FIXTURE_TEX = _TEX46_FIXTURE_DIR / "three_paragraph_eject.tex"
_TEX46_MIKTEX_DVI = _TEX46_FIXTURE_DIR / "three_paragraph_eject.miktex.dvi"

_ONE_POINT_SP = 65_536 # 1 pt tolerance for DVI y-coordinate parity


class TestEjectSemantics:
 """ contract: ``\\eject`` ≡ ``\\par\\penalty-10000``, no ``\\vfil``."""

 def test_eject_does_not_inject_vfil(self, monkeypatch) -> None:
 """No FIL/FILL/FILLL stretch reaches the body box on \\eject pages.

 The architect's RCA: the bug was a spurious ``make_vfil_glue()`` in
 ``exec_eject``. After , the only stretch the page builder
 contributes is from explicit author glue (none here) and from the
 plain-TeX parskip glue (NORMAL order). This test pins the contract
 by snooping the body_nodes that ``PlainOutputRoutine._build_pagebody``
 receives on each shipout.
 """
 from aspose_tex._engine import page_builder as pb

 captured: list[list[object]] = []
 original = pb.PlainOutputRoutine._build_pagebody

 def spy(self, body_nodes): # type: ignore[no-untyped-def]
 captured.append(list(body_nodes))
 return original(self, body_nodes)

 monkeypatch.setattr(pb.PlainOutputRoutine, "_build_pagebody", spy)

 _run("Hello\\eject World\\bye")

 assert len(captured) >= 1, "page 1 body never reached _build_pagebody"
 # Only page 1 is \eject-terminated; page 2 is \bye-terminated and
 # legitimately carries a \vfill from _exec_bye.
 page1_body = captured[0]
 for node in page1_body:
 if isinstance(node, GlueNode):
 assert node.glue.stretch_order == GlueOrder.NORMAL, (
 f"page 1 body has higher-order stretch "
 f"({node.glue.stretch_order.name}) — \\eject must "
 f"not inject \\vfil per ; node={node!r}"
 )

 def test_eject_in_horizontal_mode_calls_par_first(self) -> None:
 """``text\\eject more\\bye`` ships "text" on page 1 and "more" on page 2.

 The implicit ``\\par`` half of ``\\def\\eject{\\par\\break}`` finalises
 the open paragraph before the page break is enqueued; otherwise the
 ``-10000`` penalty would be appended *inside* the running paragraph
 list and the break would be dropped.
 """
 dvi = _run("text\\eject more\\bye")
 pages = collect_chars_per_page(dvi)
 assert len(pages) == 2, f"expected 2 pages, got {len(pages)}: {pages!r}"

 # Page 1: "text" body + folio "1" (plain-TeX footline).
 body1 = [c for c in pages[0] if c != ord("1")]
 assert body1 == [ord(c) for c in "text"], (
 f"page 1 body chars {body1!r} != expected 'text' codes"
 )
 assert ord("1") in pages[0], "page 1 missing folio glyph '1'"

 # Page 2: "more" body + folio "2".
 body2 = [c for c in pages[1] if c != ord("2")]
 assert body2 == [ord(c) for c in "more"], (
 f"page 2 body chars {body2!r} != expected 'more' codes"
 )
 assert ord("2") in pages[1], "page 2 missing folio glyph '2'"

 def test_eject_distributes_paragraphs(self) -> None:
 """Three short paragraphs on an \\eject-terminated page distribute
 across ``\\vsize`` within ±1 pt of the MiKTeX baseline.

 Canonical regression for AC-3 / AC-5. The fixture sets
 ``\\vsize=300pt``; without the body would collapse to its
 natural 6-line height and paragraphs 2-3 would land tens of points
 too high (clustered at top). With the only stretch in the
 body is NORMAL parskip glue, so ``set_glue_vbox`` distributes the
 ``\\vsize - nat_h`` deficit across the parskips just as MiKTeX does
 (with a finite, high glue-set ratio of ~133x).
 """
 tex_source = _TEX46_FIXTURE_TEX.read_text(encoding="utf-8")
 ours_dvi = _run(tex_source)
 miktex_dvi = _TEX46_MIKTEX_DVI.read_bytes()

 ours_lines = walk_line_starts(ours_dvi)
 miktex_lines = walk_line_starts(miktex_dvi)
 assert len(ours_lines) >= 1 and len(miktex_lines) >= 1

 # Page 1 lines 1..3 are the three paragraphs (line 4 is the folio).
 ours_p1 = ours_lines[0]
 miktex_p1 = miktex_lines[0]
 assert len(ours_p1) >= 3, f"page 1 has {len(ours_p1)} lines; need 3 paragraphs"
 assert len(miktex_p1) >= 3, "MiKTeX baseline page 1 missing paragraphs"

 for idx in range(3):
 ours_v = ours_p1[idx][0]
 ref_v = miktex_p1[idx][0]
 delta = ours_v - ref_v
 assert abs(delta) <= _ONE_POINT_SP, (
 f"paragraph {idx + 1}: ours v={ours_v / 65536:.3f} pt "
 f"differs from MiKTeX v={ref_v / 65536:.3f} pt by "
 f"{delta / 65536:+.3f} pt (tolerance: 1 pt)"
 )


# ---------------------------------------------------------------------------
# / v4: rule-first baseline contract on rule_then_para.tex
# ---------------------------------------------------------------------------

_TEX54_FIXTURE_DIR = Path(__file__).parent.parent / "testdata" / "fixtures" / "rule_then_para"
_TEX54_FIXTURE_TEX = _TEX54_FIXTURE_DIR / "rule_then_para.tex"
_TEX54_MIKTEX_DVI = _TEX54_FIXTURE_DIR / "rule_then_para.miktex.dvi"

_HALF_POINT_SP = 32_768 # ±0.5 pt tolerance for v4 AC-8 / AC-9


def _rule_then_para_baselines(dvi: bytes) -> dict[str, int]:
 """Return ``{rule, para1, para2, folio}`` page-1 baseline v-coords (sp).

 The fixture ships exactly four baselines on page 1 (rule + 2 paragraphs +
 folio). Rule baseline comes from ``walk_rules`` (the single
 ``putrule``); the three text baselines from ``walk_line_starts``.
 """
 rules = walk_rules(dvi)
 lines = walk_line_starts(dvi)
 assert rules and rules[0], "no rule found on page 1"
 assert lines and len(lines[0]) >= 3, "expected >=3 line starts on page 1"
 return {
 "rule": rules[0][0][1],
 "para1": lines[0][0][0],
 "para2": lines[0][1][0],
 "folio": lines[0][2][0],
 }


class TestRuleThenParaBaseline:
 """ v4 AC-8 / AC-9: rule-first baseline contract.

 The fixture ``testdata/fixtures/rule_then_para/rule_then_para.tex`` is a minimal
 `\\hrule`-then-two-paragraphs document at `\\vsize=120pt`. Per 
 v4 Measurement B, MiKTeX places the rule at ``v = \\topskip.width =
 655_360 sp``, with subsequent paragraph + folio baselines at fixed
 `v` values. Under Revision 4, our cascade hits rule + para-2 + folio
 byte-for-byte; para-1 stays off by ~+2.528 pt (the joint defect
 routed to ).
 """

 def test_rule_then_para_baseline_matches_miktex(self) -> None:
 """Rule + para-2 + folio baselines within ±0.5 pt of MiKTeX ( v4 AC-8)."""
 tex_source = _TEX54_FIXTURE_TEX.read_text(encoding="utf-8")
 ours_dvi = _run(tex_source)
 miktex_dvi = _TEX54_MIKTEX_DVI.read_bytes()

 ours = _rule_then_para_baselines(ours_dvi)
 miktex = _rule_then_para_baselines(miktex_dvi)

 for label in ("rule", "para2", "folio"):
 delta = ours[label] - miktex[label]
 assert abs(delta) <= _HALF_POINT_SP, (
 f"{label} baseline: ours v={ours[label]} sp "
 f"({ours[label] / 65536:.3f} pt) differs from MiKTeX "
 f"v={miktex[label]} sp ({miktex[label] / 65536:.3f} pt) "
 f"by {delta / 65536:+.3f} pt (tolerance: ±0.5 pt)"
 )

 def test_rule_then_para_para1_baseline_pending_tex110(self) -> None:
 """Para-1 baseline within ±0.5 pt vs MiKTeX 4_094_180 sp ( v5 AC-9).

 Previously xfailed (strict=True) under Revision 4 with diff ≈+2.528 pt.
 v5 Component 6 closes the joint residual via the
 §679 sentinel `_prev_depth` write + §253 sentinel guard in the
 interline-glue prelude — the spurious 5.056 pt glue between the rule
 and the post-rule paragraph is suppressed. The xfail decorator
 has been removed: this test must now pass green per AC-5 of .
 """
 tex_source = _TEX54_FIXTURE_TEX.read_text(encoding="utf-8")
 ours_dvi = _run(tex_source)
 miktex_dvi = _TEX54_MIKTEX_DVI.read_bytes()

 ours = _rule_then_para_baselines(ours_dvi)
 miktex = _rule_then_para_baselines(miktex_dvi)

 delta = ours["para1"] - miktex["para1"]
 assert abs(delta) <= _HALF_POINT_SP, (
 f"para-1 baseline: ours v={ours['para1']} sp differs from "
 f"MiKTeX v={miktex['para1']} sp by {delta / 65536:+.3f} pt"
 )


# ---------------------------------------------------------------------------
# / v5 Component 6 — three split-probe fixtures from 
# ---------------------------------------------------------------------------

_TEX110_FIXTURE_DIR = Path(__file__).parent.parent / "testdata" / "fixtures" / "rule_split_probes"
_TEX110_PROBES = (
 "probe_rule_first_then_para",
 "probe_rule_midpage_then_para",
 "probe_two_rules_then_para",
)
_HUNDRED_SP = 100 # Tolerance for the probe baseline comparisons ( AC-4).


@pytest.mark.parametrize("probe_name", _TEX110_PROBES)
def test_tex110_probe_baseline_matches_miktex(probe_name: str) -> None:
 """ v5 Component 6 / AC-4: probe baselines ≤100 sp vs MiKTeX.

 Three split-probe fixtures committed by the architect spike under
 ``testdata/fixtures/rule_split_probes/`` isolate the rule-first arm, the mid-page
 rule arm, and consecutive mid-page rules. Each pairs a ``.tex`` source
 with a MiKTeX-pdfTeX 4.19 ``.miktex.dvi`` baseline. Under v5
 Component 6 (sentinel ``_prev_depth`` + sentinel guard), every visible
 line-baseline v-coordinate on every MiKTeX page must match the
 corresponding ours-page v-coordinate within 100 sp (= 0.00153 pt, three
 orders below 's ±0.5 pt tolerance). Our engine may ship one
 additional trailing folio-only page on ``\\eject\\bye`` (a known
 engine-vs-MiKTeX divergence orthogonal to v5); that trailing
 page is not part of the body baseline contract and is ignored here.

 Args:
 probe_name: Bare basename of the probe fixture (no extension).
 """
 tex_path = _TEX110_FIXTURE_DIR / f"{probe_name}.tex"
 miktex_path = _TEX110_FIXTURE_DIR / f"{probe_name}.miktex.dvi"
 tex_source = tex_path.read_text(encoding="utf-8")
 ours_dvi = _run(tex_source)
 miktex_dvi = miktex_path.read_bytes()

 ours_pages = walk_line_starts(ours_dvi)
 miktex_pages = walk_line_starts(miktex_dvi)

 assert len(ours_pages) >= len(miktex_pages), (
 f"{probe_name}: ours produced fewer pages ({len(ours_pages)}) "
 f"than MiKTeX ({len(miktex_pages)})"
 )
 for page_idx, miktex_lines in enumerate(miktex_pages):
 ours_lines = ours_pages[page_idx]
 assert len(ours_lines) == len(miktex_lines), (
 f"{probe_name}: page {page_idx} line-start count differs — "
 f"ours={len(ours_lines)} vs MiKTeX={len(miktex_lines)}"
 )
 for line_idx, ((ours_v, _ours_h), (miktex_v, _miktex_h)) in enumerate(
 zip(ours_lines, miktex_lines, strict=True)
 ):
 delta = ours_v - miktex_v
 assert abs(delta) <= _HUNDRED_SP, (
 f"{probe_name}: page {page_idx} line {line_idx} baseline "
 f"ours v={ours_v} sp ({ours_v / 65536:.3f} pt) differs from "
 f"MiKTeX v={miktex_v} sp ({miktex_v / 65536:.3f} pt) by "
 f"{delta / 65536:+.3f} pt (tolerance: 100 sp / 0.00153 pt)"
 )


# ---------------------------------------------------------------------------
# v6 §Component 2 / AC-11 + AC-12 — cross-module
# `_prev_depth` sentinel convergence after vertical-mode `\hrule`.
# ---------------------------------------------------------------------------


def test_interp_prev_depth_sentinel_after_vmode_hrule() -> None:
 """ v6 §Component 2 / AC-11: interpreter mirror sentinel.

 After a vertical-mode ``\\hrule`` contribution, both ``_prev_depth``
 shadows (``interp._prev_depth`` — the named-parameter registry source
 for ``\\prevdepth`` reads at ``interpreter.py:1094`` — and
 ``interp._page_builder._prev_depth`` — the page builder's own copy
 consulted by ``_insert_interline_or_topskip``) must equal the TeXbook
 §253 ``ignore_depth`` sentinel (``-1000 pt`` = ``_PREVDEPTH_SENTINEL``).
 The integrator's reproducer (1002 pt shadow drift after
 ``\\hrule height1pt depth2pt``) was the regression this AC pins.
 """
 interp = TeXInterpreter()
 interp.run_with_device(
 StringInputSource(r"\hrule height1pt depth2pt \par\end"),
 DviDevice(),
 )
 assert interp._prev_depth == _PREVDEPTH_SENTINEL, (
 f"interp._prev_depth = {interp._prev_depth} sp "
 f"({interp._prev_depth / 65536:+.3f} pt); expected sentinel "
 f"{_PREVDEPTH_SENTINEL} sp (= -1000 pt)"
 )
 assert interp._page_builder._prev_depth == _PREVDEPTH_SENTINEL, (
 f"interp._page_builder._prev_depth = {interp._page_builder._prev_depth} sp "
 f"({interp._page_builder._prev_depth / 65536:+.3f} pt); expected sentinel "
 f"{_PREVDEPTH_SENTINEL} sp (= -1000 pt)"
 )


# ---------------------------------------------------------------------------
# / — \hsize wiring to the line-breaker and the page box
# ---------------------------------------------------------------------------

# A paragraph long enough to wrap at narrow \hsize but fit in two lines at the
# 6.5in default — the body used by the line-break-selection tests below.
_HSIZE_PARA = (
 r"\noindent The quick brown fox jumps over the lazy dog. "
 r"The quick brown fox jumps over the lazy dog. Pack my box with "
 r"five dozen liquor jugs.\par"
)


def _line_counts(dvi: bytes) -> list[int]:
 """Return the number of typeset lines on each DVI page."""
 return [len(page) for page in walk_line_starts(dvi)]


class TestHsizeWiring:
 r""" / : ``\hsize`` reaches break selection and the page box.

 Before the fix the line-breaker and the page box used a stale ``_HSIZE``
 constant set once at construction, so paragraphs broke at 6.5in at every
 width and a full-``\hsize`` ``\hrule`` painted the leaked default width.
 These tests pin the live-read (line-breaker) + ``config.hsize`` mirror
 (page box) contract.
 """

 def test_hsize_assignment_reaches_line_breaker(self) -> None:
 r"""A narrower ``\hsize`` yields strictly more lines than the default.

 Confirms ``\hsize`` reaches the break-point evaluator: at 3in the body
 wraps to more lines than at the 6.5in default (it broke identically at
 both widths before the fix).
 """
 wide = _line_counts(_run(r"\hsize=6.5in " + _HSIZE_PARA + r"\bye"))
 narrow = _line_counts(_run(r"\hsize=3in " + _HSIZE_PARA + r"\bye"))
 assert sum(narrow) > sum(wide), (
 f"narrow \\hsize must wrap to more lines: 3in={narrow} "
 f"not > 6.5in={wide}"
 )

 def test_hsize_grouped_restore(self) -> None:
 r"""``\hsize`` is group-aware: a ``{\hsize=… \par}`` group restores.

 The paragraph inside ``{\hsize=2in …}`` breaks narrow; the identical
 paragraph after the group breaks at the restored default. Because the
 live register read (not a cached mirror) drives break selection, the
 post-group paragraph must use fewer lines than the in-group one.
 """
 # Two paragraphs: first inside {\hsize=2in …}, second after the group.
 grouped = sum(_line_counts(_run(
 r"{\hsize=2in " + _HSIZE_PARA + r"}" + _HSIZE_PARA + r"\bye"
 )))
 # Reference totals: both paragraphs narrow (2in) vs both at the default.
 both_narrow = 2 * sum(_line_counts(_run(r"\hsize=2in " + _HSIZE_PARA + r"\bye")))
 both_default = 2 * sum(_line_counts(_run(_HSIZE_PARA + r"\bye")))
 assert both_narrow > both_default, (
 "precondition: 2in must wrap to more lines than the default"
 )
 # If \hsize leaked out of the group, the second paragraph would also
 # break at 2in and the total would reach `both_narrow`. If the restore
 # works, only the first paragraph is narrow, so the total sits strictly
 # between the all-default and all-narrow extremes.
 assert both_default < grouped < both_narrow, (
 f"grouped \\hsize did not restore: total={grouped} not in "
 f"({both_default}, {both_narrow})"
 )

 def test_page_box_rule_width_tracks_hsize(self) -> None:
 r"""A full-``\hsize`` ``\hrule`` paints the document width, not 6.5in.

 With ``\hsize=3in`` the resolved rule width is ~3in (14208860 sp)
 within sp-rounding slack — not the leaked default 6.5in (30785886 sp).
 """
 dvi = _run(r"\hsize=3in \hrule \noindent Hi.\par\bye")
 rules = walk_rules(dvi)
 widths = [r[3] for page in rules for r in page]
 assert widths, "expected at least one rule"
 three_in = round(3 * 72.27 * 65536)
 assert abs(widths[0] - three_in) <= 4, (
 f"rule width {widths[0]} sp not ~3in ({three_in} sp); "
 f"leaked default would be 30785886 sp"
 )


