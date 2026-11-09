r"""register owners outrank built-in spellings; frozen primitives bypass owners.

Every expectation is the message MiKTeX 24.4 ``tex`` (plain)
prints for the same source, measured 2026-10-29.
"""
import warnings

import pytest

from aspose_tex import DviDevice, StringInputSource, TeXJob, TeXOptions


def _messages(source: str) -> list[str]:
    job = TeXJob(StringInputSource(source + "\n\\bye\n"), DviDevice(), options=TeXOptions(load_format="plain"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job.run()
    return [m for m in job.messages if m.startswith("R[")]


@pytest.mark.parametrize(("source", "expected"), [
    # repros: a \countdef owner named \count, a frozen \tolerance
    (r"\count1=5\countdef\count=1\message{R[\the\count]}", ["R[5]"]),
    (r"\tolerance=200\let\tol=\tolerance\chardef\tolerance=65\message{R[\the\tol]}", ["R[200]"]),
    # every owner family and reader
    (r"\dimen3=4pt\dimendef\dimen=3\message{R[\the\dimen]}", ["R[4.0pt]"]),
    (r"\skip3=4pt plus 1fil\skipdef\skip=3\message{R[\the\skip]}", ["R[4.0pt plus 1.0fil]"]),
    (r"\toks3={abc}\toksdef\toks=3\message{R[\the\toks]}", ["R[abc]"]),
    (r"\count1=5\countdef\count=1\message{R[\number\count]}", ["R[5]"]),
    (r"\count1=5\countdef\count=1\advance\count by 2 \message{R[\the\count]}", ["R[7]"]),
    (r"\dimen3=2pt\dimendef\dimen=3\dimendef\d=4 \d=3\dimen \message{R[\the\d]}", ["R[6.0pt]"]),
    (r"\tolerance=200\let\tol=\tolerance\chardef\tolerance=65\message{R[\number\tol]}", ["R[200]"]),
    # frozen \count reached through a \let made before the owner
    (r"\count1=5 \let\cc=\count \countdef\count=2 \message{R[\number\cc1]}", ["R[5]"]),
    (r"\count1=5 \let\cc=\count \countdef\count=2 \advance\cc1 by 3 \message{R[\the\cc1/\the\count]}",
     ["R[8/0]"]),
    # direct, alias and local-scope controls
    (r"\count1=7 \message{R[\the\count1]}", ["R[7]"]),
    (r"\count1=8 \let\cc=\count \message{R[\the\cc1]}", ["R[8]"]),
    (r"\countdef\count=1\message{R[\meaning\count]}", ["R[\\count1]"]),
])
def test_readers_resolve_the_current_meaning(source, expected):
    assert _messages(source) == expected


@pytest.mark.parametrize(("source", "expected"), [
    # repro: assignment to an owner named \count takes no index
    (r"\countdef\c=1\countdef\count=1\count=5\message{R[\the\c]}", ["R[5]"]),
    (r"\dimendef\d=3\dimendef\dimen=3\dimen=5pt\message{R[\the\d]}", ["R[5.0pt]"]),
    (r"\toksdef\t=3\toksdef\toks=3\toks={xyz}\message{R[\the\t]}", ["R[xyz]"]),
    # local and global scope through the owner
    (r"\countdef\c=1{\countdef\count=1\global\count=6 }\message{R[\the\c/\the\count1]}", ["R[6/6]"]),
    (r"\count1=3{\countdef\count=1\count=9 }\message{R[\the\count1]}", ["R[3]"]),
    (r"\count1=5{\countdef\count=1\count=9 \message{R[\the\count]}}\message{R[\the\count1]}",
     ["R[9]", "R[5]"]),
    # a frozen \count keeps scanning an index; the owner is assigned alongside
    (r"\count1=5 \let\cc=\count \countdef\count=2 \count=9 \message{R[\the\cc1/\the\count/\the\cc2]}",
     ["R[5/9/9]"]),
    (r"\let\cc=\count \countdef\count=2 \cc1=6 \message{R[\the\cc1/\the\count]}", ["R[6/0]"]),
    # direct-family, alias and frozen-primitive controls
    (r"\count1=5 \message{R[\the\count1]}", ["R[5]"]),
    (r"\let\cc=\count \cc1=6 \message{R[\the\count1]}", ["R[6]"]),
    (r"\let\tol=\tolerance \tol=300 \message{R[\the\tolerance]}", ["R[300]"]),
    # the same rule inside restricted box lists
    (r"\countdef\c=1\setbox0\hbox{\countdef\count=1\count=5 \global\c=\count}\message{R[\the\c]}", ["R[5]"]),
])
def test_assignments_resolve_the_current_meaning(source, expected):
    assert _messages(source) == expected
