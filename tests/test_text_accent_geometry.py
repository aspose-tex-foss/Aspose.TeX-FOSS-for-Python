r"""real-component geometry and bounded assignment scanner witnesses.

Expected glyph positions are frozen MiKTeX 24.4 measurements, never computed
from the implementation's formula. Font/node assertions cover invisible state.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aspose_tex._engine.box_builder import _measure_hlist
from aspose_tex._engine.box_primitives import _scan_accent_base
from aspose_tex._engine.linebreak import _line_starts
from aspose_tex._engine.nodes import CharNode, HlistNode, KernNode
from aspose_tex._input.catcode import Catcode
from aspose_tex._input.token import CharToken, ControlSequenceToken, PrimitiveRefToken
from aspose_tex.exceptions import EngineError
from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_box_vocab import _run_capture
from tests.test_expansion import make_expander
from tests.test_plain_tie import _run, _tfm_width

_EVIDENCE = Path(__file__).resolve().parents[1] / "testdata/reference/text_accent_geometry"
_ROWS = []
for _file in ("base-probes.json", "extra-probes.json", "rounding-probe.json",
              "assignment-probes.json", "binding-probes.json",
              "frozen-relax-probe.json", "global-font-probe.json",
              "second-probes.json", "third-probes.json", "fourth-probes.json"):
    _ROWS.extend(json.loads((_EVIDENCE / _file).read_text(encoding="utf-8"))["rows"])


@pytest.mark.parametrize("row", [r for r in _ROWS if r["miktex_exit"] == 0], ids=lambda r: r["name"])
def test_frozen_miktex_contexts(row):
    job = _run(row["body"])
    pages = walk_chars_with_positions(job._dvi, _tfm_width()) if job._dvi else []
    assert pages == [[tuple(g) for g in page] for page in row["miktex_pages"]]
    # MiKTeX adds one [page-number] token per shipped page to its console log.
    messages = row["miktex_messages"][:-len(pages)] if pages else row["miktex_messages"]
    assert [m for m in job.messages if m.startswith("[")] == messages


@pytest.mark.parametrize("command", [r"\setbox", r"\alias"])
def test_setbox_rejected_before_installing_box(command):
    with pytest.raises(EngineError, match=r"Improper.*setbox"):
        _run(r"\let\alias\setbox\noindent\hbox{\accent19" + command + r"1=\hbox{o}A}")


def _accent_nodes(body):
    interp = _run_capture(body + r"\par\bye")
    return interp, [n for n in interp.captured_paragraphs[0] if isinstance(n, (CharNode, KernNode, HlistNode))]


def test_direct_node_shape_and_mixed_font_ownership():
    interp, nodes = _accent_nodes(r"\font\tenit=cmti10\noindent\accent19\tenit A")
    assert len(nodes) == 4
    assert nodes[0] == KernNode(191691, False, accent_kern=True)
    assert nodes[2] == KernNode(-519372, False, accent_kern=True)
    assert isinstance(nodes[1], HlistNode)
    assert nodes[1].list == [CharNode(19, interp._font_manager.font_id("tenrm"))]
    assert nodes[1].shift_amount == 165660
    assert nodes[3] == CharNode(65, interp._font_manager.font_id("tenit"))
    # MiKTeX's measured \wd of \hbox{\it A} (see measured_width witness).
    assert _measure_hlist(nodes, interp._font_manager)[0] == 487148


def test_xheight_fast_path_and_accent_kerns_survive_line_discard():
    interp, nodes = _accent_nodes(r"\noindent\accent18 y")
    assert nodes == [KernNode(9103, False, accent_kern=True), CharNode(18, interp._font_manager.font_id("tenrm")),
                     KernNode(-336784, False, accent_kern=True), CharNode(121, interp._font_manager.font_id("tenrm"))]
    assert _line_starts([KernNode(10, True), *nodes])[0] == 1


def test_no_base_keeps_original_font_and_spacefactor():
    interp, nodes = _accent_nodes(r"\font\tenit=cmti10\noindent x.\accent19\tenit\relax")
    assert nodes[-1] == CharNode(19, interp._font_manager.font_id("tenrm"))
    assert interp._spacefactor == 1000


@pytest.mark.parametrize("tail", ["", r"\relax", r"\message{stop}", "}", r"\afterassignment A"])
def test_standalone_scanner_stops_without_executing_commands(tail):
    expander = make_expander(tail)
    assert _scan_accent_base(expander) is None
    if tail not in ("", r"\relax"):
        assert expander.get_x_token() is not None


@pytest.mark.parametrize("prefix", ["global", "long", "outer"])
@pytest.mark.parametrize("tail", ["", r"\message{stop}"])
def test_rejected_prefix_clears_pending_flags(prefix, tail):
    expander = make_expander("\\" + prefix + " " + tail)
    with pytest.raises(EngineError, match="prefix"):
        _scan_accent_base(expander)
    assert not expander._long_pending and not expander._outer_pending


@pytest.mark.parametrize("body", [r"\long\count1=1 A", r"\outer\let\b=A A"])
def test_invalid_definition_prefix_rejects_assignment(body):
    with pytest.raises(EngineError, match="prefix"):
        _run(r"\noindent\hbox{\accent19" + body + "}")


def test_zero_size_loaded_font_has_real_base_slots():
    interp, nodes = _accent_nodes(r"\font\zero=cmr10 at0pt\noindent\accent19\zero A")
    zero = interp._font_manager.get_metrics("zero")
    assert zero.at_size_sp == 0 and zero.has_char(65)
    assert zero is not interp._font_manager._nullfont_metrics
    assert len(nodes) == 4 and nodes[-1] == CharNode(65, interp._font_manager.font_id("zero"))


def test_zero_size_loaded_accent_scans_its_real_base():
    interp, nodes = _accent_nodes(r"\font\zero=cmr10 at0pt\zero\noindent\accent19\tenrm A")
    assert len(nodes) == 4
    accent = nodes[1]
    assert isinstance(accent, HlistNode) and accent.list == [CharNode(19, interp._font_manager.font_id("zero"))]
    assert nodes[-1] == CharNode(65, interp._font_manager.font_id("tenrm"))


def test_active_show_and_frozen_primitive_meanings_keep_owner_precedence():
    interp = _run_capture(r"\catcode`?=13\chardef\c=65\let?\c\chardef\relax=66\noindent x\par\bye")
    expander = interp._expander
    # MiKTeX meaning_chardef_same records the active slot's exact meaning.
    row = next(r for r in _ROWS if r["name"] == "meaning_chardef_same")
    meaning = row["miktex_messages"][0][1:-1]
    assert expander.show_text(CharToken("?", Catcode.ACTIVE)) == "> ?=" + meaning + "."
    assert expander._meaning_text(PrimitiveRefToken("relax")) == r"\relax"
    assert expander._meaning_text(ControlSequenceToken("relax")) == r'\char"42'


@pytest.mark.parametrize("prefix", ["", r"\catcode`?=13"])
def test_undefined_math_active_retains_existing_diagnostic(prefix):
    with pytest.raises(EngineError, match="math-active char without macro"):
        _run_capture(prefix + r'\mathcode`?="8000 $?$\bye')
