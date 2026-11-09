"""Byte-stability gate for the migration of
``\\vsize`` / ``\\topskip`` / ``\\maxdepth`` from ad-hoc ``_exec_*`` handlers
into the ``NamedParameterRegistry`` (§"Migration plan").

The MD5 constants below were captured against the codebase BEFORE the three
handlers were retired (`_exec_vsize` / `_exec_topskip` / `_exec_maxdepth`
still live under ``TeXInterpreter._build_primitives``), so any drift after
the migration commit signals an observable behaviour change and fails the
AC-9 byte-stability gate.

PDF output embeds a ``/CreationDate`` and an ``/ID`` derived from it
(``PdfWriter._now_pdf_date``), so the smoke-PDF check freezes that value
the same way ``test_presentation_pdf_integration`` does.

If a future code change legitimately needs to break one of these hashes
(font upgrade, output-format spec change, etc.) update the constants in the
SAME commit that introduces the change and document the reason in the
commit message and CHANGELOG — this file is the canonical guard against
silent regressions.

Re-baselined (2026-05-25): the three
``smoke_m2`` constants (``_SMOKE_DVI_MD5``, ``_SMOKE_PDF_MD5``,
``_SMOKE_SVG_MD5``) capture the §679-correct rule-then-paragraph
interline arithmetic on smoke_m2.tex (`\\hrule` mid-page now sets
``\\prevdepth := \\rule.depth``, eliminating an extra interline-glue
node that pre-cascade emitted between a descender-bearing prior line
and the post-rule paragraph).

Re-baselined **again** on 2026-05-27:
the SAME three ``smoke_m2`` constants are updated to
capture the TeX:The Program §679 sentinel write
(``_prev_depth := ignore_depth = -1000 pt``) on both ``\\hrule`` arms
of ``PageBuilder.contribute`` + the TeXbook §253 sentinel guard in
``_interline_glue``.  The §679-correct sentinel
suppresses the spurious 5.056 pt interline glue between the
``\\hrule`` and the following hbox on ``smoke_m2.tex`` page 1 (AVAST
line) and page 2 ('End...' line), closing the joint residual
that Revision 4 explicitly routed.

The two non-smoke_m2 constants (``_HELLO_DVI_MD5``,
``_EJECT_DVI_MD5``) are unchanged across both v4 and v5
re-baselines — neither fixture contains a main-vertical-list
``\\hrule`` contribution, so the sentinel fix is a no-op for them.

Re-baselined **once more** (2026-05-29): ONLY the
``_SMOKE_SVG_MD5`` constant changes.  encodes the font at-size
into every SVG glyph id (``g-{tfm}-{code}`` → ``g-{tfm}-{at_size_int}-{code}``;
e.g. ``g-cmr10-49`` → ``g-cmr10-10-49``) so a TFM loaded at multiple sizes
no longer collides on a single ``<path id>``.  This is an SVG output-format
spec change (the docstring's "output-format spec change" re-baseline case);
it touches glyph-id strings only, so the DVI / PDF baselines
(``_SMOKE_DVI_MD5`` / ``_SMOKE_PDF_MD5``) and the two DVI-only constants
are unaffected.  ``smoke_m2.tex`` uses cmr10 at a single size, so the engine
output is otherwise byte-identical to the v5 baseline — verified by reverting
the ``svg_writer.py`` change and re-capturing the old hash.

Re-baselined **once more** (2026-05-30): ONLY the
``_SMOKE_DVI_MD5`` constant changes (``1567698f…`` → ``badeff8a…``).  The
``DviWriter._traverse_vlist`` rule arm now resolves the ``RUNNING_DIMEN``
sentinel against the enclosing box (mirroring the hlist arm + PDF/SVG writers),
so ``smoke_m2.tex``'s two top-level full-\\hsize ``\\hrule``s emit the concrete
page-box width instead of the ``-2^30`` running-dimension code.  This is a DVI
output-format change (the docstring's "output-format spec change" re-baseline
case); it touches the DVI rule-width opcode only, so the PDF / SVG baselines
(``_SMOKE_PDF_MD5`` / ``_SMOKE_SVG_MD5``) are unaffected — both already resolved
the sentinel — and the two non-smoke DVI constants (``_HELLO_DVI_MD5`` /
``_EJECT_DVI_MD5``) carry no main-vertical-list ``\\hrule`` so they are no-ops.

Re-baselined **once more** (2026-05-31): ONLY the
``_SMOKE_DVI_MD5`` constant changes (``badeff8a…`` → ``319e61d…``).  The
``DviWriter._traverse_vlist`` rule arm now ships a vertically placed rule with
``put_rule`` (opcode 137) instead of ``set_rule`` (132), per TeX:The Program
§624 (``vlist_out``) — a vlist rule paints WITHOUT advancing the horizontal
reference point.  ``set_rule`` had advanced the DVI ``h`` register by the rule
width, shifting post-``\\hrule`` material right in strict DVI viewers (Yap).
This is a DVI output-format change (the rule opcode byte 132 → 137); it touches
the DVI rule opcode only, so the PDF / SVG baselines are unaffected (those
writers place an absolutely positioned rectangle, no reference-point advance),
and the two non-smoke DVI constants carry no main-vertical-list ``\\hrule`` so
they are no-ops.

Re-baselined **once more** under ** / §G** (2026-06-04): ONLY the
``_SMOKE_SVG_MD5`` constant changes (``67222044…`` → ``924fab00…``).
(FR-10, closes) changes the SVG glyph-id at-size component from the
rounded integer pt to the **exact** ``at_size_sp`` (``g-{tfm}-{round(pt)}-{code}``
→ ``g-{tfm}-{at_size_sp}-{code}``; e.g. ``g-cmr10-10-49`` → ``g-cmr10-655360-49``)
so two fractional sizes rounding to the same int pt no longer collide on one
``<path id>``.  This is an SVG output-format change (glyph-id strings only), so
the DVI / PDF baselines (``_SMOKE_DVI_MD5`` / ``_SMOKE_PDF_MD5``) and the two
DVI-only constants are unaffected — verified: the same run re-baselined ONLY the
SVG hash, DVI/PDF stayed green.  FR-9 (exact ``at_size_sp`` through the DVI
``fnt_def``) is verified DVI-byte-stable — the path was already exact, no DVI
movement.

Re-baselined **once more** (2026-07-29): ALL THREE
``smoke_m2`` constants change (DVI ``319e61d2…`` → ``abddb61f…``, PDF
``051d8a8d…`` → ``28983efe…``, SVG ``924fab00…`` → ``6870b062…``).
unifies the split ``\\sfcode`` store: ``_exec_sfcode`` wrote ``CodeArrays``
while ``TeXInterpreter._get_sfcode`` read a private 3-entry ``_sfcodes`` dict
that hardcoded ``.``/``!``/``?`` = 3000.  Those are **not** IniTeX values —
they come from plain.tex's ``\\nonfrenchspacing`` (line 1238).  Verified
against MiKTeX ``initex``: with no format loaded ``\\the\\sfcode`\\.`` is
**1000**, and ``\\the\\sfcode`\\A`` is 999.  ``smoke_m2.tex`` runs with
``load_format=False``, so its ``fiddle.``, ``AVAST!`` and ``AVA.`` spaces were
being built at a fabricated ``sf=3000`` — wider ``width`` (``\\xspaceskip``
via fontdimen 7), tripled ``stretch`` and one-third ``shrink`` — where real
IniTeX builds a
plain interword space.  The new bytes are therefore a **correctness fix, not a
drift**: this is the docstring's "observable behaviour change" case, and the
constants are updated in the same commit per the protocol above.  All three
formats move because the change is in the engine's glue widths, upstream of
every writer.  ``_HELLO_DVI_MD5`` / ``_EJECT_DVI_MD5`` are unchanged —
verified: neither fixture has a sentence-ending ``.``/``!``/``?`` followed by
a space.  All 13 MiKTeX-baseline e2e fixtures stayed green across this change.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from aspose_tex._input.reader import FileInputSource, StringInputSource
from aspose_tex._output.pdf_writer import PdfWriter
from aspose_tex.presentation import (
    DviDevice,
    PdfDevice,
    SvgDevice,
    TeXJob,
    TeXOptions,
)

# Pre-migration MD5 baselines (captured 2026-05-07 with the legacy
# ``_exec_vsize`` / ``_exec_topskip`` / ``_exec_maxdepth`` handlers active).
# The three ``_SMOKE_*`` constants were re-baselined
# on 2026-05-25 and AGAIN on 2026-05-27 — see the module
# docstring above.
_HELLO_DVI_MD5 = "cd55caa1125f71ca4e03341b9358788d"
_SMOKE_DVI_MD5 = "9c9eb5845882227a5d160dd82582f5d2"  # cumulative binary32 glue setting
_SMOKE_PDF_MD5 = "60667094b1189f2b51dd150a3d1cbcb2"  # TeX pt -> bp, PDF side
_SMOKE_SVG_MD5 = "596921618c7f6f1d473d52053b42525f"  # TeX pt -> bp, SVG side
_EJECT_DVI_MD5 = "9c92abccb7b6d19f9ffd5d8741fdf439"

_FROZEN_PDF_DATE = b"D:20260101000000Z"

_TESTDATA = Path(__file__).resolve().parent.parent / "testdata"
_SMOKE_TEX = _TESTDATA / "smoke_m2.tex"
_EJECT_TEX = _TESTDATA / "fixtures" / "eject" / "three_paragraph_eject.tex"


@pytest.fixture
def frozen_pdf_date() -> Iterator[None]:
    """Freeze ``PdfWriter._now_pdf_date`` so PDF byte-stability is decidable."""
    original = PdfWriter._now_pdf_date
    PdfWriter._now_pdf_date = lambda self: _FROZEN_PDF_DATE  # type: ignore[method-assign]
    try:
        yield
    finally:
        PdfWriter._now_pdf_date = original  # type: ignore[method-assign]


def _md5(payload: bytes) -> str:
    return hashlib.md5(payload).hexdigest()


def _run_dvi(source) -> bytes:
    device = DviDevice()
    TeXJob(source, device, options=TeXOptions(load_format=False)).run()
    out = device.get_bytes()
    assert out is not None
    return out


def _run_pdf(source) -> bytes:
    device = PdfDevice()
    TeXJob(source, device, options=TeXOptions(load_format=False)).run()
    out = device.get_bytes()
    assert out is not None
    return out


def _run_svg_all_pages(source) -> bytes:
    device = SvgDevice()
    TeXJob(source, device, options=TeXOptions(load_format=False)).run()
    pages = device.get_all_pages()
    assert pages is not None
    return b"|".join(pages)


def test_hello_world_dvi_byte_stable() -> None:
    """``Hello World\\bye`` DVI bytes match the pre-migration baseline."""
    dvi = _run_dvi(StringInputSource("Hello World\\bye"))
    assert _md5(dvi) == _HELLO_DVI_MD5


def test_smoke_m2_dvi_md5_unchanged() -> None:
    """``smoke_m2.tex`` DVI bytes match the pre-migration baseline."""
    dvi = _run_dvi(FileInputSource(_SMOKE_TEX))
    assert _md5(dvi) == _SMOKE_DVI_MD5


def test_smoke_m2_pdf_md5_unchanged(frozen_pdf_date: None) -> None:
    """``smoke_m2.tex`` PDF bytes match the pre-migration baseline."""
    pdf = _run_pdf(FileInputSource(_SMOKE_TEX))
    assert _md5(pdf) == _SMOKE_PDF_MD5


def test_smoke_m2_svg_md5_unchanged() -> None:
    """``smoke_m2.tex`` SVG bytes (all pages joined by ``|``) are stable."""
    svg = _run_svg_all_pages(FileInputSource(_SMOKE_TEX))
    assert _md5(svg) == _SMOKE_SVG_MD5


def test_three_paragraph_eject_dvi_md5_unchanged() -> None:
    """ ``three_paragraph_eject.tex`` DVI bytes are stable.

    The fixture sets ``\\vsize=300pt``; with that assignment now goes
    through ``NamedParameterRegistry.dispatch_assignment`` instead of the
    legacy ``_exec_vsize`` handler.  Output must not drift.
    """
    dvi = _run_dvi(FileInputSource(_EJECT_TEX))
    assert _md5(dvi) == _EJECT_DVI_MD5
