# End-to-end DVI baseline suite

Plain-TeX documents compiled through the **public** API
(`TeXJob(source, DviDevice()).run()`) and compared **semantically** against
MiKTeX-generated `.dvi` references in [`testdata/baselines/`](../baselines/).

Driver: [`tests/test_e2e_dvi_baseline.py`](../../tests/test_e2e_dvi_baseline.py).
It runs on **every** `pytest` invocation; no external tools are needed at test
time. The history of the suite and of the defects it found is kept with the
project's development records, not here.

## The corpus

Every `testdata/e2e/*.tex` is asserted: `_FIXTURES` must equal the set of
documents in this directory (`test_every_corpus_document_is_asserted`), so a
committed document can never sit here unchecked. Every document must match its
MiKTeX baseline at the standard tolerances, and the divergence ledger must be
empty.

The documents fall into two classes:

- **Admitted documents**: two *independent* human-written documents and six
  *idiom* documents written by the project owner. They are kept verbatim and
  SHA-pinned (`test_admitted_documents_unchanged`).
- **Regression pins**: every other fixture. Each pins a delivered behaviour
  against MiKTeX, but its content was chosen by the developers of the engine,
  so on its own it cannot show that plain TeX works on documents written by
  someone else. That is what the admitted documents are for.

### Admitted documents and provenance

| # | Document | Origin | Author | SHA-256 (line ends as hashed) |
|---|---|---|---|---|
| 1 | `sample-1.tex` | Aspose.TeX for .NET regression set, `testdata/Aspose.TeX/ObjectTeX/Regression/` in the aspose.tex.net repository (2020–21); byte copy of `testdata/reference/input_bytes/sample-1.tex` | Aleksey Kolodyazhnyy | `2296e59d9200c6701c5b86ad686c487f7440de861aab2399e1a112c14a1063e7` (CRLF) |
| 2 | `tex-what-is-what.tex` | same set | Aleksey Kolodyazhnyy | `3f1ea6c5a7a254fe2eca064ac8345e273457e4d5e8c2065c679e4d447968338a` (CRLF) |
| 3 | `owner_raggedright.tex` | `\raggedright` idiom, written 2026-10-16 | project owner | `d7c14e84e4000ea9265ae528c9b6e549460352b9ac26fbad77d61b6f93d6a8ea` (LF) |
| 4 | `owner_narrower.tex` | `\narrower` idiom, same day | project owner | `59f02191722d8f884a06f5f5d215ce25845e3553e137d57d3e00f56d1e51ec74` (LF) |
| 5 | `owner_table.tex` | `\multispan` / `\noalign` table, same day | project owner | `dcc3335daec47348a793ea69b219f74f0700cc4c5c994296c1f8b3c4505e1dad` (LF) |
| 6 | `owner_dashes.tex` | `--` / `---` prose, same day | project owner | `f6ac39572de6e1c55a8a9700594b172fe00beb9c0d842e074eea4218add92798` (LF) |
| 7 | `owner_footnote.tex` | footnote at the end of a sentence, written to reproduce a reported defect at the project owner's request | project team | `71aecaf038623407846a4b82072eae6c85c909238a91293fbf40f5a0c1fdbc64` (LF) |
| 8 | `owner_hyphenation.tex` | automatic hyphenation at `\hsize=1.6in`, same day | project owner | `2292ea2f7e4f68999f4b0537301cad4fbc5a487de9b8870d39b245eb31b9fe7b` (LF) |

The `owner_` prefix names the author of documents 3–8; it is part of the
pinned file names.

**Licence / permission.** Documents 1–2 are internal Aspose documents; the
project owner permitted publishing them in the open test data on
**2026-10-20**. Documents 3–8 were written for this project and are covered by
its MIT licence.

**Line ends.** The repository checks text out under `* text=auto`, so the
bytes on disk depend on the platform. Each pin records the line-end form its
hash was taken in (documents 1–2 were hashed as their CRLF upstream files,
3–8 as LF files with a final newline), and the test rewrites the line ends to
that form before hashing (`_canonical_sha256`), so the check holds on any
checkout and still catches every content change.

## Fixtures

| Fixture | Pins |
|---------|------|
| `sample-1.tex` | **Independent** (#1): unchanged human-authored regression document; UTF-8 quotes the fonts lack (six missing-character warnings), `---`, an overfull line carrying its `\overfullrule` marker; two pages. |
| `tex-what-is-what.tex` | **Independent** (#2): unchanged human-authored regression document; title footnote via `\centerline`, running footnote, two pages. |
| `owner_raggedright.tex` | **Idiom** (#3): `\raggedright` at 4in, two paragraphs. |
| `owner_narrower.tex` | **Idiom** (#4): `{\narrower …\par}` then a normal paragraph. |
| `owner_table.tex` | **Idiom** (#5): `\halign` with `\multispan3`, `\noalign{\smallskip\hrule\smallskip}` and `\noalign{\medskip}`. |
| `owner_dashes.tex` | **Idiom** (#6): en/em dashes in justified prose at 2.2in; MiKTeX hyphenates `chap-ters`, and so does the engine. |
| `owner_footnote.tex` | **Idiom** (#7): `\footnote*` at the end of a sentence, sentence space after the mark. |
| `owner_hyphenation.tex` | **Idiom** (#8): long words at `\hsize=1.6in`; MiKTeX hyphenates four line ends, and so does the engine. |
| `paragraph_raggedright.tex` | **Regression pin**: a rewrite of document 3 with other text and `\hyphenchar\font=-1` (hyphenation off): live rightskip stretch and two-paragraph wrapping at 4in. |
| `paragraph_narrower.tex` | **Regression pin**: a rewrite of document 4 with other text and hyphenation off: local left/right margins, indentation and group restoration. |
| `hello.tex` | Minimal single-line shipout; one page; `cmr10` glyph stream. |
| `paragraph.tex` | Line breaking, `\baselineskip` interline glue and `\parskip`; multi-line wrap on one page (default `\hsize=6.5in`). |
| `paragraph_narrow.tex` | The `paragraph.tex` body at `\hsize=3in`: line breaks track the column width. |
| `multipage.tex` | Natural page breaks (two or more pages, no `\eject`) and the folio on each page. |
| `rules.tex` | `\hrule` first on the page **and** in mid-body. |
| `footnotes.tex` | `\footnote*{…}` → `\insert\footins` with the `\footnoterule` separator. |
| `math_inline.tex` | Inline math: Ord/Bin/Rel atom spacing and `\mathchardef` Greek. |
| `math_scripts.tex` | Scripts, `\over`, a short-radicand `\sqrt`, `\hat`, `\overline`. |
| `math_display.tex` | Display centring, `\over` and `\eqno`. |
| `math_delimiters.tex` | `\left(...\over...\right)` delimiter growth (cmex), and the size switch and limits of a display `$$\sum_{i=1}^{n}$$`. |
| `alignment_text.tex` | Text-mode `\halign` with the §807 interline glue between rows. |
| `alignment_matrix.tex` | Inline math `\matrix` and `\pmatrix` grids. |
| `alignment_eqalign.tex` | Display `\eqalign` relation-column alignment and `\openup\jot`. |
| `combined_math_in_cells.tex` | Math inside `\halign` cells (`$#$` cells with Ord/Bin/Rel atoms and `\alpha\beta`). |
| `combined_document.tex` | A realistic document (text, inline and display math, `\halign`, `$\matrix$`/`$\pmatrix$`, `$$\eqalign$$`) on two pages at `\vsize=2.2in`: least-cost page breaking, §890 line penalties, display penalties, §1004 depth folding and the `\maxdepth` page box choose MiKTeX's pages; §866/§767/§1039 give its line breaks. |
| `combined_document_vsize_{2_0,2_5,3_0}.tex` | The same document at `\vsize` 2.0/2.5/3.0in (MiKTeX gives 2/2/1 pages): the page-break choice at other goal heights. |
| `paging_text.tex` | Text-only prose at `\vsize=1.0in` (MiKTeX gives 3 pages): breaks between the lines of a paragraph, club and widow penalties, least cost. |
| `page_state_footnote.tex` | A footnote, a display `\eqalign`, an `\halign` and prose at `\vsize=2.6in` (3 pages): the insertion lowers the page goal instead of adding to the page total, and `\box255` is packed to that goal. |
| `page_state_display_space.tex` | A page fires at a display's `\postdisplaypenalty` at `\vsize=1.15in` (4 pages); the page is built only after the space after `$$` is scanned, so page 4 starts at h=0. |
| `page_state_pageinsert.tex` | A plain `\pageinsert` after body text floats whole to page 2. |
| `page_state_eject_empty.tex` | `\eject\eject` ships no empty page: a penalty before the first box is discarded (3 pages). |
| `combined_display_families.tex` | `\eqalign`/`\eqalignno`/`\displaylines`/`\cases` in sequence. |
| `combined_settabs_math.tex` | `\settabs`/`\+` fields with inline math. |
| `text_accent_geometry.tex`, `text_accent_assignments.tex` | Text accents: page-top and subsequent-line accents, tall and narrow bases, mixed fonts, unboxed copies, and assignments scanned inside the accent. |

A document that diverges from MiKTeX stays in `_FIXTURES` and is carried in
the ledger below: **characterize, never hide, never widen a tolerance to force
a pass.**

## The divergence ledger (`_CORPUS_LEDGER`)

One ledger, keyed by document and check, carries every known divergence of
a corpus document. An entry names the diverging checks (page count, glyph
stream, font metadata, line baselines, per-glyph positions, visible rules),
each with its measured symptom and the issue that tracks it; or, in the
**crash form** (`Check.CRASH`, exclusive), that the document raises during
compilation.

- A listed check is **skipped with its ledger text**, so the divergence shows
  in every test report. Every check that is not listed is asserted at the
  standard tolerances. A crash-form entry skips all checks of its document.
- `TestCorpusLedger.test_ledger_is_live` fails when an entry stops describing
  a live divergence: a listed check now matches MiKTeX, a crash-form document
  now compiles, or the entry names a document outside `_FIXTURES`. A fix
  therefore forces its entry out. Synthetic-ledger tests prove the guard
  catches each of these forms.

The ledger is empty: every document passes all checks.

A ledger rationale is a hypothesis, not a verified root cause. Re-derive the
cause by measurement when you pick an entry up; do not inherit it.

## What the suite compares (semantic, not byte-exact)

Built on [`tests/_verification/dvi_walker.py`](../../tests/_verification/dvi_walker.py)
(`collect_chars_per_page`, `walk_line_starts`, `walk_chars_with_positions`,
`walk_rules`) plus a POST `page_count` read, and
[`tests/_verification/position_compare.py`](../../tests/_verification/position_compare.py)
for the per-glyph comparison.

- **Page count**: exact (DVI POST `page_count`, cross-checked against the BOP count).
- **Glyph stream**: exact, per page (`collect_chars_per_page`).
- **Per-glyph positions**: every glyph's `(h, v)`, at ±0.1 pt H / ±0.5 pt V,
  via `compare_glyph_positions`. Without this check a dropped interword space
  or a lost kern would leave the glyph stream and the line starts unchanged.
- **Line baselines**: first-char `v` per line, at ±0.5 pt (32768 sp), where
  line counts match.
- **Rule placement**: `(h, v, height, width)` per rule, with `v` at ±0.5 pt
  and exact height and width, where rule counts match.

Byte-for-byte comparison is intentionally **out of scope**: byte stability is
owned by `tests/test_named_param_migration_byte_stability.py`.

The suite checks DVI only. PDF and SVG output is checked by eye before a
release, in a viewer, against the MiKTeX rendering; those screenshots are kept
outside this repository.

## Other DVI regressions

`testdata/fixtures/` holds the fixtures of older, defect-specific DVI checks in
`tests/test_interpreter_integration.py` (`\vfil` distribution, `\eject`
semantics, rule-first baselines). Each has tolerances tied to the analysis of
its defect, so they stay separate from this suite.

## Regenerating baselines

See [`testdata/baselines/README.md`](../baselines/README.md) (requires pdftex
≥ 4.19; not needed to run the tests).
