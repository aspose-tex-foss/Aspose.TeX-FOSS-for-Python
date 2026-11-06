"""MCP server for aspose_tex — run with ``python -m aspose_tex.mcp``.

Exposes the library as callable MCP tools (compile TeX to PDF/SVG/DVI, report
the version). Each tool is a thin wrapper over the public API and returns a
JSON-serialisable dict; it adds no TeX processing logic of its own.

The ``mcp`` package is an optional dependency::

    pip install aspose-tex[mcp]
"""

from __future__ import annotations

from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "aspose_tex MCP server requires the 'mcp' package: pip install aspose-tex[mcp]"
    ) from exc

from aspose_tex import (
    DviDevice,
    PdfDevice,
    SvgDevice,
    TeXJob,
    TeXOptions,
    __version__,
    create_input_source,
)

mcp = FastMCP("aspose-tex")

#: Output-format name -> output device class.
_DEVICES = {"pdf": PdfDevice, "svg": SvgDevice, "dvi": DviDevice}


def _err(exc: Exception | str) -> dict:
    """Build a uniform error result for a tool."""
    return {"ok": False, "error": str(exc)}


@mcp.tool()
def tex_version() -> dict:
    """Return the aspose-tex library version."""
    return {"ok": True, "version": __version__}


@mcp.tool()
def compile_tex(source: str, output_path: str, fmt: str = "pdf", load_format: bool = False) -> dict:
    """Compile a TeX source string to a file.

    Args:
        source: TeX input as a string (e.g. ``"Hello\\bye"``).
        output_path: Destination file path.
        fmt: Output format, one of ``pdf``, ``svg``, ``dvi``.
        load_format: Whether to preload the Plain TeX format before the input.

    Returns:
        ``{"ok": True, "output": ..., "format": ...}`` on success, otherwise
        ``{"ok": False, "error": ...}``.
    """
    try:
        if fmt not in _DEVICES:
            raise ValueError(f"unsupported format {fmt!r}; expected one of {sorted(_DEVICES)}")
        device = _DEVICES[fmt](Path(output_path))
        load = "plain" if load_format else False
        job = TeXJob(create_input_source(source), device, options=TeXOptions(load_format=load))
        job.run()
        return {"ok": True, "output": output_path, "format": fmt}
    except Exception as exc:  # tools must not raise across the MCP boundary
        return _err(exc)


@mcp.tool()
def tex_to_pdf(source: str, output_path: str, load_format: bool = False) -> dict:
    """Compile a TeX source string to a PDF file (convenience for ``compile_tex``)."""
    return compile_tex(source, output_path, fmt="pdf", load_format=load_format)


@mcp.tool()
def tex_to_svg(source: str, output_path: str, load_format: bool = False) -> dict:
    """Compile a TeX source string to an SVG file (convenience for ``compile_tex``)."""
    return compile_tex(source, output_path, fmt="svg", load_format=load_format)


if __name__ == "__main__":
    mcp.run()
