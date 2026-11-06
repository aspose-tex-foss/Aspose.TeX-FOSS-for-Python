"""Tests for the ``aspose-tex`` command-line interface.

The CLI is a thin wrapper over the public API, so these tests focus on argument
dispatch, exit codes, and that each subcommand drives the library end to end and
writes a non-empty output file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aspose_tex import __version__
from aspose_tex.cli import main

# A minimal document that compiles without loading the full Plain TeX format.
_HELLO = "Hello World\n\\bye\n"


def _write_input(tmp_path: Path) -> Path:
    src = tmp_path / "in.tex"
    # Write bytes (not write_text) so the on-disk size is platform-independent;
    # write_text would translate "\n" to "\r\n" on Windows.
    src.write_bytes(_HELLO.encode("utf-8"))
    return src


def test_version_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0
    out = capsys.readouterr().out.strip()
    assert out == __version__


def test_global_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    # argparse `action="version"` exits with code 0 via SystemExit.
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_info_reports_basic_facts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = _write_input(tmp_path)
    assert main(["info", str(src)]) == 0
    out = capsys.readouterr().out
    assert f"bytes={len(_HELLO.encode('utf-8'))}" in out
    assert "has_bye=True" in out


def test_info_missing_file_returns_error(tmp_path: Path) -> None:
    assert main(["info", str(tmp_path / "nope.tex")]) == 2


@pytest.mark.parametrize("fmt", ["pdf", "svg", "dvi"])
def test_compile_writes_output(tmp_path: Path, fmt: str) -> None:
    src = _write_input(tmp_path)
    out = tmp_path / f"out.{fmt}"
    rc = main(["compile", str(src), "-o", str(out), "--format", fmt, "--load-format", "false"])
    assert rc == 0
    assert out.is_file()
    assert out.stat().st_size > 0


def test_compile_missing_input_returns_error(tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    rc = main(["compile", str(tmp_path / "nope.tex"), "-o", str(out), "--load-format", "false"])
    assert rc == 2


def test_no_command_errors() -> None:
    # Subcommand is required; argparse exits with code 2.
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
