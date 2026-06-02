from __future__ import annotations

from pathlib import Path


def test_production_code_does_not_write_stdout() -> None:
 root = Path(__file__).resolve().parent.parent / "src" / "aspose_tex"
 offenders: list[str] = []
 for path in root.rglob("*.py"):
 text = path.read_text(encoding="utf-8")
 if "print(" in text or "sys.stdout" in text:
 offenders.append(str(path.relative_to(root)))

 assert offenders == []
