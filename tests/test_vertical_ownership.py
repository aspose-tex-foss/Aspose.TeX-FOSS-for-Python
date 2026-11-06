""": abort paths preserve enclosing save/list ownership."""

import pytest

from aspose_tex import DviDevice, StringInputSource
from aspose_tex._engine.group import GroupKind
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.nodes import AdjustNode, KernNode, deep_copy_node
from aspose_tex.exceptions import EngineError
from tests.test_plain_tie import _messages


@pytest.mark.parametrize("content", [
    r"\begingroup y}", r"y\endgroup", r"$y}",
    r"\setbox1\hbox\bgroup\begingroup y}",
    r"\setbox1\vtop\bgroup y\endgroup",
])
def test_eager_abort_restores_enclosing_owner(content):
    interp = TeXInterpreter()
    body = (r"\font\tenrm=cmr10\tenrm\let\bgroup={"
            r"\begingroup\count200=7\aftergroup Q\noindent x"
            r"\setbox0\vbox{\count200=9\noindent " + content)
    with pytest.raises(EngineError):
        interp.run_with_device(StringInputSource(body), DviDevice())
    assert [f.kind for f in interp._group_stack._frames] == [GroupKind.SEMI_SIMPLE]
    assert interp._register_set.get_count(200) == 7
    assert len(interp._group_stack._frames[0].aftergroup) == 1
    assert interp._box_regs.peekbox(0) is None
    assert not interp._box_construction_stack
    assert interp._par_list is not None
    assert any(getattr(n, "char", None) == ord("x") for n in interp._par_list.nodes)


@pytest.mark.parametrize("body", ["}", r"\endgroup", r"\vadjust{}"])
def test_invalid_vertical_commands_raise_engine_error(body):
    interp = TeXInterpreter()
    with pytest.raises(EngineError):
        interp.run_with_device(StringInputSource(body), DviDevice())


def test_adjustment_deepcopy_owns_its_material():
    node = AdjustNode([KernNode(65536, explicit=True)])
    cloned = deep_copy_node(node)
    cloned.list.clear()
    assert len(node.list) == 1


def test_global_setbox_does_not_globalize_body_assignments():
    body = (r"\count200=7\begingroup\global\setbox0\vbox{\count200=9\noindent x}"
            r"\endgroup\message{[\the\count200]}\ifvoid0\message{[void]}\else\message{[set]}\fi")
    assert _messages(body) == ["[7]", "[set]"]


@pytest.mark.parametrize("kind", ["vbox", "vtop"])
def test_afterassignment_enters_deferred_box(kind):
    body = (r"\noindent a\afterassignment\noindent\setbox0" + "\\" + kind
            + r"\bgroup x\par\message{[\the\prevgraf]}\egroup"
            r"\message{[\the\prevgraf]}b")
    assert _messages(body) == ["[1]", "[0]"]
