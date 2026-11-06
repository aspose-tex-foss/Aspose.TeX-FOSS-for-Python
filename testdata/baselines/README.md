# E2E DVI baselines

MiKTeX-generated reference `.dvi` files for the canonical fixtures under
[`testdata/e2e/`](../e2e/). The pytest E2E suite
[`tests/test_e2e_dvi_baseline.py`](../../tests/test_e2e_dvi_baseline.py)
compiles each `testdata/e2e/<fixture>.tex` with **our** engine and compares
the result against the matching `<fixture>.miktex.dvi` here, **semantically**
(page count, glyph stream, line/rule positions) — never byte-for-byte.

## Files

| Baseline | Source fixture |
|----------|----------------|
| `sample-1.miktex.dvi` | Unchanged `testdata/e2e/sample-1.tex` ( independent document,); two pages. SHA-256 `25d44d5b1f4376fff1b2e847a88da304841d0eb83d45c7eca19f3c332b143eb1` |
| `owner_{raggedright,narrower,table,dashes,footnote,hyphenation}.miktex.dvi` | `testdata/e2e/owner_*.tex` ( owner idiom documents,) |
| `tex-what-is-what.miktex.dvi` | Unchanged `testdata/e2e/tex-what-is-what.tex`; MiKTeX-pdfTeX 4.19 DVI mode, 2026-10-16, two pages. SHA-256 `35a93e5f6dacfc7f0e504de09af35e4ebd1e3a46d5de86610ea0aa726ab8136e` |
| `paragraph_raggedright.miktex.dvi` | `testdata/e2e/paragraph_raggedright.tex` |
| `paragraph_narrower.miktex.dvi` | `testdata/e2e/paragraph_narrower.tex` |
| `hello.miktex.dvi` | `testdata/e2e/hello.tex` |
| `paragraph.miktex.dvi` | `testdata/e2e/paragraph.tex` |
| `paragraph_narrow.miktex.dvi` | `testdata/e2e/paragraph_narrow.tex` ( — 3in column) |
| `multipage.miktex.dvi` | `testdata/e2e/multipage.tex` |
| `rules.miktex.dvi` | `testdata/e2e/rules.tex` |
| `footnotes.miktex.dvi` | `testdata/e2e/footnotes.tex` |
| `math_inline.miktex.dvi` | `testdata/e2e/math_inline.tex` ( — inline math) |
| `math_scripts.miktex.dvi` | `testdata/e2e/math_scripts.tex` ( — scripts/fraction/radical/accent/overline) |
| `math_display.miktex.dvi` | `testdata/e2e/math_display.tex` ( — display + `\over` + `\eqno`) |
| `math_delimiters.miktex.dvi` | `testdata/e2e/math_delimiters.tex` ( — `\left(...\over...\right)` rule-19 delimiter growth + display `$$\sum_{i=1}^{n}$$` large-op size switch + limits) |
| `alignment_text.miktex.dvi` | `testdata/e2e/alignment_text.tex` ( — text `\halign` §807 inter-row interline glue) |
| `alignment_matrix.miktex.dvi` | `testdata/e2e/alignment_matrix.tex` ( — math `\matrix` + `\pmatrix` grid) |
| `alignment_eqalign.miktex.dvi` | `testdata/e2e/alignment_eqalign.tex` ( — display `\eqalign`) |
| `combined_document_vsize_{2_0,2_5,3_0}.miktex.dvi` | `testdata/e2e/combined_document_vsize_*.tex` ( — `combined_document` at `\vsize` 2.0/2.5/3.0in) |
| `paging_text.miktex.dvi` | `testdata/e2e/paging_text.tex` ( — text-only page breaks between paragraph lines) |
| `page_state_{footnote,display_space,pageinsert,eject_empty}.miktex.dvi` | `testdata/e2e/page_state_*.tex` ( — contribution list, insertions and the output nest) |
| `text_accent_{geometry,assignments}.miktex.dvi` | `testdata/e2e/text_accent_*.tex` ( — direct accent list, rounded slant delta, assignment scanning) |

## Provenance

added only the seven baselines on 2026-10-20 with
`python tools/regen_e2e_baselines.py sample-1 owner_raggedright owner_narrower owner_table owner_dashes owner_footnote owner_hyphenation`
(MiKTeX-pdfTeX 4.19 / MiKTeX 24.4). Existing baselines were not regenerated.
Owner documents: `owner_raggedright` `89f49cc6…`, `owner_narrower` `a7a1c5cf…`,
`owner_table` `24b59cff…`, `owner_dashes` `e241cf4e…`, `owner_footnote`
`efb1ccaa…`, `owner_hyphenation` `961330f0…` (DVI SHA-256 prefixes).

added only the two `text_accent_*` baselines on 2026-10-15 with
`uv run python tools/regen_e2e_baselines.py text_accent_geometry text_accent_assignments`.
Existing baselines were not regenerated. The new references retain page-top
and subsequent-line accents, tall/narrow bases, mixed fonts and unboxed copies.

- **Generator:** MiKTeX-pdfTeX 4.19 (MiKTeX 24.4), DVI output mode.
- **Command (per fixture):**
  `pdftex --output-format=dvi --interaction=batchmode --output-directory=<scratch> testdata/e2e/<fixture>.tex`
- **Regenerated:** 2026-05-29 (initial set); `paragraph_narrow.miktex.dvi`
  added 2026-05-30; `math_inline.miktex.dvi` added 2026-06-07
  ( — inline math, MiKTeX-pdfTeX 4.19); `math_scripts.miktex.dvi` +
  `math_display.miktex.dvi` added 2026-06-10 ( — scripts/
  fractions/radical/accent/overline + display/`\eqno`, MiKTeX-pdfTeX 4.19);
  `math_delimiters.miktex.dvi` added 2026-06-12 ( — variable
  delimiters + large operators, MiKTeX-pdfTeX 4.19); `alignment_text` +
  `alignment_matrix` + `alignment_eqalign` `.miktex.dvi` added 2026-06-26
  ( — alignment row spacing; in the tree but not yet in
  the e2e `_FIXTURES` pending, see `testdata/e2e/README.md`);
  `combined_document_vsize_{2_0,2_5,3_0}` + `paging_text` `.miktex.dvi` added
  2026-10-14 ( — page-break selection, MiKTeX-pdfTeX 4.19);
  the four `page_state_*` `.miktex.dvi` added 2026-10-15 ( —
  page-state ownership, MiKTeX-pdfTeX 4.19).
- **Format:** plain TeX (the `\bye` in each fixture terminates the job; pdfTeX
  in DVI mode loads its plain format by default).

This is the same generator and command convention used by the /
fixtures (`testdata/fixtures/**/*.miktex.dvi`), so all MiKTeX baselines
in the tree share one provenance story.

## Regeneration

```sh
make e2e-baselines                          # all fixtures
python tools/regen_e2e_baselines.py hello   # a subset
```

Requirements: `pdftex` (MiKTeX-pdfTeX **>= 4.19**) on `PATH`. The tool prints a
SHA-256 of every regenerated `.dvi` and the source `.tex` so the committed diff
can be reviewed. When a fixture changes, regenerate and commit the new
`.miktex.dvi` **together with** the `.tex` change in the same commit, and bump
the "Regenerated" date above.

CI does **not** need pdftex: the committed baselines are what the test suite
reads, and the suite has no MiKTeX dependency at test time (see
[`testdata/e2e/README.md`](../e2e/README.md) for the skip discipline).
