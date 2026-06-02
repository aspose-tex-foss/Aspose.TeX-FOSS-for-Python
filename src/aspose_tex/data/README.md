# Data Directory

This directory contains bundled data files shipped with the `aspose_tex` package.

## fonts/

Holds TFM (TeX Font Metric) files and glyph data for Computer Modern fonts.
Populated with the bundled TFM font metrics. Empty at this stage.

## hyphenation/

Holds language-specific hyphenation pattern files.
US-English hyphenation patterns (public domain) will be added.
The mechanism is extensible for other languages. Empty at this stage.

## format/

Holds TeX format files (macro packages loaded at engine startup).
Currently contains:

- `plain.tex` — Knuth's canonical Plain TeX format (1241 lines, ~46 KB).
 Source: identical to the file distributed with TeX Live / MiKTeX
 (md5 `11ca0f57510642604c9863a9d4853a64`). License: unlimited redistribution
 permitted as long as the file is not modified (per Knuth's preamble).
 Loaded by the engine to provide user-level macros (`\bf`, `\it`,
 `\centerline`, `\beginsection`, `\footnote`, etc.) on top of TeX
 primitives. Required for M3.
