"""Reading what a printer cuts its sheets into from its driver's page sizes."""

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.print_sizes import FALLBACK_PAGE_SIZES, sheet_layout, describe, describe_all, read_ppd


def test_the_qw410_cuts_a_4x6_into_three_2x4():
    size = describe('w288h432-div3', '2x4*3')

    assert (size['short_in'], size['long_in'], size['count']) == (2, 4, 3)
    assert size['page_size'] == 'w288h432-div3'
    assert size['label'] == '2x4*3'


def test_the_same_name_is_a_different_cut_on_another_printer():
    """The reason the labels are read rather than the names: w288h432-div2 is not one thing."""
    ds620 = describe('w288h432-div2', '2x6*2')
    qw410 = describe('w288h432-div2', '4x3*2')

    assert (ds620['short_in'], ds620['long_in']) == (2, 6)
    assert (qw410['short_in'], qw410['long_in']) == (3, 4)


def test_a_whole_sheet_is_one_print():
    size = describe('w288h432', '4x6')

    assert (size['short_in'], size['long_in'], size['count']) == (4, 6, 1)


def test_a_size_without_a_readable_label_is_the_sheet_in_its_name():
    size = describe('w288h432', 'Postcard')

    assert (size['short_in'], size['long_in'], size['count']) == (4, 6, 1)
    assert size['label'] == 'Postcard'   # the operator's driver calls it that


def test_a_size_without_a_label_is_named_after_it():
    assert describe('w288h432')['label'] == '4x6'


@pytest.mark.parametrize('name, label', [
    ('w288h432_w288h144', '4x6+4x2'),   # two different prints on one sheet
    ('B7', '3.5x5'),                    # a name that is not a sheet size
    ('w288h432-div3', 'Three'),         # cut in three, but into what
    ('w288h432-div3', '3x5*3'),         # prints that do not tile the sheet
    ('', ''),
])
def test_a_size_the_booth_cannot_lay_out_is_left_out(name, label):
    assert describe(name, label) is None


def test_a_printer_list_keeps_its_order_and_drops_what_it_cannot_use():
    sizes = describe_all([
        ('w288h432', '4x6'),
        ('w288h432_w288h144', '4x6+4x2'),
        ('w288h432-div3', '2x4*3'),
        ('w288h432', '4x6'),
    ])

    assert [size['page_size'] for size in sizes] == ['w288h432', 'w288h432-div3']


# PageSize lines of a QW410's PPD, as Gutenprint installs it on the booth.
QW410_PPD = (
    'w288h288/4x4 w288h288-div2/2x4*2 w288h216/4x3 w288h288_w288h144/4x4+4x2 w288h432/4x6 '
    'w288h432-div2/4x3*2 w288h432-div3/2x4*3 w288h576/4x8 w288h432_w288h144/4x6+4x2 '
    'w288h432-div2_w288h144/4x3*2+4x2 w288h576-div2/4x4*2 w288h576-div4/2x4*4 w324h216/4.5x3 '
    'w324h288/4.5x4 w324h324/4.5x4.5 w324h432/4.5x6 w324h432-div2/4.5x3*2 w324h486/4.5x6.75 '
    'w324h432-div3/4.5x2*3 w324h576/4.5x8 w324h576-div2/4.5x4*2 w324h576-div4/4.5x2*4 '
    'w324h432_w324h144/4.5x6+4.5x2 w324h432-div2_w324h144/4.5x3*2+4.5x2'
)


def test_a_real_qw410_driver_offers_every_size_but_the_mixed_ones():
    sizes = describe_all(tuple(entry.split('/', 1)) for entry in QW410_PPD.split())

    assert len(sizes) == 19
    assert not [size for size in sizes if '+' in size['label']]
    by_name = {size['page_size']: size for size in sizes}
    assert (by_name['w288h432-div3']['short_in'], by_name['w288h432-div3']['long_in'],
            by_name['w288h432-div3']['count']) == (2, 4, 3)


def test_every_fallback_size_is_usable():
    assert len(describe_all(FALLBACK_PAGE_SIZES)) == len(FALLBACK_PAGE_SIZES)


# --- a print on its own, on a sheet that could carry several -----------------

def fuller_sheets(choices):
    return {size['page_size']: size['fuller_sheet'] for size in describe_all(choices)}


def test_a_4x3_on_its_own_spends_the_ink_of_the_4x6_it_is_cut_from():
    """What the QW410 does: one panel of ribbon per sheet, so 4x3*2 prints two for the same."""
    sheets = fuller_sheets(tuple(entry.split('/', 1)) for entry in QW410_PPD.split())

    assert sheets['w288h216'] == {'page_size': 'w288h432-div2', 'label': '4x3*2', 'count': 2, 'sheet': '4x6'}
    assert sheets['w324h216']['page_size'] == 'w324h432-div2'
    assert sheets['w324h288'] == {'page_size': 'w324h576-div2', 'label': '4.5x4*2', 'count': 2, 'sheet': '4.5x8'}


@pytest.mark.parametrize('page_size', [
    'w288h432',        # 4x6: the sheet itself
    'w288h288',        # 4x4: the sheet 2x4*2 is cut from, so media of its own
    'w324h324',        # 4.5x4.5: no sheet is cut into these
    'w288h432-div2',   # already two per sheet
])
def test_a_print_that_fills_its_sheet_is_not_flagged(page_size):
    sheets = fuller_sheets(tuple(entry.split('/', 1)) for entry in QW410_PPD.split())

    assert sheets[page_size] is None


def test_a_ds620_strip_on_its_own_is_pointed_at_the_smallest_sheet_of_strips():
    """2x6*2 on a 4x6 rather than 2x6*4 on a 6x8: two strips nobody asked for are fewer than four."""
    sheets = fuller_sheets([
        ('w144h432', '2x6'), ('w288h432', '4x6'), ('w288h432-div2', '2x6*2'),
        ('w432h576-div4', '2x6*4'), ('w432h576-div2', '4x6*2'),
    ])

    assert sheets['w144h432']['page_size'] == 'w288h432-div2'
    # The DS620's 4x6 is the sheet its strips are cut from: media of its own,
    # though a 6x8 is also cut into 4x6.
    assert sheets['w288h432'] is None


# --- knowing the media loaded ------------------------------------------------

def qw410_on(media):
    sizes = describe_all((tuple(entry.split('/', 1)) for entry in QW410_PPD.split()), media)
    return {size['page_size']: size['fuller_sheet'] for size in sizes}


def test_on_4x6_two_2x4_are_pointed_at_three():
    """A 4x4 sheet printed on a 4x6 panel: the third 2x4 costs no ink."""
    sheets = qw410_on((4, 6))

    assert sheets['w288h288-div2'] == {'page_size': 'w288h432-div3', 'label': '2x4*3', 'count': 3, 'sheet': '4x6'}
    assert sheets['w288h216']['page_size'] == 'w288h432-div2'


def test_on_4x6_a_4x4_alone_wastes_ink_with_nothing_to_offer():
    assert qw410_on((4, 6))['w288h288'] == {'page_size': None, 'label': None, 'count': None, 'sheet': '4x6'}


@pytest.mark.parametrize('page_size', [
    'w288h432', 'w288h432-div2', 'w288h432-div3',   # fill the 4x6
    'w288h576', 'w324h216', 'w324h432',             # not printed on a 4x6
])
def test_on_4x6_what_fills_it_or_does_not_fit_it_is_left_alone(page_size):
    assert qw410_on((4, 6))[page_size] is None


def test_a_ds620_on_4x6_flags_a_strip_but_not_its_own_4x6():
    sizes = describe_all([('w144h432', '2x6'), ('w288h432', '4x6'), ('w288h432-div2', '2x6*2'),
                          ('w432h576-div4', '2x6*4')], (4, 6))
    sheets = {size['page_size']: size['fuller_sheet'] for size in sizes}

    assert sheets['w144h432']['page_size'] == 'w288h432-div2'
    assert sheets['w288h432'] is None and sheets['w288h432-div2'] is None


def test_a_ds620_on_6x8_points_a_4x6_at_two_per_sheet():
    """The same 4x6 the automatic rule calls media of its own wastes half a 6x8."""
    sizes = describe_all([('w288h432', '4x6'), ('w432h576-div2', '4x6*2'), ('w432h576', '6x8')], (6, 8))
    sheets = {size['page_size']: size['fuller_sheet'] for size in sizes}

    assert sheets['w288h432']['page_size'] == 'w432h576-div2'


# --- laying copies out where the cutter separates them ----------------------

# The QW410's own lines for the sizes measured with tools/manual/cut_calibration.py.
QW410_GEOMETRY = '''
*PageSize w288h288-div2/2x4*2:  "<</PageSize[296.640 337.920]/ImagingBBox null>>setpagedevice"
*PageSize w288h432-div3/2x4*3:  "<</PageSize[337.920 440.640]/ImagingBBox null>>setpagedevice"
*ImageableArea w288h288-div2/2x4*2:     "0.000 17.040 296.640 320.880"
*ImageableArea w288h432-div3/2x4*3:     "17.040 0.000 320.880 440.640"
*PaperDimension w288h288-div2/2x4*2:    "296.640 337.920"
*PaperDimension w288h432-div3/2x4*3:    "337.920 440.640"
*PageSize w288h216/4x3: "<</PageSize[440.640 337.920]/ImagingBBox null>>setpagedevice"
*ImageableArea w288h216/4x3:    "216.000 17.040 440.640 320.880"
*PaperDimension w288h216/4x3:   "440.640 337.920"
'''


def test_the_ppd_gives_each_size_its_label_and_page():
    pages = read_ppd(QW410_GEOMETRY)

    assert pages['w288h432-div3'] == {
        'label': '2x4*3', 'paper': [337.92, 440.64], 'area': [17.04, 0.0, 320.88, 440.64]}


@pytest.mark.parametrize('design, rotate', [((600, 1200), True), ((1200, 600), False)])
def test_three_2x4_start_where_the_qw410_cuts_a_4x6(design, rotate):
    """Measured: the cuts fall at 620 and 1220 on a 1836 px page, 20 px in."""
    layout = sheet_layout('w288h432-div3', read_ppd(QW410_GEOMETRY)['w288h432-div3'], 3, design, 20)

    assert layout == {'rotate': rotate, 'along_x': False, 'pad': (20, 16, 33, 33)}


def test_on_a_page_the_driver_turns_the_copies_follow_each_other_along_x():
    layout = sheet_layout('w288h288-div2', read_ppd(QW410_GEOMETRY)['w288h288-div2'], 2, (600, 1200), 20)

    assert layout == {'rotate': False, 'along_x': True, 'pad': (33, 33, 20, 16)}


@pytest.mark.parametrize('copies, design', [
    (3, (600, 1800)),   # not one 2x4 print
    (2, (600, 1200)),   # the sheet is cut in three, not two
])
def test_a_design_that_is_not_one_print_of_the_size_is_left_to_be_fitted(copies, design):
    assert sheet_layout('w288h432-div3', read_ppd(QW410_GEOMETRY)['w288h432-div3'], copies, design, 20) is None


def test_a_size_the_driver_gave_no_geometry_for_is_left_to_be_fitted():
    assert sheet_layout('w288h432-div3', {'label': '2x4*3'}, 3, (600, 1200), 20) is None


def test_a_4x3_on_its_own_is_printed_as_it_is():
    """At the far end of a 4x6 page, 936 px along for 900 of paper: fitted, it lost 4% at every edge."""
    layout = sheet_layout('w288h216', read_ppd(QW410_GEOMETRY)['w288h216'], 1, (900, 1200), 20)

    assert layout == {'rotate': False, 'along_x': True, 'pad': (33, 33, 20, 16)}


def test_a_4x3_drawn_lying_down_is_turned_onto_its_print():
    layout = sheet_layout('w288h216', read_ppd(QW410_GEOMETRY)['w288h216'], 1, (1200, 900), 20)

    assert layout['rotate'] is True
