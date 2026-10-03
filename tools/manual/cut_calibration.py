#!/usr/bin/env python3
"""Print a sheet that shows exactly where the printer's cutter goes through it.

A printer that cuts one sheet into several prints (a QW410's 2x4*3) cuts at
fixed distances, while the image it is given is stretched over a page slightly
longer than the paper. Where the cuts land in that page is not written in the
PPD: this sheet measures it.

Across each cut runs a diagonal that drops one pixel every ten: wherever the
cutter goes, the diagonal leaves the cut edge at a point ten times easier to
read than the cut itself, under a scale numbered in page pixels (300 dpi,
counted from the start of the page along the paper). Read the number where the
diagonal meets the edge, on both pieces of each cut.

    python3 tools/manual/cut_calibration.py w288h432-div3
    lp -d QW410 -o PageSize=w288h432-div3 -o print-scaling=fit cut_calibration_w288h432-div3.png
"""

import argparse
import re
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from libs.print_sizes import describe

DPI = 300
POINTS_PER_INCH = 72
# How far around the nominal cut the diagonal reaches, in page pixels. The
# cut has been seen up to about 25 px from where the booth expected it.
BEFORE_CUT = 40
AFTER_CUT = 80
MAGNIFICATION = 10


def ppd_entry(ppd_text, keyword, page_size):
    match = re.search(rf'^\*{keyword} {re.escape(page_size)}/([^:]*):\s*"([^"]*)"', ppd_text, re.MULTILINE)
    if not match:
        sys.exit(f'{page_size}: no *{keyword} line in the PPD')
    return match.group(1).strip(), [float(value) for value in match.group(2).split()]


def to_pixels(points):
    return int(round(points * DPI / POINTS_PER_INCH))


def draw_cut_gauge(sheet, cut, across_start, across_length):
    """The diagonal and its scales around one nominal cut, rows along the paper."""
    black, grey = (0, 0, 0), (120, 120, 120)
    top = cut - BEFORE_CUT
    bottom = cut + AFTER_CUT
    span = (bottom - top) * MAGNIFICATION
    left = across_start + (across_length - span) // 2

    cv2.line(sheet, (left, top), (left + span, bottom), black, 2, cv2.LINE_AA)
    for row in range(top, bottom + 1):
        x = left + (row - top) * MAGNIFICATION
        major = row % 10 == 0
        length = 22 if major else 10
        # The same scale on both sides of the cut, so either piece can be read.
        cv2.line(sheet, (x, top - 6 - length), (x, top - 6), black if major else grey, 2 if major else 1)
        cv2.line(sheet, (x, bottom + 6), (x, bottom + 6 + length), black if major else grey, 2 if major else 1)
        if major:
            label = str(row)
            (width, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
            cv2.putText(sheet, label, (x - width // 2, top - 36), cv2.FONT_HERSHEY_SIMPLEX, 0.8, black, 2, cv2.LINE_AA)
            cv2.putText(sheet, label, (x - width // 2, bottom + 62), cv2.FONT_HERSHEY_SIMPLEX, 0.8, black, 2, cv2.LINE_AA)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('page_size', help='PageSize to measure, e.g. w288h432-div3')
    parser.add_argument('--ppd', default='/etc/cups/ppd/QW410.ppd')
    parser.add_argument('--output', help='PNG to write (default: cut_calibration_<page_size>.png)')
    args = parser.parse_args()

    ppd_text = Path(args.ppd).read_text(encoding='latin-1')
    label, paper = ppd_entry(ppd_text, 'PaperDimension', args.page_size)
    _, area = ppd_entry(ppd_text, 'ImageableArea', args.page_size)
    size = describe(args.page_size, label)
    if size is None or size['count'] < 2:
        sys.exit(f'{args.page_size} ({label}) is not a sheet cut into several prints')

    # The image is made the size of the imageable area, so print-scaling=fit
    # leaves it at 300 dpi and a pixel of this file is a pixel of the page.
    left, bottom, right, top = area
    width, height = to_pixels(right - left), to_pixels(top - bottom)
    # Along the paper is the side the driver prints right to the edge of the
    # page: the other one has margins, the paper being narrower than the head.
    along_x = left == 0 and right == paper[0]
    length, across = (width, height) if along_x else (height, width)

    # The paper is as wide as the w in the name; a print's other side is the
    # one that runs along it, the length the cutter measures off.
    paper_width = float(re.match(r'w(\d+(?:\.\d+)?)', args.page_size).group(1)) / POINTS_PER_INCH
    along = size['long_in'] if abs(size['short_in'] - paper_width) < 0.05 else size['short_in']
    piece = to_pixels(along * POINTS_PER_INCH)

    sheet = np.full((length, across, 3), 255, dtype=np.uint8)
    for number in range(1, size['count']):
        draw_cut_gauge(sheet, number * piece, 0, across)
    for number in range(size['count']):
        middle = number * piece + piece // 2
        text = f'{args.page_size}  {label}  piece {number + 1}/{size["count"]}  page {length} px'
        cv2.putText(sheet, text, (40, middle + 140), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2, cv2.LINE_AA)

    if along_x:
        # Rows were laid along the paper: turn them so they run along x, as the
        # page does. Row r becomes column r, so the numbers still count from
        # the start of the page.
        sheet = cv2.rotate(sheet, cv2.ROTATE_90_COUNTERCLOCKWISE)

    output = args.output or f'cut_calibration_{args.page_size}.png'
    cv2.imwrite(output, sheet)
    print(f'{output}: {sheet.shape[1]}x{sheet.shape[0]} px, cuts expected near '
          + ', '.join(str(number * piece) for number in range(1, size['count'])))
    print(f'lp -o PageSize={args.page_size} -o print-scaling=fit {output}')


if __name__ == '__main__':
    main()
