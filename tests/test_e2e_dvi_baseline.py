""" — automated E2E DVI baseline suite against MiKTeX references.

Compiles each canonical fixture under ``testdata/e2e/`` through the **public**
API (``TeXJob(source, DviDevice()).run()``) and compares the result against a
committed MiKTeX-generated ``.dvi`` reference under ``testdata/baselines/``,
**semantically** (page count, glyph stream, per-glyph positions, line/rule
positions, font/page metadata) — never byte-for-byte ( AC-9;;
;).

**Mid-line horizontal advances are compared.** Until
this suite checked the glyph-code *stream* and each line's *start*
position, but never where each glyph landed *within* a line — so a dropped
interword space, a lost kern or a wrong template advance was invisible while
the suite stayed green. ``test_midline_glyph_positions_match`` closes that hole
by comparing every glyph's (h, v) at the ±0.1 pt H / ±0.5 pt V bounds.
A "matches MiKTeX" claim for a fixture that passes it is therefore now accurate
about full horizontal layout, not just the glyph stream.

**One divergence ledger.** A corpus document that still
diverges from MiKTeX is carried in ``_CORPUS_LEDGER`` — per document and per
check, or in the crash form — with its measured symptom and owning task(s). A
listed check is skipped with that text, so the divergence is visible in every
test report; every check that is not listed is asserted at the standard
tolerances, which are never widened. ``TestCorpusLedger`` fails as soon as an
entry stops describing a live divergence, so an entry cannot outlive the defect
it documents. The ledger replaced's ``_MIDLINE_H_DIVERGENCE`` and the
``_V_TOPSKIP_DIVERGENCE`` (both empty when they were retired);
criterion 1 reads this one ledger.

Every ``testdata/e2e/*.tex`` is asserted (``_FIXTURES``), and the eight
owner-admitted documents are pinned to their recorded SHA-256 regardless of the
checkout's line-end conversion (``_ADMITTED_DOCUMENTS``).

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
"""
from __future__ import annotations

import dataclasses
import enum
import functools
import hashlib
import re
import struct
from collections.abc import Callable, Collection, Mapping
from pathlib import Path

import pytest

from aspose_tex import DviDevice, TeXJob, TeXOptions
from aspose_tex._input.reader import FileInputSource
from aspose_tex.exceptions import EngineError

# AC-7: the suite is built on the shared DVI walker. If it cannot be imported
# (e.g. a stripped-down checkout), skip the whole module rather than error.
dvi_walker = pytest.importorskip("tests._verification.dvi_walker")

position_compare = pytest.importorskip("tests._verification.position_compare")

collect_chars_per_page = dvi_walker.collect_chars_per_page
walk_line_starts = dvi_walker.walk_line_starts
walk_rules = dvi_walker.walk_rules
walk_chars_with_positions = dvi_walker.walk_chars_with_positions
compare_glyph_positions = position_compare.compare_glyph_positions

# ---------------------------------------------------------------------------
# Paths + tolerances
# ---------------------------------------------------------------------------

_E2E_DIR = Path(__file__).parent.parent / "testdata" / "e2e"
_BASELINE_DIR = Path(__file__).parent.parent / "testdata" / "baselines"

_SP_PER_PT = 65_536
# The AC-5 bounds live in position_compare so no module
# re-derives them. Read off the importorskip'd module object rather than via a
# top-level ``from`` import, or the AC-7 stripped-checkout skip path regresses
# into a collection error.
_HALF_PT_SP = position_compare.TOL_V_SP  # ±0.5 pt — line/rule v tolerance.
_TENTH_PT_SP = position_compare.TOL_H_SP  # ±0.1 pt — horizontal tolerance.
_RULE_DIM_TOL_SP = 4  # Rule height/width: a few sp of sp-rounding slack.

# resolved the full-\hsize \hrule running-dimension width:
# the page box now tracks \hsize, so rule widths are compared unconditionally
# against MiKTeX in _diff_visible_rules (the former _DVI_RUNNING_DIMEN /
# _LEAKED_DEFAULT_HSIZE_SP guard + constants were removed when landed).

# resolved the continuation-page body offset: the missing
# TeXbook §1000 leading-discardables sweep at page recommencement let the
# interline glue between the shipped page's last box and the next page's first
# box leak atop the topskip (+3.11 pt). With the sweep in place, page 2+ body
# baselines match MiKTeX at the tight ±0.5 pt bound, so the former widened
# page-2+ tolerance (and its constant) were removed here.

_POST = 248
_POST_POST = 249

# Every testdata/e2e/*.tex document — TestFixtureInventory enforces that the
# two sets are equal ( FR-4), so a committed document cannot sit in the
# corpus without being asserted.
_FIXTURES = (
    # independent documents: unchanged human-authored Aspose .NET
    # regression documents (2020-21), published with the owner's permission of
    # 2026-10-20. tex-what-is-what has a title footnote; sample-1 has
    # UTF-8 quotes the fonts lack and an overfull line with its \overfullrule
    # marker.
    "sample-1",
    "tex-what-is-what",
    # owner idiom documents ( owner session, verbatim; the
    # footnote document was written from the repro on owner request).
    "owner_raggedright",
    "owner_narrower",
    "owner_table",
    "owner_dashes",
    "owner_footnote",
    "owner_hyphenation",
    # regression pins: agent rewrites of owner documents 3/4 (other
    # text, \hyphenchar\font=-1 switches hyphenation off) — not owner documents.
    "paragraph_raggedright",
    "paragraph_narrower",
    "hello",
    "paragraph",
    "paragraph_narrow",
    "multipage",
    "rules",
    "footnotes",
    "math_inline",
    # layout fixtures: scripts/fraction/short-radicand
    # radical/accent/overline (math_scripts) + display centring + \over + \eqno
    # (math_display).  Short radicands / null fraction delims keep the glyph
    # stream MiKTeX-exact without delimiter growth (§0 / §H).
    "math_scripts",
    "math_display",
    # cascade #4: variable-size delimiters + large operators.
    # A tall \left(...\over...\right) (rule-19 sizing, var_delimiter §706-710)
    # plus a display $$\sum_{i=1}^{n}$$ (make_op size switch + limits §749-750).
    # Committed with its baseline since but asserted only since
    # FR-4; closed the \big-family gap that kept it out.
    "math_delimiters",
    # text-mode \halign (§807 inter-row interline glue +
    # §812 fin_align row-splice so the first row attracts \topskip):
    # first baseline at \topskip, rows \baselineskip apart — MiKTeX-exact.
    "alignment_text",
    # inline math \halign fixture: $\matrix{…}$ +
    # $\pmatrix{…}$ via real plain.tex, now byte-matches MiKTeX end-to-end.
    # (C1 \mathstrut reaches the math branch + C2 \vcenter §735 axis-
    # centring), (\mathchoice branches EXECUTE — the phantom ( stops
    # leaking as glyph 0x28), (\finph@nt's equals-less \ht\tw@\ht\z@
    # box-dimension copy now runs and is not group-restore-corrupted). The
    # \pmatrix fence is the MiKTeX cmex 0x12/0x13, the \vcenter block is
    # axis-centred, and the absolute line baselines match — closing
    # AC #1/#2 and the inline half of AC #3.
    "alignment_matrix",
    # display math \halign fixture: $$\eqalign{…}$$ via
    # real plain.tex, now byte-matches MiKTeX end-to-end.  computes
    # \predisplaysize (§1146) from the last pre-display line, so the §1204
    # short-skip test selects \abovedisplayshortskip/\belowdisplayshortskip when
    # the preceding line ("The system") is short — closing the former +12 pt
    # display-low offset.  Glyph/H/font were already exact.
    "alignment_eqalign",
    # thematic fixture (a) — math inside \halign cells: a
    # text \halign whose cells contain inline $…$ (Ord/Bin/Rel atoms + Greek
    # \mathchardef), the historically weakest cross-construct seam
    #.  Byte-matches MiKTeX end-to-end (glyph stream / fonts /
    # page count exact; row baselines within ±0.5 pt), reusing the already-
    # byte-exact math-cell machinery + §807 interline
    # glue.
    "combined_math_in_cells",
    # (b) and optional (c), admitted by: the display-
    # family sequence — its last gate, the \cases extent, closed with
    # the \left\{ delimiter — and the \settabs/\+ math fields (,
    # closed by).  Both pass every check below unchanged.
    "combined_display_families",
    "combined_settabs_math",
    # FR-1: the comprehensive document across
    # pages.  Least-cost page breaking (§1000-§1017), §890 line penalties and
    # the display penalties choose MiKTeX's break; §866/§767/§1039 give its
    # line breaks.  The vsize variants pin the choice at other goal heights,
    # and paging_text pins breaks between the lines of plain prose.
    "combined_document",
    "combined_document_vsize_2_0",
    "combined_document_vsize_2_5",
    "combined_document_vsize_3_0",
    "paging_text",
    # page-state ownership: footnote insertions lower the
    # page goal (§1008-§1009), a page firing at a display keeps no space after
    # it (§1200), \pageinsert floats to the next page (§1010) and a penalty
    # before the first box is discarded (§1000).
    "page_state_footnote",
    "page_state_display_space",
    "page_state_pageinsert",
    "page_state_eject_empty",
    "text_accent_geometry",
    "text_accent_assignments",
)


# ---------------------------------------------------------------------------
# — the corpus divergence ledger
# ---------------------------------------------------------------------------

class Check(enum.Enum):
    """One comparison of the suite; the value is the label used in reports."""

    PAGE_COUNT = "page count"
    GLYPH_STREAM = "glyph stream"
    FONT_METADATA = "font metadata"
    LINE_BASELINES = "line baselines"
    GLYPH_POSITIONS = "per-glyph positions"
    VISIBLE_RULES = "visible rules"
    # Crash form: the document raises during compilation, so no check can run.
    CRASH = "compilation error"


@dataclasses.dataclass(frozen=True)
class Divergence:
    """A measured divergence from MiKTeX and the task(s) that own its fix.

    Example:
        >>> Divergence("glyph stream 145 vs 146; MiKTeX hyphenates chap-ters",
        ...            ("",)).owners
        ('',)
    """

    symptom: str
    owners: tuple[str, ...]


# Each entry is a REAL rendering defect, characterized and owned, never masked:
# there is ZERO tolerance widening anywhere in this module. Every check of a
# listed document that is NOT listed here is asserted; ``TestCorpusLedger``
# fails the moment a listed check matches MiKTeX (or a crash-form document
# compiles), forcing the entry out when its owning task lands.
#
# History:'s mid-line ledger once held six entries ( / 181 / 182
# / 183, all fixed) and's topskip set one (fixed); both were empty when
# folded them into this ledger. (automatic hyphenation) deleted
# its last entries, owner_dashes and owner_hyphenation; criterion 1
# needs it empty.
_CORPUS_LEDGER: dict[str, dict[Check, Divergence]] = {}

_OWNER_RE = re.compile(r"^TEX-\d+$")

# FR-1/FR-3: the eight owner-admitted documents, pinned to the SHA-256
# records, in the line-end form that hash was taken in — the two
# independent documents were hashed as their CRLF upstream files, the owner
# documents as LF files (§3). ``_canonical_sha256`` rewrites line ends
# first, so the pin holds whatever the checkout's ``* text=auto`` produced.
_ADMITTED_DOCUMENTS: dict[str, tuple[str, str]] = {
    "sample-1": ("2296e59d9200c6701c5b86ad686c487f7440de861aab2399e1a112c14a1063e7", "crlf"),
    "tex-what-is-what": (
        "3f1ea6c5a7a254fe2eca064ac8345e273457e4d5e8c2065c679e4d447968338a", "crlf"
    ),
    "owner_raggedright": (
        "d7c14e84e4000ea9265ae528c9b6e549460352b9ac26fbad77d61b6f93d6a8ea", "lf"
    ),
    "owner_narrower": ("59f02191722d8f884a06f5f5d215ce25845e3553e137d57d3e00f56d1e51ec74", "lf"),
    "owner_table": ("dcc3335daec47348a793ea69b219f74f0700cc4c5c994296c1f8b3c4505e1dad", "lf"),
    "owner_dashes": ("f6ac39572de6e1c55a8a9700594b172fe00beb9c0d842e074eea4218add92798", "lf"),
    "owner_footnote": ("71aecaf038623407846a4b82072eae6c85c909238a91293fbf40f5a0c1fdbc64", "lf"),
    "owner_hyphenation": (
        "2292ea2f7e4f68999f4b0537301cad4fbc5a487de9b8870d39b245eb31b9fe7b", "lf"
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@functools.cache
def _run(fixture: str) -> bytes:
    """Compile ``testdata/e2e/<fixture>.tex`` through the public DVI API.

    Uses exactly the path AC-3 names: ``TeXJob(source, DviDevice()).run()``
    with the plain-TeX format loaded. Cached: compilation is deterministic and
    the bytes are immutable, so each document compiles once per session rather
    than once per check ( NFR-3); a raised error is not cached.

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


def _canonical_sha256(data: bytes, line_end: str) -> str:
    """SHA-256 of ``data`` with every CRLF/LF line end rewritten to ``line_end``.

    Args:
        data: File bytes as checked out (LF or CRLF line ends).
        line_end: ``"lf"`` or ``"crlf"`` — the form the pinned hash was taken in.

    Returns:
        The hex digest, independent of the checkout's line-end conversion.

    Example:
        >>> _canonical_sha256(b"x", "lf") == hashlib.sha256(b"x").hexdigest()
        True
    """
    text = data.replace(b"\r\n", b"\n")
    if line_end == "crlf":
        text = text.replace(b"\n", b"\r\n")
    elif line_end != "lf":
        raise ValueError(f"line_end must be 'lf' or 'crlf', not {line_end!r}")
    return hashlib.sha256(text).hexdigest()


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
    #       max_stack(2) page_count(2)
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
    i = 15 + dvi[14]  # skip PRE (op + i + num/den/mag (12) + k(1) + comment k)
    n = len(dvi)
    while i < n:
        op = dvi[i]
        if op == _POST:
            break
        if 243 <= op <= 246:  # fnt_def1..4
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
    if op <= 127:  # set_char_0..127
        return 0
    if 128 <= op <= 131:  # set1..4
        return op - 127
    if op == 132 or op == 137:  # set_rule / put_rule
        return 8
    if 133 <= op <= 136:  # put1..4
        return op - 132
    if op == 138:  # nop
        return 0
    if op == 139:  # bop
        return 44
    if op == 140:  # eop
        return 0
    if op == 141 or op == 142:  # push / pop
        return 0
    if 143 <= op <= 146:  # right1..4
        return op - 142
    if op == 147:  # w0
        return 0
    if 148 <= op <= 151:  # w1..4
        return op - 147
    if op == 152:  # x0
        return 0
    if 153 <= op <= 156:  # x1..4
        return op - 152
    if 157 <= op <= 160:  # down1..4
        return op - 156
    if op == 161:  # y0
        return 0
    if 162 <= op <= 165:  # y1..4
        return op - 161
    if op == 166:  # z0
        return 0
    if 167 <= op <= 170:  # z1..4
        return op - 166
    if 171 <= op <= 234:  # fnt_num_0..63
        return 0
    if 235 <= op <= 238:  # fnt1..4
        return op - 234
    if 239 <= op <= 242:  # xxx1..4 (length-prefixed; caller handles payload)
        kbytes = op - 238
        length = int.from_bytes(dvi[i + 1 : i + 1 + kbytes], "big")
        return kbytes + length
    raise AssertionError(f"unexpected DVI opcode {op} at offset {i}")


# ---------------------------------------------------------------------------
# The six comparisons (§2) — each returns diagnostics, never raises on
# a shape mismatch, so the ledger guard can ask "does this check still diverge?"
# ---------------------------------------------------------------------------

def _diff_page_count(fixture: str, ours: bytes, ref: bytes) -> list[str]:
    """Page count is exact vs MiKTeX (POST.page_count)."""
    our_pages, ref_pages = _page_count(ours), _page_count(ref)
    if our_pages == ref_pages:
        return []
    return [f"{fixture}: page count ours={our_pages} != MiKTeX={ref_pages}"]


def _diff_glyph_stream(fixture: str, ours: bytes, ref: bytes) -> list[str]:
    """Per-page glyph code stream is exact vs MiKTeX."""
    our_pages = collect_chars_per_page(ours)
    ref_pages = collect_chars_per_page(ref)
    if len(our_pages) != len(ref_pages):
        return [
            f"{fixture}: page count for glyph stream ours={len(our_pages)} "
            f"!= MiKTeX={len(ref_pages)}"
        ]
    return [
        f"{fixture}: page {page_idx} glyph stream differs — "
        f"ours={bytes(c for c in op if c < 256)!r} "
        f"MiKTeX={bytes(c for c in mp if c < 256)!r}"
        for page_idx, (op, mp) in enumerate(zip(our_pages, ref_pages, strict=True))
        if op != mp
    ]


def _diff_font_metadata(fixture: str, ours: bytes, ref: bytes) -> list[str]:
    """AC-4: font_def metadata (checksum, scaled/design, name) matches MiKTeX.

    The DVI *font number* is an engine-internal id assigned at first use —
    MiKTeX uses TeX's internal font register number (e.g. cmmi10 is
    ``\\textfont1`` = font 6 in plain.tex's font table), whereas our engine
    numbers the fonts it emits sequentially. The number is self-consistent
    within each DVI (every ``fnt`` opcode references its own ``fnt_def``), so
    it does not affect rendering — only the metadata that *does*
    (checksum / scaled / design / name, keyed by font name) must match. This
    divergence first appeared with the math fonts: the
    text fixtures happen to number cmr10 = 0 the same way, but a math
    document pulls in cmmi10/cmsy10 at non-text positions.
    """
    our_fonts = {name: (cs, sc, ds) for _num, cs, sc, ds, name in _font_defs(ours)}
    ref_fonts = {name: (cs, sc, ds) for _num, cs, sc, ds, name in _font_defs(ref)}
    if our_fonts == ref_fonts:
        return []
    return [
        f"{fixture}: font_def metadata differs (keyed by name; DVI font number "
        f"is engine-internal)\n  ours = {our_fonts}\n  mik  = {ref_fonts}"
    ]


def _diff_line_baselines(fixture: str, ours: bytes, ref: bytes) -> list[str]:
    """Line baseline v-coords match within ±0.5 pt where line counts agree.

    Every page — including continuation pages (page 2+) — is held to the tight
    ±0.5 pt tolerance. The former widened page-2+ bound was removed when
    landed the TeXbook §1000 leading-discardables sweep,
    which eliminated the +3.11 pt continuation-page topskip offset.
    ``TestMultipagePageOneStrict`` keeps an explicit page-1 regression pin so a
    future page-builder change cannot re-introduce a leading-glue leak
    unnoticed.
    """
    our_pages = walk_line_starts(ours)
    ref_pages = walk_line_starts(ref)
    diagnostics: list[str] = []
    for page_idx, ref_lines in enumerate(ref_pages):
        if page_idx >= len(our_pages):
            diagnostics.append(f"{fixture}: our output is missing page {page_idx}")
            continue
        our_lines = our_pages[page_idx]
        if len(our_lines) != len(ref_lines):
            diagnostics.append(
                f"{fixture}: page {page_idx} line count ours={len(our_lines)} "
                f"!= MiKTeX={len(ref_lines)}"
            )
            continue
        for line_idx, ((ov, _oh), (rv, _rh)) in enumerate(
            zip(our_lines, ref_lines, strict=True)
        ):
            delta = ov - rv
            if abs(delta) > _HALF_PT_SP:
                diagnostics.append(
                    f"{fixture}: page {page_idx} line {line_idx} baseline "
                    f"ours v={ov / _SP_PER_PT:.3f} pt vs MiKTeX "
                    f"v={rv / _SP_PER_PT:.3f} pt — Δ={delta / _SP_PER_PT:+.3f} pt "
                    f"(tolerance {_HALF_PT_SP / _SP_PER_PT:.3f} pt)"
                )
    return diagnostics


def _diff_glyph_positions(fixture: str, ours: bytes, ref: bytes) -> list[str]:
    """: every glyph's (h, v) matches MiKTeX.

    This is the mid-line horizontal check: it compares where each glyph lands
    *within* a line, not just the line's start, so a dropped interword space,
    a lost kern or a wrong alignment-template advance can no longer pass
    unnoticed behind a matching glyph-code stream. Tolerances are the
    bounds (±0.1 pt H, ±0.5 pt V) — never widened for any fixture.
    """
    return [
        f"{fixture}: {line}"
        for line in compare_glyph_positions(
            walk_chars_with_positions(ours),
            walk_chars_with_positions(ref),
            h_tol_sp=_TENTH_PT_SP,
            v_tol_sp=_HALF_PT_SP,
        )
    ]


def _diff_visible_rules(fixture: str, ours: bytes, ref: bytes) -> list[str]:
    """Rule count + placement match MiKTeX, compared unconditionally.

    Rule v- and h-position are within ±0.5 pt; height **and width** within a
    few sp of sp-rounding slack. As of the shipout writers no
    longer emit non-painting rules (zero-width ``\\strut`` / zero-height
    rules), matching TeX:The Program §622/§634, so the rule stream is compared
    **without** filtering. Width is compared unconditionally as of /
    : a full-\\hsize ``\\hrule`` in an \\hsize-overriding fixture
    (rules.tex at 4in) resolves to MiKTeX's concrete 18945146 sp within
    rounding slack.
    """
    our_pages = walk_rules(ours)
    ref_pages = walk_rules(ref)
    # A math fraction-bar width is the max of the numerator/denominator
    # advances (a sum of glyph widths), so it accrues a few sp more rounding
    # than a single \hrule; the math fixtures compare rule width at the
    # ±0.1 pt H tolerance.
    width_tol = _TENTH_PT_SP if fixture.startswith("math") else _RULE_DIM_TOL_SP
    diagnostics: list[str] = []
    for page_idx, ref_rules in enumerate(ref_pages):
        our_rules = our_pages[page_idx] if page_idx < len(our_pages) else []
        if len(our_rules) != len(ref_rules):
            diagnostics.append(
                f"{fixture}: page {page_idx} visible-rule count "
                f"ours={len(our_rules)} != MiKTeX={len(ref_rules)}"
            )
            continue
        for rule_idx, ((oh, ov, oht, ow), (rh, rv, rht, rw)) in enumerate(
            zip(our_rules, ref_rules, strict=True)
        ):
            if abs(oht - rht) > _RULE_DIM_TOL_SP:
                diagnostics.append(
                    f"{fixture}: page {page_idx} rule {rule_idx} height differs — "
                    f"ours={oht} != MiKTeX={rht} sp"
                )
            if abs(ow - rw) > width_tol:
                diagnostics.append(
                    f"{fixture}: page {page_idx} rule {rule_idx} width differs — "
                    f"ours={ow} != MiKTeX={rw} sp"
                )
            if abs(ov - rv) > _HALF_PT_SP:
                diagnostics.append(
                    f"{fixture}: page {page_idx} rule {rule_idx} v-position "
                    f"ours={ov / _SP_PER_PT:.3f} pt vs MiKTeX={rv / _SP_PER_PT:.3f} pt"
                )
            if abs(oh - rh) > _HALF_PT_SP:
                diagnostics.append(
                    f"{fixture}: page {page_idx} rule {rule_idx} h-position "
                    f"ours={oh / _SP_PER_PT:.3f} pt vs MiKTeX={rh / _SP_PER_PT:.3f} pt"
                )
    return diagnostics


_CHECKS: dict[Check, Callable[[str, bytes, bytes], list[str]]] = {
    Check.PAGE_COUNT: _diff_page_count,
    Check.GLYPH_STREAM: _diff_glyph_stream,
    Check.FONT_METADATA: _diff_font_metadata,
    Check.LINE_BASELINES: _diff_line_baselines,
    Check.GLYPH_POSITIONS: _diff_glyph_positions,
    Check.VISIBLE_RULES: _diff_visible_rules,
}


def _skip_text(fixture: str, check: Check, divergence: Divergence) -> str:
    """The ledger text a skipped check reports ( FR-5)."""
    return (
        f"{fixture}: characterized divergence [{check.value}] — "
        f"{divergence.symptom} (owner: {', '.join(divergence.owners)})"
    )


def _assert_check(fixture: str, check: Check) -> None:
    """Skip with the ledger text when ledgered, else assert no diagnostics."""
    entry = _CORPUS_LEDGER.get(fixture, {})
    if Check.CRASH in entry:
        pytest.skip(_skip_text(fixture, Check.CRASH, entry[Check.CRASH]))
    if check in entry:
        pytest.skip(_skip_text(fixture, check, entry[check]))
    diagnostics = _CHECKS[check](fixture, _run(fixture), _baseline(fixture))
    assert not diagnostics, "\n  ".join(diagnostics)


def _stale_ledger_entries(
    ledger: Mapping[str, Mapping[Check, Divergence]],
    fixtures: Collection[str],
    compile_fixture: Callable[[str], bytes] = _run,
) -> list[str]:
    """Return one message per ledger claim that no longer describes a live divergence.

    Args:
        ledger: Document name → diverging checks (or ``Check.CRASH``).
        fixtures: The asserted corpus; a ledgered document outside it is stale.
        compile_fixture: Compiles a document to DVI bytes (``_run``; the guard
            tests substitute stubs).

    Returns:
        Messages for unknown documents, crash entries that now compile and
        listed checks that now match MiKTeX; empty when every claim is live.
    """
    stale: list[str] = []
    for fixture, entry in sorted(ledger.items()):
        if fixture not in fixtures:
            stale.append(f"{fixture}: not in _FIXTURES")
            continue
        if Check.CRASH in entry:
            try:
                compile_fixture(fixture)
            except Exception:  # any raise keeps the crash form live
                continue
            stale.append(f"{fixture}: compiles now; crash-form entry is stale")
            continue
        try:
            ours = compile_fixture(fixture)
        except Exception as exc:  # reported, not propagated
            stale.append(
                f"{fixture}: raises {type(exc).__name__}, but the entry lists "
                f"checks, not the crash form"
            )
            continue
        ref = _baseline(fixture)
        for check, divergence in entry.items():
            if not _CHECKS[check](fixture, ours, ref):
                stale.append(
                    f"{fixture}: [{check.value}] now matches MiKTeX; remove it "
                    f"from _CORPUS_LEDGER (ledger said: {divergence.symptom})"
                )
    return stale


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

    def test_every_corpus_document_is_asserted(self) -> None:
        """ FR-4: every testdata/e2e/*.tex is in _FIXTURES, once."""
        duplicates = sorted({f for f in _FIXTURES if _FIXTURES.count(f) > 1})
        assert not duplicates, f"_FIXTURES lists documents twice: {duplicates}"
        on_disk = {p.stem for p in _E2E_DIR.glob("*.tex")}
        assert on_disk == set(_FIXTURES), (
            f"corpus and _FIXTURES differ — not asserted: "
            f"{sorted(on_disk - set(_FIXTURES))}; no such document: "
            f"{sorted(set(_FIXTURES) - on_disk)}"
        )

    def test_admitted_documents_unchanged(self) -> None:
        """ FR-3: the admitted documents keep their recorded SHA-256."""
        for name, (sha256, line_end) in sorted(_ADMITTED_DOCUMENTS.items()):
            path = _E2E_DIR / f"{name}.tex"
            assert path.is_file(), f"admitted document {name}.tex missing"
            digest = _canonical_sha256(path.read_bytes(), line_end)
            assert digest == sha256, (
                f"{name}.tex changed: SHA-256 ({line_end}) {digest} != recorded "
                f"{sha256}. Admitted documents are kept verbatim; changing one is "
                f"an owner decision."
            )

    def test_canonical_hash_ignores_checkout_line_ends(self) -> None:
        """The pin is the same for LF and CRLF checkouts, and content-sensitive."""
        lf = b"\\hsize=4in\nText.\n\\bye\n"
        crlf = b"\\hsize=4in\r\nText.\r\n\\bye\r\n"
        for line_end in ("lf", "crlf"):
            assert _canonical_sha256(lf, line_end) == _canonical_sha256(crlf, line_end)
        assert _canonical_sha256(lf, "lf") == hashlib.sha256(lf).hexdigest()
        assert _canonical_sha256(lf, "crlf") == hashlib.sha256(crlf).hexdigest()
        assert _canonical_sha256(lf.replace(b"Text", b"Test"), "lf") != (
            _canonical_sha256(lf, "lf")
        )

    def test_readme_records_admitted_provenance(self) -> None:
        """ FR-2: the README records every pin and the permission date."""
        text = (_E2E_DIR / "README.md").read_text(encoding="utf-8")
        missing = sorted(
            name for name, (sha256, _) in _ADMITTED_DOCUMENTS.items() if sha256 not in text
        )
        assert not missing, f"README lacks the recorded SHA-256 of {missing}"
        assert "2026-10-20" in text, "README lacks the owner's publication permission date"


# ---------------------------------------------------------------------------
# AC-3 / AC-4 — semantic comparison of our engine output vs the baseline
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fixture", _FIXTURES)
class TestSemanticBaseline:
    """AC-3 + AC-4: run each fixture through the public API and compare
    page count, glyph stream, line/rule positions, and font metadata
    against the MiKTeX baseline with explicit tolerances. A check listed in
    ``_CORPUS_LEDGER`` skips with its ledger text instead."""

    def test_page_count_matches(self, fixture: str) -> None:
        """Page count is exact vs MiKTeX (POST.page_count)."""
        _assert_check(fixture, Check.PAGE_COUNT)

    def test_glyph_stream_matches(self, fixture: str) -> None:
        """Per-page glyph code stream is exact vs MiKTeX."""
        _assert_check(fixture, Check.GLYPH_STREAM)

    def test_font_metadata_matches(self, fixture: str) -> None:
        """AC-4: font_def metadata matches MiKTeX (see ``_diff_font_metadata``)."""
        _assert_check(fixture, Check.FONT_METADATA)

    def test_line_baselines_within_tolerance(self, fixture: str) -> None:
        """Line baseline v-coords match within ±0.5 pt on every page."""
        _assert_check(fixture, Check.LINE_BASELINES)

    def test_midline_glyph_positions_match(self, fixture: str) -> None:
        """: every glyph's (h, v) matches MiKTeX."""
        _assert_check(fixture, Check.GLYPH_POSITIONS)

    def test_visible_rules_match(self, fixture: str) -> None:
        """Rule count, placement and dimensions match MiKTeX."""
        _assert_check(fixture, Check.VISIBLE_RULES)


# ---------------------------------------------------------------------------
# FR-6 / — the ledger must not outlive its defects
# ---------------------------------------------------------------------------

def _divergence(symptom: str = "synthetic") -> Divergence:
    return Divergence(symptom, ("ISSUE-1",))


def _must_not_compile(fixture: str) -> bytes:
    raise AssertionError(f"the guard compiled {fixture} for an unknown document")


class TestCorpusLedger:
    """Guards against ``_CORPUS_LEDGER`` rotting into permanent cover.

    A skip list is only honest while every entry still describes a live
    defect. ``test_ledger_is_live`` makes that structural: fixing an owning
    task *forces* the entry out, because the guard fails the moment a listed
    check matches MiKTeX. The synthetic tests prove the guard catches each
    stale form without depending on any engine defect staying unfixed
    ( AC-5).
    """

    def test_ledger_is_live(self) -> None:
        """Every ledger claim still diverges; delete the reported entries."""
        stale = _stale_ledger_entries(_CORPUS_LEDGER, _FIXTURES)
        assert not stale, "stale _CORPUS_LEDGER entries:\n  " + "\n  ".join(stale)

    def test_ledger_entries_well_formed(self) -> None:
        """Entries are non-empty, crash form is exclusive, owners are TEX ids."""
        for fixture, entry in _CORPUS_LEDGER.items():
            assert entry, f"{fixture}: empty ledger entry"
            if Check.CRASH in entry:
                assert len(entry) == 1, (
                    f"{fixture}: the crash form excludes per-check entries"
                )
            for check, divergence in entry.items():
                assert divergence.symptom.strip(), f"{fixture}/{check.value}: no symptom"
                assert divergence.owners, f"{fixture}/{check.value}: no owning task"
                bad = [o for o in divergence.owners if not _OWNER_RE.match(o)]
                assert not bad, f"{fixture}/{check.value}: owners {bad} are not TEX ids"

    def test_every_check_has_a_comparison(self) -> None:
        """Each non-crash Check is backed by exactly one comparison."""
        assert set(_CHECKS) == set(Check) - {Check.CRASH}

    def test_guard_flags_check_that_now_passes(self) -> None:
        """A listed check that matches MiKTeX is reported."""
        stale = _stale_ledger_entries(
            {"hello": {Check.GLYPH_STREAM: _divergence()}}, _FIXTURES
        )
        assert len(stale) == 1
        assert "hello" in stale[0] and "glyph stream" in stale[0]

    def test_guard_flags_crash_entry_that_compiles(self) -> None:
        """A crash-form entry for a document that compiles is reported."""
        stale = _stale_ledger_entries({"hello": {Check.CRASH: _divergence()}}, _FIXTURES)
        assert len(stale) == 1
        assert "hello" in stale[0] and "compiles now" in stale[0]

    def test_guard_flags_unknown_document(self) -> None:
        """An entry naming a document outside _FIXTURES is reported, uncompiled."""
        stale = _stale_ledger_entries(
            {"no_such_document": {Check.GLYPH_STREAM: _divergence()}},
            _FIXTURES,
            compile_fixture=_must_not_compile,
        )
        assert stale == ["no_such_document: not in _FIXTURES"]

    def test_guard_flags_checks_entry_that_crashes(self) -> None:
        """A per-check entry whose document now raises is reported."""

        def crash(fixture: str) -> bytes:
            raise EngineError(f"synthetic failure in {fixture}")

        stale = _stale_ledger_entries(
            {"hello": {Check.GLYPH_STREAM: _divergence()}}, _FIXTURES, crash
        )
        assert len(stale) == 1 and "EngineError" in stale[0]

    def test_guard_accepts_live_divergences(self) -> None:
        """A still-crashing document and a still-diverging check are not stale."""

        def stub(fixture: str) -> bytes:
            if fixture == "rules":
                raise EngineError("synthetic crash")
            return _baseline("paragraph")

        ledger = {
            "rules": {Check.CRASH: _divergence()},
            "hello": {Check.GLYPH_STREAM: _divergence()},
        }
        assert _stale_ledger_entries(ledger, _FIXTURES, stub) == []

    def test_skip_text_names_check_symptom_and_owner(self) -> None:
        """The report text carries the check, the symptom and every owner."""
        text = _skip_text(
            "doc", Check.VISIBLE_RULES, Divergence("0 vs 3 rules", ("ISSUE-1", "ISSUE-2"))
        )
        assert text == (
            "doc: characterized divergence [visible rules] — 0 vs 3 rules "
            "(owner: ISSUE-1, ISSUE-2)"
        )


# ---------------------------------------------------------------------------
# AC-4 — page-1 strictness pin for multipage (regression guard for)
# ---------------------------------------------------------------------------

class TestMultipagePageOneStrict:
    """ guard: multipage page 1 must stay byte-position-perfect.

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
