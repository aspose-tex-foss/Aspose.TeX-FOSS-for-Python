"""exact TeX bytes across source and public API boundaries."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from aspose_tex import DviDevice, FileInputSource, StringInputSource, TeXJob, TeXOptions, create_input_source
from aspose_tex._fonts.font_manager import FontManager
from aspose_tex._input.reader import InputReader, InputSource
from aspose_tex.exceptions import EngineError, InputError
from tests._verification.dvi_walker import walk_chars_with_positions
from tests._verification.position_compare import TOL_H_SP, TOL_V_SP, compare_glyph_positions
from tests.test_e2e_dvi_baseline import _font_defs

EVIDENCE = Path(__file__).resolve().parents[1] / "testdata" / "reference" / "input_bytes"


def _lines(source):
    return list(iter(source.read_line, None))


def _font_positions(payload):
    fonts = []
    manager = FontManager()

    def width(font, code, at_sp):
        fonts.append((font, at_sp, code))
        key = f"{font}:{at_sp}"
        if manager.get_metrics(key) is None:
            manager.load_font(key, font, at_sp=at_sp)
        return manager.get_metrics(key).char_metrics(code).width

    return walk_chars_with_positions(payload, scaled_char_width=width), fonts


@pytest.mark.parametrize("code", range(256))
def test_all_raw_bytes(code, tmp_path):
    raw = bytes([code])
    path = tmp_path / "byte.tex"
    path.write_bytes(raw)
    expected = [chr(code)] if code not in (10, 13) else [""]
    assert _lines(FileInputSource(path)) == _lines(StringInputSource(raw)) == expected


@pytest.mark.parametrize("text,expected", [
    ("", []), ("\r", [""]), ("\n", [""]), ("\r\n", [""]),
    ("a\r\nb\rc\n", ["a", "b", "c"]), ("a\n\n", ["a", ""]),
    ("\x85\v\f\x1c\x1d\x1e\u2028\u2029", ["\x85\v\f\x1c\x1d\x1e\u2028\u2029"]),
])
def test_only_physical_newlines(text, expected, tmp_path):
    path = tmp_path / "lines.tex"
    path.write_bytes(text.encode())
    byte_expected = [line.encode().decode("latin-1") for line in expected]
    assert _lines(FileInputSource(path)) == _lines(StringInputSource(text)) == byte_expected
    assert _lines(StringInputSource(text.encode())) == byte_expected


def test_str_encodes_once_and_byte_locations():
    assert StringInputSource("\xe2").read_line() == "\xc3\xa2"
    assert StringInputSource(b"\xe2").read_line() == "\xe2"
    items = list(InputReader(StringInputSource("“^^e2X")))
    assert [(ord(c), loc.column) for c, loc in items] == [
        (226, 1), (128, 2), (156, 3), (226, 4), (88, 8), (13, 9),
    ]


def test_surrogate_has_named_input_error():
    with pytest.raises(InputError, match=r"bad\.tex") as caught:
        StringInputSource("\ud800", name="bad.tex")
    assert isinstance(caught.value.__cause__, UnicodeEncodeError)


def test_custom_source_never_reencodes():
    class Custom(InputSource):
        name = "custom"

        def __init__(self):
            self.lines = iter(["\xe2"])

        def read_line(self):
            return next(self.lines, None)

    assert [ord(c) for c, _ in InputReader(Custom())] == [226, 13]


@pytest.mark.parametrize("kind", ["file", "bytes", "str"])
def test_original_sample_public_api(kind):
    path = EVIDENCE / "sample-1.tex"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "2296e59d9200c6701c5b86ad686c487f7440de861aab2399e1a112c14a1063e7"
    source = {"file": path, "bytes": raw, "str": raw.decode()}[kind]
    job = TeXJob(create_input_source(source), DviDevice(), TeXOptions(load_format="plain"))
    ours = job.run()
    ref = (EVIDENCE / "sample-1.dvi").read_bytes()
    (ours_walk, ours_fonts), (ref_walk, ref_fonts) = _font_positions(ours), _font_positions(ref)
    assert ours_fonts == ref_fonts
    assert [len(p) for p in ours_walk] == [2943, 1282]
    assert compare_glyph_positions(ours_walk, ref_walk, h_tol_sp=TOL_H_SP, v_tol_sp=TOL_V_SP) == []
    assert {f[1:] for f in _font_defs(ours)} == {f[1:] for f in _font_defs(ref)}
    assert len([m for m in job.messages if m.startswith("Missing character:")]) == 6


@pytest.mark.parametrize("body", [
    "\\edef\\x{“}\\message{[\\x]}X", "% “\nX",
    "\\catcode226=9 \\catcode128=9 \\catcode156=9 A“B",
])
def test_tokens_warn_only_when_constructed(body):
    job = TeXJob(StringInputSource(body + r"\bye"), DviDevice())
    job.run()
    assert not any(m.startswith("Missing character:") for m in job.messages)
    if body.startswith(r"\edef"):
        assert "[\xe2\x80\x9c]" in job.messages


def test_nested_input_and_custom_format(tmp_path):
    (tmp_path / "child.tex").write_bytes(b"X\xff Y")
    (tmp_path / "custom.tex").write_bytes(
        b"\\font\\rm=cmr10 \\rm \\tracinglostchars=1 \\def\\saved{\xff} \\dump")
    job = TeXJob(StringInputSource(r"\input child \saved Z\end"), DviDevice(),
                 TeXOptions(load_format="custom", extra_format_paths=[tmp_path]))
    job.run()
    assert len([m for m in job.messages if "Missing character:" in m]) == 2


@pytest.mark.parametrize("body,error", [(r"\catcode255=15 ^^ff", InputError), (r"\undefinedCommand", EngineError)])
def test_real_errors_remain_errors(body, error):
    with pytest.raises(error):
        TeXJob(StringInputSource(body + r"\bye"), DviDevice()).run()
