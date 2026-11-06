""" scan-time owner transaction and hard-abort/save-history coverage."""
import json
from pathlib import Path

import pytest

from aspose_tex import DviDevice, StringInputSource
from aspose_tex._engine.interpreter import TeXInterpreter
from aspose_tex._engine.meanings import BindingKind
from aspose_tex.exceptions import EngineError, FontError
from tests.test_plain_tie import _run

_ROOT = Path(__file__).parents[1]
_ROWS = {}
for _path in ('testdata/reference/definition_scanning/guard_baseline.json',
              'testdata/reference/definition_scanning/scan_target_baseline.json'):
    for _name, _row in json.loads((_ROOT / _path).read_text()).items():
        _ROWS[_path + ':' + _name] = _row


@pytest.mark.parametrize('name', list(_ROWS))
def test_exact_preserved_timing_and_reader_witnesses(name):
    row = _ROWS[name]
    assert not row['errors']
    assert [m for m in _run(row['source']).messages if m.startswith('R[')] == row['miktex']


_DEFINITIONS = {
    'macro': (r'\def\q{outer}', r'\def\q{inner}'),
    'register': (r'\countdef\q=9\relax', r'\countdef\q=8\relax'),
    'constant': (r'\chardef\q=66\relax', r'\chardef\q=65\relax'),
    'font': (r'\font\q=cmr17\relax', r'\font\q=cmr7\relax'),
}


def _assert_owner(interp, owner, inner):
    binding = interp._bindings.binding_of('q')
    assert binding.kind is {'macro': BindingKind.MACRO, 'register': BindingKind.REGISTER,
                            'constant': BindingKind.CONSTANT, 'font': BindingKind.FONT}[owner]
    if owner == 'macro':
        assert ''.join(t.char for t in binding.value.replacement) == ('inner' if inner else 'outer')
    elif owner == 'register':
        assert binding.value == ('count', 8 if inner else 9)
    elif owner == 'constant':
        assert binding.value == ('chardef', 65 if inner else 66)
    else:
        assert interp._font_manager.font_name_text(binding.value) == ('cmr7' if inner else 'cmr17')


@pytest.mark.parametrize('outer', list(_DEFINITIONS))
@pytest.mark.parametrize('inner', list(_DEFINITIONS))
@pytest.mark.parametrize('global_prefix', ['', r'\global'])
@pytest.mark.parametrize('globaldefs', [-1, 0, 1])
@pytest.mark.parametrize('failure', [r'\font\q=missing401\relax', r'\countdef\q=256\relax'])
def test_failed_target_restores_all_owners_and_earlier_save_history(
        outer, inner, global_prefix, globaldefs, failure):
    interp = TeXInterpreter()
    source = (_DEFINITIONS[outer][0] + r'\textfont1=\tenrm{'
              + _DEFINITIONS[inner][1] + r'{\def\done{\message{R[bad]}}'
              + r'\globaldefs=' + str(globaldefs) + r'\relax\afterassignment\done'
              + global_prefix + failure)
    with pytest.raises((FontError, EngineError)):
        interp.run_with_device(StringInputSource(source), DviDevice())
    _assert_owner(interp, inner, True)
    fonts = interp._font_manager
    assert fonts.font_name_text(fonts.current_font_id) == 'cmr10'
    assert interp._math_family_registry.get_text(1) == fonts.font_id('tenrm')
    assert len(fonts._fonts) == 2 + (outer == 'font') + (inner == 'font')
    assert all(record.id_text == 'q' for record in fonts._fonts.values()
               if record.metrics.tfm_name in ('cmr7', 'cmr17'))
    assert not interp._group_stack._global_pending
    assert 'R[bad]' not in interp._messages
    interp._group_stack.close_group()
    _assert_owner(interp, inner, True)
    # A later local write after failed global must save the original local owner.
    interp._group_stack.open_group(interp._group_stack._frames[-1].kind)
    interp._register_set.define_constant('q', 'chardef', 67, is_global=False)
    interp._group_stack.close_group()
    _assert_owner(interp, inner, True)
    interp._group_stack.close_group()
    _assert_owner(interp, outer, False)


def test_failure_keeps_unrelated_csname_save_record_and_old_font_metadata():
    interp = TeXInterpreter()
    source = (r'\font\q=cmr17\let\old=\q{\font\q=cmr7{'
              r'\global\font\q=missing401 at\csname made401\endcsname')
    with pytest.raises(EngineError):
        interp.run_with_device(StringInputSource(source), DviDevice())
    fonts = interp._font_manager
    assert fonts.font_name_text(fonts.font_id('q')) == 'cmr7'
    assert fonts.font_name_text(fonts.font_id('old')) == 'cmr17'
    assert fonts.font_id_text(fonts.font_id('q')) == 'q'
    assert fonts.font_id_text(fonts.font_id('old')) == 'q'
    assert 'made401' in interp._expander._macros
    assert ('macro', 'made401') in interp._group_stack._frames[-1].saved_keys
    interp._group_stack.close_group()
    assert 'made401' not in interp._expander._macros
    assert fonts.font_name_text(fonts.font_id('q')) == 'cmr7'
    interp._group_stack.close_group()
    assert fonts.font_id('q') == fonts.font_id('old')


def test_failed_new_target_does_not_leave_provisional_binding():
    interp = TeXInterpreter()
    with pytest.raises(FontError):
        interp.run_with_device(StringInputSource(r'{\global\font\new401=missing401\relax'), DviDevice())
    assert interp._bindings.binding_of('new401') is None
    assert all(record.key[1] != 'new401' for record in interp._group_stack._save_records)
    interp._group_stack.close_group()
    assert interp._bindings.binding_of('new401') is None


_SCOPE_ROWS = json.loads((_ROOT / 'testdata/reference/definition_scanning/scan_scope.json').read_text())


@pytest.mark.parametrize('name', list(_SCOPE_ROWS))
def test_all_shorthand_definers_and_target_scope_matrix(name):
    row = _SCOPE_ROWS[name]
    assert row['match'] and not row['errors']
    assert [m for m in _run(row['source']).messages if m.startswith('R[')] == row['miktex']
