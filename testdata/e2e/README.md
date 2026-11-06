# — Automated E2E DVI baseline suite

Canonical plain-TeX fixtures compiled through the **public** API
(`TeXJob(source, DviDevice()).run()`) and compared **semantically** against
MiKTeX-generated `.dvi` references in [`testdata/baselines/`](../baselines/).

Driver: [`tests/test_e2e_dvi_baseline.py`](../../tests/test_e2e_dvi_baseline.py).
Runs on **every** `pytest` invocation; no external tools required at test time.

## The corpus is the M4 gate

Every `testdata/e2e/*.tex` is asserted: `_FIXTURES` must equal the set of
documents in this directory (`test_every_corpus_document_is_asserted`), so a
committed document can never sit here unchecked. Under the owner-approved M4
exit criterion ( criterion 1) every document must match its MiKTeX
baseline at the standard tolerances and the divergence ledger must be empty.

**Corpus extension is an owner decision.** Adding a document makes its
divergences M4-blocking, so documents are admitted only by the owner; agents
add regression pins, never corpus documents on their own authority. The
documents here fall into two classes:

- **Owner-admitted documents** — the two *independent* human-written
  documents and the six *owner idiom* documents below. They are kept
  verbatim and SHA-pinned (`test_admitted_documents_unchanged`); changing
  one is an owner decision.
- **Agent-authored regression pins** — every other fixture. They pin a
  delivered behaviour against MiKTeX, but an agent chose their content, so
  they cannot show that plain TeX works outside the agents' own blind spot.

### Admitted documents and provenance

| # | Document | Origin | Author | SHA-256 (line ends as hashed) |
|---|---|---|---|---|
| 1 | `sample-1.tex` | Aspose.TeX for .NET regression set, `testdata/Aspose.TeX/ObjectTeX/Regression/` in the aspose.tex.net repository (2020–21); byte copy of a reference probe | Aleksey Kolodyazhnyy | `2296e59d9200c6701c5b86ad686c487f7440de861aab2399e1a112c14a1063e7` (CRLF) |
| 2 | `tex-what-is-what.tex` | same set | Aleksey Kolodyazhnyy | `3f1ea6c5a7a254fe2eca064ac8345e273457e4d5e8c2065c679e4d447968338a` (CRLF) |
| 3 | `owner_raggedright.tex` | `\raggedright` idiom, owner session 2026-10-16 | project owner | `d7c14e84e4000ea9265ae528c9b6e549460352b9ac26fbad77d61b6f93d6a8ea` (LF) |
| 4 | `owner_narrower.tex` | `\narrower` idiom, same session | project owner | `59f02191722d8f884a06f5f5d215ce25845e3553e137d57d3e00f56d1e51ec74` (LF) |
| 5 | `owner_table.tex` | `\multispan` / `\noalign` table, same session | project owner | `dcc3335daec47348a793ea69b219f74f0700cc4c5c994296c1f8b3c4505e1dad` (LF) |
| 6 | `owner_dashes.tex` | `--` / `---` prose, same session | project owner | `f6ac39572de6e1c55a8a9700594b172fe00beb9c0d842e074eea4218add92798` (LF) |
| 7 | `owner_footnote.tex` | footnote at the end of a sentence, written from the repro on owner instruction | analyst | `71aecaf038623407846a4b82072eae6c85c909238a91293fbf40f5a0c1fdbc64` (LF) |
| 8 | `owner_hyphenation.tex` | automatic hyphenation at `\hsize=1.6in`, same session | project owner | `2292ea2f7e4f68999f4b0537301cad4fbc5a487de9b8870d39b245eb31b9fe7b` (LF) |

**Licence / permission.** Documents 1–2 are internal Aspose documents; the
project owner permitted publishing them in the open test data on
**2026-10-20** (`testdata/` is in the published set). Documents 3–8
were written for this project and are covered by its MIT licence.

**Line ends.** The repository checks text out under `* text=auto`, so the
bytes on disk depend on the platform. Each pin records the line-end form its
hash was taken in — documents 1–2 were hashed as their CRLF upstream files,
3–8 as LF files with a final newline — and the test rewrites the line ends
to that form before hashing (`_canonical_sha256`), so the check holds on any
checkout and still catches every content change.

## Fixtures

| Fixture | Pins |
|---------|------|
| `sample-1.tex` | **Independent** ( #1): unchanged human-authored Aspose .NET regression document; UTF-8 quotes the fonts lack (six missing-character warnings,), `---`, an overfull line carrying its `\overfullrule` marker; two pages. Passes every check. |
| `tex-what-is-what.tex` | **Independent** ( #2,): unchanged human-authored Aspose .NET regression document (2020–21); title footnote via `\centerline`, running footnote, two pages. |
| `owner_raggedright.tex` | **Owner idiom** ( #3): `\raggedright` at 4in, two paragraphs. |
| `owner_narrower.tex` | **Owner idiom** ( #4): `{\narrower …\par}` then a normal paragraph. |
| `owner_table.tex` | **Owner idiom** ( #5): `\halign` with `\multispan3`, `\noalign{\smallskip\hrule\smallskip}` and `\noalign{\medskip}`. |
| `owner_dashes.tex` | **Owner idiom** ( #6): en/em dashes in justified prose at 2.2in; MiKTeX hyphenates `chap-ters`, and so do we since. |
| `owner_footnote.tex` | **Owner idiom** ( #7): `\footnote*` at the end of a sentence, sentence space after the mark. |
| `owner_hyphenation.tex` | **Owner idiom** ( #8): long words at `\hsize=1.6in` — MiKTeX hyphenates four line ends, and so do we since. |
| `paragraph_raggedright.tex` | **Regression pin**,: an agent rewrite of owner document 3 (other text, `\hyphenchar\font=-1` switches hyphenation off) — live rightskip stretch and two-paragraph wrapping at 4in. Not an owner document. |
| `paragraph_narrower.tex` | **Regression pin**,: an agent rewrite of owner document 4 (other text, hyphenation off) — local left/right margins, indentation and group restoration. Not an owner document. |
| `hello.tex` | Minimal single-line shipout; one page; `cmr10` glyph stream. |
| `paragraph.tex` | Line-breaker + baselineskip interline + parskip; multi-line wrap, single page (default `\hsize=6.5in`). |
| `paragraph_narrow.tex` | Width-sensitive line breaking at `\hsize=3in` — same body as `paragraph.tex`, pins that breaks track the column width. |
| `multipage.tex` | Page-builder natural break decisions (≥2 pages, no `\eject`) + per-page folio. |
| `rules.tex` | `\hrule` rule-first **and** mid-body arms ( v6.1 §679 sentinel path). |
| `footnotes.tex` | `\footnote*{…}` → `\insert\footins` + `\footnoterule` separator. |
| `math_inline.tex` | inline math — Ord/Bin/Rel atom spacing + `\mathchardef` Greek. |
| `math_scripts.tex` | scripts / `\over` / short-radicand `\sqrt` / `\hat` / `\overline`. |
| `math_display.tex` | display centring + `\over` + `\eqno`. |
| `math_delimiters.tex` | `\left(...\over...\right)` rule-19 delimiter growth (cmex) + display `$$\sum_{i=1}^{n}$$` large-op size switch + limits. In `_FIXTURES` since ( FR-4); before that it was committed with a baseline but not asserted. |
| `alignment_text.tex` | text-mode `\halign` §807 inter-row interline glue. In `_FIXTURES`. |
| `alignment_matrix.tex` | inline math `\matrix` + `\pmatrix` grid. In `_FIXTURES` — byte-exact. |
| `alignment_eqalign.tex` | display `\eqalign` relation-column alignment + `\openup\jot`. In `_FIXTURES` — byte-exact ( short-skip). |
| `combined_math_in_cells.tex` | (a) — math inside `\halign` cells (`$#$` cells with Ord/Bin/Rel atoms + `\alpha\beta`),. In `_FIXTURES` — byte-exact. |
| `combined_document.tex` | FR-1 — comprehensive realistic doc (text + inline/display math + `\halign` + `$\matrix$`/`$\pmatrix$` + `$$\eqalign$$`), 2 pages at `\vsize=2.2in`,. **In `_FIXTURES`**: least-cost page breaking, §890 line penalties, display penalties, §1004 depth folding and the `\maxdepth` page box choose and set MiKTeX's pages; §866/§767/§1039 give its line breaks. |
| `combined_document_vsize_{2_0,2_5,3_0}.tex` | The same document at `\vsize` 2.0/2.5/3.0in (MiKTeX 2/2/1 pages) — pins the page-break choice at other goal heights. In `_FIXTURES`. |
| `paging_text.tex` | Text-only prose at `\vsize=1.0in` (MiKTeX 3 pages): breaks between the lines of a paragraph, club/widow penalties, least cost (; before it gave 587/0/374/161 glyphs). In `_FIXTURES`. |
| `page_state_footnote.tex` | A footnote, a display `\eqalign`, an `\halign` and prose at `\vsize=2.6in` (MiKTeX 3 pages): the insertion lowers the page goal instead of adding to the page total, and `\box255` is packed to that goal. In `_FIXTURES`. |
| `page_state_display_space.tex` | A page fires at a display's `\postdisplaypenalty` at `\vsize=1.15in` (MiKTeX 4 pages); the page is built only after the space after `$$` is scanned, so page 4 starts at h=0. In `_FIXTURES`. |
| `page_state_pageinsert.tex` | Plain `\pageinsert` after body text floats whole to page 2 (insertion splitting,). In `_FIXTURES`. |
| `page_state_eject_empty.tex` | `\eject\eject` ships no empty page: a penalty before the first box is discarded (MiKTeX 3 pages,). In `_FIXTURES`. |
| `combined_display_families.tex` | (b) — `\eqalign`/`\eqalignno`/`\displaylines`/`\cases` in sequence,. **In `_FIXTURES`** — the `\displ@y` offset, the `\displaylines` doubling and the `\cases` extent (, closed by the `\left\{` delimiter) are all resolved; every check passes at the unwidened bounds. |
| `combined_settabs_math.tex` | (c, optional) — `\settabs`/`\+` fields with inline math,. **In `_FIXTURES`** — glyph-position exact since; baseline and tolerances unchanged. |

`hello` / `paragraph` / `multipage` / `rules` are the four AC-1 required
fixtures; `footnotes` is the optional fifth (high-value `\insert` regression pin);
`paragraph_narrow` was added by once the line-breaker honoured `\hsize`.
The `math_*` fixtures pin the math-layout legs against MiKTeX.
The `alignment_*` fixtures pin the alignment legs. The `combined_*`
fixtures pin math + alignment **combined** in realistic
documents. All four are now in `_FIXTURES`: `combined_math_in_cells` from the
start, `combined_display_families`/`combined_settabs_math` since and
`combined_document` since — each after the cross-construct divergence it
surfaced (characterized below) was fixed.

No fixture is committed without being asserted: `math_delimiters` was the last
one held outside `_FIXTURES`, and FR-4 now forbids it. A document
that diverges from MiKTeX stays in `_FIXTURES` and is carried in the ledger
below. This is the FR-5 rule: **characterize, never hide, never widen a
tolerance to force a pass.**

## The divergence ledger (`_CORPUS_LEDGER`,)

One ledger, keyed by document and check, carries every known divergence of
a corpus document. An entry names the diverging checks — page count, glyph
stream, font metadata, line baselines, per-glyph positions, visible rules —
each with its measured symptom and owning task(s); or, in the **crash form**
(`Check.CRASH`, exclusive), that the document raises during compilation.

- A listed check is **skipped with its ledger text**
  (`<doc>: characterized divergence [<check>] — <symptom> (owner: TEX-…)`), so
  the divergence shows in every test report. Every check that is not listed
  is asserted at the standard tolerances. A crash-form entry skips all checks
  of its document.
- `TestCorpusLedger.test_ledger_is_live` fails when an entry stops describing
  a live divergence: a listed check now matches MiKTeX, a crash-form document
  now compiles, or the entry names a document outside `_FIXTURES`. Fixing an
  owning task therefore forces its entry out. Synthetic-ledger tests prove the
  guard catches each of these forms.
- The ledger replaced's `_MIDLINE_H_DIVERGENCE` and's
  `_V_TOPSKIP_DIVERGENCE`, both empty when they were retired. It is the one
  place criterion 1 reads.

The ledger is empty:'s hyphenation pass removed its last entries, the
`owner_dashes` and `owner_hyphenation` divergences, so all eight admitted
documents and every regression pin pass all checks ( criterion 1).

## What the suite compares (AC-4 — semantic, not byte-exact)

Built on [`tests/_verification/dvi_walker.py`](../../tests/_verification/dvi_walker.py)
(`collect_chars_per_page`, `walk_line_starts`, `walk_chars_with_positions`,
`walk_rules`) plus a POST `page_count` read — the same harness the v6.1
integration tests use — and
[`tests/_verification/position_compare.py`](../../tests/_verification/position_compare.py)
for the per-glyph comparison.

- **Page count** — exact (DVI POST `page_count`, cross-checked against BOP count).
- **Glyph stream** — exact, per page (`collect_chars_per_page`).
- **Per-glyph positions (mid-line horizontal advances)** — every glyph's
  `(h, v)`, at ±0.1 pt H / ±0.5 pt V, via
  `compare_glyph_positions` (****).
- **Line baselines** — first-char `v` per line, compared with explicit
  tolerance (±0.5 pt = 32768 sp, AC-5), where line counts match.
- **Rule placement** — `(h, v, height, width)` per rule, with `v` tolerance
  ±0.5 pt and exact height/width, where rule counts match.

### Mid-line horizontal advances are now covered

Before the suite compared the glyph-code *stream* and each line's
*start* position, but never where a glyph landed **within** a line. A dropped
interword space, a lost kern or a wrong alignment-template advance left both of
those signals untouched, so a fixture could be recorded as "byte-exact vs
MiKTeX" while its whole line tail was shifted. Any such claim in the task
history predating should be read as *"glyph stream + line starts +
rules match"*.

`test_midline_glyph_positions_match` closes that hole. Adding it turned **six
of thirteen** fixtures red at the time — four distinct real defects, all
previously invisible. Each was characterized below and skipped **with
attribution**, never tolerance-widened; the ledger guard failed as soon as a
listed fixture stopped diverging, so an entry could not outlive its defect.
**All** of those defects have since been fixed (see the Status column); the
table below is kept current as each one lands.

| Fixture | Δ vs MiKTeX | Cause | Owner | Status |
|---|---|---|---|---|
| `math_inline` | −3.333 pt after the 1st `$…$`, −6.666 pt after the 2nd | interword space dropped after inline math (per-occurrence, cumulative) | | **RESOLVED** |
| `math_scripts` | −3.333 pt | same — trailing `here.` after inline math | | **RESOLVED** |
| `alignment_matrix` | −3.333 pt | same — after `$\matrix{}$` (originally reported case) | | **RESOLVED** |
| `paragraph_narrow` | up to +0.432 pt | ~~justified-line glue-set rounding~~ — **cause disproved**; the real one is a missing TeX §1042 `shrink *= 1000/sf` on sentence spaces, which skewed the whole line's glue-set ratio | | **RESOLVED** |
| `alignment_text` | −10.000 pt | `\halign` template `u`-part (`\quad`) emitted *after* the cell's first token; row-1 `t`–`w` kern also lost. Symptom as reported, but the cause was **not** in the alignment scanner: `peek()` parks its token in the expander's one-slot `_peeked` cache, which `_next_raw` drains *before* `_stack`, so the u-template `push_tokens` arrived second | | **RESOLVED** |
| `alignment_eqalign` | +20.000 pt | paragraph resumed after `$$…$$` wrongly indented by `\parindent` (§1206 `resume_after_display`). The symptom was as reported, but it was only **half** the defect: §1206's trailing §1207 optional-space discard was also missing, leaving a further 3.333 pt interword space once the indent was removed | | **RESOLVED** |

**All 13 fixtures then asserted clean** and `_MIDLINE_H_DIVERGENCE` was empty.
It and `TestMidlineDivergenceLedger` were retired by: a future
per-glyph divergence is a `per-glyph positions` entry in `_CORPUS_LEDGER`.

's scope widened as a result: the dropped space is **not**
`\matrix`-specific — `math_inline` and `math_scripts` show it after ordinary
inline math too.

**Caution — a ledger rationale is a hypothesis, not a verified root cause.**
`paragraph_narrow` is the cautionary case: its entry confidently attributed the
drift to glue-set rounding accumulating across the line, and that attribution
survived unchallenged until measured it. The packer and writers were
already §625–§630-correct; the apparent accumulation was one identical per-node
error repeated at each space. The *magnitude* and the *verdict* recorded here
were accurate — only the mechanism was wrong. Re-derive the cause when you pick
an entry up; do not inherit it.

**Standing rule.** A surfaced divergence is *fixed* or *characterized with a
committed rationale and an owning follow-up*. It is never absorbed by widening
a tolerance, and never quietly dropped from a fixture list.

Byte-for-byte comparison is intentionally **out of scope** — the 5-MD5
byte-stability fixture (`tests/test_named_param_migration_byte_stability.py`)
owns byte stability; owns semantic regression coverage. See also
[[project-svg-md5-byte-stability]] for the orthogonal SVG MD5 gate.

## Known engine-vs-MiKTeX divergences (characterized, with follow-ups)

The suite surfaced three real defects. Each was filed as a follow-up and the
suite **pins** the behaviour (so a change re-trips the test) rather than hiding
the gap. ** and are now all RESOLVED**:

| Symptom | Follow-up | How the suite handles it |
|---------|-----------|--------------------------|
| Line-breaker ignored `\hsize`: same breaks at any column width. | ** — RESOLVED** | The line-breaker now reads `\hsize` live and the page box tracks it. `paragraph.tex` stays at 6.5in; `paragraph_narrow.tex` (3in) pins the width-sensitive break path against a regenerated MiKTeX baseline (byte-identical glyph stream + baselines). |
| Continuation-page (page 2+) first baseline offset ~+3.11 pt (topskip). | ** — RESOLVED** | The missing TeXbook §1000 leading-discardables sweep at page recommencement let the interline glue between the shipped page's last box and the next page's first box leak atop the topskip. With the sweep in place, `multipage.tex` page 2+ baselines match MiKTeX at the tight ±0.5 pt bound (the former widened tolerance was removed); `TestMultipagePageOneStrict` keeps a page-1 regression pin. |
| `\footnote*{…}` emits a spurious zero-width 12 pt strut rule MiKTeX omits. | ** — RESOLVED** | The footnote `\strut` (`\vrule width\z@`) built a correct zero-width `RuleNode`, but the shipout writers emitted a `set_rule` for *every* rule. Per TeX: The Program §622/§634 a rule ships only when both its total height and width are positive; the writers now apply that painting guard, so the strut advances the reference point but emits no rule. `footnotes.tex` now compares the full rule stream **unconditionally** — exactly the one real `\footnoterule` separator, matching MiKTeX. |
| Top-level `\hrule` shipped `set_rule`, shifting post-rule content right in Yap. | ** — RESOLVED** | A vertically placed `\hrule` was emitted with `set_rule` (DVI opcode 132), which paints the rule **and** advances the horizontal reference point by the rule width (~469.76 pt). Per TeX: The Program §624 (`vlist_out`) a vlist rule must ship `put_rule` (137), which paints without moving `h`. The stray h-advance pushed every paragraph after the `\hrule` off the right edge in Yap (the file still validated — each vlist line is `push…pop`-bracketed so coordinate trackers recover correct positions). `DviWriter._traverse_vlist` now emits `put_rule` with no h-advance; the hlist arm keeps `set_rule` (§622: an hlist rule *does* advance `h`). Distinct from (rule *width*); here the width was already correct and the *opcode* was wrong. Verified with MiKTeX `dvitype`: `smoke_m2_ours.dvi` now reports `putrule` on both pages, matching MiKTeX. |
| `\displ@y` display families (`\eqalignno`/`\leqalignno`/`\displaylines`) carried a uniform vertical offset. | **CLOSED by** | History: the original characterization here was wrong on both cause and scope and was corrected by measurement in — the `\everycr`/`\prevdepth` `\vskip` named in it was provably not at fault. **** fixed the horizontal (`\displaywidth` was never assigned; a −212.9 pt `\eqno` error) and the §1204 skip choice. **** closed the vertical, via three defects: the page builder read `\baselineskip` from a static snapshot, a display opened no §1145 group so `\openup\jot` accumulated (12→15→18 pt), and the pre-display line was contributed inside that group. With the `\cases` leg removed the document is **MiKTeX-exact to 0.000 pt on all 10 lines**. |
| `\displaylines` rows are placed at twice their correct horizontal offset. | **CLOSED by** | Found by the review with the glyph-level comparator; itself measured only line-start **v**, so it was invisible there. MiKTeX `dvitype` puts the first row glyph at `h = 215.556 pt`; ours was at **431.111 pt** — exactly double. **The original hypothesis here (the inner `\hbox to\displaywidth` centring applied twice) was refuted by measurement** in: `\displaylines` carries no `to` spec at all, so the row-level packing never runs for it. The real cause was ordering — math-mode `\hfil` was appended to the *enclosing* hlist, which the formula only joins at the `$`-close, so **both** of the template's centring `\hfil`s landed ahead of the formula and each took the full 215.556 pt glue set. TeX §1171 puts that glue in the math list instead. Rows are now MiKTeX-exact (215.556 / 220.820 pt) and the no-`\cases` document reports **0 diagnostics** at the unwidened bound. |
| `\leqalignno`'s equation-number column is one full `\displaywidth` too far left. | **RESOLVED by ( Component 2)** | The number column's cells are `\kern-\displaywidth\rlap{…}`, i.e. `-\displaywidth` wide; TeX §801 starts a column at `null_flag`, so the column keeps that negative width and the trailing `\tabskip\displaywidth` compensates it. Our column measurement started at 0 and dropped negative widths; it now starts at `null_flag`. |
| `\cases` display block is 1.848 pt short in both height and depth. | **RESOLVED (; recorded by)** | Bisected: the shortfall was the undersized `\left\{` delimiter (fixed by, `601d1505`), split symmetrically by §735 axis centring;'s `half()` rounding (`abbd3292`) removed the last 1 sp. `\eqalign`/`\matrix`/`\pmatrix` share `\vcenter` but were never affected. |
| `\settabs`/`\+` tab/row positioning. | **RESOLVED by ( optional FR-2(c))** | All 17 body glyph triples in `combined_settabs_math.tex` now match MiKTeX exactly: row V positions 655360/1441792/2228224 sp and second-field H 15392931 sp. repaired shared rows; repairs recorded stops and baselines through the live list owner. Baseline bytes and comparison tolerances are unchanged. The fixture is in `_FIXTURES` (admitted by). |
| Page-builder over-breaks a mixed math+alignment document under short `\vsize`. | ** — RESOLVED** | `combined_document.tex` is byte-exact vs MiKTeX at the natural `\vsize=8.9in` (25 lines, 1 page — the combined *layout* is perfect), but once `\vsize` is short enough to force ≥2 pages the break point + page count diverge (at 2.0 in both give 2 pages but ours keeps fewer lines on page 1; at 2.2 in ours=4 vs MiKTeX=2). The defect is break-point selection over display + `\halign` contributions (TeX §970–§1000), not construct layout. The cause was not math- or alignment-specific: the page builder broke greedily, never at the interline glue it inserted itself, had no §890/display penalties and kept contributing to a page already cut by a token-list `\output`; the document's line breaks also needed §866/§767/§1039 and its page box §1004 and `\maxdepth`. Now in `_FIXTURES` with three `\vsize` variants and `paging_text`. |

**Running-dimension `\hrule` width encoding — RESOLVED ( +
):** previously, for a top-level full-`\hsize` `\hrule` our
`DviWriter` emitted the DVI *running-dimension* code (`-2^30`, TeX: The Program
§589) for the rule width instead of the resolved concrete width. That code is
*legal* DVI (§589) and dvitype-aware tools render it, but **Yap (MiKTeX's own
DVI viewer) does not resolve the running code** and failed to render the rule
plus the trailing page content (verified by human visual check of
`testdata/smoke_m2_ours.dvi`, 2026-05-29). **** made the
`DviWriter._traverse_vlist` rule arm resolve `RUNNING_DIMEN` against the
enclosing box width at shipout (mirroring the hlist arm + the already-correct
PDF/SVG paths). **** then made the page-box width track the
document's `\hsize`, so for an `\hsize`-overriding fixture (`rules.tex` at 4in)
the resolved width is now MiKTeX's `18945146` sp (within sp-rounding slack), not
the leaked default. `test_visible_rules_match` therefore compares rule width
**unconditionally** — the former `_DVI_RUNNING_DIMEN` / `_LEAKED_DEFAULT_HSIZE_SP`
guard and constants were removed.

## Relationship to PDF/SVG visual verification (AC-8)

** ≠.** They are complementary and intentionally separate:

| | (this suite) | visual verification |
|---|---|---|
| Output | DVI | PDF / SVG |
| When | every `pytest` run, automated | per-release manual smoke ( reports) |
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
