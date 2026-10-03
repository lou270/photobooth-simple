"""Hot pixel removal for DSLR frames.

An ageing sensor has pixels that read bright whatever the light: white or
coloured dots, most visible in the dark parts of the picture and more numerous
as the sensor warms up in live view. The camera's own JPEG spreads each one
into a blob of up to 3x3 pixels with a dark halo.

A plain median filter is no answer: a 3x3 one leaves a cross where each blob
was, and a 5x5 one blurs every eye and every strand of hair. This one only
touches small spots that are much brighter than everything around them. A line
or an edge is not surrounded by darker pixels on every side, and a highlight in
an eye is larger than a blob, so both are left exactly as they were.
"""

import cv2
import numpy as np

# How much brighter than its surroundings a pixel must be to count as hot.
SPIKE_THRESHOLD = 40
# Neighbourhood that sets the reference level a pixel is compared with. 5x5 is
# the widest OpenCV runs on its fast path: 7x7 finds the same spots for three
# times the cost on a 12 MP photo.
DETECT_MEDIAN_SIZE = 5
# Largest spot, in pixels per side, still taken for a hot pixel.
MAX_SPOT_SIZE = 5
# The replaced area reaches this far past each spot, to take its halo too.
HALO_RADIUS = 2
# The ring checked around a spot sits just outside the halo. A hot pixel is
# darker all the way round it; the corner of a bright object is not.
RING_RADIUS = HALO_RADIUS + 1
RING_PERCENTILE = 75
RING_SAMPLES_PER_SIDE = 4
# Neighbourhood a spot takes its new colour from: wide enough that a blob and
# its halo do not pull the median their way.
FILL_MEDIAN_SIZE = 7


def _brightness(image):
    blue, green, red = cv2.split(image)
    return cv2.max(cv2.max(blue, green), red)


def _expand(box, radius, height, width):
    left, top, w, h = box
    return (max(0, top - radius), min(height, top + h + radius),
            max(0, left - radius), min(width, left + w + radius))


def _mirror(index, size):
    """Fold coordinates past the frame back inside it, as BORDER_REFLECT_101 does.

    Clamping them instead would put the ring of a spot in a corner on the spot
    itself, and a spot is never brighter than itself.
    """
    index = np.abs(index)
    return np.where(index >= size, 2 * (size - 1) - index, index)


def _hot_spots(image):
    """(y0, y1, x0, x1) of the area to repaint around each hot pixel."""
    brightness = _brightness(image)
    local = cv2.medianBlur(brightness, DETECT_MEDIAN_SIZE)
    flagged = (cv2.subtract(brightness, local) > SPIKE_THRESHOLD).astype(np.uint8)
    if not flagged.any():
        return []

    height, width = flagged.shape
    count, labels, stats, _ = cv2.connectedComponentsWithStats(flagged, connectivity=8)
    left, top, w, h = (stats[1:count, i] for i in range(4))
    small = (w <= MAX_SPOT_SIZE) & (h <= MAX_SPOT_SIZE)

    # Brightest pixel of each spot.
    peak = np.zeros(count, dtype=np.int32)
    ys, xs = np.nonzero(labels)
    np.maximum.at(peak, labels[ys, xs], brightness[ys, xs])
    peak = peak[1:]

    # The ring is sampled rather than read whole: a noisy high-ISO frame has
    # thousands of candidates, and one Python loop iteration each cost the
    # preview its frame rate. Points along each side of the box around the spot,
    # corners included.
    y0, y1 = top - RING_RADIUS, top + h - 1 + RING_RADIUS
    x0, x1 = left - RING_RADIUS, left + w - 1 + RING_RADIUS
    steps = np.linspace(0.0, 1.0, RING_SAMPLES_PER_SIDE, endpoint=False)[:, None]
    along_x = np.rint(x0 + (x1 - x0) * steps).astype(int)
    along_y = np.rint(y0 + (y1 - y0) * steps).astype(int)
    ring_y = np.concatenate((np.broadcast_to(y0, along_x.shape), along_y,
                             np.broadcast_to(y1, along_x.shape), y1 - (along_y - y0)))
    ring_x = np.concatenate((along_x, np.broadcast_to(x1, along_y.shape),
                             x1 - (along_x - x0), np.broadcast_to(x0, along_y.shape)))
    ring = brightness[_mirror(ring_y, height), _mirror(ring_x, width)]
    surroundings = np.percentile(ring, RING_PERCENTILE, axis=0)

    hot = small & (peak - surroundings > SPIKE_THRESHOLD)
    return [_expand(box, HALO_RADIUS, height, width)
            for box in zip(left[hot], top[hot], w[hot], h[hot])]


def find_hot_pixels(image):
    """Mask (bool, image height x width) of the pixels remove_hot_pixels() repaints."""
    mask = np.zeros(image.shape[:2], dtype=bool)
    for y0, y1, x0, x1 in _hot_spots(image):
        mask[y0:y1, x0:x1] = True
    return mask


def remove_hot_pixels(image):
    """Return a BGR uint8 image with its hot pixels painted over.

    The input is never modified; it comes back as is when there is nothing to
    paint. Each spot takes the median colour of its neighbourhood, computed
    around the spot only: a 12 MP photo has a few hundred of them, and a
    full-frame median of that size costs the Raspberry Pi far more.
    """
    spots = _hot_spots(image)
    if not spots:
        return image

    result = image.copy()
    margin = FILL_MEDIAN_SIZE // 2
    height, width = image.shape[:2]
    for y0, y1, x0, x1 in spots:
        # Mirror the frame where the neighbourhood runs past its edge: the
        # median's own border handling repeats the edge row, which for a spot
        # in a corner repeats the spot itself and hands it back unchanged.
        ry0, ry1 = max(0, y0 - margin), min(height, y1 + margin)
        rx0, rx1 = max(0, x0 - margin), min(width, x1 + margin)
        patch = cv2.copyMakeBorder(
            image[ry0:ry1, rx0:rx1],
            margin - (y0 - ry0), margin - (ry1 - y1), margin - (x0 - rx0), margin - (rx1 - x1),
            cv2.BORDER_REFLECT_101,
        )
        smoothed = cv2.medianBlur(patch, FILL_MEDIAN_SIZE)
        result[y0:y1, x0:x1] = smoothed[margin:margin + (y1 - y0), margin:margin + (x1 - x0)]
    return result
