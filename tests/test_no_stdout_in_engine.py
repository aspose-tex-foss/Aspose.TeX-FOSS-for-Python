from __future__ import annotations

from pathlib import Path

# User-facing entry-point modules are allowed to write to stdout: printing
# results and diagnostics is their job. The rule exists to keep the *engine*
# and library internals silent, not the CLI/MCP/reporting surfaces.
_STDOUT_ALLOWED = {"cli.py", "mcp.py", "reporting.py"}


def test_production_code_does_not_write_stdout() -> None:
    root = Path(__file__).resolve().parent.parent / "src" / "aspose_tex"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if path.name in _STDOUT_ALLOWED and path.parent == root:
            continue
        text = path.read_text(encoding="utf-8")
        if "print(" in text or "sys.stdout" in text:
            offenders.append(str(path.relative_to(root)))

    assert offenders == []
