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
| `hello.miktex.dvi` | `testdata/e2e/hello.tex` |
| `paragraph.miktex.dvi` | `testdata/e2e/paragraph.tex` |
| `paragraph_narrow.miktex.dvi` | `testdata/e2e/paragraph_narrow.tex` ( — 3in column) |
| `multipage.miktex.dvi` | `testdata/e2e/multipage.tex` |
| `rules.miktex.dvi` | `testdata/e2e/rules.tex` |
| `footnotes.miktex.dvi` | `testdata/e2e/footnotes.tex` |

## Provenance

- **Generator:** MiKTeX-pdfTeX 4.19 (MiKTeX 24.4), DVI output mode.
- **Command (per fixture):**
 `pdftex --output-format=dvi --interaction=batchmode --output-directory=<scratch> testdata/e2e/<fixture>.tex`
- **Regenerated:** 2026-05-29 (initial set); `paragraph_narrow.miktex.dvi`
 added 2026-05-30.
- **Format:** plain TeX (the `\bye` in each fixture terminates the job; pdfTeX
 in DVI mode loads its plain format by default).

This is the same generator and command convention used by the / /
 fixtures (`testdata/fixtures/**/*.miktex.dvi`), so all MiKTeX baselines
in the tree share one provenance story.

## Regeneration

```sh
make e2e-baselines # all fixtures
python tools/regen_e2e_baselines.py hello # a subset
```

Requirements: `pdftex` (MiKTeX-pdfTeX **>= 4.19**) on `PATH`. The tool prints a
SHA-256 of every regenerated `.dvi` and the source `.tex` so the committed diff
can be reviewed. When a fixture changes, regenerate and commit the new
`.miktex.dvi` **together with** the `.tex` change in the same commit, and bump
the "Regenerated" date above.

CI does **not** need pdftex: the committed baselines are what the test suite
reads, and the suite has no MiKTeX dependency at test time (see
[`testdata/e2e/README.md`](../e2e/README.md) for the skip discipline).
