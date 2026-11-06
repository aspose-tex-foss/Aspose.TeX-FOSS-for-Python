""" exact glue-setting regression guard; tolerances unchanged."""
from pathlib import Path

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob
from tests._verification.shipout_events import dvi_events
from tests.test_e2e_dvi_baseline import _FIXTURES, _baseline, _run


@pytest.mark.parametrize("name", _FIXTURES)
def test_corpus_exact(name):
    assert dvi_events(_run(name)) == dvi_events(_baseline(name))


def test_smoke_many_stretched_glues_exact():
    root = Path(__file__).parents[1] / "testdata"
    data = TeXJob(StringInputSource((root / "smoke_m2.tex").read_text()), DviDevice()).run()
    assert dvi_events(data) == dvi_events((root / "smoke_m2_miktex.dvi").read_bytes())
