"""The print sizes a printer offers, as the booth lays a template out on them.

A dye-sub printer is fed one sheet and can cut it into several prints: the DNP
QW410 cuts a 4x6 sheet into three 2x4 prints, the DS620 cuts the same sheet
into two 2x6 strips. Gutenprint names each of these after the sheet
("w288h432-div3", in points) and labels it after the prints ("2x4*3", in
inches). The same name does not mean the same cut on every printer:
"w288h432-div2" is two 2x6 strips on a DS620 and two 4x3 prints on a QW410. So
the booth reads the labels from the printer's own driver rather than guessing
from names, and only falls back to a list of its own when no printer is there.
"""

import re

POINTS_PER_INCH = 72

# "w288h432", "w288h432-div3"; combined cuts ("w288h432_w288h144", two sizes on
# one sheet) are left out: one template cannot fill two different prints.
_NAME = re.compile(r'^w(\d+(?:\.\d+)?)h(\d+(?:\.\d+)?)(?:-div(\d+))?$')
# "4x6", "2x4*3", "3.5x5"; Gutenprint's own spelling.
_LABEL = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*(?:\*\s*(\d+))?\s*$')

# Room for rounding in labels: "3.375x6" is written to three decimals.
_TOLERANCE_INCHES = 0.05

# What a DNP QW410 offers on 4x6 and 4.5x8 media, from Gutenprint's driver.
# Shown by the editor when the booth has no printer to ask, so that a template
# can still be designed for the printer this booth is normally used with.
FALLBACK_PAGE_SIZES = [
    ('w288h432', '4x6'),
    ('w288h288', '4x4'),
    ('w288h216', '4x3'),
    ('w288h432-div2', '4x3*2'),
    ('w288h432-div3', '2x4*3'),
    ('w288h288-div2', '2x4*2'),
    ('w288h576', '4x8'),
    ('w288h576-div2', '4x4*2'),
    ('w288h576-div4', '2x4*4'),
    ('w324h432', '4.5x6'),
    ('w324h324', '4.5x4.5'),
    ('w324h576', '4.5x8'),
    ('w324h576-div2', '4.5x4*2'),
    ('w324h432-div2', '4.5x3*2'),
    ('w324h432-div3', '4.5x2*3'),
    ('w324h576-div4', '4.5x2*4'),
]


def _fits(pieces_long, pieces_short, sheet_long, sheet_short):
    return (abs(pieces_long - sheet_long) <= _TOLERANCE_INCHES * max(1, pieces_long)
            and abs(pieces_short - sheet_short) <= _TOLERANCE_INCHES * max(1, pieces_short))


def describe(page_size, label=''):
    """One print size as the booth uses it, or None for one it cannot use.

    Returns a dict with the PageSize to send, its label, the size of one print
    (short and long side, in inches) and how many prints the sheet is cut into.
    A label that does not read as a size falls back to the sheet in the name:
    one print, the whole sheet.
    """
    match = _NAME.match(page_size or '')
    if not match:
        return None
    sheet = sorted((float(match.group(1)) / POINTS_PER_INCH, float(match.group(2)) / POINTS_PER_INCH))
    sheet_short, sheet_long = sheet
    count = int(match.group(3) or 1)

    piece = None
    label_match = _LABEL.match(label or '')
    if label_match:
        piece = sorted((float(label_match.group(1)), float(label_match.group(2))))
        count = int(label_match.group(3) or 1)
    if count < 1:
        return None
    if piece is None:
        if count != 1:
            return None
        piece = sheet

    short, long = piece
    if count > 1:
        # The prints have to tile the sheet, one way or the other: if they do
        # not, the label means something this module does not understand, and
        # laying a template out on it would put the cuts through the photos.
        side_by_side = sorted((short * count, long))
        end_to_end = sorted((short, long * count))
        if not (_fits(side_by_side[1], side_by_side[0], sheet_long, sheet_short)
                or _fits(end_to_end[1], end_to_end[0], sheet_long, sheet_short)):
            return None

    return {
        'page_size': page_size,
        'label': (label or '').strip() or f'{_inches(short)}x{_inches(long)}',
        'short_in': short,
        'long_in': long,
        'count': count,
    }


def _inches(value):
    return f'{value:g}'


_PPD_ENTRY = re.compile(r'^\*(PageSize|PaperDimension|ImageableArea) ([^/:\s]+)(?:/([^:]*))?:\s*"([^"]*)"', re.MULTILINE)


def read_ppd(ppd_text):
    """Every page size in a PPD, with what the driver says of its page.

    Returns {name: {'label': ..., 'paper': [width, height], 'area': [left,
    bottom, right, top]}}, in points; a size missing either dimension is left
    without it. Read from the text rather than through pycups, which hides the
    two geometry keywords behind a per-attribute lookup.
    """
    pages = {}
    for keyword, name, label, value in _PPD_ENTRY.findall(ppd_text):
        page = pages.setdefault(name, {'label': ''})
        if keyword == 'PageSize':
            page['label'] = (label or '').strip()
            continue
        try:
            numbers = [float(number) for number in value.split()]
        except ValueError:
            continue
        if keyword == 'PaperDimension' and len(numbers) == 2:
            page['paper'] = numbers
        elif keyword == 'ImageableArea' and len(numbers) == 4:
            page['area'] = numbers
    return pages


def _pixels(points, dpi=300):
    return int(round(points * dpi / POINTS_PER_INCH))


def page_axes(page_size, page):
    """How the paper lies on the driver's page for this size, or None if it cannot tell.

    In pixels at 300 dpi: along_x (the paper runs along x), the imageable
    area's length along the paper and width across it, the paper's own, the
    number of prints and the length of one. The page drawn is the imageable
    area, so these are the sizes of the image the booth sends.
    """
    size = describe(page_size, (page or {}).get('label', ''))
    if size is None or 'paper' not in page or 'area' not in page:
        return None
    match = _NAME.match(page_size)
    paper_across = _pixels(float(match.group(1)))
    paper_along = _pixels(float(match.group(2)))
    count = size['count']
    piece = paper_along // count
    if piece * count != paper_along:
        return None

    # Along the paper the driver prints a little past each end; across, past
    # each side of a paper narrower than the head, by more. The QW410's 4x3
    # sits at the far end of a 4x6 page, so where the area starts says nothing.
    left, bottom, right, top = page['area']
    span_x, span_y = _pixels(right - left), _pixels(top - bottom)
    fits_along_x = 0 <= span_x - paper_along and 0 <= span_y - paper_across
    fits_along_y = 0 <= span_y - paper_along and 0 <= span_x - paper_across
    if fits_along_x and fits_along_y:
        along_x = span_x - paper_along < span_y - paper_along
    elif fits_along_x or fits_along_y:
        along_x = fits_along_x
    else:
        return None
    page_along, page_across = (span_x, span_y) if along_x else (span_y, span_x)
    return {'along_x': along_x, 'page_along': page_along, 'page_across': page_across,
            'paper_along': paper_along, 'paper_across': paper_across, 'count': count, 'piece': piece}


def sheet_layout(page_size, page, copies, design_size, cut_offset):
    """Where the copies of a design go on the driver's page, printed as they are.

    The driver's page is larger than the paper: 1836 px at 300 dpi along a
    6-inch print (1800 px), 1266 across a 4-inch one (1200), the excess
    printed past the edges. Stretched to that page, as print-scaling=fit does,
    a design loses about 4% of itself at every edge, and on a sheet the
    printer cuts, the copies drift away from the cuts: on a QW410's 2x4*3 the
    joins land at 612 and 1224 while the cutter goes through 620 and 1220.
    Laid out at the page's own size, the sheet is printed as it is, the paper
    starting cut_offset pixels in along it and centred across it.

    Returns None when the design is not exactly one print of this size, or
    the driver did not describe the page: the sheet is then laid out as
    before, and fitted. Otherwise a dict, in pixels at 300 dpi:
        rotate: the design is turned a quarter turn first,
        along_x: copies follow each other along x rather than y,
        pad: (top, bottom, left, right) around the copies, filled by
            prolonging their edges, since all of it is printed past the paper.
    The page drawn is the driver's imageable area, so fitting it is 1:1.
    """
    axes = page_axes(page_size, page)
    if axes is None or axes['count'] != copies:
        return None
    along_x, piece = axes['along_x'], axes['piece']
    paper_along, paper_across = axes['paper_along'], axes['paper_across']
    page_along, page_across = axes['page_along'], axes['page_across']

    # One print, either way round: piece along the paper, its width across.
    wanted = (piece, paper_across) if along_x else (paper_across, piece)
    if tuple(design_size) == wanted:
        rotate = False
    elif tuple(design_size[::-1]) == wanted:
        rotate = True
    else:
        return None

    lead = cut_offset
    trail = page_along - lead - paper_along
    side = page_across - paper_across
    if trail < 0:
        return None
    before, after = side // 2, side - side // 2
    pad = (before, after, lead, trail) if along_x else (lead, trail, before, after)
    return {'rotate': rotate, 'along_x': along_x, 'pad': pad}


def describe_all(choices):
    """Every usable size in a printer's (name, label) list, in the driver's order."""
    sizes = []
    seen = set()
    for name, label in choices:
        size = describe(name, label)
        if size and size['page_size'] not in seen:
            seen.add(size['page_size'])
            sizes.append(size)
    return sizes
