""" — automated E2E DVI baseline suite against MiKTeX references.

Compiles each canonical fixture under ``testdata/e2e/`` through the **public**
API (``TeXJob(source, DviDevice()).run()``) and compares the result against a
committed MiKTeX-generated ``.dvi`` reference under ``testdata/baselines/``,
**semantically** (page count, glyph stream, line/rule positions, font/page
metadata) — never byte-for-byte ( AC-9; ; ; ).

This is the durable, automated DVI regression suite. It is distinct from and
complementary to:

* The 5-MD5 byte-stability fixture
 (``tests/test_named_param_migration_byte_stability.py``) — owns *byte*
 stability; owns *semantic* regression.
* manual PDF/SVG visual smoke verification
 (``testdata/verification-reports/``) — periodic human-eye render checks;
 runs on every ``pytest`` invocation.
* The task-specific DVI regressions under
 ``testdata/fixtures/{vsize_stretch,eject,rule_then_para,rule_split_probes}``
 — bespoke defect pins, intentionally kept separate (see
 ``testdata/e2e/README.md`` AC-5 rationale).

The committed baselines are what this suite reads, so there is **no MiKTeX
dependency at test time**. Only baseline *regeneration*
(``make e2e-baselines`` / ``tools/regen_e2e_baselines.py``) needs pdftex.
If the shared DVI walker is unavailable the whole module skips cleanly
(AC-7).

Three engine-vs-MiKTeX divergences this suite surfaced are characterized,
not hidden — see ``testdata/e2e/README.md`` and follow-ups / 
/ . Where they apply, the relevant comparison is widened or filtered
with an inline rationale so a behaviour change still re-trips the test.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from aspose_tex import DviDevice, TeXJob, TeXOptions
from aspose_tex._input.reader import FileInputSource

# AC-7: the suite is built on the shared DVI walker. If it cannot be imported
# (e.g. a stripped-down checkout), skip the whole module rather than error.
dvi_walker = pytest.importorskip("tests._verification.dvi_walker")

collect_chars_per_page = dvi_walker.collect_chars_per_page
walk_line_starts = dvi_walker.walk_line_starts
walk_rules = dvi_walker.walk_rules

# ---------------------------------------------------------------------------
# Paths + tolerances
# ---------------------------------------------------------------------------

_E2E_DIR = Path(__file__).parent.parent / "testdata" / "e2e"
_BASELINE_DIR = Path(__file__).parent.parent / "testdata" / "baselines"

_SP_PER_PT = 65_536
_HALF_PT_SP = 32_768 # ±0.5 pt — AC-5 line/rule v tolerance.
_RULE_DIM_TOL_SP = 4 # Rule height/width: a few sp of sp-rounding slack.

# / resolved the full-\hsize \hrule running-dimension width:
# the page box now tracks \hsize, so rule widths are compared unconditionally
# against MiKTeX in test_visible_rules_match (the former _DVI_RUNNING_DIMEN /
# _LEAKED_DEFAULT_HSIZE_SP guard + constants were removed when landed).

# / resolved the continuation-page body offset: the missing
# TeXbook §1000 leading-discardables sweep at page recommencement let the
# interline glue between the shipped page's last box and the next page's first
# box leak atop the topskip (+3.11 pt). With the sweep in place, page 2+ body
# baselines match MiKTeX at the tight ±0.5 pt bound, so the former widened
# page-2+ tolerance (and its constant) were removed here.

_POST = 248
_POST_POST = 249

# The four AC-1 required fixtures, the optional footnotes fixture, and the
# narrow-\hsize fixture (paragraph_narrow at 3in — pins width-sensitive
# line breaking now that the line-breaker honours \hsize, ).
_FIXTURES = (
 "hello",
 "paragraph",
 "paragraph_narrow",
 "multipage",
 "rules",
 "footnotes",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(fixture: str) -> bytes:
 """Compile ``testdata/e2e/<fixture>.tex`` through the public DVI API.

 Uses exactly the path AC-3 names: ``TeXJob(source, DviDevice()).run()``
 with the plain-TeX format loaded.

 Args:
 fixture: Bare fixture base name (no extension).

 Returns:
 The DVI byte stream produced by our engine.
 """
 source = FileInputSource(_E2E_DIR / f"{fixture}.tex")
 job = TeXJob(source, DviDevice(), options=TeXOptions(load_format="plain"))
 dvi = job.run()
 assert dvi is not None, "DviDevice() must yield bytes for a BytesIO destination"
 return dvi


def _baseline(fixture: str) -> bytes:
 """Return the committed MiKTeX ``.dvi`` baseline bytes for a fixture."""
 return (_BASELINE_DIR / f"{fixture}.miktex.dvi").read_bytes()


def _page_count(dvi: bytes) -> int:
 """Read the DVI POST ``page_count`` field (TeX: The Program §588).

 Walks from the trailing POST_POST opcode to the POST opcode and decodes
 the 2-byte ``total_pages`` field, rather than scanning for the BOP byte
 value (139), which can occur inside multi-byte operands.
 """
 pp_idx = dvi.rfind(bytes([_POST_POST]))
 assert pp_idx > 0, "POST_POST opcode missing"
 post_offset = struct.unpack(">i", dvi[pp_idx + 1 : pp_idx + 5])[0]
 assert dvi[post_offset] == _POST, "POST opcode not at post_offset"
 # POST: op(1) last_bop(4) num(4) den(4) mag(4) max_h(4) max_w(4)
 # max_stack(2) page_count(2)
 pc_off = post_offset + 1 + 4 + 4 + 4 + 4 + 4 + 4 + 2
 (page_count,) = struct.unpack(">H", dvi[pc_off : pc_off + 2])
 return page_count


def _font_defs(dvi: bytes) -> list[tuple[int, int, int, int, str]]:
 """Return ``[(font_num, checksum, scaled, design, name), ...]``.

 Scans the preamble-to-POST span for ``fnt_def1..4`` (243..246). Every
 other opcode is skipped via its known operand size so the scan stays
 aligned. Used for the AC-4 font-metadata comparison (font number,
 scaled size, design size, name must match MiKTeX exactly).
 """
 defs: list[tuple[int, int, int, int, str]] = []
 i = 15 + dvi[14] # skip PRE (op + i + num/den/mag (12) + k(1) + comment k)
 n = len(dvi)
 while i < n:
 op = dvi[i]
 if op == _POST:
 break
 if 243 <= op <= 246: # fnt_def1..4
 fn_bytes = op - 242
 font_num = int.from_bytes(dvi[i + 1 : i + 1 + fn_bytes], "big")
 base = i + 1 + fn_bytes
 checksum = int.from_bytes(dvi[base : base + 4], "big")
 scaled = int.from_bytes(dvi[base + 4 : base + 8], "big")
 design = int.from_bytes(dvi[base + 8 : base + 12], "big")
 area_len = dvi[base + 12]
 name_len = dvi[base + 13]
 name_start = base + 14 + area_len
 name = dvi[name_start : name_start + name_len].decode("ascii", "replace")
 defs.append((font_num, checksum, scaled, design, name))
 i = name_start + name_len
 continue
 i += _operand_size(dvi, i) + 1
 return defs


def _operand_size(dvi: bytes, i: int) -> int:
 """Return the operand byte count of the DVI opcode at offset ``i``.

 Covers every opcode our DviWriter and MiKTeX emit between PRE and POST.
 ``set_char_0..127`` and the single-byte movement/font opcodes have a
 zero-length operand. xxx and fnt_def are length-prefixed and handled by
 the caller, so they are not expected here.
 """
 op = dvi[i]
 if op <= 127: # set_char_0..127
 return 0
 if 128 <= op <= 131: # set1..4
 return op - 127
 if op == 132 or op == 137: # set_rule / put_rule
 return 8
 if 133 <= op <= 136: # put1..4
 return op - 132
 if op == 138: # nop
 return 0
 if op == 139: # bop
 return 44
 if op == 140: # eop
 return 0
 if op == 141 or op == 142: # push / pop
 return 0
 if 143 <= op <= 146: # right1..4
 return op - 142
 if op == 147: # w0
 return 0
 if 148 <= op <= 151: # w1..4
 return op - 147
 if op == 152: # x0
 return 0
 if 153 <= op <= 156: # x1..4
 return op - 152
 if 157 <= op <= 160: # down1..4
 return op - 156
 if op == 161: # y0
 return 0
 if 162 <= op <= 165: # y1..4
 return op - 161
 if op == 166: # z0
 return 0
 if 167 <= op <= 170: # z1..4
 return op - 166
 if 171 <= op <= 234: # fnt_num_0..63
 return 0
 if 235 <= op <= 238: # fnt1..4
 return op - 234
 if 239 <= op <= 242: # xxx1..4 (length-prefixed; caller handles payload)
 kbytes = op - 238
 length = int.from_bytes(dvi[i + 1 : i + 1 + kbytes], "big")
 return kbytes + length
 raise AssertionError(f"unexpected DVI opcode {op} at offset {i}")


# ---------------------------------------------------------------------------
# AC-1 / AC-2 — fixtures and baselines exist and pair up
# ---------------------------------------------------------------------------

class TestFixtureInventory:
 """AC-1 + AC-2: the canonical fixture set and its baselines are present."""

 def test_required_fixtures_present(self) -> None:
 """testdata/e2e/ has at least the four AC-1 canonical fixtures."""
 for name in ("hello", "paragraph", "multipage", "rules"):
 assert (_E2E_DIR / f"{name}.tex").is_file(), f"missing fixture {name}.tex"

 def test_every_fixture_has_a_baseline(self) -> None:
 """Every E2E fixture has a matching committed MiKTeX .dvi baseline."""
 for tex_path in sorted(_E2E_DIR.glob("*.tex")):
 baseline = _BASELINE_DIR / f"{tex_path.stem}.miktex.dvi"
 assert baseline.is_file(), f"missing baseline for {tex_path.name}"

 def test_provenance_documented(self) -> None:
 """AC-2: baseline source provenance is documented."""
 readme = _BASELINE_DIR / "README.md"
 assert readme.is_file(), "testdata/baselines/README.md missing"
 text = readme.read_text(encoding="utf-8")
 assert "MiKTeX-pdfTeX 4.19" in text
 assert "--output-format=dvi" in text


# ---------------------------------------------------------------------------
# AC-3 / AC-4 — semantic comparison of our engine output vs the baseline
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture", _FIXTURES)
class TestSemanticBaseline:
 """AC-3 + AC-4: run each fixture through the public API and compare
 page count, glyph stream, line/rule positions, and font metadata
 against the MiKTeX baseline with explicit tolerances."""

 def test_page_count_matches(self, fixture: str) -> None:
 """Page count is exact vs MiKTeX (POST.page_count)."""
 ours = _page_count(_run(fixture))
 ref = _page_count(_baseline(fixture))
 assert ours == ref, f"{fixture}: page count ours={ours} != MiKTeX={ref}"

 def test_glyph_stream_matches(self, fixture: str) -> None:
 """Per-page glyph code stream is exact vs MiKTeX."""
 ours = collect_chars_per_page(_run(fixture))
 ref = collect_chars_per_page(_baseline(fixture))
 assert len(ours) == len(ref), (
 f"{fixture}: page count for glyph stream ours={len(ours)} "
 f"!= MiKTeX={len(ref)}"
 )
 for page_idx, (op, mp) in enumerate(zip(ours, ref, strict=True)):
 assert op == mp, (
 f"{fixture}: page {page_idx} glyph stream differs — "
 f"ours={bytes(c for c in op if c < 256)!r} "
 f"MiKTeX={bytes(c for c in mp if c < 256)!r}"
 )

 def test_font_metadata_matches(self, fixture: str) -> None:
 """AC-4: font_def metadata (number, checksum, scaled/design, name)
 matches MiKTeX exactly."""
 ours = _font_defs(_run(fixture))
 ref = _font_defs(_baseline(fixture))
 assert ours == ref, (
 f"{fixture}: font_def metadata differs\n ours = {ours}\n mik = {ref}"
 )

 def test_line_baselines_within_tolerance(self, fixture: str) -> None:
 """Line baseline v-coords match within ±0.5 pt where line counts agree.

 Every page — including continuation pages (page 2+) — is asserted at
 the tight ±0.5 pt tolerance. The former widened page-2+ bound was
 removed when / landed the TeXbook §1000 leading-
 discardables sweep, which eliminated the +3.11 pt continuation-page
 topskip offset. ``TestMultipagePageOneStrict`` keeps an explicit
 page-1 regression pin so a future page-builder change cannot
 re-introduce a leading-glue leak unnoticed.
 """
 ours = walk_line_starts(_run(fixture))
 ref = walk_line_starts(_baseline(fixture))
 for page_idx, ref_lines in enumerate(ref):
 assert page_idx < len(ours), (
 f"{fixture}: our output is missing page {page_idx}"
 )
 our_lines = ours[page_idx]
 assert len(our_lines) == len(ref_lines), (
 f"{fixture}: page {page_idx} line count ours={len(our_lines)} "
 f"!= MiKTeX={len(ref_lines)}"
 )
 for line_idx, ((ov, _oh), (rv, _rh)) in enumerate(
 zip(our_lines, ref_lines, strict=True)
 ):
 delta = ov - rv
 assert abs(delta) <= _HALF_PT_SP, (
 f"{fixture}: page {page_idx} line {line_idx} baseline "
 f"ours v={ov / _SP_PER_PT:.3f} pt vs MiKTeX "
 f"v={rv / _SP_PER_PT:.3f} pt — Δ={delta / _SP_PER_PT:+.3f} pt "
 f"(tolerance {_HALF_PT_SP / _SP_PER_PT:.3f} pt)"
 )

 def test_visible_rules_match(self, fixture: str) -> None:
 """Rule count + placement match MiKTeX, compared unconditionally.

 Rule v-position is within ±0.5 pt; height **and width** within a few sp
 of sp-rounding slack. As of / the shipout writers no
 longer emit non-painting rules (zero-width ``\\strut`` / zero-height
 rules), matching TeX:The Program §622/§634, so the footnote ``\\strut``
 no longer leaks a spurious zero-width rule and the rule stream is
 compared **without** filtering.

 Width is compared **unconditionally** as of / : the
 line-breaker now honours ``\\hsize`` and the page box tracks the
 document width, so a full-\\hsize ``\\hrule`` in an \\hsize-overriding
 fixture (rules.tex at 4in) resolves to MiKTeX's concrete 18945146 sp
 within rounding slack — no running-dimension / leaked-default guard.
 """
 ours = walk_rules(_run(fixture))
 ref = walk_rules(_baseline(fixture))
 for page_idx, ref_rules in enumerate(ref):
 our_rules = ours[page_idx] if page_idx < len(ours) else []
 assert len(our_rules) == len(ref_rules), (
 f"{fixture}: page {page_idx} visible-rule count "
 f"ours={len(our_rules)} != MiKTeX={len(ref_rules)}"
 )
 for rule_idx, ((oh, ov, oht, ow), (rh, rv, rht, rw)) in enumerate(
 zip(our_rules, ref_rules, strict=True)
 ):
 assert abs(oht - rht) <= _RULE_DIM_TOL_SP, (
 f"{fixture}: page {page_idx} rule {rule_idx} height differs — "
 f"ours={oht} != MiKTeX={rht} sp"
 )
 # Width compared unconditionally: the page
 # box now tracks \hsize so a full-\hsize \hrule resolves to the
 # document column width, matching MiKTeX within rounding slack.
 assert abs(ow - rw) <= _RULE_DIM_TOL_SP, (
 f"{fixture}: page {page_idx} rule {rule_idx} width differs — "
 f"ours={ow} != MiKTeX={rw} sp"
 )
 assert abs(ov - rv) <= _HALF_PT_SP, (
 f"{fixture}: page {page_idx} rule {rule_idx} v-position "
 f"ours={ov / _SP_PER_PT:.3f} pt vs MiKTeX={rv / _SP_PER_PT:.3f} pt"
 )
 assert abs(oh - rh) <= _HALF_PT_SP, (
 f"{fixture}: page {page_idx} rule {rule_idx} h-position "
 f"ours={oh / _SP_PER_PT:.3f} pt vs MiKTeX={rh / _SP_PER_PT:.3f} pt"
 )


# ---------------------------------------------------------------------------
# AC-4 — page-1 strictness pin for multipage (regression guard for )
# ---------------------------------------------------------------------------

class TestMultipagePageOneStrict:
 """ / guard: multipage page 1 must stay byte-position-perfect.

 Page 1 has no preceding leftover, so it never carried the continuation-page
 topskip offset that closed. This pins every page-1 baseline at the
 tight ±0.5 pt tolerance so a future page-builder change (e.g. an over-eager
 §1000 leading-discardables sweep) that disturbs page 1 is caught
 immediately.
 """

 def test_multipage_page1_baselines_strict(self) -> None:
 ours = walk_line_starts(_run("multipage"))
 ref = walk_line_starts(_baseline("multipage"))
 assert ours and ref, "multipage produced no pages"
 our_p1, ref_p1 = ours[0], ref[0]
 assert len(our_p1) == len(ref_p1) >= 6, (
 f"multipage page 1 line count ours={len(our_p1)} ref={len(ref_p1)}"
 )
 for line_idx, ((ov, _), (rv, _)) in enumerate(
 zip(our_p1, ref_p1, strict=True)
 ):
 assert abs(ov - rv) <= _HALF_PT_SP, (
 f"multipage page 1 line {line_idx} baseline drifted: "
 f"ours v={ov / _SP_PER_PT:.3f} pt vs MiKTeX v={rv / _SP_PER_PT:.3f} pt"
 )
