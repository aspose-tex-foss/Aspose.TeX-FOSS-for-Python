r""" leaders: MiKTeX 24.4 measured glyph and painted-rule events.

Expected coordinates are measured sp; full set_rule advancement is enabled
explicitly for these witnesses. Older walker callers keep their convention.
"""
from __future__ import annotations

import re
import warnings

import pytest

from aspose_tex import DviDevice, PdfDevice, StringInputSource, SvgDevice, TeXJob, TeXOptions
from aspose_tex._engine.leaders import leader_positions
from aspose_tex._engine.nodes import LeadersKind
from tests._verification.dvi_walker import walk_chars_with_positions, walk_rules
from tests.test_plain_tie import _tfm_width

# PDF/SVG write big points; a TeX pt is 72.27/72 bp smaller.
_SP_PER_BP = 65536 * 72.27 / 72

CASES = [['v_leaders_box',
  '\\vbox{\\kern3pt\\leaders\\hbox{A}\\vskip23pt\\hbox{Z}}',
  [[65, 0, 895656], [65, 0, 1343484], [90, 0, 2151764]],
  []],
 ['v_leaders_vbox',
  '\\vbox{\\kern3pt\\leaders\\vbox{\\hbox{A}}\\vskip23pt\\hbox{Z}}',
  [[65, 0, 895656], [65, 0, 1343484], [90, 0, 2151764]],
  []],
 ['v_leaders_rule',
  '\\vbox{\\leaders\\hrule width10pt\\vskip10pt\\hbox{Z}}',
  [[90, 0, 1103188]],
  [[0, 655360, 655360, 655360]]],
 ['v_leaders_rulebox',
  '\\vbox{\\kern3pt\\leaders\\hbox{\\vrule width2pt height3pt}\\vskip23pt}',
  [],
  [[0, 393216, 196608, 131072],
   [0, 589824, 196608, 131072],
   [0, 786432, 196608, 131072],
   [0, 983040, 196608, 131072],
   [0, 1179648, 196608, 131072],
   [0, 1376256, 196608, 131072],
   [0, 1572864, 196608, 131072]]],
 ['v_leaders_fil',
  '\\vbox to31pt{\\kern3pt\\leaders\\hbox{A}\\vfil\\hbox{Z}}',
  [[65, 0, 895656], [65, 0, 1343484], [90, 0, 2031616]],
  []],
 ['v_leaders_shrink',
  '\\vbox to25pt{\\leaders\\hbox{A}\\vskip30pt minus20pt\\hbox{Z}}',
  [[65, 0, 447828], [65, 0, 895656], [90, 0, 1638400]],
  []],
 ['v_leaders_deferred',
  '\\vbox\\bgroup\\kern3pt\\leaders\\hbox{A}\\vskip23pt\\hbox{Z}\\egroup',
  [[65, 0, 895656], [65, 0, 1343484], [90, 0, 2151764]],
  []],
 ['h_leaders_box',
  '\\hbox{\\kern3pt\\leaders\\hbox{A}\\hskip23pt Z}',
  [[65, 491521, 655360], [65, 983042, 655360], [90, 1703936, 655360]],
  []],
 ['h_leaders_vbox',
  '\\hbox{\\kern3pt\\leaders\\vbox{\\hbox{A}}\\hskip23pt Z}',
  [[65, 491521, 655360], [65, 983042, 655360], [90, 1703936, 655360]],
  []],
 ['h_leaders_rule',
  '\\hbox{\\leaders\\hrule height2pt depth1pt\\hskip10pt Z}',
  [[90, 655360, 655360]],
  [[0, 720896, 196608, 655360]]],
 ['h_leaders_rulebox',
  '\\hbox{\\kern3pt\\leaders\\hbox{\\vrule width2pt height3pt}\\hskip23pt}',
  [],
  [[262144, 655360, 196608, 131072],
   [393216, 655360, 196608, 131072],
   [524288, 655360, 196608, 131072],
   [655360, 655360, 196608, 131072],
   [786432, 655360, 196608, 131072],
   [917504, 655360, 196608, 131072],
   [1048576, 655360, 196608, 131072],
   [1179648, 655360, 196608, 131072],
   [1310720, 655360, 196608, 131072],
   [1441792, 655360, 196608, 131072],
   [1572864, 655360, 196608, 131072]]],
 ['h_leaders_fil',
  '\\hbox to31pt{\\kern3pt\\leaders\\hbox{A}\\hfil Z}',
  [[65, 491521, 655360], [65, 983042, 655360], [90, 1631118, 655360]],
  []],
 ['h_leaders_shrink',
  '\\hbox to25pt{\\leaders\\hbox{A}\\hskip30pt minus20pt Z}',
  [[65, 0, 655360], [65, 491521, 655360], [90, 1237902, 655360]],
  []],
 ['h_leaders_deferred',
  '\\hbox\\bgroup\\kern3pt\\leaders\\hbox{A}\\hskip23pt Z\\egroup',
  [[65, 491521, 655360], [65, 983042, 655360], [90, 1703936, 655360]],
  []],
 ['v_cleaders_box',
  '\\vbox{\\kern3pt\\cleaders\\hbox{A}\\vskip23pt\\hbox{Z}}',
  [[65, 0, 726363], [65, 0, 1174191], [65, 0, 1622019], [90, 0, 2151764]],
  []],
 ['v_cleaders_vbox',
  '\\vbox{\\kern3pt\\cleaders\\vbox{\\hbox{A}}\\vskip23pt\\hbox{Z}}',
  [[65, 0, 726363], [65, 0, 1174191], [65, 0, 1622019], [90, 0, 2151764]],
  []],
 ['v_cleaders_rule',
  '\\vbox{\\cleaders\\hrule width10pt\\vskip10pt\\hbox{Z}}',
  [[90, 0, 1103188]],
  [[0, 655360, 655360, 655360]]],
 ['v_cleaders_rulebox',
  '\\vbox{\\kern3pt\\cleaders\\hbox{\\vrule width2pt height3pt}\\vskip23pt}',
  [],
  [[0, 458757, 196608, 131072],
   [0, 655365, 196608, 131072],
   [0, 851973, 196608, 131072],
   [0, 1048581, 196608, 131072],
   [0, 1245189, 196608, 131072],
   [0, 1441797, 196608, 131072],
   [0, 1638405, 196608, 131072]]],
 ['v_cleaders_fil',
  '\\vbox to31pt{\\kern3pt\\cleaders\\hbox{A}\\vfil\\hbox{Z}}',
  [[65, 0, 666289], [65, 0, 1114117], [65, 0, 1561945], [90, 0, 2031616]],
  []],
 ['v_cleaders_shrink',
  '\\vbox to25pt{\\cleaders\\hbox{A}\\vskip30pt minus20pt\\hbox{Z}}',
  [[65, 0, 595291], [65, 0, 1043119], [90, 0, 1638400]],
  []],
 ['v_cleaders_deferred',
  '\\vbox\\bgroup\\kern3pt\\cleaders\\hbox{A}\\vskip23pt\\hbox{Z}\\egroup',
  [[65, 0, 726363], [65, 0, 1174191], [65, 0, 1622019], [90, 0, 2151764]],
  []],
 ['h_cleaders_box',
  '\\hbox{\\kern3pt\\cleaders\\hbox{A}\\hskip23pt Z}',
  [[65, 212995, 655360], [65, 704516, 655360], [65, 1196037, 655360], [90, 1703936, 655360]],
  []],
 ['h_cleaders_vbox',
  '\\hbox{\\kern3pt\\cleaders\\vbox{\\hbox{A}}\\hskip23pt Z}',
  [[65, 212995, 655360], [65, 704516, 655360], [65, 1196037, 655360], [90, 1703936, 655360]],
  []],
 ['h_cleaders_rule',
  '\\hbox{\\cleaders\\hrule height2pt depth1pt\\hskip10pt Z}',
  [[90, 655360, 655360]],
  [[0, 720896, 196608, 655360]]],
 ['h_cleaders_rulebox',
  '\\hbox{\\kern3pt\\cleaders\\hbox{\\vrule width2pt height3pt}\\hskip23pt}',
  [],
  [[229381, 655360, 196608, 131072],
   [360453, 655360, 196608, 131072],
   [491525, 655360, 196608, 131072],
   [622597, 655360, 196608, 131072],
   [753669, 655360, 196608, 131072],
   [884741, 655360, 196608, 131072],
   [1015813, 655360, 196608, 131072],
   [1146885, 655360, 196608, 131072],
   [1277957, 655360, 196608, 131072],
   [1409029, 655360, 196608, 131072],
   [1540101, 655360, 196608, 131072]]],
 ['h_cleaders_fil',
  '\\hbox to31pt{\\kern3pt\\cleaders\\hbox{A}\\hfil Z}',
  [[65, 422347, 655360], [65, 913868, 655360], [90, 1631118, 655360]],
  []],
 ['h_cleaders_shrink',
  '\\hbox to25pt{\\cleaders\\hbox{A}\\hskip30pt minus20pt Z}',
  [[65, 127435, 655360], [65, 618956, 655360], [90, 1237902, 655360]],
  []],
 ['h_cleaders_deferred',
  '\\hbox\\bgroup\\kern3pt\\cleaders\\hbox{A}\\hskip23pt Z\\egroup',
  [[65, 212995, 655360], [65, 704516, 655360], [65, 1196037, 655360], [90, 1703936, 655360]],
  []],
 ['v_xleaders_box',
  '\\vbox{\\kern3pt\\xleaders\\hbox{A}\\vskip23pt\\hbox{Z}}',
  [[65, 0, 685400], [65, 0, 1174191], [65, 0, 1662982], [90, 0, 2151764]],
  []],
 ['v_xleaders_vbox',
  '\\vbox{\\kern3pt\\xleaders\\vbox{\\hbox{A}}\\vskip23pt\\hbox{Z}}',
  [[65, 0, 685400], [65, 0, 1174191], [65, 0, 1662982], [90, 0, 2151764]],
  []],
 ['v_xleaders_rule',
  '\\vbox{\\xleaders\\hrule width10pt\\vskip10pt\\hbox{Z}}',
  [[90, 0, 1103188]],
  [[0, 655360, 655360, 655360]]],
 ['v_xleaders_rulebox',
  '\\vbox{\\kern3pt\\xleaders\\hbox{\\vrule width2pt height3pt}\\vskip23pt}',
  [],
  [[0, 409602, 196608, 131072],
   [0, 622595, 196608, 131072],
   [0, 835588, 196608, 131072],
   [0, 1048581, 196608, 131072],
   [0, 1261574, 196608, 131072],
   [0, 1474567, 196608, 131072],
   [0, 1687560, 196608, 131072]]],
 ['v_xleaders_fil',
  '\\vbox to31pt{\\kern3pt\\xleaders\\hbox{A}\\vfil\\hbox{Z}}',
  [[65, 0, 655363], [65, 0, 1114117], [65, 0, 1572871], [90, 0, 2031616]],
  []],
 ['v_xleaders_shrink',
  '\\vbox to25pt{\\xleaders\\hbox{A}\\vskip30pt minus20pt\\hbox{Z}}',
  [[65, 0, 546137], [65, 0, 1092273], [90, 0, 1638400]],
  []],
 ['v_xleaders_deferred',
  '\\vbox\\bgroup\\kern3pt\\xleaders\\hbox{A}\\vskip23pt\\hbox{Z}\\egroup',
  [[65, 0, 685400], [65, 0, 1174191], [65, 0, 1662982], [90, 0, 2151764]],
  []],
 ['h_xleaders_box',
  '\\hbox{\\kern3pt\\xleaders\\hbox{A}\\hskip23pt Z}',
  [[65, 204802, 655360], [65, 704516, 655360], [65, 1204230, 655360], [90, 1703936, 655360]],
  []],
 ['h_xleaders_vbox',
  '\\hbox{\\kern3pt\\xleaders\\vbox{\\hbox{A}}\\hskip23pt Z}',
  [[65, 204802, 655360], [65, 704516, 655360], [65, 1204230, 655360], [90, 1703936, 655360]],
  []],
 ['h_xleaders_rule',
  '\\hbox{\\xleaders\\hrule height2pt depth1pt\\hskip10pt Z}',
  [[90, 655360, 655360]],
  [[0, 720896, 196608, 655360]]],
 ['h_xleaders_rulebox',
  '\\hbox{\\kern3pt\\xleaders\\hbox{\\vrule width2pt height3pt}\\hskip23pt}',
  [],
  [[202071, 655360, 196608, 131072],
   [338605, 655360, 196608, 131072],
   [475139, 655360, 196608, 131072],
   [611673, 655360, 196608, 131072],
   [748207, 655360, 196608, 131072],
   [884741, 655360, 196608, 131072],
   [1021275, 655360, 196608, 131072],
   [1157809, 655360, 196608, 131072],
   [1294343, 655360, 196608, 131072],
   [1430877, 655360, 196608, 131072],
   [1567411, 655360, 196608, 131072]]],
 ['h_xleaders_fil',
  '\\hbox to31pt{\\kern3pt\\xleaders\\hbox{A}\\hfil Z}',
  [[65, 347101, 655360], [65, 989114, 655360], [90, 1631118, 655360]],
  []],
 ['h_xleaders_shrink',
  '\\hbox to25pt{\\xleaders\\hbox{A}\\hskip30pt minus20pt Z}',
  [[65, 84957, 655360], [65, 661434, 655360], [90, 1237902, 655360]],
  []],
 ['h_xleaders_deferred',
  '\\hbox\\bgroup\\kern3pt\\xleaders\\hbox{A}\\hskip23pt Z\\egroup',
  [[65, 204802, 655360], [65, 704516, 655360], [65, 1204230, 655360], [90, 1703936, 655360]],
  []],
 ['nested',
  '\\hbox{\\cleaders\\vbox{\\cleaders\\hbox{A}\\vskip20pt}\\hskip25pt Z}',
  [[65, 81923, 655365],
   [65, 81923, 1103193],
   [65, 573444, 655365],
   [65, 573444, 1103193],
   [65, 1064965, 655365],
   [65, 1064965, 1103193],
   [90, 1638400, 1310720]],
  []],
 ['font',
  '\\font\\foo=cmtt10\\hbox{\\cleaders\\hbox{\\foo A}\\hskip25pt Z}',
  [[65, 131083, 655360],
   [65, 475144, 655360],
   [65, 819205, 655360],
   [65, 1163266, 655360],
   [90, 1638400, 655360]],
  []],
 ['alias_copy',
  '\\setbox0\\hbox{A}\\let\\sk=\\vskip\\vbox{\\xleaders\\copy0\\sk23pt\\hbox{Z}}',
  [[65, 0, 488792], [65, 0, 977583], [65, 0, 1466374], [90, 0, 1955156]],
  []],
 ['negative', '\\hbox{\\leaders\\hbox{A}\\hskip-2pt Z}', [[90, -131072, 655360]], []],
 ['zero', '\\vbox{\\leaders\\hbox{}\\vskip10pt\\hbox{Z}}', [[90, 0, 1103188]], []],
 ['nested_rule',
  '\\hbox{\\cleaders\\vbox{\\leaders\\hrule width2pt\\vskip3pt}\\hskip12pt}',
  [],
  [[5, 655360, 196608, 131072],
   [131077, 655360, 196608, 131072],
   [262149, 655360, 196608, 131072],
   [393221, 655360, 196608, 131072],
   [524293, 655360, 196608, 131072],
   [655365, 655360, 196608, 131072]]],
 ['v_leaders_odd',
  '\\vbox{\\kern3sp\\leaders\\hbox{\\vrule width1sp height7sp}\\vskip20sp}',
  [],
  [[0, 655351, 7, 1], [0, 655358, 7, 1], [0, 655365, 7, 1]]],
 ['v_leaders_negative_origin',
  '\\vbox{\\kern-3sp\\leaders\\hbox{\\vrule width1sp height7sp}\\vskip20sp}',
  [],
  [[0, 655350, 7, 1], [0, 655357, 7, 1], [0, 655364, 7, 1]]],
 ['h_leaders_odd',
  '\\hbox{\\kern3sp\\leaders\\hbox{\\vrule width7sp height1sp}\\hskip20sp}',
  [],
  [[7, 655360, 1, 7], [14, 655360, 1, 7], [21, 655360, 1, 7]]],
 ['h_leaders_negative_origin',
  '\\hbox{\\kern-3sp\\leaders\\hbox{\\vrule width7sp height1sp}\\hskip20sp}',
  [],
  [[0, 655360, 1, 7], [7, 655360, 1, 7], [14, 655360, 1, 7]]],
 ['v_cleaders_odd',
  '\\vbox{\\kern3sp\\cleaders\\hbox{\\vrule width1sp height7sp}\\vskip20sp}',
  [],
  [[0, 655348, 7, 1], [0, 655355, 7, 1], [0, 655362, 7, 1], [0, 655369, 7, 1]]],
 ['v_cleaders_negative_origin',
  '\\vbox{\\kern-3sp\\cleaders\\hbox{\\vrule width1sp height7sp}\\vskip20sp}',
  [],
  [[0, 655348, 7, 1], [0, 655355, 7, 1], [0, 655362, 7, 1], [0, 655369, 7, 1]]],
 ['h_cleaders_odd',
  '\\hbox{\\kern3sp\\cleaders\\hbox{\\vrule width7sp height1sp}\\hskip20sp}',
  [],
  [[4, 655360, 1, 7], [11, 655360, 1, 7], [18, 655360, 1, 7], [25, 655360, 1, 7]]],
 ['h_cleaders_negative_origin',
  '\\hbox{\\kern-3sp\\cleaders\\hbox{\\vrule width7sp height1sp}\\hskip20sp}',
  [],
  [[-2, 655360, 1, 7], [5, 655360, 1, 7], [12, 655360, 1, 7], [19, 655360, 1, 7]]],
 ['v_xleaders_odd',
  '\\vbox{\\kern3sp\\xleaders\\hbox{\\vrule width1sp height7sp}\\vskip20sp}',
  [],
  [[0, 655348, 7, 1], [0, 655355, 7, 1], [0, 655362, 7, 1], [0, 655369, 7, 1]]],
 ['v_xleaders_negative_origin',
  '\\vbox{\\kern-3sp\\xleaders\\hbox{\\vrule width1sp height7sp}\\vskip20sp}',
  [],
  [[0, 655348, 7, 1], [0, 655355, 7, 1], [0, 655362, 7, 1], [0, 655369, 7, 1]]],
 ['h_xleaders_odd',
  '\\hbox{\\kern3sp\\xleaders\\hbox{\\vrule width7sp height1sp}\\hskip20sp}',
  [],
  [[4, 655360, 1, 7], [11, 655360, 1, 7], [18, 655360, 1, 7], [25, 655360, 1, 7]]],
 ['h_xleaders_negative_origin',
  '\\hbox{\\kern-3sp\\xleaders\\hbox{\\vrule width7sp height1sp}\\hskip20sp}',
  [],
  [[-2, 655360, 1, 7], [5, 655360, 1, 7], [12, 655360, 1, 7], [19, 655360, 1, 7]]]]


def _compile(body, device):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return TeXJob(StringInputSource(body+'\n\\bye\n'), device, options=TeXOptions()).run()


@pytest.mark.parametrize('name,body,glyphs,rules', CASES, ids=[r[0] for r in CASES])
def test_dvi_measured_payload_events(name, body, glyphs, rules):
    data = _compile(body, DviDevice())
    assert walk_chars_with_positions(data, _tfm_width(), advance_rules=True)[0][:-1] == [tuple(g) for g in glyphs]
    assert walk_rules(data)[0] == [tuple(r) for r in rules]


@pytest.mark.parametrize('name,body,glyphs,rules', CASES, ids=[r[0] for r in CASES])
def test_svg_measured_paint_coordinates(name, body, glyphs, rules):
    device = SvgDevice()
    data = _compile(body, device)
    writer = device._backend
    assert [(c,h,v) for _,c,h,v in writer._char_placements][:-1] == [tuple(g) for g in glyphs]
    assert writer._rule_placements == [(h,v-height,width,height) for h,v,height,width in rules]
    assert b'<svg' in data
    if rules:
        assert b'<rect' in data
    if glyphs:
        assert b'<use' in data


@pytest.mark.parametrize('name,body,glyphs,rules', CASES, ids=[r[0] for r in CASES])
def test_pdf_measured_paint_coordinates(name, body, glyphs, rules):
    device = PdfDevice()
    data = _compile(body, device)
    writer = device._backend
    streams = re.findall(rb'stream\n(.*?)endstream', data, re.S)
    paints = b'\n'.join(s for s in streams if b'BT\n' in s or b' re f' in s)
    text = re.findall(rb'([-\d.]+) ([-\d.]+) Td\n\((.*?)\) Tj', paints)
    # The fixtures use one-character runs, including the final plain folio.
    assert [(t.decode('ascii'), round(float(x),4), round(float(y),4)) for x,y,t in text[:-1]] == [
        (chr(c), round(72+h/_SP_PER_BP,4), round(writer._page_height_pt-72-v/_SP_PER_BP,4)) for c,h,v in glyphs
    ]
    rectangles = re.findall(rb'([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) re\s+f', paints)
    assert [tuple(round(float(n),4) for n in rect) for rect in rectangles] == [
        (round(72+h/_SP_PER_BP,4), round(writer._page_height_pt-72-v/_SP_PER_BP,4),
         round(width/_SP_PER_BP,4), round(height/_SP_PER_BP,4)) for h,v,height,width in rules
    ]
    assert data.startswith(b'%PDF')


@pytest.mark.parametrize('kind,edges', [(LeadersKind.NORMAL,(7,14,21)),
                                     (LeadersKind.C,(4,11,18,25)),
                                     (LeadersKind.X,(4,11,18,25))])
def test_integer_placement_odd_allowance_measured(kind, edges):
    # MiKTeX h_*_odd rule events, relative to the containing hbox's left.
    assert leader_positions(kind,start=3,span=20,extent=7,origin=0) == edges


@pytest.mark.parametrize('kind', list(LeadersKind))
@pytest.mark.parametrize('span,extent', [(0,7),(-1,7),(20,0),(20,-1)])
def test_nonpositive_placement(kind, span, extent):
    assert leader_positions(kind,start=3,span=span,extent=extent,origin=0) == ()


# MiKTeX 24.4: 1pt set box containing italic A and a special, three
# copies over 3pt, then roman Z / italic Q. Nested and flat agree.
_SPECIAL_GLYPHS = {
    False: [(65,0,0),(65,65536,0),(65,131072,0),(90,196608,0),(81,597106,0)],
    True: [(65,0,0),(65,0,65536),(65,0,131072),(90,0,578900),(81,400498,578900)],
}


def _special_page(vertical, nested):
    from aspose_tex._engine.nodes import CharNode, GlueSign, HlistNode, LeadersNode, VlistNode, WhatsitNode
    from aspose_tex._engine.registers import Glue, GlueOrder
    from tests.test_output_dvi_writer import _make_char_hbox, _make_mgr_with_cmr10, _make_page_with_hbox
    mgr = _make_mgr_with_cmr10()
    mgr.load_font('tenit','cmti10')
    attrs = dict(shift_amount=0,glue_sign=GlueSign.NORMAL,glue_order=GlueOrder.NORMAL,glue_set=0.0)
    payload = HlistNode([CharNode(65,'tenit'),WhatsitNode(b'leader-special')],65536,65536,0,**attrs)
    if nested:
        payload.list.pop()
        payload = VlistNode([WhatsitNode(b'leader-special'),payload],65536,65536,0,**attrs)
    leader = LeadersNode(LeadersKind.NORMAL,payload,Glue(196608,0,GlueOrder.NORMAL,0,GlueOrder.NORMAL))
    follow = _make_char_hbox('Z','tenrm',mgr.get_metrics('tenrm'))
    italic = _make_char_hbox('Q','tenit',mgr.get_metrics('tenit'))
    follow.list += italic.list
    follow.width += italic.width
    follow.height = max(follow.height,italic.height)
    follow.depth = max(follow.depth,italic.depth)
    if vertical:
        page = VlistNode([leader,follow],follow.width,196608+follow.height,follow.depth,**attrs)
    else:
        page = _make_page_with_hbox(HlistNode([leader,*follow.list],196608+follow.width,
                                             follow.height,follow.depth,**attrs))
    return mgr,page


def _relative_glyphs(glyphs):
    h,v = glyphs[0][1:]
    return [(c,x-h,y-v) for c,x,y in glyphs]


@pytest.mark.parametrize('vertical',[False,True],ids=['horizontal','vertical'])
@pytest.mark.parametrize('nested',[False,True],ids=['flat','nested'])
def test_leader_specials_measured_dvi_font_and_cursor(vertical,nested):
    from tests.test_output_dvi_writer import _make_writer, _parse_dvi_opcodes
    mgr,page = _special_page(vertical,nested)
    writer,_ = _make_writer(mgr)
    writer.shipout(1,page)
    writer.finalize()
    data = writer.get_bytes()
    ops = _parse_dvi_opcodes(data)
    assert [op[1] for op in ops if op[0]=='xxx'] == [b'leader-special']*3
    assert _relative_glyphs(walk_chars_with_positions(data,_tfm_width())[0]) == _SPECIAL_GLYPHS[vertical]
    selected = None
    fonts = []
    names = {rec.font_num:rec.cs_name for rec in writer._font_registry.values()}
    for op in ops:
        if op[0] in ('fnt_num','fnt1'):
            selected = names[op[1]]
        elif op[0]=='set_char':
            fonts.append(selected)
    assert fonts == ['tenit']*3+['tenrm','tenit']


@pytest.mark.parametrize('vertical',[False,True],ids=['horizontal','vertical'])
@pytest.mark.parametrize('nested',[False,True],ids=['flat','nested'])
@pytest.mark.parametrize('backend',['pdf','svg'])
def test_leader_specials_once_diagnostics_and_cursor(vertical,nested,backend):
    from tests.test_output_pdf_writer import _make_writer as pdf_writer
    from tests.test_output_svg_writer import _make_writer as svg_writer
    mgr,page = _special_page(vertical,nested)
    writer,_ = pdf_writer(mgr) if backend=='pdf' else svg_writer(font_manager=mgr)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        writer.shipout(1,page)
        writer.shipout(2,page)  # once per special, also across pages
        writer.finalize()
    diagnostics = [w for w in caught if 'whatsit ignored' in str(w.message)]
    assert len(diagnostics) == 1
    assert 'leader-special' in str(diagnostics[0].message)
    if backend=='svg':
        placements = writer._char_placements
        assert [font.cs_name for font,_,_,_ in placements] == ['tenit']*3+['tenrm','tenit']
        assert _relative_glyphs([(c,h,v) for _,c,h,v in placements]) == _SPECIAL_GLYPHS[vertical]
    else:
        data = writer.get_bytes()
        streams = re.findall(rb'stream\n(.*?)endstream',data,re.S)
        content = next(stream for stream in streams if b'BT\n' in stream)
        texts = re.findall(rb'([-\d.]+) ([-\d.]+) Td\n\((.*?)\) Tj',content)
        resources = {rec.resource_name:rec.cs_name for rec in writer._fonts.values()}
        used = re.findall(rb'/([^ ]+) [\d.]+ Tf',content)
        assert [resources[name.decode()] for name in used] == ['tenit']*3+['tenrm','tenit']
        x,y,_ = texts[0]
        expected = [(chr(c),h/_SP_PER_BP,-v/_SP_PER_BP) for c,h,v in _SPECIAL_GLYPHS[vertical]]
        got = [(t.decode(),float(h)-float(x),float(v)-float(y)) for h,v,t in texts]
        assert [c for c,_,_ in got] == [c for c,_,_ in expected]
        # Each serialized coordinate is rounded to 4 places on its own.
        assert all(abs(gh-eh) < 2e-4 and abs(gv-ev) < 2e-4
                   for (_,gh,gv),(_,eh,ev) in zip(got,expected,strict=True))
