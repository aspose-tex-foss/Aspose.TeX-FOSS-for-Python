""" plain.tex footnote integration fixtures."""
from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from aspose_tex._engine.box_primitives import OverfullBoxWarning
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._input.reader import FileInputSource, StringInputSource
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions
from tests._verification.dvi_walker import (
    collect_chars_per_page,
    walk_chars_with_positions,
    walk_rules,
)
from tests._verification.position_compare import TOL_H_SP, compare_glyph_positions
from tests.test_plain_tie import _tfm_width

_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "testdata" / "fixtures" / "footnote"
_PLAIN = TeXOptions(load_format="plain")

_FOOTNOTERULE_HEIGHT_SP = 26214  # plain.tex `\footnoterule` = 0.4pt
_TOL_1PT_SP = 65536  # AC #3 vertical tolerance for body/note text vs MiKTeX
_V_UNCHECKED_SP = 0x3FFFFFFF  # MAX_DIMEN — disables the helper's v-axis (see below)

# Folio v-position vs MiKTeX is now within ±0.5pt ( closed
# cascade #1 — `\makefootline`'s `\baselineskip=24pt` is
# honoured by the outer `\plainoutput` vbox interline-glue path).
# Footnote note text h-position now matches MiKTeX within ±0.1pt
# ( closed cascade #3 — `\indent`/`\noindent` in the
# vbox scanner now bootstrap a paragraph with a `\parindent`-wide
# indent kern, so `\textindent{#1}\footstrut Note.` lands as a
# single hlist line at h=`\parindent`=20pt instead of three
# separate vlist items at h=0).
# Footnote separator rule v-position also lands within ±1pt as a
# side effect of the cascade #3 fix (the insert vbox is no longer
# inflated by interline glue between the three former vlist items,
# so the page-vbox FILL glue redistributes vertically to match
# MiKTeX).  The previously deferred cascade #2 deviation
# (~16pt-above-MiKTeX) is therefore also resolved in this commit.


def _run_fixture(name: str) -> bytes:
    device = DviDevice()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", OverfullBoxWarning)
        TeXJob(FileInputSource(_FIXTURE_DIR / f"{name}.tex"), device, options=_PLAIN).run()
    out = device.get_bytes()
    assert out is not None
    return out


def _page_text(dvi: bytes) -> list[str]:
    return [
        "".join(chr(c) for c in page if 32 <= c < 127)
        for page in collect_chars_per_page(dvi)
    ]


@pytest.mark.parametrize("name", ["footnote_basic", "footnote_with_separator"])
def test_footnote_basic_renders_separator_and_note(name: str) -> None:
    """AC #3 + AC-6: body, 0.4pt rule, and note text appear in correct order.

    Asserts:
      * Same character set as MiKTeX baseline (chars-only equivalence).
      * Body text v matches MiKTeX exactly.
      * `\\footnoterule` height = 26214 sp (0.4pt) and width matches
        MiKTeX within 1 sp (rounding noise).
      * Note text v matches MiKTeX within ±1pt (AC #3 tolerance).
      * Note text h matches MiKTeX within ±0.1pt ( AC-6,
        closed by cascade #3).
      * Note text appears below the separator rule.
      * Separator rule appears below body text.
    """
    ours = _run_fixture(name)
    miktex = (_FIXTURE_DIR / f"{name}.miktex.dvi").read_bytes()

    # Chars-only equivalence with MiKTeX baseline.
    assert _page_text(ours) == _page_text(miktex)

    our_chars = walk_chars_with_positions(ours)[0]
    miktex_chars = walk_chars_with_positions(miktex)[0]
    our_rules = walk_rules(ours)[0]
    miktex_rules = walk_rules(miktex)[0]

    assert our_rules, "footnote separator rule missing"
    _rule_h, rule_v, rule_height, rule_width = our_rules[0]
    assert rule_height == _FOOTNOTERULE_HEIGHT_SP, (
        f"separator rule height {rule_height} sp != plain.tex 26214 sp (0.4pt)"
    )
    miktex_rule = miktex_rules[0]
    assert abs(rule_width - miktex_rule[3]) <= 1, (
        f"separator rule width {rule_width} sp differs from MiKTeX "
        f"{miktex_rule[3]} sp by more than rounding noise"
    )
    # AC-6 / AC-1: separator-rule v-position matches
    # MiKTeX baseline within ±1pt.  Empirically closed by
    # ( cascade #3 side effect: rule_v dv collapsed from
    # -1_507_305 sp / -23pt to +23 sp / <0.001pt on both fixtures).
    assert abs(rule_v - miktex_rule[1]) <= _TOL_1PT_SP, (
        f"separator rule baseline dv={rule_v - miktex_rule[1]} sp exceeds ±1pt"
    )

    body_v_ours = our_chars[0][2]
    body_v_miktex = miktex_chars[0][2]
    assert body_v_ours == body_v_miktex, (
        f"body baseline v={body_v_ours} sp differs from MiKTeX {body_v_miktex} sp"
    )

    # Note text v matches MiKTeX within ±1pt.  Below the rule the page
    # holds three v-clusters: the footnote mark `*`, the note body text
    # (multi-character), and the folio (single digit). Pick the cluster
    # with the most chars — that's the note body baseline in both paths.
    def _note_body_v(chars: list[tuple[int, int, int]], rule_v_local: int) -> int:
        from collections import Counter

        below_rule = [v for _, _, v in chars if v > rule_v_local]
        counts = Counter(below_rule)
        return counts.most_common(1)[0][0]

    note_v_ours = _note_body_v(our_chars, rule_v)
    note_v_miktex = _note_body_v(miktex_chars, miktex_rule[1])
    assert abs(note_v_ours - note_v_miktex) <= _TOL_1PT_SP, (
        f"note baseline dv={note_v_ours - note_v_miktex} sp exceeds ±1pt"
    )

    # AC-6: per-char h-position of every footnote-text char
    # (footnote mark `*` + note body) must match MiKTeX within ±0.1pt
    # ( cascade #3).  Without the fix, the note text
    # appears at h=0 instead of h=`\parindent` (=20pt).
    our_below = [(ch, h, v) for ch, h, v in our_chars if v > rule_v]
    miktex_below = [(ch, h, v) for ch, h, v in miktex_chars if v > miktex_rule[1]]
    # Only the h-axis is asserted here: the note baseline's v is checked above
    # against the looser ±1pt cluster tolerance, and the footnote mark `*` sits
    # on a different baseline than the note body, so a per-glyph v comparison
    # would assert something this test never asserted. `_V_UNCHECKED_SP`
    # neutralizes the helper's v-axis rather than changing what is compared.
    diagnostics = compare_glyph_positions(
        [our_below], [miktex_below], h_tol_sp=TOL_H_SP, v_tol_sp=_V_UNCHECKED_SP
    )
    assert not diagnostics, "footnote-text h-deviation vs MiKTeX:\n" + "\n".join(
        diagnostics
    )

    # Ordering: body line < separator rule < note text.
    assert rule_v > body_v_ours, "separator rule must sit below body text"
    assert note_v_ours > rule_v, "note text must sit below separator rule"


def test_footnote_footins_box_voided_after_shipout() -> None:
    """AC #4: `\\box\\footins` is void after `\\bye` ships the page."""
    interp = TeXInterpreter(load_format="plain")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", OverfullBoxWarning)
        interp.run_with_device(
            FileInputSource(_FIXTURE_DIR / "footnote_basic.tex"),
            DviDevice(),
        )

    footins = interp._register_set.resolve_constant("footins")
    assert footins == ("chardef", 254)
    assert interp._box_regs.copybox(254) is None


@pytest.mark.parametrize(
    ("note", "note_v", "page_v"),
    [
        (
            r"$\cases{1&a\cr 2&b\cr}$",
            41974520,
            [655360, 41247064, 41628635, 41974520, 42415067, 43725786],
        ),
        (
            r"$\vcenter{\hbox{a}\hbox{b}}$",
            42044604,
            [655360, 41628632, 42044604, 42415064, 43725786],
        ),
        (r"$(a)$", 42152920, [655360, 42152920, 43725786]),
    ],
    ids=["cases", "vcenter", "control"],
)
def test_footnote_line_depth_raises_its_baseline(
    note: str, note_v: int, page_v: list[int]
) -> None:
    r""": a deep footnote line sits higher, by MiKTeX 24.4's exact v.

    The insertion counts the depth of the note's line, so a `\cases` or
    `\vcenter` in it moves the baseline up; `$(a)$` is the plain control.
    """
    source = rf"\hsize=5in \noindent x\footnote*{{A note with {note}.}}\bye" + "\n"
    device = DviDevice()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", OverfullBoxWarning)
        TeXJob(StringInputSource(source), device, options=_PLAIN).run()
    dvi = device.get_bytes()
    assert dvi is not None

    (page,) = walk_chars_with_positions(dvi, _tfm_width())
    assert [v for code, _, v in page if code == ord("A")] == [note_v]
    assert sorted({v for _, _, v in page}) == page_v
