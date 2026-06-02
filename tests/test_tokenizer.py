"""Unit tests for the Tokenizer (N/M/S state machine).

Tests mirror test plan (tests/test_tokenizer.py section).
"""

import pytest

from aspose_tex._input.catcode import Catcode, CatcodeTable
from aspose_tex._input.reader import InputReader, StringInputSource
from aspose_tex._input.token import CharToken, ControlSequenceToken
from aspose_tex._input.tokenizer import Tokenizer
from aspose_tex.exceptions import InputError


def tokenize(text: str, catcodes: CatcodeTable | None = None) -> list:
 """Convenience helper: tokenize *text* with default (IniTeX) catcodes."""
 if catcodes is None:
 catcodes = CatcodeTable()
 reader = InputReader(StringInputSource(text))
 return list(Tokenizer(reader, catcodes))


# ---------------------------------------------------------------------------
# Helpers to build expected tokens
# ---------------------------------------------------------------------------

def cs(name: str) -> ControlSequenceToken:
 return ControlSequenceToken(name)


def ch(char: str, catcode: Catcode) -> CharToken:
 return CharToken(char, catcode)


L = Catcode.LETTER
OT = Catcode.OTHER
SP = Catcode.SPACE
BG = Catcode.BEGIN_GROUP
EG = Catcode.END_GROUP
MS = Catcode.MATH_SHIFT
AC = Catcode.ACTIVE
SS = Catcode.SUPERSCRIPT
SB = Catcode.SUBSCRIPT
PA = Catcode.PARAMETER


# ---------------------------------------------------------------------------
# Basic tokenization
# ---------------------------------------------------------------------------

class TestSimpleTokens:
 def test_simple_letters(self):
 """'Hello' → 5 LETTER CharTokens + trailing space from EOL."""
 tokens = tokenize("Hello")
 # EOL in state M produces a space token
 assert tokens == [
 ch("H", L), ch("e", L), ch("l", L), ch("l", L), ch("o", L),
 ch(" ", SP),
 ]

 def test_mixed_catcodes(self):
 """'Hi!' → letter, letter, OTHER + trailing space."""
 tokens = tokenize("Hi!")
 assert tokens == [
 ch("H", L), ch("i", L), ch("!", OT), ch(" ", SP),
 ]

 def test_digits_are_other(self):
 tokens = tokenize("42")
 assert tokens == [ch("4", OT), ch("2", OT), ch(" ", SP)]

 def test_begin_end_group(self):
 tokens = tokenize("{}")
 assert tokens == [ch("{", BG), ch("}", EG), ch(" ", SP)]

 def test_math_shift_token(self):
 tokens = tokenize("$x$")
 assert tokens == [
 ch("$", MS), ch("x", L), ch("$", MS), ch(" ", SP),
 ]

 def test_active_char_token(self):
 tokens = tokenize("~")
 assert tokens == [ch("~", AC), ch(" ", SP)]


# ---------------------------------------------------------------------------
# Control sequences
# ---------------------------------------------------------------------------

class TestControlSequences:
 def test_control_word(self):
 r"""\def → [CS("def")] (trailing EOL swallowed in state S→N)."""
 tokens = tokenize("\\def")
 assert tokens == [cs("def")]

 def test_control_symbol(self):
 r"""\! → [CS("!"), space from EOL (state M)]."""
 tokens = tokenize("\\!")
 assert tokens == [cs("!"), ch(" ", SP)]

 def test_control_word_skips_trailing_space(self):
 r"""\hello world — space after control word swallowed in state S."""
 tokens = tokenize("\\hello world")
 assert tokens == [
 cs("hello"),
 ch("w", L), ch("o", L), ch("r", L), ch("l", L), ch("d", L),
 ch(" ", SP),
 ]

 def test_control_symbol_keeps_space(self):
 r"""\! foo — space after control symbol NOT swallowed (state M)."""
 tokens = tokenize("\\! foo")
 assert tokens == [
 cs("!"), ch(" ", SP),
 ch("f", L), ch("o", L), ch("o", L),
 ch(" ", SP),
 ]

 def test_def_foo_bar(self):
 r"""\def\foo{bar} → expected sequence of control sequences and char tokens."""
 tokens = tokenize("\\def\\foo{bar}")
 assert tokens == [
 cs("def"), cs("foo"),
 ch("{", BG),
 ch("b", L), ch("a", L), ch("r", L),
 ch("}", EG),
 ch(" ", SP),
 ]

 def test_control_word_at_eof(self):
 r"""\relax with no trailing newline still produces the token."""
 # StringInputSource on empty last line: no trailing EOL after last line
 # BUT InputReader appends chr(13) at end of each line always.
 tokens = tokenize("\\relax")
 assert tokens == [cs("relax")]

 def test_control_word_multiple_letters(self):
 tokens = tokenize("\\textbf")
 assert tokens == [cs("textbf")]

 def test_backslash_space(self):
 r"""\ (backslash-space) → CS(" "), then state S."""
 tokens = tokenize("\\ x")
 # After CS(" ") we are in state S, so the literal space is skipped
 assert tokens == [cs(" "), ch("x", L), ch(" ", SP)]


# ---------------------------------------------------------------------------
# Comment stripping
# ---------------------------------------------------------------------------

class TestComments:
 def test_comment_stripped(self):
 r"""a%ignored\nb → comment consumed; state N before 'b'."""
 tokens = tokenize("a%comment\nb")
 # 'a' in state N → state M; '%' → skip to EOL, state N
 # 'b' in state N → state M; EOL → space
 assert tokens == [ch("a", L), ch("b", L), ch(" ", SP)]

 def test_comment_only_line(self):
 """A line consisting entirely of a comment produces no tokens."""
 tokens = tokenize("%everything\nok")
 assert tokens == [ch("o", L), ch("k", L), ch(" ", SP)]

 def test_comment_at_end_of_file(self):
 """Comment at the very end of input produces no tokens."""
 tokens = tokenize("x%trail")
 assert tokens == [ch("x", L)]


# ---------------------------------------------------------------------------
# State machine — spaces and blank lines
# ---------------------------------------------------------------------------

class TestStateMachine:
 def test_state_n_skips_leading_spaces(self):
 """Spaces at the start of a line (state N) are skipped."""
 tokens = tokenize(" Hello")
 assert tokens[0] == ch("H", L)

 def test_state_s_skips_multiple_spaces(self):
 r"""\word followed by many spaces — all swallowed in state S."""
 tokens = tokenize("\\word next")
 assert tokens == [cs("word"), ch("n", L), ch("e", L), ch("x", L), ch("t", L), ch(" ", SP)]

 def test_blank_line_produces_par(self):
 """A single blank line yields ControlSequenceToken('par')."""
 # "\n" → reader yields only chr(13) on the empty line
 tokens = tokenize("\n")
 assert cs("par") in tokens

 def test_multiple_blank_lines(self):
 """Two blank lines produce two \\par tokens."""
 tokens = tokenize("\n\n")
 par_count = sum(1 for t in tokens if t == cs("par"))
 assert par_count == 2

 def test_eol_in_mid_produces_space(self):
 """End-of-line in state M produces a space token."""
 tokens = tokenize("ab")
 assert tokens == [ch("a", L), ch("b", L), ch(" ", SP)]

 def test_space_in_mid_produces_space_token(self):
 tokens = tokenize("a b")
 assert tokens == [ch("a", L), ch(" ", SP), ch("b", L), ch(" ", SP)]

 def test_multiple_spaces_in_mid_one_token(self):
 """Multiple consecutive spaces in state M → one space token, rest swallowed."""
 tokens = tokenize("a b")
 # First space: state M → space token, state S
 # Remaining spaces: state S → swallowed
 assert tokens == [ch("a", L), ch(" ", SP), ch("b", L), ch(" ", SP)]


# ---------------------------------------------------------------------------
# Special catcodes: IGNORED, INVALID
# ---------------------------------------------------------------------------

class TestSpecialCatcodes:
 def test_ignored_char_skipped(self):
 """chr(0) (catcode IGNORED) produces no token and does not change state."""
 tokens = tokenize("a" + chr(0) + "b")
 assert tokens == [ch("a", L), ch("b", L), ch(" ", SP)]

 def test_invalid_char_raises(self):
 """chr(127) (catcode INVALID) raises InputError."""
 with pytest.raises(InputError):
 tokenize(chr(127))

 def test_parameter_token(self):
 tokens = tokenize("#1")
 assert tokens[0] == ch("#", PA)

 def test_superscript_token(self):
 # ^ is superscript catcode 7; InputReader already decoded ^^
 tokens = tokenize("x^2")
 assert tokens == [ch("x", L), ch("^", SS), ch("2", OT), ch(" ", SP)]

 def test_subscript_token(self):
 tokens = tokenize("x_i")
 assert tokens == [ch("x", L), ch("_", SB), ch("i", L), ch(" ", SP)]


# ---------------------------------------------------------------------------
# peek() — non-destructive lookahead
# ---------------------------------------------------------------------------

class TestPeek:
 def test_peek_nondestructive(self):
 """Two consecutive peek() calls return the same token."""
 reader = InputReader(StringInputSource("ab"))
 tok = Tokenizer(reader, CatcodeTable())
 p1 = tok.peek()
 p2 = tok.peek()
 assert p1 == p2 == ch("a", L)

 def test_peek_then_iter(self):
 """peek() followed by iteration consumes the peeked token first."""
 reader = InputReader(StringInputSource("ab"))
 tok = Tokenizer(reader, CatcodeTable())
 peeked = tok.peek()
 first = next(iter(tok))
 assert peeked == first == ch("a", L)

 def test_peek_on_empty_stream(self):
 """peek() returns None when the stream is exhausted."""
 reader = InputReader(StringInputSource(""))
 tok = Tokenizer(reader, CatcodeTable())
 # Empty string → reader gives only chr(13) in state N → \par
 # Consume it
 list(tok)
 assert tok.peek() is None


# ---------------------------------------------------------------------------
# Mutated catcode table
# ---------------------------------------------------------------------------

class TestMutatedCatcodes:
 def test_at_as_letter(self):
 """After setting @ to LETTER it is collected into control words."""
 tbl = CatcodeTable()
 tbl.set("@", Catcode.LETTER)
 tokens = tokenize("\\make@other", tbl)
 assert tokens[0] == cs("make@other")

 def test_digit_as_letter(self):
 tbl = CatcodeTable()
 tbl.set("1", Catcode.LETTER)
 tokens = tokenize("\\cmd1", tbl)
 # '1' is now LETTER so it is collected into the control word
 assert tokens[0] == cs("cmd1")
