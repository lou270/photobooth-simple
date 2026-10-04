#!/usr/bin/env python3
"""Print a sheet that shows exactly where the paper's edges and cuts fall on it.

The page a dye-sub driver describes is larger than the paper: the excess is
printed past the edges, and on a sheet cut into several prints the cutter
measures its lengths off from a point inside that page. Neither is written in
the PPD: this sheet measures both, for any size, cut or not.

At each end of each print, and at both sides of the paper, runs a diagonal
under a numbered scale: wherever the edge falls, the diagonal meets it at a
point several times easier to read than the edge itself. Read the number
where the diagonal meets the edge. The numbers are pixels of the page at
300 dpi, counted from its start along the paper (ends and cuts) or from its
first side across it (sides).

    python3 tools/manual/cut_calibration.py w288h432-div3
    lp -d QW410 -o PageSize=w288h432-div3 -o print-scaling=fit cut_calibration_w288h432-div3.png

The booth expects the paper to start CUT_OFFSET pixels into the page (20 on
a QW410) and to sit centred across it.
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from libs.print_sizes import page_axes, read_ppd

# How far either side of where the booth expects an edge the diagonal reaches.
REACH = 30
BLACK, GREY = (0, 0, 0), (120, 120, 120)


def draw_text(sheet, text, centre, scale=0.8):
    (width, height), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    origin = (int(centre[0] - width / 2), int(centre[1] + height / 2))
    cv2.putText(sheet, text, origin, cv2.FONT_HERSHEY_SIMPLEX, scale, BLACK, 2, cv2.LINE_AA)


def draw_gauge(sheet, start, stop, run_from, magnification, label, scale_sides, across_cut):
    """A diagonal measuring where an edge falls between start and stop, with its scale.

    Rows run along the paper, columns across it. An end or a cut runs across
    the paper, at some row between start and stop: the diagonal goes down
    those rows while moving magnification columns per row, so the edge meets
    it at a column that says which row it is. A side of the paper runs along
    it: the same, rows and columns swapped. scale_sides says where the scale
    goes, -1 before the diagonal and/or +1 after it, so it is on the paper.
    """
    def at(value, offset):
        """(x, y) of a point offset from the edge's coordinate value, run along with it."""
        run = run_from + (value - start) * magnification
        return (run, offset) if across_cut else (offset, run)

    cv2.line(sheet, at(start, start), at(stop, stop), BLACK, 2, cv2.LINE_AA)
    for side in scale_sides:
        base = stop + 6 if side > 0 else start - 6
        for value in range(start, stop + 1):
            major = value % 10 == 0
            length = 22 if major else 10
            cv2.line(sheet, at(value, base), at(value, base + side * length),
                     BLACK if major else GREY, 2 if major else 1)
            if major:
                draw_text(sheet, label(value), at(value, base + side * (length + 22)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('page_size', help='PageSize to measure, e.g. w288h432-div3 or w288h216')
    parser.add_argument('--ppd', default='/etc/cups/ppd/QW410.ppd')
    parser.add_argument('--cut-offset', type=int, default=20, help='where the booth expects the paper to start')
    parser.add_argument('--output', help='PNG to write (default: cut_calibration_<page_size>.png)')
    args = parser.parse_args()

    pages = read_ppd(Path(args.ppd).read_text(encoding='latin-1'))
    axes = page_axes(args.page_size, pages.get(args.page_size))
    if axes is None:
        sys.exit(f'{args.page_size}: the PPD does not describe a page the booth can lay out')

    length, across = axes['page_along'], axes['page_across']
    side = (across - axes['paper_across']) // 2
    sheet = np.full((length, across, 3), 255, dtype=np.uint8)

    # Ends and cuts: rows across which the paper is cut, read along a row.
    for number in range(axes['count'] + 1):
        expected = args.cut_offset + number * axes['piece']
        start, stop = max(0, expected - REACH), min(length - 1, expected + REACH)
        # Its scale on the paper: after the first edge, before the last one,
        # both sides of a cut between two prints.
        sides = [1] if number == 0 else [-1] if number == axes['count'] else [-1, 1]
        magnification = min(10, (across - 2 * side - 40) // (stop - start))
        run_from = (across - (stop - start) * magnification) // 2
        draw_gauge(sheet, start, stop, run_from, magnification, str, sides, across_cut=True)

    # Sides: columns along which the paper ends, read down a column, in the
    # middle of the first print where no cut gauge reaches.
    middle = args.cut_offset + axes['piece'] // 2
    magnification = min(10, max(2, (axes['piece'] - 260) // (2 * REACH)))
    run_from = middle - REACH * magnification
    # Columns count from the first side of the image; once turned onto a page
    # that runs along x, that side is at the bottom, so the numbers count from there.
    label = (lambda value: str(across - 1 - value)) if axes['along_x'] else str
    for expected, inward in ((side, 1), (across - 1 - side, -1)):
        draw_gauge(sheet, expected - REACH, expected + REACH, run_from, magnification, label, [inward],
                   across_cut=False)

    for number in range(axes['count']):
        middle = args.cut_offset + number * axes['piece'] + axes['piece'] // 2
        draw_text(sheet, f'{args.page_size}  print {number + 1}/{axes["count"]}', (across // 2, middle + 40), 0.7)

    if axes['along_x']:
        # Rows were laid along the paper: turn them so they run along x, as the
        # page does. Row r becomes column r, so the numbers still count from
        # the start of the page.
        sheet = cv2.rotate(sheet, cv2.ROTATE_90_COUNTERCLOCKWISE)

    output = args.output or f'cut_calibration_{args.page_size}.png'
    cv2.imwrite(output, sheet)
    ends = ', '.join(str(args.cut_offset + number * axes['piece']) for number in range(axes['count'] + 1))
    first, last = (across - 1 - side, side) if axes['along_x'] else (side, across - 1 - side)
    print(f'{output}: {sheet.shape[1]}x{sheet.shape[0]} px')
    print(f'expected: ends and cuts at {ends}; sides at {first} and {last}')
    print(f'lp -o PageSize={args.page_size} -o print-scaling=fit {output}')


if __name__ == '__main__':
    main()
