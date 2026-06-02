"""Integration test for AC-7: stem-heavy phrase renders without
orphan movetos in any glyph path.

The phrase "WAVE hiking pan" covers letters (W, A, V, E, h, i, k, n, g, p,
a) whose Type 1 charstrings exercise the Flex mechanism via OtherSubr
0/1/2 — the code path where injected spurious `M` commands.
"""
from __future__ import annotations

from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import SvgDevice, TeXJob, TeXOptions
from tests._verification.svg_glyph_integrity import orphan_movetos, scan_svg


def test_stem_heavy_phrase_has_no_orphan_movetos(tmp_path):
 """Rendering "WAVE hiking pan" produces no `g-*` path with
 ``M_count - Z_count >= 2`` ( FR-4a)."""
 out = tmp_path / "stem_heavy"
 TeXJob(
 StringInputSource(r"WAVE hiking pan\bye"),
 SvgDevice(out),
 options=TeXOptions(load_format=False),
 ).run()
 svg_file = tmp_path / "stem_heavy.svg"
 assert svg_file.exists()

 reports = scan_svg(svg_file)
 assert reports, "expected at least one <path id='g-*'> in rendered SVG"

 offenders = orphan_movetos(reports)
 assert not offenders, (
 "orphan moveto in glyph paths: "
 + ", ".join(f"{r.path_id} (M={r.m_count},Z={r.z_count})" for r in offenders)
 )
