"""Tests for the dimension/glue parser.

Tests parse_integer, parse_dimen, parse_glue, and _scan_keyword in isolation
by building a real Expander from a string and driving the parser functions
directly.
"""

from __future__ import annotations

import pytest

from aspose_tex._engine.dimparser import (
    _scan_keyword,
    parse_dimen,
    parse_glue,
    parse_integer,
)
from aspose_tex._engine.expansion import Expander
from aspose_tex._engine.registers import GlueOrder, RegisterSet
from aspose_tex._input import (
    CatcodeTable,
    CharToken,
    InputReader,
    StringInputSource,
    Tokenizer,
)
from aspose_tex.exceptions import EngineError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_expander(text: str, regs: RegisterSet | None = None) -> Expander:
    src = StringInputSource(text)
    reader = InputReader(src)
    catcodes = CatcodeTable()
    tok = Tokenizer(reader, catcodes)
    exp = Expander(reader, tok, catcodes, register_provider=regs)
    if regs is not None:
        exp._register_set = regs
    return exp


# ---------------------------------------------------------------------------
# parse_integer
# ---------------------------------------------------------------------------

def test_parse_integer_decimal():
    exp = make_expander("42 ")
    assert parse_integer(exp) == 42


def test_parse_integer_negative():
    exp = make_expander("-17 ")
    assert parse_integer(exp) == -17


def test_parse_integer_plus_sign():
    exp = make_expander("+5 ")
    assert parse_integer(exp) == 5


def test_parse_integer_double_negative():
    exp = make_expander("--3 ")
    assert parse_integer(exp) == 3


def test_parse_integer_octal():
    # '77 octal = 63
    exp = make_expander("'77 ")
    assert parse_integer(exp) == 63


def test_parse_integer_hex_upper():
    # "FF hex = 255
    exp = make_expander('"FF ')
    assert parse_integer(exp) == 255


def test_parse_integer_hex_lower():
    exp = make_expander('"ff ')
    assert parse_integer(exp) == 255


def test_parse_integer_charcode():
    # `A = 65
    exp = make_expander("`A ")
    assert parse_integer(exp) == 65


def test_parse_integer_no_digits_raises():
    exp = make_expander("pt")
    with pytest.raises(EngineError):
        parse_integer(exp)


def test_parse_integer_allow_negative_false_raises():
    exp = make_expander("-5 ")
    with pytest.raises(EngineError):
        parse_integer(exp, allow_negative=False)


# ---------------------------------------------------------------------------
# parse_dimen
# ---------------------------------------------------------------------------

def test_parse_dimen_pt():
    exp = make_expander("1pt")
    assert parse_dimen(exp) == 65536


def test_parse_dimen_fraction():
    # 1.5pt = 65536 + 32768 = 98304
    exp = make_expander("1.5pt")
    assert parse_dimen(exp) == 98304


def test_parse_dimen_72_27pt():
    # MiKTeX 24.4: 72.27pt is 4736287sp, one more than 1in (4736286sp) —
    # .27 rounds to 17695/2^16 (§452), while 1in scales 1pt by 7227/100 (§458).
    exp = make_expander("72.27pt")
    assert parse_dimen(exp) == 4736287


def test_parse_dimen_in():
    exp = make_expander("1in")
    assert parse_dimen(exp) == 4736286


def test_parse_dimen_pc():
    exp = make_expander("1pc")
    assert parse_dimen(exp) == 786432


def test_parse_dimen_bp():
    exp = make_expander("1bp")
    assert parse_dimen(exp) == 65781


def test_parse_dimen_cm():
    # MiKTeX 24.4: 1cm = xn_over_d(1pt, 7227, 254) = 1864679sp (§458)
    exp = make_expander("1cm")
    assert parse_dimen(exp) == 1864679


def test_parse_dimen_mm():
    # MiKTeX 24.4: 1mm = 186467sp
    exp = make_expander("1mm")
    assert parse_dimen(exp) == 186467


def test_parse_dimen_dd():
    exp = make_expander("1dd")
    assert parse_dimen(exp) == 70124


def test_parse_dimen_cc():
    exp = make_expander("1cc")
    assert parse_dimen(exp) == 841489


def test_parse_dimen_sp():
    exp = make_expander("65536sp")
    assert parse_dimen(exp) == 65536


def test_parse_dimen_negative():
    exp = make_expander("-2pt")
    assert parse_dimen(exp) == -131072


def test_parse_dimen_overflow_raises():
    # MAX_DIMEN + 1 should raise
    # 16384pt = 16384 * 65536 = 1073741824 > MAX_DIMEN (1073741823)
    exp = make_expander("16384pt")
    with pytest.raises(EngineError, match="exceeds TeX maximum"):
        parse_dimen(exp)


def test_parse_dimen_unknown_unit_raises():
    exp = make_expander("1xy")
    with pytest.raises(EngineError, match="unknown dimension unit"):
        parse_dimen(exp)


def test_parse_dimen_mu_unit():
    """§4d — ``mu`` parses as 1pt-equivalent (math unit)."""
    exp = make_expander("3mu")
    assert parse_dimen(exp) == 3 * 65536


# ---------------------------------------------------------------------------
# parse_dimen — true* units (FR-16)
# ---------------------------------------------------------------------------

class _RegistryStub:
    """Stand-in for NamedParameterRegistry exposing only ``mag`` lookup."""

    def __init__(self, mag_slot: int) -> None:
        self._mag_slot = mag_slot

    def lookup(self, name: str):
        if name == "mag":
            class _Entry:
                slot = self._mag_slot
            return _Entry()
        return None


def _make_expander_with_mag(text: str, mag: int) -> Expander:
    """Build an expander whose ``\\mag`` slot is populated to ``mag``."""
    src = StringInputSource(text)
    reader = InputReader(src)
    catcodes = CatcodeTable()
    tok = Tokenizer(reader, catcodes)
    regs = RegisterSet()
    # Slot 297 is the catalog slot for \mag.  Use _internal=True
    # so we can write the named-param slot directly.
    regs.set_count(297, mag, _internal=True)
    exp = Expander(reader, tok, catcodes, register_provider=regs)
    exp._register_set = regs
    exp._named_params = _RegistryStub(mag_slot=297)
    return exp


def test_truept_default_mag():
    """With \\mag=1000, ``10truept`` == ``10pt`` == 655_360sp."""
    exp = _make_expander_with_mag("10truept", mag=1000)
    assert parse_dimen(exp) == 10 * 65536


def test_truept_mag_1200():
    """With \\mag=1200, ``10truept`` == floor(10 * 65536 * 1000 / 1200)."""
    exp = _make_expander_with_mag("10truept", mag=1200)
    assert parse_dimen(exp) == (10 * 65536 * 1000) // 1200


def test_truept_mag_500():
    """With \\mag=500, ``10truept`` is *larger* (the document is shrunk)."""
    exp = _make_expander_with_mag("10truept", mag=500)
    assert parse_dimen(exp) == (10 * 65536 * 1000) // 500


@pytest.mark.parametrize(
    "unit,miktex_sp",
    [
        # MiKTeX 24.4 with \mag=2000.  §457 halves the number first (5 -> 2.5)
        # and only then applies the unit, so 5truecm is 2.5cm = 4661699sp,
        # not half of 5cm.
        ("truept", 163840),
        ("truein", 11840716),
        ("truecm", 4661699),
        ("truemm", 466169),
        ("truebp", 164454),
        ("truepc", 1966080),
        ("truedd", 175310),
        ("truecc", 2103722),
        ("truesp", 2),
    ],
)
def test_true_units_apply_mag_correction(unit: str, miktex_sp: int) -> None:
    """Every ``true<unit>`` applies the ``1000/mag`` correction (AC-6)."""
    exp = _make_expander_with_mag(f"5{unit}", mag=2000)
    assert parse_dimen(exp) == miktex_sp


def test_unknown_truepx_raises():
    """``10truepx`` — ``px`` is not a known unit, registry should reject."""
    exp = _make_expander_with_mag("10truepx", mag=1000)
    with pytest.raises(EngineError, match="unknown dimension unit"):
        parse_dimen(exp)


def test_no_named_params_falls_back_to_mag_1000():
    """When ``_named_params`` is absent, ``true*`` defaults to mag=1000."""
    exp = make_expander("10truept")
    # Bare expander has no _named_params attribute → no scaling.
    assert parse_dimen(exp) == 10 * 65536


# ---------------------------------------------------------------------------
# parse_integer — count1<digit> concatenation regression (FR-17 / AC-5)
# ---------------------------------------------------------------------------

def test_parse_integer_two_digits():
    """parse_integer is greedy on contiguous digits — ``10`` yields 10."""
    exp = make_expander("10 ")
    assert parse_integer(exp) == 10


def test_parse_integer_count_index_two_digits():
    """``\\count`` then digits ``10`` reads slot 10 — primitive composition path."""
    src = StringInputSource(r"\count10 ")
    reader = InputReader(src)
    catcodes = CatcodeTable()
    tok = Tokenizer(reader, catcodes)
    regs = RegisterSet()
    regs.set_count(10, 7)
    exp = Expander(reader, tok, catcodes, register_provider=regs)
    exp._register_set = regs
    # parse_integer treats \count as register family then reads index 10
    assert parse_integer(exp) == 7


def test_count1_digit_concatenation_via_interpreter() -> None:
    """FR-17: ``\\count1#1`` from a macro reads as \\count<10..19> after expansion.

    Uses the full interpreter so macro expansion happens before the integer
    scanner sees the digits — the bug guarded against would split the leading
    ``1`` from the expanded ``#1`` and write \\count1 instead of \\count10.
    """
    from aspose_tex._engine.interpreter import TeXInterpreter
    from aspose_tex.presentation import DviDevice

    interp = TeXInterpreter()
    device = DviDevice()
    src = StringInputSource(
        r"\def\setn#1{\count1#1=#1 }"
        r"\setn 0\setn 5\bye"
    )
    interp.run_with_device(src, device)
    assert interp._register_set.get_count(10) == 0
    assert interp._register_set.get_count(15) == 5


# ---------------------------------------------------------------------------
# _scan_keyword
# ---------------------------------------------------------------------------

def test_scan_keyword_hit():
    exp = make_expander("plus ")
    assert _scan_keyword(exp, "plus") is True


def test_scan_keyword_miss():
    exp = make_expander("minus ")
    assert _scan_keyword(exp, "plus") is False
    # Tokens should be pushed back — stream still has "minus"
    assert _scan_keyword(exp, "minus") is True


def test_scan_keyword_case_insensitive():
    exp = make_expander("BY ")
    assert _scan_keyword(exp, "by") is True


def test_scan_keyword_partial_miss():
    exp = make_expander("plx ")
    assert _scan_keyword(exp, "plus") is False
    # Stream should be restored: can still read 'p'
    from aspose_tex._engine.dimparser import _next_raw
    tok = _next_raw(exp)
    assert isinstance(tok, CharToken) and tok.char == "p"


def test_scan_keyword_fil():
    exp = make_expander("fil ")
    assert _scan_keyword(exp, "filll") is False
    assert _scan_keyword(exp, "fill") is False
    assert _scan_keyword(exp, "fil") is True


def test_scan_keyword_fill():
    exp = make_expander("fill ")
    assert _scan_keyword(exp, "filll") is False
    assert _scan_keyword(exp, "fill") is True


def test_scan_keyword_filll():
    exp = make_expander("filll ")
    assert _scan_keyword(exp, "filll") is True


# ---------------------------------------------------------------------------
# parse_glue
# ---------------------------------------------------------------------------

def test_parse_glue_width_only():
    exp = make_expander("3pt")
    g = parse_glue(exp)
    assert g.width == 3 * 65536
    assert g.stretch == 0
    assert g.stretch_order == GlueOrder.NORMAL
    assert g.shrink == 0
    assert g.shrink_order == GlueOrder.NORMAL


def test_parse_glue_full():
    # 3pt plus 2pt minus 1pt (AC-5)
    exp = make_expander("3pt plus 2pt minus 1pt")
    g = parse_glue(exp)
    assert g.width == 3 * 65536
    assert g.stretch == 2 * 65536
    assert g.stretch_order == GlueOrder.NORMAL
    assert g.shrink == 1 * 65536
    assert g.shrink_order == GlueOrder.NORMAL


def test_parse_glue_no_shrink():
    exp = make_expander("3pt plus 1pt")
    g = parse_glue(exp)
    assert g.width == 3 * 65536
    assert g.stretch == 1 * 65536
    assert g.shrink == 0


def test_parse_glue_fil():
    # 0pt plus 1fil  (AC-6)
    exp = make_expander("0pt plus 1fil")
    g = parse_glue(exp)
    assert g.stretch == 65536  # §454: 1fil is unity, like \hfil
    assert g.stretch_order == GlueOrder.FIL


def test_parse_glue_fill():
    exp = make_expander("0pt plus 1fill")
    g = parse_glue(exp)
    assert g.stretch == 65536
    assert g.stretch_order == GlueOrder.FILL


def test_parse_glue_filll():
    exp = make_expander("0pt plus 1filll")
    g = parse_glue(exp)
    assert g.stretch == 65536
    assert g.stretch_order == GlueOrder.FILLL


def test_parse_glue_fil_shrink():
    exp = make_expander("0pt plus 0pt minus 2fil")
    g = parse_glue(exp)
    assert g.shrink == 131072
    assert g.shrink_order == GlueOrder.FIL


# ---------------------------------------------------------------------------
# fil units are unity-scaled like \hfil's built-in glue (TeX §454)
# ---------------------------------------------------------------------------

class TestFilUnitsScaled:
    r"""``<n>fil`` is stored as ``n * 2^16``, the scale ``\hfil``/``\hss`` use."""

    @pytest.mark.parametrize(
        ("spec", "stretch", "stretch_order", "shrink", "shrink_order"),
        [
            ("0pt plus 1fil", 65536, GlueOrder.FIL, 0, GlueOrder.NORMAL),
            ("0pt plus 2fill", 131072, GlueOrder.FILL, 0, GlueOrder.NORMAL),
            ("0pt plus -3filll", -196608, GlueOrder.FILLL, 0, GlueOrder.NORMAL),
            ("0pt plus 1pt minus 2fil", 65536, GlueOrder.NORMAL, 131072, GlueOrder.FIL),
            ("0pt plus --1fill minus -1fil", 65536, GlueOrder.FILL, -65536, GlueOrder.FIL),
        ],
    )
    def test_scanned_value(self, spec, stretch, stretch_order, shrink, shrink_order):
        g = parse_glue(make_expander(spec))
        assert (g.stretch, g.stretch_order) == (stretch, stretch_order)
        assert (g.shrink, g.shrink_order) == (shrink, shrink_order)

    def test_too_large_raises(self):
        # §454 rejects |cur_val| >= 2^30 for fil units as for pt.
        with pytest.raises(EngineError):
            parse_glue(make_expander("0pt plus 16384fil"))
        assert parse_glue(make_expander("0pt plus 16383fil")).stretch == 16383 * 65536

    @staticmethod
    def _run_plain(body: str):
        import warnings

        from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

        job = TeXJob(StringInputSource(body + r"\bye"), DviDevice(), options=TeXOptions())
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            dvi = job.run()
        return job, dvi

    def test_mixed_scanned_and_builtin_fil_split_evenly(self):
        r"""MiKTeX 24.4 ``dvitype`` h of ``A`` in each ``\hbox to 100pt``.

        A scanned ``plus 1fil`` must weigh the same as ``\hfil``; before the
        fix they split the free space 65536:1 and ``A`` sat at 92.5pt.
        """
        from tests._verification.dvi_walker import walk_chars_with_positions

        boxes = [
            r"\hfil A\hskip 0pt plus 1fil",
            r"\hfil A\hskip 0pt plus 2fil",
            r"\hskip 0pt plus 1fill A\hfill\hfill",
            r"\hss A\hskip 0pt plus 3fil",
            r"\hfil A\hskip 0pt plus -1fil\hskip 0pt plus 3fil",
        ]
        body = "".join(rf"\noindent\hbox to 100pt{{{b}}}\par" for b in boxes)
        _, dvi = self._run_plain(body)
        a_h = [h for code, h, _v in walk_chars_with_positions(dvi)[0] if code == ord("A")]
        assert a_h == [3031040, 2020693, 2020693, 1515520, 2020693]

    def test_the_fil_component_matches_miktex(self):
        r"""``\the`` prints fil amounts with §103 ``print_scaled`` as MiKTeX
        does: ``2.0fil``, and ``0.33333fil`` for a divided fil."""
        job, _ = self._run_plain(
            r"\skip0=1pt plus 2fil minus 3fill \message{[\the\skip0]}"
            r"\skip2=0pt plus 1fil \divide\skip2 by 3 \message{[\the\skip2]}"
        )
        msgs = [m for m in job.messages if m.startswith("[")]
        assert msgs == ["[1.0pt plus 2.0fil minus 3.0fill]", "[0.0pt plus 0.33333fil]"]

    def test_the_whole_fil_rescans_to_same_glue(self):
        job, _ = self._run_plain(
            r"\skip0=1pt plus 2fil minus 3filll \edef\x{\skip1=\the\skip0 }\x"
            r"\message{[\the\skip1]}"
        )
        msgs = [m for m in job.messages if m.startswith("[")]
        assert msgs == ["[1.0pt plus 2.0fil minus 3.0filll]"]


class TestFractionalFilUnits:
    r"""``1.5fil`` attaches its fraction like ``1.5pt`` (§452, §454)."""

    @pytest.mark.parametrize(
        ("spec", "stretch", "stretch_order", "shrink", "shrink_order"),
        [
            ("0pt plus 1.5fil", 98304, GlueOrder.FIL, 0, GlueOrder.NORMAL),
            ("0pt minus .25fill", 0, GlueOrder.NORMAL, 16384, GlueOrder.FILL),
            ("0pt plus -2.5filll", -163840, GlueOrder.FILLL, 0, GlueOrder.NORMAL),
            # §452 round_decimals, not a float: .33333 -> 21845
            ("1pt plus 0.33333fil minus 2.fil", 21845, GlueOrder.FIL, 131072, GlueOrder.FIL),
            # a decimal that is not followed by fil still scans as a dimen
            ("0pt plus 1.5pt minus .5fil", 98304, GlueOrder.NORMAL, 32768, GlueOrder.FIL),
        ],
    )
    def test_scanned_value(self, spec, stretch, stretch_order, shrink, shrink_order):
        g = parse_glue(make_expander(spec))
        assert (g.stretch, g.stretch_order) == (stretch, stretch_order)
        assert (g.shrink, g.shrink_order) == (shrink, shrink_order)

    def test_too_large_raises(self):
        assert parse_glue(make_expander("0pt plus 16383.99999fil")).stretch == 0x3FFFFFFF
        with pytest.raises(EngineError):
            parse_glue(make_expander("0pt plus 16384.0fil"))

    def test_fractional_and_whole_fil_share_the_box(self):
        r"""MiKTeX 24.4 ``dvitype`` h of ``A`` in each box."""
        from tests._verification.dvi_walker import walk_chars_with_positions

        boxes = [
            r"\hbox to 100pt{\hfil A\hskip 0pt plus 1.5fil}",
            r"\hbox to 100pt{\hskip 0pt plus .25fill A\hfill}",
            r"\hbox to 100pt{\hskip 0pt plus 1filll A"
            r"\hskip 0pt plus -2.5filll\hskip 0pt plus 4filll}",
            r"\hbox to 20pt{\hskip 0pt minus .5fil A\hskip 30pt minus 1fil}",
        ]
        body = "".join(rf"\noindent{b}\par" for b in boxes)
        _, dvi = TestFilUnitsScaled._run_plain(body)
        a_h = [h for code, h, _v in walk_chars_with_positions(dvi)[0] if code == ord("A")]
        assert a_h == [2424832, 1212416, 2424832, -382294]


# ---------------------------------------------------------------------------
# em / ex read the current font (TeX §455)
# ---------------------------------------------------------------------------

def _plain_widths(*boxes: str, preamble: str = "") -> list[int]:
    r"""Return ``\wd`` (sp) of ``\hbox{<box>}`` for each body, under plain TeX."""
    import warnings

    from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

    src = preamble + "".join(
        rf"\setbox0\hbox{{{body}}}\dimen0=\wd0 \message{{[\number\dimen0]}}"
        for body in boxes
    )
    job = TeXJob(StringInputSource(src + r"\end"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        job.run()
    return [int(m[1:-1]) for m in job.messages if m.startswith("[")]


class TestEmExUseCurrentFont:
    r"""Expected values are MiKTeX 24.4 plain ``\number\wd0`` of the same box."""

    @pytest.mark.parametrize(
        ("body", "miktex_sp"),
        [
            # cmr10: \fontdimen6 = 655361, \fontdimen5 = 282168 — not 10pt/4.3pt
            (r"\hskip1em", 655361),
            (r"\hskip2em", 1310722),
            (r"\hskip1ex", 282168),
            # the quad of the font in force, not cmr10's
            (r"\sevenrm\quad", 522469),
            (r"\tenbf\quad", 753660),
            (r"\font\twelverm=cmr12 \twelverm\hskip1em\hskip1ex", 1108643),
        ],
    )
    def test_matches_miktex(self, body: str, miktex_sp: int) -> None:
        assert _plain_widths(body) == [miktex_sp]

    @pytest.mark.parametrize(
        ("body", "miktex_sp"),
        [
            # §452/§455: the fraction is rounded to 2^-16, then xn_over_d
            (r"\hskip.3333em", 218430),
            (r"\sevenrm\hskip.123456789ex", 24385),
            (r"\hskip-1.5ex", -423252),
            (r"\tenit\hskip3.7em plus .5em minus 1ex", 2478701),
            # math mode still uses cur_font, not a math family
            (r"$\hskip1em$", 655361),
            # \nullfont's parameters are all zero
            (r"\nullfont\hskip1em", 0),
        ],
    )
    def test_fraction_sign_math_and_nullfont_match_miktex(
        self, body: str, miktex_sp: int
    ) -> None:
        assert _plain_widths(body) == [miktex_sp]

    def test_glue_stretch_and_shrink_use_the_current_font(self) -> None:
        r"""The ``plus``/``minus`` components scan em/ex in the same font."""
        import warnings

        from aspose_tex._engine.interpreter import TeXInterpreter
        from aspose_tex.presentation import DviDevice

        interp = TeXInterpreter()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            interp.run_with_device(
                StringInputSource(
                    r"\font\sevenrm=cmr7 \sevenrm"
                    r"\skip0=1em plus 2em minus 1ex \bye"
                ),
                DviDevice(),
            )
        g = interp._register_set.get_skip(0)
        # MiKTeX: 7.97224pt plus 15.94449pt minus 3.01389pt
        assert (g.width, g.stretch, g.shrink) == (522469, 1044938, 197518)

    def test_explicit_override_is_still_honoured(self) -> None:
        assert parse_dimen(make_expander("2em "), em_sp=100) == 200
        assert parse_dimen(make_expander("1ex "), ex_sp=7) == 7

    def test_bare_expander_has_nullfont_units(self) -> None:
        r"""No font manager wired means the current font is ``\nullfont``."""
        assert parse_dimen(make_expander("3em ")) == 0
        assert parse_glue(make_expander("1pt plus 1ex")).stretch == 0


# ---------------------------------------------------------------------------
# Fixed units round like TeX (TeX §452/§457/§458)
# ---------------------------------------------------------------------------

class TestFixedUnitsRoundLikeTeX:
    r"""Expected values are MiKTeX 24.4 plain ``\number\dimen0`` after ``\dimen0=<X>``."""

    @pytest.mark.parametrize(
        ("text", "miktex_sp"),
        [
            # §452: the decimal fraction is rounded to 2^-16, not truncated
            (".3pt", 19661),
            (".1pt", 6554),
            ("1.7pt", 111411),
            ("3.3pt", 216269),
            ("-.3pt", -19661),
            ("0.000007pt", 0),
            ("0.123456789123456789pt", 8091),  # digits past the 17th are ignored
            ("16383.99999pt", 1073741823),
            # §458: number and fraction are scaled together by num/denom
            (".33333in", 1578738),
            ("2.5in", 11840716),
            (".7pc", 550500),
            (".6pc", 471864),
            ("1.234pc", 970452),
            ("2.54cm", 4736274),
            (".5cm", 932339),
            ("12.7mm", 2368142),
            (".3mm", 55940),
            ("72.27bp", 4754048),
            (".5bp", 32890),
            ("7.5bp", 493363),
            ("1.5dd", 105186),
            (".3dd", 21037),
            ("12.5dd", 876551),
            ("100.5dd", 7047470),
            ("2.25cc", 1893350),
            (".1cc", 84154),
            (".6cc", 504898),
            # sp keeps the integer and drops the fraction
            ("1.9sp", 1),
            ("3.99999sp", 3),
            # §456: mu attaches its fraction exactly as pt does
            ("3.3mu", 216269),
        ],
    )
    def test_fixed_unit_matches_miktex(self, text: str, miktex_sp: int) -> None:
        assert parse_dimen(make_expander(text + " ")) == miktex_sp

    @pytest.mark.parametrize(
        ("text", "mag", "miktex_sp"),
        [
            # §457 divides number and fraction by mag/1000 before the unit
            (".3truept", 1095, 17955),
            ("2.7truein", 1095, 11678470),
            ("1.5truecm", 1095, 2554346),
            ("5truecm", 1095, 8514515),
            (".3truept", 1200, 16384),
            ("2.7truein", 1200, 10656572),
            ("1.5truecm", 2000, 1398509),
            ("2.7truein", 500, 25575919),
            # sp drops the fraction only after §457 has scaled it
            ("3.7truesp", 500, 7),
            ("1.5truesp", 500, 3),
        ],
    )
    def test_true_unit_with_fraction_matches_miktex(self, text: str, mag: int, miktex_sp: int) -> None:
        assert parse_dimen(_make_expander_with_mag(text, mag=mag)) == miktex_sp

    @pytest.mark.parametrize(
        ("text", "miktex_sp"),
        [
            # §455: a dimension used as the unit gets xn_over_d(v, f, 2^16);
            # \dimen1=1.1pt (72090sp), \dimen2=-3.7pt (-242483sp)
            (r"1.5\dimen1", 108135),
            (r"-.3\dimen1", -21627),
            (r".5\dimen2", -121241),
        ],
    )
    def test_dimension_as_unit_matches_miktex(self, text: str, miktex_sp: int) -> None:
        regs = RegisterSet()
        regs.set_dimen(1, 72090)
        regs.set_dimen(2, -242483)
        assert parse_dimen(make_expander(text + " ", regs)) == miktex_sp

    @pytest.mark.parametrize(
        ("kern", "miktex_sp"),
        [
            # a fractional \mkern scans with §452 rounding, then §716 mu_mult
            ("3.3mu", 120146),
            ("-3.3mu", -120146),
            (".1mu", 3641),
            ("1.7mu", 61893),
            ("2.25mu", 81918),
            ("18mu", 655344),
        ],
    )
    def test_fractional_mkern_matches_miktex(self, kern: str, miktex_sp: int) -> None:
        assert _plain_widths(rf"$\mkern{kern}$") == [miktex_sp]

    def test_plain_page_dimensions_match_miktex(self) -> None:
        r"""plain.tex's ``\hsize=6.5in`` and ``\vsize=8.9in`` land on MiKTeX's values."""
        assert _plain_widths(r"\hskip\hsize", r"\hskip\vsize") == [30785863, 42152922]


# ---------------------------------------------------------------------------
# Scanners read with expansion — get_x_token (TeX §380/§407/§440/§448)
# ---------------------------------------------------------------------------

def _plain_run(body: str):
    import warnings

    from aspose_tex.presentation import DviDevice, TeXJob, TeXOptions

    job = TeXJob(StringInputSource(body + r"\bye"), DviDevice(), options=TeXOptions())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dvi = job.run()
    return job, dvi


def _plain_messages(body: str) -> list[str]:
    job, _ = _plain_run(body)
    return [m for m in job.messages if m.startswith("[")]


def _tfm_char_width():
    """``char_width`` for the DVI walker: TFM widths at design size, as dvitype."""
    from aspose_tex._fonts.font_manager import FontManager

    mgr = FontManager()

    def width(font: str, code: int) -> int:
        if mgr.get_metrics(font) is None:
            mgr.load_font(font, font)
        return mgr.get_metrics(font).char_metrics(code).width

    return width


def _plain_glyph_h(body: str) -> list[tuple[int, int]]:
    r"""``(code, h)`` of every glyph on page 1 but the folio, as MiKTeX ``dvitype`` prints them."""
    from tests._verification.dvi_walker import walk_chars_with_positions

    _, dvi = _plain_run(body)
    return [(c, h) for c, h, _v in walk_chars_with_positions(dvi, _tfm_char_width())[0]][:-1]


class TestScannersExpandMacros:
    r"""Every expected value is MiKTeX 24.4 plain ``\message`` output of the same line."""

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # the six lines measured
            (r"\def\x{5}\count1=\x \message{[\the\count1]}", "[5]"),
            (r"\def\x{5}\dimen1=\x pt \message{[\the\dimen1]}", "[5.0pt]"),
            (r"\def\x{0.5}\dimen1=\x pt \message{[\the\dimen1]}", "[0.5pt]"),
            (r"\def\x{-5}\dimen1=\x pt \message{[\the\dimen1]}", "[-5.0pt]"),
            (r"\def\x{5pt}\dimen1=\x \message{[\the\dimen1]}", "[5.0pt]"),
            (
                r"\catcode`\@=11 \def\x{.5}\dimen@=2pt \setbox0\hbox{\kern\x\dimen@}"
                r"\dimen9=\wd0 \message{[\the\dimen9]}",
                "[1.0pt]",
            ),
            # keywords and units come from macros too (§407, §453)
            (r"\def\u{pt}\dimen1=5\u\message{[\the\dimen1]}", "[5.0pt]"),
            (r"\def\p{plus}\def\f{fil}\skip1=1pt\p 2\f\message{[\the\skip1]}", "[1.0pt plus 2.0fil]"),
            (r"\def\m{minus}\skip1=1pt plus 2pt\m 3pt\message{[\the\skip1]}", "[1.0pt plus 2.0pt minus 3.0pt]"),
            # digits, radix prefix and decimal point inside or around a macro
            (r"\def\y{1}\count1=1\y2\message{[\the\count1]}", "[112]"),
            (r"\def\h{" '"' r"}\count1=\h FF \message{[\the\count1]}", "[255]"),
            (r"\def\e{.}\dimen1=1\e5pt\message{[\the\dimen1]}", "[1.5pt]"),
            # conditionals expand while the number is scanned
            (r"\count1=\ifcase 1 5\or 6\fi \message{[\the\count1]}", "[6]"),
            (r"\newif\iffoo \count1=\iffoo 1\else 2\fi\message{[\the\count1]}", "[2]"),
            # \the after the digits is expanded into them, as in TeX
            (r"\count1=1 \count2=5\the\count1 \message{[\the\count2]}", "[51]"),
        ],
    )
    def test_line_matches_miktex(self, body: str, miktex: str) -> None:
        assert _plain_messages(body) == [miktex]

    @pytest.mark.parametrize(
        ("body", "miktex"),
        [
            # a command after the digits ends the number unexecuted: \global
            # must not leak onto the \count5 assignment, \def runs afterwards
            (r"{\count5=5\global\count6=3 }\message{[\the\count5,\the\count6]}", "[0,3]"),
            (r"{\count7=5\def\w{}\global\count8=6 }\message{[\the\count7,\the\count8]}", "[0,6]"),
            (r"{\dimen1=2pt\global\dimen2=3pt }\message{[\the\dimen1,\the\dimen2]}", "[0.0pt,3.0pt]"),
            # a \let alias is pushed back as itself (open-group box)
            (r"\setbox1\hbox to 20pt\bgroup\hfil x\egroup \dimen9=\wd1 \message{[\the\dimen9]}", "[20.0pt]"),
            (r"\let\q=\relax \count5=7\q \message{[\the\count5]}", "[7]"),
        ],
    )
    def test_command_after_number_is_not_executed_early(self, body: str, miktex: str) -> None:
        assert _plain_messages(body) == [miktex]

    def test_plain_d_and_b_accents_typeset(self) -> None:
        r"""plain ``\d``/``\b`` scan ``\kern\expandafter\getf@ctor\the\fontdimen1\font\dimen@``."""
        assert _plain_messages(
            r"\setbox0\hbox{\d o}\dimen9=\wd0 \message{[\the\dimen9]}"
            r"\setbox0\hbox{\b o}\dimen9=\wd0 \message{[\the\dimen9]}"
        ) == ["[5.00002pt]", "[5.00002pt]"]

    def test_plain_b_glyphs_at_miktex_positions(self) -> None:
        # MiKTeX 24.4 dvitype: o, then \b's o and bar (char 22), then o.
        assert _plain_glyph_h(r"\noindent o\b o o") == [(111, 0), (111, 327681), (22, 327681), (111, 873815)]

    def test_plain_d_letters_at_miktex_positions(self) -> None:
        # MiKTeX 24.4 dvitype: o 0, o 327681, dot 400497, o 873815.  The dot
        # The dot is also pinned in the full accent witness below;
        # now stores the glue ratio at TeX's single precision.
        glyphs = _plain_glyph_h(r"\noindent o\d o o")
        assert [g for g in glyphs if g[0] != ord(".")] == [(111, 0), (111, 327681), (111, 873815)]

    def test_plain_accent_line_matches_miktex_dvitype(self) -> None:
        assert _plain_glyph_h(r"\noindent\d o \b o {\it \d o \b a}") == [
            (111, 0), (46, 72816), (111, 546134), (22, 546134),
            (111, 1092268), (46, 1123990), (97, 1661699), (22, 1555885),
        ]


# ---------------------------------------------------------------------------
# A box dimension or \fontdimen used as a unit (TeX §455)
# ---------------------------------------------------------------------------

# \wd0 = 1.3in (6157186sp); box 1 is 2pt wide, 7pt high, 3pt deep.
_UNIT_BOXES = r"\setbox0\hbox{\hskip 1.3in}\setbox1\hbox{\vrule height 7pt depth 3pt width 2pt}"


class TestBoxAndFontDimensionsAsUnits:
    r"""Expected values are MiKTeX 24.4 plain ``\number\dimen0`` after the same input.

    ``\wd``/``\ht``/``\dp`` and ``\fontdimen`` were read as dimensions on their
    own but not as the unit of ``<number><internal dimen>``, so ``.5\wd0``
    raised "Dimension unit expected".
    """

    @pytest.mark.parametrize(
        ("assignment", "miktex_sp"),
        [
            (r"\dimen0=2.25\wd0", 13853670),
            (r"\dimen0=.5\fontdimen6\tenrm", 327680),
            (r"\dimen0=-.5\wd0", -3078593),
            (r"\dimen0=0.33333\wd0", 2052364),
            (r"\dimen0=3\wd1", 393216),
            (r"\dimen0=2\wd 1", 262144),
            (r"\dimen0=-2.5\ht1", -1146880),
            (r"\dimen0=.3\ht1", 137627),
            (r"\dimen0=1.5\dp1", 294912),
            (r"\dimen0=-1\dp1", -196608),
            (r"\dimen0=-.5\fontdimen2\font", -109226),
            (r"\dimen0=1.5\fontdimen5\tenrm", 423252),
            (r"\dimen0=.5\wd1 \advance\dimen0 by 1pt", 131072),
        ],
    )
    def test_assignment_matches_miktex(self, assignment: str, miktex_sp: int) -> None:
        assert _plain_messages(
            rf"{_UNIT_BOXES}{assignment}\message{{[\number\dimen0]}}"
        ) == [f"[{miktex_sp}]"]

    @pytest.mark.parametrize(
        ("box", "miktex_sp"),
        [
            (r"\hbox{\hskip 2.25\wd0}", 13853670),
            (r"\hbox{\hskip .5\fontdimen6\tenrm}", 327680),
            (r"\hbox{\kern-.5\wd1 x}", 280350),
            (r"\hbox to 10pt{\hskip 0pt plus .5\wd0 x}", 655360),
            (r"\hbox to 4pt{\hskip 10pt minus 2\ht1 x}", 262144),
        ],
    )
    def test_box_width_matches_miktex(self, box: str, miktex_sp: int) -> None:
        assert _plain_messages(
            rf"{_UNIT_BOXES}\setbox2{box}\dimen0=\wd2 \message{{[\number\dimen0]}}"
        ) == [f"[{miktex_sp}]"]

    @pytest.mark.parametrize(
        ("glue", "miktex"),
        [
            (r"1pt plus .5\wd1 minus 2\ht1", "1.0pt plus 1.0pt minus 14.0pt"),
            (r"1pt plus -1.5\fontdimen2\tenrm", "1.0pt plus -4.99998pt"),
        ],
    )
    def test_glue_components_match_miktex(self, glue: str, miktex: str) -> None:
        assert _plain_messages(
            rf"{_UNIT_BOXES}\skip3={glue} \message{{[\the\skip3]}}"
        ) == [f"[{miktex}]"]
