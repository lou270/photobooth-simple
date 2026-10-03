#!/bin/sh
# Hold photobooth.service back until the desktop it draws on exists.
#
# graphical.target is reached when the login manager starts, not when the
# desktop has logged in and opened its display, which is several seconds later
# on a Pi. Started before that, the booth found no display, crashed, and spent
# its restart budget before the desktop was up. This waits for the X socket
# of $DISPLAY - X11's own, or the one Wayland opens for X clients.
#
# Run by systemd as ExecStartPre; exits 1 after two minutes so systemd reports
# the failure instead of the booth waiting forever on a machine with no desktop.

display_number="${DISPLAY:-:0}"
display_number="${display_number#*:}"
display_number="${display_number%%.*}"
socket="/tmp/.X11-unix/X${display_number}"

waited=0
while [ ! -S "$socket" ]; do
    if [ "$waited" -ge 120 ]; then
        echo "wait-for-display: no display at $socket after ${waited}s" >&2
        exit 1
    fi
    sleep 1
    waited=$((waited + 1))
done
exit 0
