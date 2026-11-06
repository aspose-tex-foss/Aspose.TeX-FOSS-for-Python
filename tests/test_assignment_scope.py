"""Effective globaldefs across every binding owner."""
import json
from pathlib import Path

import pytest

from aspose_tex._engine.group import GroupKind, GroupStack
from tests.test_plain_tie import _run

_ROWS = json.loads((Path(__file__).parents[1] / 'testdata/reference/assignment_scope/reference.json').read_text())
_ARCH = json.loads((Path(__file__).parents[1] / 'testdata/reference/assignment_scope/baseline.json').read_text())


@pytest.mark.parametrize('name', [k for k in _ROWS if k.startswith('scope_')])
def test_measured_assignment_scope(name):
    row = _ROWS[name]
    assert not row['errors']
    job = _run(row['source'])
    assert [m for m in job.messages if m.startswith('R[')] == row['miktex']


@pytest.mark.parametrize('name', [k for k in _ARCH if k.startswith('cross_kind_')])
def test_original_cross_kind_contexts(name):
    row = _ARCH[name]
    assert [m for m in _run(row['source']).messages if m.startswith('R[')] == row['miktex']


@pytest.mark.parametrize('globaldefs', [-1, 0, 1])
def test_local_guard_preserves_prefix_on_nested_exception(globaldefs):
    gs = GroupStack()
    gs.open_group(GroupKind.BRACE)
    gs.set_globaldefs_source(lambda: globaldefs)
    gs.set_global()
    with pytest.raises(RuntimeError), gs.local_assignment():
        assert not gs.assignment_is_global(command_global=True)
        gs.consume_global()
        with gs.local_assignment():
            gs.set_global()
            assert not gs.is_global_pending
        raise RuntimeError('probe')
    assert gs._global_pending
    assert gs.assignment_is_global() == (globaldefs >= 0)


def test_globaldefs_reads_old_value_before_its_own_assignment():
    from aspose_tex._engine.registers import RegisterSet
    gs = GroupStack()
    registers = RegisterSet(group_stack=gs)
    gs.set_globaldefs_source(lambda: registers.get_count(293, _internal=True))
    gs.open_group(GroupKind.BRACE)
    registers.set_count(293, 1, _internal=True)
    registers.set_count(293, 0, _internal=True)
    gs.close_group()
    assert registers.get_count(293, _internal=True) == 0


@pytest.mark.parametrize('name', [k for k in _ROWS if k.startswith('inline_')])
def test_inline_effective_scope_contexts(name):
    row = _ROWS[name]
    assert not row['errors']
    assert [m for m in _run(row['source']).messages if m.startswith('R[')] == row['miktex']


@pytest.mark.parametrize('name', [k for k in _ARCH if k.startswith('inline_')])
def test_original_inline_and_conversion_order_controls(name):
    row = _ARCH[name]
    assert [m for m in _run(row['source']).messages if m.startswith('R[')] == row['miktex']


@pytest.mark.parametrize('content', [
    r'\left(a$', r'\right)', 'a', '{a$',
    r'\hbox{$\count200=8 a', r'\hbox\bgroup$\count200=8 a',
])
@pytest.mark.parametrize('globaldefs,expected', [(1, 9), (-1, 5)])
def test_globaldefs_fatal_math_restores_only_owned_frames(content, globaldefs, expected):
    from aspose_tex import DviDevice, StringInputSource
    from aspose_tex._engine.interpreter import ModeKind, TeXInterpreter
    from aspose_tex.exceptions import EngineError
    messages = []
    interp = TeXInterpreter(load_format='plain', messages=messages)
    source = (r'\def\qa{\message{R[aborted]}}{\count200=5 $'
              + f'\\globaldefs={globaldefs} '
              + r'\global\count200=9 \aftergroup\qa ' + content)
    with pytest.raises(EngineError):
        interp.run_with_device(StringInputSource(source), DviDevice())
    if globaldefs > 0 and 'count200=8' in content:
        expected = 8  # The nested formula inherits positive globaldefs.
    assert 'R[aborted]' not in messages
    assert interp._group_stack.depth == 1
    assert interp._register_set.get_count(200) == expected
    assert interp._register_set.get_count(293, _internal=True) == 0
    assert interp._math_group_base is None
    assert interp._math_builder is None
    assert interp._math_tail_depths == []
    assert interp._math_shell._left_right_depth == 0
    assert interp._mode_stack.current == ModeKind.HORIZONTAL


@pytest.mark.parametrize('deferred', [False, True])
def test_nested_conversion_failure_restores_parent_builder(monkeypatch, deferred):
    from aspose_tex import DviDevice, StringInputSource
    from aspose_tex._engine.interpreter import TeXInterpreter
    from aspose_tex.exceptions import EngineError
    interp = TeXInterpreter(load_format='plain')
    original = interp.run_inline_math_in_box
    verified = []

    def nested(open_tok):
        parent = interp._math_builder
        groups = interp._group_stack.depth
        modes = interp._mode_stack.depth
        tails = list(interp._tail_providers)
        try:
            return original(open_tok)
        finally:
            assert interp._math_builder is parent
            assert interp._group_stack.depth == groups
            assert interp._mode_stack.depth == modes
            assert interp._tail_providers == tails
            verified.append(True)

    def fail(*args, **kwargs):
        raise EngineError('injected conversion failure')

    monkeypatch.setattr(interp, 'run_inline_math_in_box', nested)
    monkeypatch.setattr(interp, '_translate_mlist', fail)
    box = r'\hbox\bgroup' if deferred else r'\hbox{'
    close = r'\egroup' if deferred else '}'
    source = '$a' + box + r'$\globaldefs=1 \count200=9 a$' + close + 'b$'
    with pytest.raises(EngineError, match='injected conversion failure'):
        interp.run_with_device(StringInputSource(source), DviDevice())
    assert verified
    assert interp._register_set.get_count(200) == 9
