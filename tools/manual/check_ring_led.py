"""Manual hardware check: drives every ring-light effect in sequence.

Run on the booth itself: `python tools/manual/check_ring_led.py`
"""

import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))
from libs.hardware.led import RingLed

leds = RingLed(num_pixels=12)

print('Start countdown')
leds.start_countdown(5)
time.sleep(6)

print('Start rainbow')
leds.start_rainbow()
time.sleep(5)
leds.clear()

print('Start flash')
leds.flash()
time.sleep(0.5)
leds.flash(stop=True)
time.sleep(1)

print('Start blink')
leds.blink([255, 255, 255])
time.sleep(5)

print('Start wave')
leds.wave([255, 255, 255])
time.sleep(5)

print('Stop')
leds.clear()
