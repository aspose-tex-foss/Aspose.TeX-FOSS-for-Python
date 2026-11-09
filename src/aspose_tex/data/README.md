# Data Directory

This directory contains bundled data files shipped with the `aspose_tex` package.

## fonts/

Holds TFM (TeX Font Metric) files and glyph data for Computer Modern fonts.
Populated with the bundled TFM font metrics. Empty at this stage.

## hyphenation/

Reserved for further language pattern files; empty. The US-English patterns
live in `format/hyphen.tex` (below), where plain's `\input hyphen` finds them.
Other languages are added the TeX way: a format file supplied through
`TeXOptions.extra_format_paths` sets `\language=N` and runs
`\patterns`/`\hyphenation`.

## format/

Holds TeX format files (macro packages loaded at engine startup).
Currently contains:

- `plain.tex` — Knuth's canonical Plain TeX format (1241 lines, ~46 KB).
  Source: identical to the file distributed with TeX Live / MiKTeX
  (md5 `11ca0f57510642604c9863a9d4853a64`). License: unlimited redistribution
  permitted as long as the file is not modified (per Knuth's preamble).
  Loaded by the engine to provide user-level macros (`\bf`, `\it`,
  `\centerline`, `\beginsection`, `\footnote`, etc.) on top of TeX
  primitives.

- `hyphen.tex` — Knuth's US-English hyphenation patterns, the file MiKTeX's
  plain format loads at `\language=0` (4447 patterns, 14 exceptions).
  Source: MiKTeX 24.4, `tex/generic/knuth-lib/hyphen.tex`; 27 860 bytes,
  LF line ends, SHA-256
  `2c18acdc04c1a066aeb1759905e7ca449f0616c314b5ed6aebe55b9d4a89b8d4`
  (pinned in `scripts/validate_format_bundle.py`). It ships byte for byte:
  `.gitattributes` marks it `-text` so no checkout converts its line ends.
  Licence (Knuth, verbatim from the file's header): "Unlimited copying and
  redistribution of this file are permitted as long as this file is not
  modified. Modifications are permitted, but only if the resulting file is
  not named hyphen.tex." It is not public domain.
