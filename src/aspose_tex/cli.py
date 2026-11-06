"""Command-line interface for aspose-tex.

Run ``aspose-tex --help`` for usage. The CLI is a thin wrapper over the public
library API (:class:`~aspose_tex.TeXJob`, the output devices, and
:func:`~aspose_tex.create_input_source`); it adds no TeX processing logic of its
own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aspose_tex import (
    DviDevice,
    PdfDevice,
    SvgDevice,
    TeXJob,
    TeXOptions,
    __version__,
    create_input_source,
)

#: Output-format name -> output device class.
_DEVICES = {"pdf": PdfDevice, "svg": SvgDevice, "dvi": DviDevice}


def _cmd_compile(args: argparse.Namespace) -> int:
    """Compile a ``.tex`` file to the requested output format."""
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 2

    source = create_input_source(input_path)
    device = _DEVICES[args.format](Path(args.output))
    job = TeXJob(source, device, options=TeXOptions(load_format=args.load_format))
    job.run()
    print(f"wrote {args.format}: {args.output}")
    return 0


def _cmd_version(args: argparse.Namespace) -> int:
    """Print the library version."""
    print(__version__)
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    """Print basic information about a ``.tex`` input file."""
    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 2

    raw = input_path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    newline = "\n"
    has_bye = "\\bye" in text
    print(f"path={input_path}")
    print(f"bytes={len(raw)}")
    print(f"lines={text.count(newline) + 1}")
    print(f"has_bye={has_bye}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="aspose-tex",
        description="Pure-Python TeX/LaTeX processing. Compile TeX to PDF, SVG, or DVI.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p_compile = sub.add_parser("compile", help="Compile a .tex file to PDF/SVG/DVI")
    p_compile.add_argument("input", help="Path to the input .tex file")
    p_compile.add_argument("-o", "--output", required=True, help="Output file path")
    p_compile.add_argument(
        "--format",
        choices=sorted(_DEVICES),
        default="pdf",
        help="Output format (default: pdf)",
    )
    p_compile.add_argument(
        "--load-format",
        dest="load_format",
        default="plain",
        help="Format to preload before input ('plain' or 'false' to skip; default: plain)",
        type=_parse_load_format,
    )
    p_compile.set_defaults(func=_cmd_compile)

    p_version = sub.add_parser("version", help="Print the library version")
    p_version.set_defaults(func=_cmd_version)

    p_info = sub.add_parser("info", help="Inspect a .tex input file")
    p_info.add_argument("input", help="Path to the input .tex file")
    p_info.set_defaults(func=_cmd_info)

    return parser


def _parse_load_format(value: str) -> bool | str:
    """Interpret the ``--load-format`` value.

    ``"false"``/``"none"``/``"off"``/``""`` disable format loading; any other
    value is passed through as the format name (e.g. ``"plain"``).
    """
    if value.strip().lower() in {"false", "none", "off", ""}:
        return False
    return value


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``aspose-tex`` console script."""
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
