"""Tests for the aspose_tex MCP server tools.

The MCP surface is a thin wrapper over the public API, so these tests check that
each tool drives the library end to end and returns a well-formed result dict.
Skipped entirely when the optional ``mcp`` package is not installed.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="mcp package not installed (install aspose-tex-foss[mcp])")

from aspose_tex import __version__
from aspose_tex.mcp import compile_tex, tex_to_pdf, tex_to_svg, tex_version

_HELLO = "Hello World\n\\bye\n"


def test_tex_version_reports_version() -> None:
    result = tex_version()
    assert result["ok"] is True
    assert result["version"] == __version__


@pytest.mark.parametrize("fmt", ["pdf", "svg", "dvi"])
def test_compile_tex_writes_output(tmp_path: Path, fmt: str) -> None:
    out = tmp_path / f"out.{fmt}"
    result = compile_tex(_HELLO, str(out), fmt=fmt)
    assert result["ok"] is True
    assert result["format"] == fmt
    assert out.is_file() and out.stat().st_size > 0


def test_compile_tex_rejects_unknown_format(tmp_path: Path) -> None:
    result = compile_tex(_HELLO, str(tmp_path / "x.bin"), fmt="bogus")
    assert result["ok"] is False
    assert "unsupported format" in result["error"]


def test_convenience_pdf_and_svg(tmp_path: Path) -> None:
    pdf = tmp_path / "a.pdf"
    svg = tmp_path / "a.svg"
    assert tex_to_pdf(_HELLO, str(pdf))["ok"] is True
    assert tex_to_svg(_HELLO, str(svg))["ok"] is True
    assert pdf.is_file() and svg.is_file()


def test_mcp_module_starts() -> None:
    # The server should start and stay up (stdio transport blocks waiting for a
    # client); if it exits immediately, that's an import/startup failure.
    proc = subprocess.Popen(
        [sys.executable, "-m", "aspose_tex.mcp"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(0.5)
        rc = proc.poll()
        if rc is not None:
            _, err = proc.communicate(timeout=5)
            pytest.fail(f"MCP server exited early (rc={rc}):\n{err}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            proc.kill()
