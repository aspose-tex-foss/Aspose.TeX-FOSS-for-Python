""" / box-vocabulary primitive tests."""
from __future__ import annotations

import pytest

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.linebreak import LinebreakParams, break_paragraph
from aspose_tex._engine.nodes import (
 RUNNING_DIMEN,
 CharNode,
 DiscretionaryNode,
 GlueNode,
 HlistNode,
 KernNode,
 LeadersKind,
 LeadersNode,
 MarkNode,
 PenaltyNode,
 RuleNode,
 VlistNode,
)
from aspose_tex._engine.registers import Glue, GlueOrder
from aspose_tex._input.reader import StringInputSource
from aspose_tex.exceptions import EngineError
from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

_NO_FORMAT = TeXOptions(load_format=False)


class _CaptureParagraphInterpreter(TeXInterpreter):
 def __init__(self) -> None:
 super().__init__()
 self.captured_paragraphs: list[list] = []

 def _end_paragraph(self) -> None:
 if self._par_list is not None:
 self.captured_paragraphs.append(self._par_list.nodes)
 super()._end_paragraph()


def _run_capture(tex: str) -> _CaptureParagraphInterpreter:
 interp = _CaptureParagraphInterpreter()
 interp.run_with_device(StringInputSource(tex), DviDevice())
 return interp


class _InspectInterpreter(TeXInterpreter):
 def __init__(self) -> None:
 super().__init__()
 self.captured_paragraphs: list[list] = []

 def _end_paragraph(self) -> None:
 if self._par_list is not None:
 self.captured_paragraphs.append(self._par_list.nodes)
 super()._end_paragraph()


class TestCharPrimitive:
 def test_char65_in_horizontal_mode_emits_char_node(self) -> None:
 interp = _run_capture(r"\noindent\char65\par\bye")

 chars = [
 n for para in interp.captured_paragraphs
 for n in para
 if isinstance(n, CharNode)
 ]
 assert chars == [CharNode(char=65, font_name="tenrm")]

 def test_char_out_of_range_raises(self) -> None:
 with pytest.raises(EngineError, match=r"\\char: code 300 out of range"):
 _run_capture(r"\noindent\char300\bye")


class TestAccentPrimitive:
 def test_accent_builds_kerned_hbox_over_base_char(self) -> None:
 interp = _run_capture(r"\noindent\accent23 a\par\bye")

 boxes = [
 n for para in interp.captured_paragraphs
 for n in para
 if isinstance(n, HlistNode)
 ]
 accent_box = boxes[0]
 chars = [n for n in accent_box.list if isinstance(n, CharNode)]
 assert chars == [
 CharNode(char=23, font_name="tenrm"),
 CharNode(char=ord("a"), font_name="tenrm"),
 ]
 assert accent_box.width > 0


class TestDiscretionaryNode:
 def test_discretionary_builds_node(self) -> None:
 interp = _run_capture(r"\noindent\discretionary{-}{}{}\par\bye")

 discs = [
 n for para in interp.captured_paragraphs
 for n in para
 if isinstance(n, DiscretionaryNode)
 ]
 assert len(discs) == 1
 assert discs[0].pre == (CharNode(char=ord("-"), font_name="tenrm"),)
 assert discs[0].post == ()
 assert discs[0].nobreak == ()

 def test_linebreaker_accepts_discretionary_without_crash(self) -> None:
 fm = TeXInterpreter()
 device = DviDevice()
 fm.run_with_device(StringInputSource(r"\bye"), device)
 params = LinebreakParams(
 hsize=10 * 65_536,
 tolerance=200,
 pretolerance=100,
 linepenalty=10,
 adjdemerits=10_000,
 leftskip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 rightskip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 parfillskip=Glue(0, 65_536, GlueOrder.FIL, 0, GlueOrder.NORMAL),
 )
 node = DiscretionaryNode(
 pre=(CharNode(ord("-"), "tenrm"),),
 post=(),
 nobreak=(CharNode(ord("x"), "tenrm"),),
 )

 lines = break_paragraph([CharNode(ord("a"), "tenrm"), node], params, fm._font_manager)

 assert len(lines) == 1
 assert any(isinstance(n, CharNode) and n.char == ord("x") for n in lines[0].list)


class TestVtop:
 def test_vtop_baseline_uses_first_item(self) -> None:
 interp = TeXInterpreter()
 interp.run_with_device(
 StringInputSource(r"\setbox0=\vbox{\hbox{a}\hbox{b}}\setbox1=\vtop{\hbox{a}\hbox{b}}\bye"),
 DviDevice(),
 )

 vbox = interp._box_regs.peekbox(0)
 vtop = interp._box_regs.peekbox(1)
 assert isinstance(vbox, VlistNode)
 assert isinstance(vtop, VlistNode)
 assert vtop.height < vbox.height
 assert vtop.height == vtop.list[0].height


class TestUnhbox:
 def test_unhbox_splices_and_voids_register(self) -> None:
 interp = _run_capture(r"\setbox0=\hbox{abc}\noindent\unhbox0\par\bye")

 chars = [
 n for para in interp.captured_paragraphs
 for n in para
 if isinstance(n, CharNode)
 ]
 assert [n.char for n in chars] == [ord("a"), ord("b"), ord("c")]
 assert interp._box_regs.peekbox(0) is None

 def test_unhcopy_preserves_register(self) -> None:
 interp = _run_capture(r"\setbox0=\hbox{a}\noindent\unhcopy0\par\bye")

 assert isinstance(interp._box_regs.peekbox(0), HlistNode)


class TestUnvbox:
 def test_unvbox_splices_vbox_contents(self) -> None:
 interp = TeXInterpreter()
 interp.run_with_device(
 StringInputSource(r"\setbox0=\vbox{\hbox{a}}\setbox1=\vbox{\unvcopy0}\bye"),
 DviDevice(),
 )

 box = interp._box_regs.peekbox(1)
 assert isinstance(box, VlistNode)
 assert any(isinstance(node, HlistNode) for node in box.list)

 def test_unvbox_in_horizontal_mode_raises(self) -> None:
 with pytest.raises(EngineError, match=r"\\unvbox in horizontal mode"):
 _run_capture(r"\setbox0=\vbox{\hbox{a}}\noindent\unvbox0\bye")


class TestTailRemoval:
 def test_unskip_unkern_unpenalty_remove_matching_tail(self) -> None:
 interp = _run_capture(
 r"\noindent a\hskip 1pt\unskip\kern 2pt\unkern"
 r"\penalty 5\unpenalty b\par\bye"
 )

 nodes = interp.captured_paragraphs[0]
 assert not any(isinstance(n, GlueNode) and n.glue.width == 65_536 for n in nodes)
 assert not any(isinstance(n, KernNode) and n.width == 131_072 for n in nodes)
 assert not any(isinstance(n, PenaltyNode) and n.penalty == 5 for n in nodes)

 # ------------------------------------------------------------------
 # / — V-mode \unskip / \unkern / \unpenalty must roll
 # back the PageBuilder accumulators that contribute() wrote, not just
 # pop the MVL tail. See cascade.
 # ------------------------------------------------------------------

 def _run_vmode(self, tex: str) -> TeXInterpreter:
 """Run *tex* in V-mode without a page break, ending with ``\\end``.

 The ``\\end`` primitive does not contribute ``\\vfill`` + a
 ``NEG_INF_PENALTY`` (unlike ``\\bye``) so the MVL is preserved for
 post-run inspection. ``end_of_document`` is a no-op when the MVL
 contains only discardable nodes.
 """
 interp = TeXInterpreter()
 interp.run_with_device(StringInputSource(tex), DviDevice())
 return interp

 def test_unskip_in_vertical_mode_rolls_back_page_builder(self) -> None:
 interp = self._run_vmode(r"\vskip 12pt\unskip\end")
 pb = interp._page_builder

 # The glue was popped — no GlueNode of width 12pt remains on the MVL.
 assert not any(
 isinstance(n, GlueNode) and n.glue.width == 786_432 for n in pb._mvl
 )
 # contribute() added 786_432 sp to _page_total; remove_last_node()
 # must roll it back.
 assert pb._page_total == 0
 # The glue was the only break candidate; clearing it is correct.
 assert pb._last_break_idx is None
 assert pb._last_break_penalty == 0

 def test_unkern_in_vertical_mode_rolls_back_page_total(self) -> None:
 interp = self._run_vmode(r"\kern 8pt\unkern\end")
 pb = interp._page_builder

 # The kern (width = 524_288 sp = 8 pt) was popped.
 assert not any(
 isinstance(n, KernNode) and n.width == 524_288 for n in pb._mvl
 )
 # _page_total was incremented by 524_288 when the kern was
 # contributed; remove_last_node() must roll it back to zero.
 assert pb._page_total == 0
 # Kerns are not break candidates, so _last_break_idx stays None.
 assert pb._last_break_idx is None

 def test_unpenalty_in_vertical_mode_clears_last_break(self) -> None:
 interp = self._run_vmode(r"\penalty 500\unpenalty\end")
 pb = interp._page_builder

 # The penalty=500 node was popped from the MVL.
 assert not any(
 isinstance(n, PenaltyNode) and n.penalty == 500 for n in pb._mvl
 )
 # The finite penalty was the only break candidate; clearing it is
 # correct.
 assert pb._last_break_idx is None
 assert pb._last_break_penalty == 0


class TestLastbox:
 def test_setbox_from_lastbox_removes_tail_box(self) -> None:
 interp = TeXInterpreter()
 interp.run_with_device(
 StringInputSource(r"\setbox0=\vbox{\hbox{a}\hbox{b}\setbox1=\lastbox}\bye"),
 DviDevice(),
 )

 box0 = interp._box_regs.peekbox(0)
 assert isinstance(box0, VlistNode)
 boxes = [n for n in box0.list if isinstance(n, HlistNode)]
 assert len(boxes) == 1
 assert [n.char for n in boxes[0].list if isinstance(n, CharNode)] == [ord("a")]

 def test_lastbox_in_outer_vertical_raises(self) -> None:
 with pytest.raises(EngineError, match=r"\\lastbox in outer vertical mode"):
 TeXInterpreter().run_with_device(StringInputSource(r"\lastbox\bye"), DviDevice())


class TestVsplit:
 def test_vsplit_returns_top_and_stores_residue(self) -> None:
 interp = TeXInterpreter()
 interp.run_with_device(
 StringInputSource(
 r"\setbox0=\vbox{\hbox{a}\kern 20pt\hbox{b}}"
 r"\setbox1=\vsplit0 to 10pt\bye"
 ),
 DviDevice(),
 )

 top = interp._box_regs.peekbox(1)
 residue = interp._box_regs.peekbox(0)
 assert isinstance(top, VlistNode)
 assert isinstance(residue, VlistNode)
 assert any(isinstance(n, HlistNode) for n in top.list)
 assert any(isinstance(n, HlistNode) for n in residue.list)

 def test_vsplit_void_register_sets_void(self) -> None:
 interp = TeXInterpreter()
 interp.run_with_device(StringInputSource(r"\setbox1=\vsplit0 to 10pt\bye"), DviDevice())

 assert interp._box_regs.peekbox(1) is None


class TestHskipTopLevel:
 def test_hskip_in_outer_vertical_starts_paragraph(self) -> None:
 interp = _run_capture(r"\hskip 1pt a\par\bye")

 assert any(isinstance(n, GlueNode) and n.glue.width == 65_536
 for n in interp.captured_paragraphs[0])


class TestMoveBox:
 def test_moveleft_and_moveright_shift_boxes(self) -> None:
 interp = TeXInterpreter()
 interp.run_with_device(
 StringInputSource(
 r"\setbox0=\hbox{a}"
 r"\setbox1=\vbox{\moveleft 5pt\copy0\moveright 3pt\box0}\bye"
 ),
 DviDevice(),
 )

 vbox = interp._box_regs.peekbox(1)
 assert isinstance(vbox, VlistNode)
 boxes = [n for n in vbox.list if isinstance(n, HlistNode)]
 assert [box.shift_amount for box in boxes] == [327_680, -196_608]

 def test_moveleft_in_horizontal_mode_raises(self) -> None:
 with pytest.raises(EngineError, match=r"\\moveleft in horizontal mode"):
 _run_capture(r"\noindent\moveleft 1pt\hbox{a}\bye")


class TestLeavevmode:
 def test_leavevmode_starts_unindented_paragraph(self) -> None:
 interp = _InspectInterpreter()
 interp.run_with_device(StringInputSource(r"\leavevmode a\par\bye"), DviDevice())

 first = interp.captured_paragraphs[0][0]
 assert isinstance(first, CharNode)
 assert first.char == ord("a")


class TestHangindent:
 def test_hangindent_hangafter_parshape_store_and_restore(self) -> None:
 interp = TeXInterpreter()
 interp.run_with_device(
 StringInputSource(
 r"\hangindent=20pt \hangafter=2 \parshape=1 0pt 5pt "
 r"{\hangindent=1pt \hangafter=3 \parshape=0 }\bye"
 ),
 DviDevice(),
 )

 assert interp._hangindent == 1_310_720
 assert interp._hangafter == 2
 assert interp._parshape == [(0, 327_680)]

 def test_parshape_negative_count_raises(self) -> None:
 with pytest.raises(EngineError, match=r"\\parshape count < 0"):
 TeXInterpreter().run_with_device(StringInputSource(r"\parshape=-1\bye"), DviDevice())


class TestFontdimen:
 def test_the_fontdimen_reads_font_parameter(self) -> None:
 job = TeXJob(
 StringInputSource(r"\message{\the\fontdimen5\tenrm}\bye"),
 DviDevice(),
 options=_NO_FORMAT,
 )
 job.run()

 assert job.messages == ["282168sp"]

 def test_fontdimen_assignment_changes_read_value(self) -> None:
 job = TeXJob(
 StringInputSource(r"\fontdimen6\tenrm=10pt \message{\the\fontdimen6\tenrm}\bye"),
 DviDevice(),
 options=_NO_FORMAT,
 )
 job.run()

 assert job.messages == ["655360sp"]


class TestSkewchar:
 def test_skewchar_assignment_and_group_restore(self) -> None:
 interp = TeXInterpreter()
 interp.run_with_device(
 StringInputSource(r"\skewchar\tenrm=10 {\skewchar\tenrm=127 }\bye"),
 DviDevice(),
 )

 assert interp._font_manager.skewchar("tenrm") == 10


class TestHyphenchar:
 def test_hyphenchar_assignment_and_group_restore(self) -> None:
 interp = TeXInterpreter()
 interp.run_with_device(
 StringInputSource(r"\hyphenchar\tenrm=45 {\hyphenchar\tenrm=127 }\bye"),
 DviDevice(),
 )

 assert interp._font_manager.hyphenchar("tenrm") == 45


class TestVrule:
 def test_vrule_in_horizontal_mode_appends_rule_node(self) -> None:
 interp = _run_capture(
 r"\noindent\vrule width 2pt height 3pt depth 1pt\par\bye"
 )

 rules = [
 n for para in interp.captured_paragraphs
 for n in para
 if isinstance(n, RuleNode)
 ]
 assert rules == [
 RuleNode(width=131_072, height=196_608, depth=65_536)
 ]

 def test_vrule_defaults(self) -> None:
 interp = _run_capture(r"\noindent\vrule\par\bye")

 rule = next(
 n for para in interp.captured_paragraphs
 for n in para
 if isinstance(n, RuleNode)
 )
 assert rule.width == 26_214
 assert rule.height == RUNNING_DIMEN
 assert rule.depth == RUNNING_DIMEN


class TestMarks:
 def test_mark_emits_mark_node(self) -> None:
 interp = _run_capture(r"\noindent\mark{abc}x\par\bye")

 marks = [
 n for para in interp.captured_paragraphs
 for n in para
 if isinstance(n, MarkNode)
 ]
 assert len(marks) == 1
 assert "".join(tok.char for tok in marks[0].tokens if hasattr(tok, "char")) == "abc"

 def test_topmark_expands_after_shipout(self) -> None:
 job = TeXJob(
 StringInputSource(r"\mark{A}\eject\message{\topmark}\bye"),
 DviDevice(),
 options=_NO_FORMAT,
 )
 job.run()

 assert job.messages == ["A"]


class TestLeaders:
 def test_leaders_hrule_hfill_produces_node(self) -> None:
 interp = _run_capture(r"\noindent\leaders\hrule\hfill\par\bye")

 leaders = [
 n for para in interp.captured_paragraphs
 for n in para
 if isinstance(n, LeadersNode)
 ]
 assert len(leaders) == 1
 assert leaders[0].kind == LeadersKind.NORMAL
 assert isinstance(leaders[0].payload, RuleNode)
 assert leaders[0].glue.stretch_order == GlueOrder.FILL

 def test_linebreaker_accepts_leaders_as_glue_shell(self) -> None:
 fm = TeXInterpreter()
 fm.run_with_device(StringInputSource(r"\bye"), DviDevice())
 params = LinebreakParams(
 hsize=10 * 65_536,
 tolerance=200,
 pretolerance=100,
 linepenalty=10,
 adjdemerits=10_000,
 leftskip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 rightskip=Glue(0, 0, GlueOrder.NORMAL, 0, GlueOrder.NORMAL),
 parfillskip=Glue(0, 65_536, GlueOrder.FIL, 0, GlueOrder.NORMAL),
 )
 node = LeadersNode(
 kind=LeadersKind.NORMAL,
 payload=RuleNode(width=65_536, height=26_214, depth=0),
 glue=Glue(65_536, 65_536, GlueOrder.FILL, 0, GlueOrder.NORMAL),
 )

 lines = break_paragraph([CharNode(ord("a"), "tenrm"), node], params, fm._font_manager)

 assert len(lines) == 1
 assert any(isinstance(n, LeadersNode) for n in lines[0].list)


class TestNodeRegistry:
 def test_discretionary_node_shape(self) -> None:
 node = DiscretionaryNode(pre=(), post=(), nobreak=())

 assert node.pre == ()
 assert node.post == ()
 assert node.nobreak == ()

 def test_mark_and_leaders_node_shape(self) -> None:
 leader = LeadersNode(
 kind=LeadersKind.C,
 payload=RuleNode(width=1, height=2, depth=3),
 glue=Glue(4, 5, GlueOrder.FIL, 0, GlueOrder.NORMAL),
 )
 mark = MarkNode(tokens=())

 assert leader.kind == LeadersKind.C
 assert isinstance(leader.payload, RuleNode)
 assert mark.tokens == ()
