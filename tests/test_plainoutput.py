r""" plain.tex ``\plainoutput`` integration fixtures."""
from __future__ import annotations

import hashlib
import warnings

import pytest

from aspose_tex._engine.box_primitives import OverfullBoxWarning
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions
from tests._verification.dvi_walker import (
 collect_chars_per_page,
 walk_chars_with_positions,
)

_PLAIN = TeXOptions(load_format="plain")
_FAST = TeXOptions(load_format=False)

# AC-5 positional tolerance (sp). 1pt = 65536 sp.
_TOL_H_SP = round(0.1 * 65536) # ±0.1pt horizontal
_TOL_V_SP = round(0.5 * 65536) # ±0.5pt vertical

# AC-5: the body characters of `Hello World\bye` are byte-identical between
# the M2 fast-path and the plain.tex token-list `\plainoutput` path, and the
# folio "1" matches within the ±0.5pt vertical tolerance. The ~17.55pt
# folio v deviation was closed by ( cascade #1): the outer
# `\vbox{\makeheadline\pagebody\makefootline}` of `\plainoutput` now honours
# the live `\baselineskip=24pt` written by `\makefootline` when inserting
# interline glue between `\pagebody` and `\line{\the\footline}`.
_FOLIO_CHAR = ord("1")


def _run(tex: str, options: TeXOptions = _PLAIN) -> bytes:
 device = DviDevice()
 with warnings.catch_warnings():
 warnings.simplefilter("ignore", OverfullBoxWarning)
 TeXJob(StringInputSource(tex), device, options=options).run()
 out = device.get_bytes()
 assert out is not None
 return out


def _md5(payload: bytes) -> str:
 return hashlib.md5(payload).hexdigest()


def _page_text(dvi: bytes) -> list[str]:
 return [
 "".join(chr(c) for c in page if 32 <= c < 127)
 for page in collect_chars_per_page(dvi)
 ]


def test_plainoutput_byte_stable_vs_m2_fast_path() -> None:
 r"""AC-5: `Hello World\bye` matches M2 fast-path within ±0.5pt V / ±0.1pt H.

 Compares per-character (h, v) coordinates between the M2 fast-path
 (`PlainOutputRoutine`) and the plain.tex token-list `\plainoutput`
 path. After ( cascade #1) all eleven characters
 (`Hello World` + folio `1`) land within the AC-5 tolerance: the body
 line is byte-equivalent and the folio v matches within the ±0.5pt
 vertical tolerance.
 """
 fast = _run(r"Hello World\bye", options=_FAST)
 plain = _run(r"Hello World\bye")

 fast_chars = walk_chars_with_positions(fast)
 plain_chars = walk_chars_with_positions(plain)

 assert len(fast_chars) == len(plain_chars) == 1, "expected one page"
 assert len(fast_chars[0]) == len(plain_chars[0]) == 11, "Hello World + folio"

 assert [c for c, _, _ in fast_chars[0]] == [c for c, _, _ in plain_chars[0]]

 for (c, hf, vf), (_, hp, vp) in zip(fast_chars[0], plain_chars[0], strict=True):
 assert abs(hf - hp) <= _TOL_H_SP, f"{chr(c)!r} dh={hf - hp}sp"
 assert abs(vf - vp) <= _TOL_V_SP, f"{chr(c)!r} dv={vf - vp}sp"


@pytest.mark.parametrize(
 ("name", "tex", "expected_md5"),
 [
 # MD5s re-anchored by ( cascade #1) — the outer
 # `\vbox{\makeheadline\pagebody\makefootline}` of `\plainoutput`
 # now inserts live-\baselineskip interline glue between
 # `\pagebody` and `\line{\the\footline}`, so every plain.tex
 # token-list page drifts by ~17.55pt for the folio.
 #
 # Re-anchored again by / : the page box now reads
 # \hsize LIVE from config.hsize instead of the hardcoded _HSIZE
 # constant, so the page-box width is the value plain.tex's own
 # `\hsize=6.5in` resolves to (30785859 sp) rather than the constant
 # 30785886 sp — a single 4-byte page-box width opcode changed (the
 # only diff; same length, same glyph stream). The `marks_page_break`
 # MD5 below is unchanged (its \eject path already matched).
 ("hello_plainoutput", r"Hello World\bye", "4ef7a723a712f22d88f652ff1ff9e79c"),
 (
 "headline",
 r"\headline={\bf TEST HEADER}Hello\bye",
 "44cdff1339f42fb7aa95082205846786",
 ),
 ("nopagenumbers", r"\nopagenumbers Hello\bye", "c2d4ae162bfdba44742410a6c90475de"),
 (
 "footline",
 r"\footline={\hfil PAGE \folio\hfil}Hello\bye",
 "0ffa62938ab3f7c4aab72beec9769a14",
 ),
 (
 "marks_page_break",
 r"\mark{first}\eject\mark{second}\bye",
 "241d4c0ab8ff6fc59f4c1c25d0831c49",
 ),
 ],
)
def test_plainoutput_dvi_md5_self_stability(name: str, tex: str, expected_md5: str) -> None:
 """Self-MD5 pin for the plain-output path — guards against silent drift.

 Companion to AC-5; complements `test_plainoutput_byte_stable_vs_m2_fast_path`.
 Touch when the plain-output bytes change intentionally; pair with a
 note in the commit explaining why.
 """
 assert _md5(_run(tex)) == expected_md5, name


def test_headline_user_override() -> None:
 """AC-7: `\\headline={\\bf TEST HEADER}` emits header in page 1."""
 assert _page_text(_run(r"\headline={\bf TEST HEADER}Hello\bye")) == [
 "TESTHEADERHello1"
 ]


def test_nopagenumbers() -> None:
 """AC-8: `\\nopagenumbers` (plain.tex 1152) suppresses folio."""
 assert _page_text(_run(r"\nopagenumbers Hello\bye")) == ["Hello"]


def test_footline_user_override() -> None:
 """AC-7 companion: `\\footline={\\hfil PAGE \\folio\\hfil}` reaches output."""
 assert _page_text(_run(r"\footline={\hfil PAGE \folio\hfil}Hello\bye")) == [
 "HelloPAGE1"
 ]


def test_marks_visible_in_output() -> None:
 """AC-12: `\\firstmark`/`\\botmark`/`\\topmark` populated in `\\output` body."""
 dvi = _run(
 r"\output={\shipout\vbox{\hbox{[\firstmark/\botmark/\topmark]}\box255}}"
 r"\mark{alpha}A\eject\mark{beta}B\eject"
 )

 assert _page_text(dvi) == ["[alpha/alpha/]A", "[beta/beta/alpha]B"]
