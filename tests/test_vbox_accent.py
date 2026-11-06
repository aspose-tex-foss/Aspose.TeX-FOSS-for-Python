""": MiKTeX 24.4 measured context regressions."""

import pytest

from tests._verification.dvi_walker import walk_chars_with_positions
from tests.test_plain_tie import _run, _tfm_width

CASES = [
    ("accent", "\\vbox{\\noindent x\\accent19 o}", [[120, 0, 655360], [19, 345886, 655360], [111, 345886, 655360]], []),
    (
        "accent_empty",
        "\\vbox{\\noindent x\\accent19\\hbox{o}}",
        [[120, 0, 655360], [19, 345886, 655360], [111, 673567, 655360]],
        [],
    ),
]


@pytest.mark.parametrize("name,body,expected,messages", CASES, ids=[x[0] for x in CASES])
def test_miktex_positions(name, body, expected, messages):
    job = _run(body)
    pages = walk_chars_with_positions(job._dvi, _tfm_width()) if job._dvi else []
    actual = pages[0][:-1] if pages else []
    assert len(actual) == len(expected)
    for (c, h, v), (ec, eh, ev) in zip(actual, expected, strict=True):
        assert c == ec
        assert abs(h - eh) <= (1 if name == "adjust_display" else 0)
        assert v == ev
    assert [m for m in job.messages if m.startswith("[")] == messages
