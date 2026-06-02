""" / — interline-glue behaviour for ``\\hrule`` / ``\\unvbox``
/ ``\\unvcopy`` arms inside ``exec_vbox``.

Covers the six test cases from §"Testing":

1. ``\\hrule`` breaks the interline-glue chain (TeX:The Program §679);
2. ``\\unvbox`` does not re-emit glue before the first spliced child
 (TeX:The Program §1083);
3. a rule-terminated splice resets ``prevdepth`` to the sentinel;
4. an empty splice leaves ``prevdepth`` unchanged;
5. adjacent ``\\hrule``s emit no interline glue between themselves;
6. ``\\unvcopy`` matches ``\\unvbox`` semantics on the splice path.
"""
from __future__ import annotations

from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import (
 GlueNode,
 HlistNode,
 RuleNode,
 VlistNode,
)
from aspose_tex._input.reader import StringInputSource
from aspose_tex.presentation import DviDevice


def _run(tex: str) -> TeXInterpreter:
 interp = TeXInterpreter()
 interp.run_with_device(StringInputSource(tex), DviDevice())
 return interp


def _peek_vbox(interp: TeXInterpreter, idx: int) -> VlistNode:
 box = interp._box_regs.peekbox(idx)
 assert isinstance(box, VlistNode), f"box{idx} is not a VlistNode: {box!r}"
 return box


class TestHruleBreaksChain:
 def test_hrule_breaks_interline_chain(self) -> None:
 # `\vbox{a\hrule b}` should compose [HlistNode(a), RuleNode, HlistNode(b)]
 # with NO interline GlueNode anywhere — the rule resets `prevdepth` to
 # the entry sentinel per TeX:The Program §679, so the post-rule hbox
 # does not pick up interline glue.
 interp = _run(r"\setbox0=\vbox{a\hrule b}\bye")
 nodes = _peek_vbox(interp, 0).list

 kinds = [type(n).__name__ for n in nodes]
 assert HlistNode.__name__ in kinds
 assert RuleNode.__name__ in kinds

 # Locate the rule; the immediately following box (if any) must NOT be
 # preceded by an interline glue.
 rule_idx = next(i for i, n in enumerate(nodes) if isinstance(n, RuleNode))
 assert rule_idx + 1 < len(nodes), "expected a post-rule hbox"
 post_rule = nodes[rule_idx + 1]
 assert isinstance(post_rule, HlistNode), (
 f"expected HlistNode after rule, got {type(post_rule).__name__}"
 )
 # And no rogue GlueNode between rule and the post-rule hbox:
 assert not isinstance(nodes[rule_idx + 1], GlueNode)
 # The pre-rule node (an hbox) must not have a trailing interline glue
 # against the rule either:
 assert rule_idx >= 1
 assert isinstance(nodes[rule_idx - 1], HlistNode)
 assert not isinstance(nodes[rule_idx], GlueNode)

 def test_adjacent_hrules_emit_no_interline_glue(self) -> None:
 # `\vbox{\hrule\hrule}` => [RuleNode, RuleNode] with no glue between.
 interp = _run(r"\setbox0=\vbox{\hrule\hrule}\bye")
 nodes = _peek_vbox(interp, 0).list

 rules = [i for i, n in enumerate(nodes) if isinstance(n, RuleNode)]
 assert len(rules) == 2, f"expected 2 RuleNodes, got nodes={nodes!r}"
 i, j = rules
 assert j == i + 1, (
 f"adjacent rules separated by intermediate nodes: {nodes[i:j+1]!r}"
 )


class TestUnvboxSplice:
 def test_unvbox_no_interline_before_first_spliced_child(self) -> None:
 # `\setbox0=\vbox{\hbox{A}}` then `\setbox1=\vbox{Line1\unvbox0}`.
 # Per §1083, `\unvbox` does NOT re-emit interline glue before the
 # first spliced child; the receiving vbox already has `prevdepth =
 # Line1.depth` (from `_track_box(Line1)`), so a single interline
 # glue between Line1 and the spliced \hbox{A} is correct. The
 # critical assertion is that there is NOT a *second* glue emitted
 # by the (now-removed) `_emit_interline_glue` shim before the splice.
 interp = _run(
 r"\setbox0=\vbox{\hbox{A}}"
 r"\setbox1=\vbox{Line1\unvbox0}"
 r"\bye"
 )
 nodes = _peek_vbox(interp, 1).list

 hboxes = [i for i, n in enumerate(nodes) if isinstance(n, HlistNode)]
 assert len(hboxes) >= 2, f"expected at least 2 HlistNodes, got {nodes!r}"

 # Between the first two hboxes there is at most one GlueNode (the one
 # that `_emit_interline_glue` would emit before the *next* contribution
 # if the spliced child were contributed directly via `_add_hbox`).
 first, second = hboxes[0], hboxes[1]
 between = nodes[first + 1 : second]
 glues = [n for n in between if isinstance(n, GlueNode)]
 assert len(glues) <= 1, (
 f"expected ≤1 interline glue between Line1 and spliced \\hbox{{A}};"
 f" got {len(glues)} in {between!r}"
 )

 def test_unvbox_rule_terminated_splice_resets_prev_depth(self) -> None:
 # `\setbox0=\vbox{\hbox{A}\hrule}` then `\setbox1=\vbox{Line1\unvbox0
 # Line2}`. After the splice, `_track_splice` reverse-walks and hits
 # the rule first, so `prevdepth` is reset to the sentinel. Therefore
 # NO interline glue must be inserted between the spliced RuleNode and
 # the subsequent Line2 hbox.
 interp = _run(
 r"\setbox0=\vbox{\hbox{A}\hrule}"
 r"\setbox1=\vbox{Line1\unvbox0 Line2}"
 r"\bye"
 )
 nodes = _peek_vbox(interp, 1).list

 rule_idx = next(
 (i for i, n in enumerate(nodes) if isinstance(n, RuleNode)),
 None,
 )
 assert rule_idx is not None, f"expected a RuleNode in splice; got {nodes!r}"
 # Locate the next HlistNode after the rule (Line2).
 post_rule_hbox = next(
 (i for i in range(rule_idx + 1, len(nodes))
 if isinstance(nodes[i], HlistNode)),
 None,
 )
 assert post_rule_hbox is not None, (
 f"expected a post-rule hbox (Line2); got {nodes!r}"
 )
 # No GlueNode between the rule and that hbox.
 between = nodes[rule_idx + 1 : post_rule_hbox]
 assert not any(isinstance(n, GlueNode) for n in between), (
 f"unexpected glue between rule-terminated splice and Line2: {between!r}"
 )

 def test_unvbox_empty_splice_leaves_prev_depth(self) -> None:
 # `\setbox0=\vbox{}` (empty); `\setbox1=\vbox{Line1\unvbox0 Line2}`.
 # The empty splice must leave `prevdepth = Line1.depth`, so the next
 # `_add_hbox(Line2)` emits exactly one interline GlueNode between
 # Line1 and Line2.
 interp = _run(
 r"\setbox0=\vbox{}"
 r"\setbox1=\vbox{Line1\unvbox0 Line2}"
 r"\bye"
 )
 nodes = _peek_vbox(interp, 1).list

 hboxes = [i for i, n in enumerate(nodes) if isinstance(n, HlistNode)]
 assert len(hboxes) >= 2, (
 f"expected Line1 + Line2 hboxes; got {nodes!r}"
 )
 first, second = hboxes[0], hboxes[1]
 between = nodes[first + 1 : second]
 glues = [n for n in between if isinstance(n, GlueNode)]
 assert len(glues) == 1, (
 f"empty splice should not affect interline glue; expected exactly"
 f" one glue between Line1 and Line2, got {len(glues)} in {between!r}"
 )


class TestUnvcopyParity:
 def test_unvcopy_matches_unvbox_semantics(self) -> None:
 # Repeat the §1083 single-spliced-child case using `\unvcopy` instead
 # of `\unvbox`. Splice path is shared, so behaviour is identical.
 interp = _run(
 r"\setbox0=\vbox{\hbox{A}}"
 r"\setbox1=\vbox{Line1\unvcopy0}"
 r"\bye"
 )
 nodes = _peek_vbox(interp, 1).list

 hboxes = [i for i, n in enumerate(nodes) if isinstance(n, HlistNode)]
 assert len(hboxes) >= 2

 first, second = hboxes[0], hboxes[1]
 between = nodes[first + 1 : second]
 glues = [n for n in between if isinstance(n, GlueNode)]
 assert len(glues) <= 1, (
 f"\\unvcopy must not re-emit interline glue before the first"
 f" spliced child; got {len(glues)} in {between!r}"
 )
 # `\unvcopy` preserves the source register.
 assert interp._box_regs.peekbox(0) is not None
