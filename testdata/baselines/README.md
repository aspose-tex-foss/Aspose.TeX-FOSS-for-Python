# End-to-end DVI baselines

MiKTeX-generated reference `.dvi` files for the documents under
[`testdata/e2e/`](../e2e/). The pytest suite
[`tests/test_e2e_dvi_baseline.py`](../../tests/test_e2e_dvi_baseline.py)
compiles each `testdata/e2e/<fixture>.tex` with **this** engine and compares
the result against the matching `<fixture>.miktex.dvi` here, **semantically**
(page count, glyph stream, line/rule positions) — never byte-for-byte.

## Files

Every `testdata/e2e/<fixture>.tex` has exactly one `<fixture>.miktex.dvi` here
(`test_every_fixture_has_a_baseline`); [`testdata/e2e/README.md`](../e2e/README.md)
says what each document pins. Two further files hold measured data read by
other tests:

| File | Read by |
|------|---------|
| `inline-breaks.json` | `tests/test_inline_math_breaks.py` |
| `paragraph-shapes.json` | `tests/test_paragraph_shapes.py` |

## Provenance

- **Generator:** MiKTeX-pdfTeX 4.19 (MiKTeX 24.4), DVI output mode.
- **Command (per fixture):**
  `pdftex --output-format=dvi --interaction=batchmode --output-directory=<scratch> testdata/e2e/<fixture>.tex`
- **Format:** plain TeX (the `\bye` in each fixture ends the job; pdfTeX in DVI
  mode loads its plain format by default).
- **Dates:** the first set was generated on 2026-05-29; baselines were added
  as documents joined the corpus, the last ones (seven of the admitted
  documents, see `testdata/e2e/README.md`) on 2026-10-20. Existing baselines are not
  regenerated when a new one is added.

The older defect-specific fixtures under `testdata/fixtures/**/*.miktex.dvi`
were generated with the same generator and command, so all MiKTeX baselines in
the tree share one provenance.

## Regeneration

Run the command above for each changed fixture and copy the `.dvi` to
`testdata/baselines/<fixture>.miktex.dvi`. Commit the new baseline **together
with** the `.tex` change, in the same commit.

The test suite does **not** need pdftex: it reads the committed baselines and
has no MiKTeX dependency at test time.
