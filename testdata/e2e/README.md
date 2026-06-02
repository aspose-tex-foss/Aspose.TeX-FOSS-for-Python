# — Automated E2E DVI baseline suite

Canonical plain-TeX fixtures compiled through the **public** API
(`TeXJob(source, DviDevice()).run()`) and compared **semantically** against
MiKTeX-generated `.dvi` references in [`testdata/baselines/`](../baselines/).

Driver: [`tests/test_e2e_dvi_baseline.py`](../../tests/test_e2e_dvi_baseline.py).
Runs on **every** `pytest` invocation; no external tools required at test time.

## Fixtures

| Fixture | Pins |
|---------|------|
| `hello.tex` | Minimal single-line shipout; one page; `cmr10` glyph stream. |
| `paragraph.tex` | Line-breaker + baselineskip interline + parskip; multi-line wrap, single page (default `\hsize=6.5in`). |
| `paragraph_narrow.tex` | Width-sensitive line breaking at `\hsize=3in` — same body as `paragraph.tex`, pins that breaks track the column width. |
| `multipage.tex` | Page-builder natural break decisions (≥2 pages, no `\eject`) + per-page folio. |
| `rules.tex` | `\hrule` rule-first **and** mid-body arms ( v6.1 §679 sentinel path). |
| `footnotes.tex` | `\footnote*{…}` → `\insert\footins` + `\footnoterule` separator. |

`hello` / `paragraph` / `multipage` / `rules` are the four AC-1 required
fixtures; `footnotes` is the optional fifth (high-value `\insert` regression pin);
`paragraph_narrow` was added by once the line-breaker honoured `\hsize`.

## What the suite compares (AC-4 — semantic, not byte-exact)

Built on [`tests/_verification/dvi_walker.py`](../../tests/_verification/dvi_walker.py)
(`collect_chars_per_page`, `walk_line_starts`, `walk_rules`) plus a POST
`page_count` read — the same harness the v6.1 integration tests use.

- **Page count** — exact (DVI POST `page_count`, cross-checked against BOP count).
- **Glyph stream** — exact, per page (`collect_chars_per_page`).
- **Line baselines** — first-char `v` per line, compared with explicit
 tolerance (±0.5 pt = 32768 sp, AC-5), where line counts match.
- **Rule placement** — `(h, v, height, width)` per rule, with `v` tolerance
 ±0.5 pt and exact height/width, where rule counts match.

Byte-for-byte comparison is intentionally **out of scope** — the 5-MD5 
byte-stability fixture (`tests/test_named_param_migration_byte_stability.py`)
owns byte stability; owns semantic regression coverage. See also
[[project-svg-md5-byte-stability]] for the orthogonal SVG MD5 gate.

## Known engine-vs-MiKTeX divergences (characterized, with follow-ups)

The suite surfaced three real defects. Each was filed as a follow-up and the
suite **pins** the behaviour (so a change re-trips the test) rather than hiding
the gap. **, and are now all RESOLVED**:

| Symptom | Follow-up | How the suite handles it |
|---------|-----------|--------------------------|
| Line-breaker ignored `\hsize`: same breaks at any column width. | ** — RESOLVED** | The line-breaker now reads `\hsize` live and the page box tracks it. `paragraph.tex` stays at 6.5in; `paragraph_narrow.tex` (3in) pins the width-sensitive break path against a regenerated MiKTeX baseline (byte-identical glyph stream + baselines). |
| Continuation-page (page 2+) first baseline offset ~+3.11 pt (topskip). | ** — RESOLVED** | The missing TeXbook §1000 leading-discardables sweep at page recommencement let the interline glue between the shipped page's last box and the next page's first box leak atop the topskip. With the sweep in place, `multipage.tex` page 2+ baselines match MiKTeX at the tight ±0.5 pt bound (the former widened tolerance was removed); `TestMultipagePageOneStrict` keeps a page-1 regression pin. |
| `\footnote*{…}` emits a spurious zero-width 12 pt strut rule MiKTeX omits. | ** — RESOLVED** | The footnote `\strut` (`\vrule width\z@`) built a correct zero-width `RuleNode`, but the shipout writers emitted a `set_rule` for *every* rule. Per TeX: The Program §622/§634 a rule ships only when both its total height and width are positive; the writers now apply that painting guard, so the strut advances the reference point but emits no rule. `footnotes.tex` now compares the full rule stream **unconditionally** — exactly the one real `\footnoterule` separator, matching MiKTeX. |
| Top-level `\hrule` shipped `set_rule`, shifting post-rule content right in Yap. | ** — RESOLVED** | A vertically placed `\hrule` was emitted with `set_rule` (DVI opcode 132), which paints the rule **and** advances the horizontal reference point by the rule width (~469.76 pt). Per TeX: The Program §624 (`vlist_out`) a vlist rule must ship `put_rule` (137), which paints without moving `h`. The stray h-advance pushed every paragraph after the `\hrule` off the right edge in Yap (the file still validated — each vlist line is `push…pop`-bracketed so coordinate trackers recover correct positions). `DviWriter._traverse_vlist` now emits `put_rule` with no h-advance; the hlist arm keeps `set_rule` (§622: an hlist rule *does* advance `h`). Distinct from (rule *width*); here the width was already correct and the *opcode* was wrong. Verified with MiKTeX `dvitype`: `smoke_m2_ours.dvi` now reports `putrule` on both pages, matching MiKTeX. |

**Running-dimension `\hrule` width encoding — RESOLVED (/ +
/):** previously, for a top-level full-`\hsize` `\hrule` our
`DviWriter` emitted the DVI *running-dimension* code (`-2^30`, TeX: The Program
§589) for the rule width instead of the resolved concrete width. That code is
*legal* DVI (§589) and dvitype-aware tools render it, but **Yap (MiKTeX's own
DVI viewer) does not resolve the running code** and failed to render the rule
plus the trailing page content (verified by human visual check of
`testdata/smoke_m2_ours.dvi`, 2026-05-29). **** made the
`DviWriter._traverse_vlist` rule arm resolve `RUNNING_DIMEN` against the
enclosing box width at shipout (mirroring the hlist arm + the already-correct
PDF/SVG paths). **/** then made the page-box width track the
document's `\hsize`, so for an `\hsize`-overriding fixture (`rules.tex` at 4in)
the resolved width is now MiKTeX's `18945146` sp (within sp-rounding slack), not
the leaked default. `test_visible_rules_match` therefore compares rule width
**unconditionally** — the former `_DVI_RUNNING_DIMEN` / `_LEAKED_DEFAULT_HSIZE_SP`
guard and constants were removed.

## Relationship to PDF/SVG visual verification (AC-8)

** ≠ .** They are complementary and intentionally separate:

| | (this suite) | visual verification |
|---|---|---|
| Output | DVI | PDF / SVG |
| When | every `pytest` run, automated | per-release manual smoke (/45/46/48 reports) |
| Method | semantic DVI compare vs committed MiKTeX baselines | human opens output in a viewer, enumerates visible diffs |
| Artifacts | `testdata/e2e/` + `testdata/baselines/` | `testdata/verification-reports/TEX-NNN/` screenshots |

 gives continuous, machine-checked DVI regression coverage; gives
periodic human-eye validation of the rendered PDF/SVG surface. Neither replaces
the other.

## Existing targeted DVI regressions (AC-5)

The pre-existing task-specific DVI/MiKTeX checks are left **in place and
separate**, by design:

- `tests/_verification/dvi_walker.py` — **reused** by this suite (shared walker).
- `testdata/fixtures//`, `testdata/fixtures//`, `/`, `/`
 and their tests in `tests/test_interpreter_integration.py` — **kept separate**:
 each pins a specific historical defect (vfil distribution, `\eject` semantics,
 rule-first baseline, the cascade) with bespoke tolerances tied to that
 defect's analysis. Folding them into the generic E2E suite would lose that
 defect-specific intent. is the durable *baseline* suite; those remain
 the *defect-regression* pins.

## Regenerating baselines

See [`testdata/baselines/README.md`](../baselines/README.md) and
`make e2e-baselines` (requires pdftex ≥ 4.19; not needed in CI).
