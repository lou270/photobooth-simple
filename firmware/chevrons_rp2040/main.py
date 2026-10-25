"""MicroPython firmware for an RP2040 (Waveshare RP2040-Zero) driving the chevrons.

The booth sends lines on the RP2040's UART0 RX (GP1), at 115200 baud:

    F <hz>                      PWM frequency
    L <inner> <middle> <outer>  duty cycles, 0 to 65535, applied at once
    I <inner> <middle> <outer>  ambient duty cycles, applied when the booth
                                has said nothing for SILENCE_MS

Every effect is worked out on the booth: this only turns numbers into
hardware PWM, which is steady whatever the Pi is busy with. Until the booth
first speaks, every row stays dark; and once it has said nothing for
DARK_AFTER_MS, the rows go dark again, so a booth that died or was unplugged
does not leave the chevrons lit for the rest of the night.

Copy it to the board as main.py, for instance with `mpremote cp main.py :main.py`.
"""

import time

from machine import PWM, UART, Pin

# Inner (next to the lens), middle, outer: each to the gate of its MOSFET.
ROW_PINS = (12, 13, 14)
RX_PIN = 1
BAUDRATE = 115200
SILENCE_MS = 3000
DARK_AFTER_MS = 60000
MAX_LINE = 64

rows = [PWM(Pin(pin)) for pin in ROW_PINS]
duties = [0, 0, 0]
idle_duties = [0, 0, 0]


def clamp(value, low, high):
    return max(low, min(high, value))


def apply(values):
    # 65535 is a steady high, with no pulse at all: MicroPython caps TOP at
    # 65534 and turns 65535 into CC = TOP + 1, which the RP2040 datasheet (4.5,
    # "0% and 100% Duty Cycle") guarantees glitch-free. The shot is taken there,
    # so the camera never sees the PWM as banding.
    for index, row in enumerate(rows):
        duties[index] = values[index]
        row.duty_u16(values[index])


def set_frequency(hz):
    for row in rows:
        row.freq(clamp(hz, 10, 20000))
    # A new frequency recomputes the counter: put the duty cycles back on it.
    apply(list(duties))


def handle(line):
    """True when the line was understood."""
    parts = line.split()
    if not parts:
        return False
    try:
        values = [int(part) for part in parts[1:]]
    except ValueError:
        return False
    command = parts[0]
    if command == b'F' and len(values) == 1:
        set_frequency(values[0])
    elif command == b'L' and len(values) == 3:
        apply([clamp(value, 0, 65535) for value in values])
    elif command == b'I' and len(values) == 3:
        for index, value in enumerate(values):
            idle_duties[index] = clamp(value, 0, 65535)
    else:
        return False
    return True


def fall_back(silent_ms, state):
    """Where a quiet booth leaves the rows: 'live', then 'idle', then 'dark'."""
    if silent_ms > DARK_AFTER_MS:
        if state != 'dark':
            apply([0, 0, 0])
        return 'dark'
    if silent_ms > SILENCE_MS and state == 'live':
        apply(list(idle_duties))
        return 'idle'
    return state


def main():
    uart = UART(0, baudrate=BAUDRATE, rx=Pin(RX_PIN), timeout=0)
    set_frequency(1000)
    apply([0, 0, 0])

    pending = b''
    last_heard = time.ticks_ms()
    state = 'dark'
    while True:
        data = uart.read()
        if data:
            pending += data
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                if handle(line.strip()):
                    last_heard = time.ticks_ms()
                    state = 'live'
            # Noise on an unplugged wire never ends in a newline.
            if len(pending) > MAX_LINE:
                pending = b''
        else:
            state = fall_back(time.ticks_diff(time.ticks_ms(), last_heard), state)
        time.sleep_ms(2)


# MicroPython runs main.py as __main__; the booth's tests import it instead.
if __name__ == '__main__':
    main()
