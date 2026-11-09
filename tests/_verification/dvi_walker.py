"""DVI byte-stream walker — opcode-level position reconstruction.

Used by interpreter integration tests that need to compare paragraph
y-coordinates between our output and a MiKTeX baseline.  Walks the DVI
stream per TeX: The Program §583..§605, tracking (h, v) state across
push/pop frames so the first ``set_char`` at each new v-value can be
reported as the start of a new "line".

Factored out of ``tests/test_interpreter_output_routine.py``
so that ``tests/test_interpreter_integration.py`` can reuse the same
walker for the ``\\eject`` regression check.
"""
from __future__ import annotations

from collections.abc import Callable

_SET_CHAR_MAX = 127
_BOP = 139
_EOP = 140
_PRE = 247
_POST = 248
_DVI_ID = 2


def _signed(raw: bytes) -> int:
    n = int.from_bytes(raw, "big")
    bits = 8 * len(raw)
    if n & (1 << (bits - 1)):
        n -= 1 << bits
    return n


def _skip_preamble(dvi: bytes) -> int:
    assert dvi[0] == _PRE and dvi[1] == _DVI_ID
    k = dvi[14]
    return 15 + k


def walk_line_starts(dvi: bytes) -> list[list[tuple[int, int]]]:
    """Return ``[[(v, first_char_code), ...], ...]`` per DVI page.

    A "line" is a run of ``set_char`` opcodes at a common v-coordinate;
    the first ``set_char`` at each new v-value is recorded.  Operand sizes
    follow ``DVI v2``; opcodes outside the subset our DviWriter emits are
    still walked correctly so unexpected payloads cannot silently shift
    later positions.
    """
    i = _skip_preamble(dvi)
    n = len(dvi)
    pages: list[list[tuple[int, int]]] = []
    current: list[tuple[int, int]] | None = None
    h = v = w = x = y = z = 0
    stack: list[tuple[int, int, int, int, int, int]] = []
    last_line_v: int | None = None

    while i < n:
        op = dvi[i]
        if op == _POST:
            break
        if op == _BOP:
            current = []
            pages.append(current)
            h = v = w = x = y = z = 0
            stack = []
            last_line_v = None
            i += 1 + 44
            continue
        if op == _EOP:
            current = None
            i += 1
            continue

        # set_char_0..127 (0..127): typeset char at current (h, v).
        if op <= _SET_CHAR_MAX:
            if current is not None and v != last_line_v:
                current.append((v, op))
                last_line_v = v
            i += 1
            continue
        # set1..set4 (128..131): k-byte char code operand.
        if 128 <= op <= 131:
            kbytes = op - 127
            code = int.from_bytes(dvi[i + 1 : i + 1 + kbytes], "big")
            if current is not None and v != last_line_v:
                current.append((v, code))
                last_line_v = v
            i += 1 + kbytes
            continue

        # set_rule (132) / put_rule (137): 8-byte operands (h-advance only).
        if op == 132 or op == 137:
            i += 1 + 8
            continue
        # put1..put4 (133..136): k-byte char code, h unchanged.
        if 133 <= op <= 136:
            i += 1 + (op - 132)
            continue
        if op == 138:  # nop
            i += 1
            continue
        if op == 141:  # push
            stack.append((h, v, w, x, y, z))
            i += 1
            continue
        if op == 142:  # pop
            h, v, w, x, y, z = stack.pop()
            i += 1
            continue
        # right1..right4 (143..146): h += signed b
        if 143 <= op <= 146:
            kbytes = op - 142
            i += 1 + kbytes
            continue
        if op == 147:  # w0
            i += 1
            continue
        if 148 <= op <= 151:  # w1..w4
            kbytes = op - 147
            w = _signed(dvi[i + 1 : i + 1 + kbytes])
            i += 1 + kbytes
            continue
        if op == 152:  # x0
            i += 1
            continue
        if 153 <= op <= 156:  # x1..x4
            kbytes = op - 152
            x = _signed(dvi[i + 1 : i + 1 + kbytes])
            i += 1 + kbytes
            continue
        # down1..down4 (157..160): v += signed b
        if 157 <= op <= 160:
            kbytes = op - 156
            v += _signed(dvi[i + 1 : i + 1 + kbytes])
            i += 1 + kbytes
            continue
        if op == 161:  # y0
            v += y
            i += 1
            continue
        if 162 <= op <= 165:  # y1..y4
            kbytes = op - 161
            y = _signed(dvi[i + 1 : i + 1 + kbytes])
            v += y
            i += 1 + kbytes
            continue
        if op == 166:  # z0
            v += z
            i += 1
            continue
        if 167 <= op <= 170:  # z1..z4
            kbytes = op - 166
            z = _signed(dvi[i + 1 : i + 1 + kbytes])
            v += z
            i += 1 + kbytes
            continue
        if 171 <= op <= 234:  # fnt_num_i
            i += 1
            continue
        if 235 <= op <= 238:  # fnt1..fnt4
            i += 1 + (op - 234)
            continue
        if 239 <= op <= 242:  # xxx1..xxx4
            kbytes = op - 238
            length = int.from_bytes(dvi[i + 1 : i + 1 + kbytes], "big")
            i += 1 + kbytes + length
            continue
        if 243 <= op <= 246:  # fnt_def1..fnt_def4
            fn_bytes = op - 242
            base = i + 1 + fn_bytes + 4 + 4 + 4
            area_len = dvi[base]
            name_len = dvi[base + 1]
            i = base + 2 + area_len + name_len
            continue
        raise AssertionError(f"unexpected DVI opcode {op} at offset {i}")

    return pages


def read_first_char_v_per_line(dvi: bytes) -> list[list[int]]:
    """Return v-coordinates (sp) of the first char on each line, per page.

    Convenience wrapper around :func:`walk_line_starts` that drops the
    char-code half of each tuple — useful when callers only care about
    vertical layout.
    """
    return [[v for v, _ in lines] for lines in walk_line_starts(dvi)]


def walk_chars_with_positions(
    dvi: bytes,
    char_width: Callable[[str, int], int] | None = None,
    *,
    advance_rules: bool = False,
    rule_events: list[tuple[int, int, int, int]] | None = None,
    scaled_char_width: Callable[[str, int, int], int] | None = None,
) -> list[list[tuple[int, int, int]]]:
    """Return ``[[(char_code, h, v), ...], ...]`` per DVI page.

    Tracks (h, v) state across push/pop/down/right/y/z opcodes so each
    typeset character is reported at its absolute page coordinates (sp).
    Used by tests that need character-level position equivalence between
    output paths (e.g. the built-in fast-path vs plain.tex `\\plainoutput`).

    ``set_char``/``set1..4`` also move h right by the character's width,
    which the DVI does not carry.  Pass ``char_width(font_name, code)`` (sp)
    to get ``dvitype``'s h for a character set right after another one;
    without it h does not advance, which is exact only when every character
    is preceded by an explicit movement.

    Set ``advance_rules`` for painted-rule witnesses: set_rule moves h by
    its width, while put_rule does not. Legacy comparisons keep their existing
    convention unless they explicitly opt into full rule accounting.
    ``rule_events`` optionally collects painted ``(h, v, height, width)``
    rectangles using the same font and cursor state as the glyph walk.
    ``scaled_char_width(name, code, at_sp)`` optionally replaces ``char_width``
    for documents selecting the same TFM at several sizes (corpus).
    """
    i = _skip_preamble(dvi)
    n = len(dvi)
    pages: list[list[tuple[int, int, int]]] = []
    current: list[tuple[int, int, int]] | None = None
    h = v = w = x = y = z = 0
    stack: list[tuple[int, int, int, int, int, int]] = []
    fonts: dict[int, str] = {}
    font_sizes: dict[int, int] = {}
    font = ""
    font_size = 0

    while i < n:
        op = dvi[i]
        if op == _POST:
            break
        if op == _BOP:
            current = []
            pages.append(current)
            h = v = w = x = y = z = 0
            stack = []
            i += 1 + 44
            continue
        if op == _EOP:
            current = None
            i += 1
            continue
        if op <= _SET_CHAR_MAX:
            if current is not None:
                current.append((op, h, v))
            if scaled_char_width is not None:
                h += scaled_char_width(font, op, font_size)
            elif char_width is not None:
                h += char_width(font, op)
            i += 1
            continue
        if 128 <= op <= 131:
            kbytes = op - 127
            code = int.from_bytes(dvi[i + 1 : i + 1 + kbytes], "big")
            if current is not None:
                current.append((code, h, v))
            if scaled_char_width is not None:
                h += scaled_char_width(font, code, font_size)
            elif char_width is not None:
                h += char_width(font, code)
            i += 1 + kbytes
            continue
        if op == 132 or op == 137:
            if rule_events is not None:
                height = _signed(dvi[i + 1 : i + 5])
                width = _signed(dvi[i + 5 : i + 9])
                if height > 0 and width > 0:
                    rule_events.append((h, v, height, width))
            if op == 132 and advance_rules:
                h += _signed(dvi[i + 5 : i + 9])
            i += 1 + 8
            continue
        if 133 <= op <= 136:
            i += 1 + (op - 132)
            continue
        if op == 138:
            i += 1
            continue
        if op == 141:
            stack.append((h, v, w, x, y, z))
            i += 1
            continue
        if op == 142:
            h, v, w, x, y, z = stack.pop()
            i += 1
            continue
        if 143 <= op <= 146:
            kbytes = op - 142
            h += _signed(dvi[i + 1 : i + 1 + kbytes])
            i += 1 + kbytes
            continue
        if op == 147:
            h += w
            i += 1
            continue
        if 148 <= op <= 151:
            kbytes = op - 147
            w = _signed(dvi[i + 1 : i + 1 + kbytes])
            h += w
            i += 1 + kbytes
            continue
        if op == 152:
            h += x
            i += 1
            continue
        if 153 <= op <= 156:
            kbytes = op - 152
            x = _signed(dvi[i + 1 : i + 1 + kbytes])
            h += x
            i += 1 + kbytes
            continue
        if 157 <= op <= 160:
            kbytes = op - 156
            v += _signed(dvi[i + 1 : i + 1 + kbytes])
            i += 1 + kbytes
            continue
        if op == 161:
            v += y
            i += 1
            continue
        if 162 <= op <= 165:
            kbytes = op - 161
            y = _signed(dvi[i + 1 : i + 1 + kbytes])
            v += y
            i += 1 + kbytes
            continue
        if op == 166:
            v += z
            i += 1
            continue
        if 167 <= op <= 170:
            kbytes = op - 166
            z = _signed(dvi[i + 1 : i + 1 + kbytes])
            v += z
            i += 1 + kbytes
            continue
        if 171 <= op <= 234:
            font = fonts.get(op - 171, "")
            font_size = font_sizes.get(op - 171, 0)
            i += 1
            continue
        if 235 <= op <= 238:
            font_num = int.from_bytes(dvi[i + 1 : i + 1 + (op - 234)], "big")
            font = fonts.get(font_num, "")
            font_size = font_sizes.get(font_num, 0)
            i += 1 + (op - 234)
            continue
        if 239 <= op <= 242:
            kbytes = op - 238
            length = int.from_bytes(dvi[i + 1 : i + 1 + kbytes], "big")
            i += 1 + kbytes + length
            continue
        if 243 <= op <= 246:
            fn_bytes = op - 242
            base = i + 1 + fn_bytes + 4 + 4 + 4
            area_len = dvi[base]
            name_len = dvi[base + 1]
            name_at = base + 2 + area_len
            font_num = int.from_bytes(dvi[i + 1 : i + 1 + fn_bytes], "big")
            fonts[font_num] = dvi[name_at : name_at + name_len].decode("ascii")
            size_at = i + 1 + fn_bytes + 4
            font_sizes[font_num] = int.from_bytes(dvi[size_at : size_at + 4], "big")
            i = name_at + name_len
            continue
        raise AssertionError(f"unexpected DVI opcode {op} at offset {i}")

    return pages


def walk_rules(dvi: bytes) -> list[list[tuple[int, int, int, int]]]:
    """Return ``[[(h, v, height, width), ...], ...]`` per DVI page.

    Captures every ``set_rule`` (132) and ``put_rule`` (137) opcode at
    its absolute (h, v) coordinates. Plain TeX's ``\\footnoterule`` (a
    0.4pt rule = 26214 sp height) is the canonical consumer.
    """
    i = _skip_preamble(dvi)
    n = len(dvi)
    pages: list[list[tuple[int, int, int, int]]] = []
    current: list[tuple[int, int, int, int]] | None = None
    h = v = w = x = y = z = 0
    stack: list[tuple[int, int, int, int, int, int]] = []

    while i < n:
        op = dvi[i]
        if op == _POST:
            break
        if op == _BOP:
            current = []
            pages.append(current)
            h = v = w = x = y = z = 0
            stack = []
            i += 1 + 44
            continue
        if op == _EOP:
            current = None
            i += 1
            continue
        if op <= _SET_CHAR_MAX:
            i += 1
            continue
        if 128 <= op <= 131:
            i += 1 + (op - 127)
            continue
        if op == 132 or op == 137:
            height = _signed(dvi[i + 1 : i + 5])
            width = _signed(dvi[i + 5 : i + 9])
            if current is not None:
                current.append((h, v, height, width))
            i += 1 + 8
            continue
        if 133 <= op <= 136:
            i += 1 + (op - 132)
            continue
        if op == 138:
            i += 1
            continue
        if op == 141:
            stack.append((h, v, w, x, y, z))
            i += 1
            continue
        if op == 142:
            h, v, w, x, y, z = stack.pop()
            i += 1
            continue
        if 143 <= op <= 146:
            kbytes = op - 142
            h += _signed(dvi[i + 1 : i + 1 + kbytes])
            i += 1 + kbytes
            continue
        if op == 147:
            h += w
            i += 1
            continue
        if 148 <= op <= 151:
            kbytes = op - 147
            w = _signed(dvi[i + 1 : i + 1 + kbytes])
            h += w
            i += 1 + kbytes
            continue
        if op == 152:
            h += x
            i += 1
            continue
        if 153 <= op <= 156:
            kbytes = op - 152
            x = _signed(dvi[i + 1 : i + 1 + kbytes])
            h += x
            i += 1 + kbytes
            continue
        if 157 <= op <= 160:
            kbytes = op - 156
            v += _signed(dvi[i + 1 : i + 1 + kbytes])
            i += 1 + kbytes
            continue
        if op == 161:
            v += y
            i += 1
            continue
        if 162 <= op <= 165:
            kbytes = op - 161
            y = _signed(dvi[i + 1 : i + 1 + kbytes])
            v += y
            i += 1 + kbytes
            continue
        if op == 166:
            v += z
            i += 1
            continue
        if 167 <= op <= 170:
            kbytes = op - 166
            z = _signed(dvi[i + 1 : i + 1 + kbytes])
            v += z
            i += 1 + kbytes
            continue
        if 171 <= op <= 234:
            i += 1
            continue
        if 235 <= op <= 238:
            i += 1 + (op - 234)
            continue
        if 239 <= op <= 242:
            kbytes = op - 238
            length = int.from_bytes(dvi[i + 1 : i + 1 + kbytes], "big")
            i += 1 + kbytes + length
            continue
        if 243 <= op <= 246:
            fn_bytes = op - 242
            base = i + 1 + fn_bytes + 4 + 4 + 4
            area_len = dvi[base]
            name_len = dvi[base + 1]
            i = base + 2 + area_len + name_len
            continue
        raise AssertionError(f"unexpected DVI opcode {op} at offset {i}")

    return pages


def collect_chars_per_page(dvi: bytes) -> list[list[int]]:
    """Return the char-code stream of each DVI page (in emit order).

    Includes every ``set_char_*`` / ``set1..set4`` byte between BOP and EOP;
    movement and font opcodes are skipped.  Useful for checking *which*
    glyphs landed on which page without caring about positions.
    """
    i = _skip_preamble(dvi)
    n = len(dvi)
    pages: list[list[int]] = []
    current: list[int] | None = None

    while i < n:
        op = dvi[i]
        if op == _POST:
            break
        if op == _BOP:
            current = []
            pages.append(current)
            i += 1 + 44
            continue
        if op == _EOP:
            current = None
            i += 1
            continue
        if op <= _SET_CHAR_MAX:
            if current is not None:
                current.append(op)
            i += 1
            continue
        if 128 <= op <= 131:
            kbytes = op - 127
            if current is not None:
                current.append(int.from_bytes(dvi[i + 1 : i + 1 + kbytes], "big"))
            i += 1 + kbytes
            continue
        # set_rule (132) / put_rule (137): 8-byte operand, no char
        if op == 132 or op == 137:
            i += 1 + 8
            continue
        if 133 <= op <= 136:  # put1..put4 — char without h-advance
            kbytes = op - 132
            if current is not None:
                current.append(int.from_bytes(dvi[i + 1 : i + 1 + kbytes], "big"))
            i += 1 + kbytes
            continue
        if op == 138 or op == 141 or op == 142:  # nop, push, pop
            i += 1
            continue
        if 143 <= op <= 146:  # right1..right4
            i += 1 + (op - 142)
            continue
        if op == 147 or op == 152 or op == 161 or op == 166:  # w0/x0/y0/z0
            i += 1
            continue
        if 148 <= op <= 151:  # w1..w4
            i += 1 + (op - 147)
            continue
        if 153 <= op <= 156:  # x1..x4
            i += 1 + (op - 152)
            continue
        if 157 <= op <= 160:  # down1..down4
            i += 1 + (op - 156)
            continue
        if 162 <= op <= 165:  # y1..y4
            i += 1 + (op - 161)
            continue
        if 167 <= op <= 170:  # z1..z4
            i += 1 + (op - 166)
            continue
        if 171 <= op <= 234:  # fnt_num_i
            i += 1
            continue
        if 235 <= op <= 238:  # fnt1..fnt4
            i += 1 + (op - 234)
            continue
        if 239 <= op <= 242:  # xxx1..xxx4
            kbytes = op - 238
            length = int.from_bytes(dvi[i + 1 : i + 1 + kbytes], "big")
            i += 1 + kbytes + length
            continue
        if 243 <= op <= 246:  # fnt_def1..fnt_def4
            fn_bytes = op - 242
            base = i + 1 + fn_bytes + 4 + 4 + 4
            area_len = dvi[base]
            name_len = dvi[base + 1]
            i = base + 2 + area_len + name_len
            continue
        raise AssertionError(f"unexpected DVI opcode {op} at offset {i}")

    return pages
