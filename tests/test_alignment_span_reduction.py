"""Signed left-to-right span reduction, measured with MiKTeX."""
import pytest

from tests.test_alignment_noalign_execution import ARCH, EXTRA, assert_reference


@pytest.mark.parametrize('name', [n for n in ARCH if n.startswith('span_')])
def test_architecture_span_context(name):
    assert_reference(ARCH[name])


@pytest.mark.parametrize('name', [n for n in EXTRA if n.startswith('span_')])
def test_additional_span_context(name):
    assert_reference(EXTRA[name])
