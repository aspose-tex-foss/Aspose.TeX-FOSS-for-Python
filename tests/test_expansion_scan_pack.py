r""" expander regressions; text measured with MiKTeX 24.4 (2026-10-15)."""

import pytest

from aspose_tex.exceptions import EngineError
from tests.test_plain_tie import _run

WRAPPERS = [('', ''), ('x', 'y'), (r'\setbox0\hbox{', '}'),
            (r'\setbox0\vbox{', '}'), ('$', '$'), (r'\halign{#\cr ', r'x\cr}')]


def _messages(body):
    return [m for m in _run(body).messages if m.startswith('[')]


@pytest.mark.parametrize(('left', 'right'), WRAPPERS)
@pytest.mark.parametrize(('body', 'expected'), [
    (r'\ifnum1>0\fi\message{[ok]}', '[ok]'),
    (r'\message{[\ifnum1<0\else w\fi]}', '[w]'),
    (r'\ifdim1pt>0pt\fi\message{[ok]}', '[ok]'),
    (r'\ifdim\hsize>0pt\fi\message{[ok]}', '[ok]'),
    (r'\ifdim\lastskip>0pt\fi\message{[ok]}', '[ok]'),
    (r'\message{[\ifcase1\or B\else C\fi]}', '[B]'),
])
def test_pending_condition_scan(body, expected, left, right):
    assert _messages(left + body + right) == [expected]


@pytest.mark.parametrize('body', [
    r'\let\stop=\fi\ifnum1>0\stop\message{[ok]}',
    r'\let\otherwise=\else\message{[\ifdim0pt>1pt\otherwise ok\fi]}',
    r'\def\stop{\fi}\ifnum1>0\stop\message{[ok]}',
    r'\message{[\ifnum\ifnum1>0 1\else 2\fi=1 ok\else no\fi]}',
])
def test_pending_condition_alias_and_nested_controls(body):
    assert _messages(body) == ['[ok]']


@pytest.mark.parametrize(('left', 'right'), WRAPPERS)
@pytest.mark.parametrize(('body', 'expected'), [
    (r'\def\x{X}\toks0={\x}\edef\y{\the\toks0}\message{[\meaning\y]}', r'[macro:->\x ]'),
    (r'\def\x{X}\toks0={\x}\message{[\the\toks0]}', r'[\x ]'),
    (r'\def\x{X}\toks0={\x}\immediate\write16{[\the\toks0]}', r'[\x ]'),
    (r'\def\x{X}\toks0={\x\undefinedqq}\message{[a\the\toks0 b]}', r'[a\x \undefinedqq b]'),
    (r'\def\x{X}\toks0={\x}\toks1={\x}\edef\y{a\the\toks0\the\toks1 b}'
     r'\message{[\meaning\y]}', r'[macro:->a\x Xb]'),
    (r'\def\x{X}\toks0={\x}\toks1={\x}\edef\y{a\the\toks0 \the\toks1 b}'
     r'\message{[\meaning\y]}', r'[macro:->a\x \x b]'),
    (r'\def\x{X}\toks0={\x}\xdef\y{\the\toks0}\def\x{Y}\message{[\y]}', '[Y]'),
    (r'\def\x{X}\toks0={\x}\let\readtokens=\the\message{[\readtokens\toks0]}', r'[\x ]'),
    (r'\toks0={}\message{[a\the\toks0 b]}', '[ab]'),
    (r'\def\x{X}\everypar={\x}\edef\y{\the\everypar}\everypar={}\message{[\meaning\y]}',
     r'[macro:->\x ]'),
])
def test_the_output_is_appended_without_expansion(body, expected, left, right):
    assert _messages(left + body + right) == [expected]


def test_the_output_expands_when_executed_as_input():
    assert _messages(r'\def\x{\message{[X]}}\toks0={\x}\the\toks0') == ['[X]']


@pytest.mark.parametrize(('left', 'right'), WRAPPERS)
@pytest.mark.parametrize(('body', 'expected'), [
    (r'\message{[\the\font]}', r'[\tenrm ]'),
    (r'\message{[\the\tenrm]}', r'[\tenrm ]'),
    (r'\message{[\the\textfont0/\the\scriptfont0/\the\scriptscriptfont0]}',
     r'[\tenrm /\sevenrm /\fiverm ]'),
    (r'\let\roman=\tenrm\roman\message{[\the\font/\the\roman]}', r'[\tenrm /\tenrm ]'),
    (r'{\tenbf\message{[\the\font]}}\message{[\the\font]}', r'[\tenbf ]'),
    (r'\font\roman=cmr10\message{[\the\roman]}', r'[\roman ]'),
    (r'\message{[\the\textfont15]}', r'[\nullfont ]'),
    (r'\let\current=\font\message{[\the\current]}', r'[\tenrm ]'),
    (r'\let\family=\textfont\message{[\the\family0]}', r'[\tenrm ]'),
    (r'\edef\saved{\the\font}\message{[\meaning\saved]}', r'[macro:->\tenrm ]'),
])
def test_font_value_tokens(body, expected, left, right):
    messages = _messages(left + body + right)
    if body.startswith(r'{\tenbf'):
        assert messages == [expected, r'[\tenrm ]']
    else:
        assert messages == [expected]


def test_showthe_font_uses_identifier_text():
    assert '> \\tenrm .' in _run(r'\showthe\font').messages


@pytest.mark.parametrize(('left', 'right'), WRAPPERS)
@pytest.mark.parametrize('condition', ['if', 'ifcat'])
@pytest.mark.parametrize('operand', [r'\undefinedqq', r'\let\alias=\undefinedqq\alias'])
def test_undefined_expanded_condition_operand_raises(condition, operand, left, right):
    setup = ''
    name = 'undefinedqq'
    if operand.startswith(r'\let'):
        setup, operand = r'\let\alias=\undefinedqq ', r'\alias'
        name = 'alias'
    with pytest.raises(EngineError, match=rf'Undefined control sequence \\{name} at'):
        _run(setup + left + '\\message{[\\' + condition + r'\relax' + operand + r' T\else F\fi]}' + right)


@pytest.mark.parametrize(('left', 'right'), WRAPPERS)
@pytest.mark.parametrize(('body', 'expected'), [
    (r'\message{[\if\relax\noexpand\undefinedqq T\else F\fi]}', '[T]'),
    (r'\message{[\ifcat\relax\noexpand\undefinedqq T\else F\fi]}', '[T]'),
    (r'\message{[\if\noexpand\undefinedqq\relax T\else F\fi]}', '[T]'),
    (r'\def\x{X}\message{[\if\noexpand\x\relax T\else F\fi]}', '[T]'),
    (r'\message{[\ifcat\noexpand~\relax T\else F\fi]}', '[F]'),
    (r'\message{[\ifcat\noexpand~\noexpand~T\else F\fi]}', '[T]'),
    (r'\message{[\ifcat\noexpand abT\else F\fi]}', '[T]'),
    (r'\let\u=\undefinedqq\message{[\ifcat\noexpand\u\relax T\else F\fi]}', '[T]'),
])
def test_noexpand_operand_keeps_comparison_code(body, expected, left, right):
    assert _messages(left + body + right) == [expected]


def test_noexpand_operand_marker_does_not_leak_to_next_read():
    with pytest.raises(EngineError, match='Undefined control sequence'):
        _run(r'\message{[\ifcat\noexpand\undefinedqq\otherundefined T\else F\fi]}')


def test_deferred_write_keeps_token_list_output_unexpanded():
    assert _messages(r'\def\x{X}\toks0={\x}\write16{[\the\toks0]}x\def\x{Y}') == [r'[\x ]']


@pytest.mark.parametrize('condition', ['if', 'ifcat'])
def test_undefined_active_condition_operand_is_diagnosed(condition):
    with pytest.raises(EngineError, match='Undefined control sequence'):
        _run(r'\catcode`\!=13 \message{[' + '\\' + condition + r'\relax!T\else F\fi]}')


@pytest.mark.parametrize('condition', ['if', 'ifcat'])
def test_noexpand_preserves_undefined_active_category(condition):
    body = r'\catcode`\!=13 \message{[' + '\\' + condition + r'\noexpand!\noexpand!T\else F\fi]}'
    assert _messages(body) == ['[T]']


@pytest.mark.parametrize(('left', 'right'), WRAPPERS)
@pytest.mark.parametrize('condition', ['if', 'ifcat'])
@pytest.mark.parametrize('operand', [
    r'\expandafter\noexpand\undefinedqq',
    r'\expandafter\noexpand\expandafter\relax\undefinedqq',
    r'\romannumeral0\undefinedqq',
])
def test_recursive_operand_expansion_attempt_cannot_be_hidden(condition, operand, left, right):
    body = '\\message{[\\' + condition + operand + r'\relax T\else F\fi]}'
    with pytest.raises(EngineError, match=r'Undefined control sequence \\undefinedqq at'):
        _run(left + body + right)


@pytest.mark.parametrize(('left', 'right'), WRAPPERS)
@pytest.mark.parametrize('condition', ['if', 'ifcat'])
@pytest.mark.parametrize(('setup', 'operand'), [
    ('', r'\noexpand\undefinedqq'),
    ('', r'\expandafter\noexpand\relax'),
    (r'\def\bad{\undefinedqq}', r'\expandafter\noexpand\bad'),
    (r'\def\bad{\undefinedqq}\let\alias=\bad ', r'\expandafter\noexpand\alias'),
    (r'\def\bad{\other}\def\other{\undefinedqq}', r'\expandafter\noexpand\bad'),
    (r'\toks0={\undefinedqq}', r'\expandafter\noexpand\the\toks0'),
    ('', r'\expandafter\noexpand\iftrue\undefinedqq\fi'),
    (r'\catcode`\!=13 \def!{\undefinedqq}', r'\expandafter\noexpand!'),
])
def test_one_step_expansion_replacement_can_still_be_protected(condition, setup, operand, left, right):
    body = '\\message{[\\' + condition + operand + r'\relax T\else F\fi]}'
    assert _messages(setup + left + body + right) == ['[T]']
