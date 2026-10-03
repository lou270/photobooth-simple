"""Reading what a printer cuts its sheets into from its driver's page sizes."""

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.print_sizes import FALLBACK_PAGE_SIZES, describe, describe_all


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
