"""Unit tests for the input reader layer.

Covers: FileInputSource, StringInputSource, InputReader,
 ^^ notation decoding, input stack, position tracking.
"""

from __future__ import annotations

import pathlib

import pytest

from aspose_tex._input.reader import (
 FileInputSource,
 InputReader,
 SourceLocation,
 StringInputSource,
 _expand_caret_caret,
)
from aspose_tex.exceptions import InputError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chars(reader: InputReader) -> list[str]:
 return [ch for ch, _ in reader]


def _locs(reader: InputReader) -> list[SourceLocation]:
 return [loc for _, loc in reader]


# ---------------------------------------------------------------------------
# FileInputSource
# ---------------------------------------------------------------------------

class TestFileInputSource:
 def test_reads_lines_without_newline(self, tmp_path: pathlib.Path) -> None:
 f = tmp_path / "test.tex"
 f.write_text("line one\nline two\n", encoding="utf-8")
 src = FileInputSource(f)
 assert src.read_line() == "line one"
 assert src.read_line() == "line two"
 assert src.read_line() is None

 def test_returns_none_on_empty_file(self, tmp_path: pathlib.Path) -> None:
 f = tmp_path / "empty.tex"
 f.write_text("", encoding="utf-8")
 src = FileInputSource(f)
 assert src.read_line() is None

 def test_name_is_path_string(self, tmp_path: pathlib.Path) -> None:
 f = tmp_path / "article.tex"
 f.write_text("x", encoding="utf-8")
 src = FileInputSource(f)
 assert src.name == str(f)

 def test_raises_input_error_on_missing_file(self, tmp_path: pathlib.Path) -> None:
 src = FileInputSource(tmp_path / "missing.tex")
 with pytest.raises(InputError, match="cannot open"):
 src.read_line()

 def test_crlf_stripped(self, tmp_path: pathlib.Path) -> None:
 f = tmp_path / "crlf.tex"
 f.write_bytes(b"hello\r\nworld\r\n")
 src = FileInputSource(f)
 assert src.read_line() == "hello"
 assert src.read_line() == "world"


# ---------------------------------------------------------------------------
# StringInputSource
# ---------------------------------------------------------------------------

class TestStringInputSource:
 def test_reads_from_str(self) -> None:
 src = StringInputSource("alpha\nbeta")
 assert src.read_line() == "alpha"
 assert src.read_line() == "beta"
 assert src.read_line() is None

 def test_reads_from_bytes(self) -> None:
 src = StringInputSource(b"alpha\nbeta")
 assert src.read_line() == "alpha"
 assert src.read_line() == "beta"
 assert src.read_line() is None

 def test_bytes_str_identical(self) -> None:
 text = "hello TeX\nworld"
 s1 = StringInputSource(text)
 s2 = StringInputSource(text.encode("utf-8"))
 lines1: list[str] = []
 while True:
 l1, l2 = s1.read_line(), s2.read_line()
 assert l1 == l2
 if l1 is None:
 break
 lines1.append(l1)
 assert lines1 == ["hello TeX", "world"]

 def test_default_name(self) -> None:
 src = StringInputSource("x")
 assert src.name == "<string>"

 def test_custom_name(self) -> None:
 src = StringInputSource("x", name="snippet.tex")
 assert src.name == "snippet.tex"

 def test_invalid_utf8_raises_input_error(self) -> None:
 with pytest.raises(InputError, match="not valid UTF-8"):
 StringInputSource(b"\xff\xfe invalid")

 def test_empty_string(self) -> None:
 src = StringInputSource("")
 assert src.read_line() is None


# ---------------------------------------------------------------------------
# _expand_caret_caret
# ---------------------------------------------------------------------------

class TestExpandCaretCaret:
 def test_hex_form_uppercase_A(self) -> None: # noqa: N802 — 'A' is the literal char under test
 result = _expand_caret_caret("^^41")
 assert result == [("A", 1)]

 def test_hex_form_cr(self) -> None:
 result = _expand_caret_caret("^^0d")
 assert result == [(chr(13), 1)]

 def test_single_char_M_gives_cr(self) -> None: # noqa: N802 — 'M' is the literal char under test
 # ord('M') = 77; 77 >= 64 → chr(77 - 64) = chr(13)
 result = _expand_caret_caret("^^M")
 assert result == [(chr(13), 1)]

 def test_single_char_at_gives_64(self) -> None:
 # ord('@') = 64; 64 >= 64 → chr(64 - 64) = chr(0)
 result = _expand_caret_caret("^^@")
 assert result == [(chr(0), 1)]

 def test_single_char_low_code(self) -> None:
 # ord('\x01') = 1; 1 < 64 → chr(1 + 64) = 'A'
 result = _expand_caret_caret("^^\x01")
 assert result == [("A", 1)]

 def test_hex_form_takes_precedence_over_single(self) -> None:
 # ^^4a — both '4' and 'a' are hex digits → chr(0x4a) = 'J'
 result = _expand_caret_caret("^^4a")
 assert result == [("J", 1)]

 def test_no_expansion_at_line_end(self) -> None:
 # ^^ with nothing following — no valid third char
 result = _expand_caret_caret("^^")
 assert result == [("^", 1), ("^", 2)]

 def test_only_one_caret_not_expanded(self) -> None:
 result = _expand_caret_caret("^A")
 assert result == [("^", 1), ("A", 2)]

 def test_column_reflects_original_position(self) -> None:
 # "ab^^41cd" — ^^ starts at index 2 (col 3)
 result = _expand_caret_caret("ab^^41cd")
 chars = [ch for ch, _ in result]
 cols = [col for _, col in result]
 assert chars == ["a", "b", "A", "c", "d"]
 assert cols == [1, 2, 3, 7, 8]

 def test_mixed_normal_and_expanded(self) -> None:
 result = _expand_caret_caret("x^^41y")
 chars = [ch for ch, _ in result]
 assert chars == ["x", "A", "y"]

 def test_uppercase_hex_not_expanded(self) -> None:
 # ^^4A — 'A' is not lowercase hex → single-char form on '4'
 # ord('4') = 52; 52 < 64 → chr(52 + 64) = chr(116) = 't'
 result = _expand_caret_caret("^^4A")
 assert result[0] == (chr(116), 1)
 assert result[1] == ("A", 4)


# ---------------------------------------------------------------------------
# InputReader — basic iteration
# ---------------------------------------------------------------------------

class TestInputReaderBasic:
 def test_iterates_chars_in_order(self) -> None:
 reader = InputReader(StringInputSource("Hi"))
 chars = _chars(reader)
 # "Hi" + chr(13) end-of-line
 assert chars == ["H", "i", chr(13)]

 def test_eol_appended_to_each_line(self) -> None:
 reader = InputReader(StringInputSource("a\nb"))
 chars = _chars(reader)
 assert chars == ["a", chr(13), "b", chr(13)]

 def test_empty_source_yields_nothing(self) -> None:
 reader = InputReader(StringInputSource(""))
 assert _chars(reader) == []

 def test_at_end_false_while_chars_remain(self) -> None:
 reader = InputReader(StringInputSource("x"))
 assert not reader.at_end

 def test_at_end_true_when_exhausted(self) -> None:
 reader = InputReader(StringInputSource(""))
 assert reader.at_end

 def test_at_end_false_when_peeked(self) -> None:
 reader = InputReader(StringInputSource("x"))
 reader.peek()
 assert not reader.at_end

 def test_multiline_char_count(self) -> None:
 reader = InputReader(StringInputSource("ab\ncd"))
 chars = _chars(reader)
 # a, b, \r, c, d, \r
 assert len(chars) == 6
 assert chars[2] == chr(13)
 assert chars[5] == chr(13)


# ---------------------------------------------------------------------------
# InputReader — position tracking
# ---------------------------------------------------------------------------

class TestInputReaderPositions:
 def test_line_numbers(self) -> None:
 reader = InputReader(StringInputSource("a\nb", name="f.tex"))
 locs = _locs(reader)
 line_nums = [loc.line for loc in locs]
 # a → line 1, eol → line 1, b → line 2, eol → line 2
 assert line_nums == [1, 1, 2, 2]

 def test_column_numbers(self) -> None:
 reader = InputReader(StringInputSource("abc", name="f.tex"))
 locs = _locs(reader)
 cols = [loc.column for loc in locs]
 # a=1, b=2, c=3, eol=4
 assert cols == [1, 2, 3, 4]

 def test_filename_in_location(self) -> None:
 reader = InputReader(StringInputSource("x", name="test.tex"))
 _, loc = next(iter(reader))
 assert loc.filename == "test.tex"

 def test_file_source_location(self, tmp_path: pathlib.Path) -> None:
 f = tmp_path / "pos.tex"
 f.write_text("AB", encoding="utf-8")
 reader = InputReader(FileInputSource(f))
 locs = _locs(reader)
 assert locs[0].filename == str(f)
 assert locs[0].line == 1
 assert locs[0].column == 1
 assert locs[1].column == 2


# ---------------------------------------------------------------------------
# InputReader — peek
# ---------------------------------------------------------------------------

class TestInputReaderPeek:
 def test_peek_nondestructive(self) -> None:
 reader = InputReader(StringInputSource("x"))
 p1 = reader.peek()
 p2 = reader.peek()
 assert p1 == p2

 def test_peek_then_iter_returns_same(self) -> None:
 reader = InputReader(StringInputSource("x"))
 peeked = reader.peek()
 first = next(iter(reader))
 assert peeked == first

 def test_peek_on_empty_returns_none(self) -> None:
 reader = InputReader(StringInputSource(""))
 assert reader.peek() is None


# ---------------------------------------------------------------------------
# InputReader — input stack (push / pop)
# ---------------------------------------------------------------------------

class TestInputReaderStack:
 def test_push_switches_source(self) -> None:
 reader = InputReader(StringInputSource("outer"))
 # consume 'o'
 chars = []
 it = iter(reader)
 chars.append(next(it)[0])
 # push inner source
 reader.push(StringInputSource("!"))
 # remaining chars from inner first, then outer resumes
 rest = [ch for ch, _ in reader]
 assert chars[0] == "o"
 assert rest[0] == "!"
 assert rest[1] == chr(13) # inner eol
 # outer continues: u, t, e, r, eol
 assert "u" in rest

 def test_inner_source_exhausted_resumes_outer(self) -> None:
 reader = InputReader(StringInputSource("AB"))
 reader.push(StringInputSource("!"))
 chars = _chars(reader)
 # inner: !, eol; outer: A, B, eol
 assert chars == ["!", chr(13), "A", "B", chr(13)]

 def test_explicit_pop(self) -> None:
 reader = InputReader(StringInputSource("outer"))
 reader.push(StringInputSource("inner"))
 reader.pop()
 # peek should now come from outer
 p = reader.peek()
 assert p is not None
 assert p[1].filename == "<string>"

 def test_pop_underflow_raises(self) -> None:
 reader = InputReader(StringInputSource("x"))
 # drain
 list(reader)
 with pytest.raises(InputError, match="underflow"):
 reader.pop()

 def test_push_invalidates_peek(self) -> None:
 reader = InputReader(StringInputSource("outer"))
 old_peek = reader.peek()
 reader.push(StringInputSource("!"))
 new_peek = reader.peek()
 # after push, peek should come from inner source
 assert new_peek is not None
 assert new_peek[0] == "!"
 assert old_peek is not None
 assert old_peek[0] == "o"


# ---------------------------------------------------------------------------
# InputReader — file vs string equivalence
# ---------------------------------------------------------------------------

class TestFileStringEquivalence:
 def test_identical_char_stream(self, tmp_path: pathlib.Path) -> None:
 text = "Hello TeX\n^^41 world\nend"
 f = tmp_path / "equiv.tex"
 f.write_text(text, encoding="utf-8")

 file_chars = _chars(InputReader(FileInputSource(f)))
 str_chars = _chars(InputReader(StringInputSource(text)))
 assert file_chars == str_chars


# ---------------------------------------------------------------------------
# InputReader — streaming (does not load whole file at once)
# ---------------------------------------------------------------------------

class TestStreaming:
 def test_large_file_no_memory_error(self, tmp_path: pathlib.Path) -> None:
 """100 000-line file iterated without MemoryError."""
 f = tmp_path / "large.tex"
 line = "x" * 80
 f.write_text("\n".join([line] * 100_000), encoding="utf-8")

 reader = InputReader(FileInputSource(f))
 count = sum(1 for _ in reader)
 # Each of the 100 000 lines has 80 chars + 1 eol = 81 chars per line
 assert count == 100_000 * 81


# ---------------------------------------------------------------------------
# InputReader — current_location accuracy
# ---------------------------------------------------------------------------

class TestCurrentLocation:
 def test_initial_location_before_any_read(self) -> None:
 reader = InputReader(StringInputSource("abc", name="t.tex"))
 loc = reader.current_location
 assert loc.filename == "t.tex"
 assert loc.line == 0
 assert loc.column == 0

 def test_column_after_first_char(self) -> None:
 reader = InputReader(StringInputSource("abc"))
 it = iter(reader)
 next(it) # 'a' at column 1
 assert reader.current_location.column == 1

 def test_column_after_second_char(self) -> None:
 reader = InputReader(StringInputSource("abc"))
 it = iter(reader)
 next(it) # 'a'
 next(it) # 'b' at column 2
 assert reader.current_location.column == 2

 def test_column_tracks_last_consumed(self) -> None:
 reader = InputReader(StringInputSource("xyz", name="f.tex"))
 locs_seen = []
 for _, loc in reader:
 locs_seen.append(loc)
 assert reader.current_location == loc

 def test_current_location_not_updated_by_peek(self) -> None:
 reader = InputReader(StringInputSource("ab"))
 reader.peek() # look ahead but do not consume
 assert reader.current_location.column == 0

 def test_current_location_after_multiline(self) -> None:
 reader = InputReader(StringInputSource("ab\ncd", name="m.tex"))
 list(reader) # consume to drive location update
 # last char is eol of line 2, which is at column len("cd")+1 = 3
 assert reader.current_location.line == 2
 assert reader.current_location.column == 3

 def test_current_location_on_exhausted_reader(self) -> None:
 reader = InputReader(StringInputSource("x", name="e.tex"))
 list(reader) # exhaust
 loc = reader.current_location
 assert loc.filename == "e.tex"
 assert loc.line == 1
 assert loc.column == 2 # eol char appended past end of "x"
