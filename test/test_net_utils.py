"""The two things a QR code can tell a phone: which network, and which address.

Both are shown on a screen in a room, with no way to correct them once a guest
has scanned. A payload that is subtly malformed does not fail loudly; it simply
never connects, and nobody at the party can tell why.
"""

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from libs.net_utils import build_url, build_wifi_payload


def test_an_open_network_is_advertised_as_such():
    """install.sh sets the access point up without a password."""
    assert build_wifi_payload('PhotoBooth') == 'WIFI:T:nopass;S:PhotoBooth;P:;H:false;;'


def test_a_password_switches_the_payload_to_wpa():
    payload = build_wifi_payload('PhotoBooth', 'unmotdepasse')

    assert payload == 'WIFI:T:WPA;S:PhotoBooth;P:unmotdepasse;H:false;;'


def test_a_hidden_network_is_flagged():
    assert build_wifi_payload('PhotoBooth', hidden=True).endswith('H:true;;')


@pytest.mark.parametrize('raw,escaped', [
    ('Booth;1', 'Booth\\;1'),
    ('Booth:Mariage', 'Booth\\:Mariage'),
    ('Booth,Salle', 'Booth\\,Salle'),
    ('Booth"Fete"', 'Booth\\"Fete\\"'),
    ('Booth\\Fete', 'Booth\\\\Fete'),
])
def test_separators_inside_a_name_are_escaped(raw, escaped):
    """An unescaped separator ends the field early and the phone joins nothing."""
    assert build_wifi_payload(raw) == f'WIFI:T:nopass;S:{escaped};P:;H:false;;'


def test_a_password_with_separators_is_escaped_too():
    payload = build_wifi_payload('PhotoBooth', 'pass;word')

    assert 'P:pass\\;word;' in payload


def test_a_space_in_the_name_is_left_alone():
    assert build_wifi_payload('Photo Booth 2026') == 'WIFI:T:nopass;S:Photo Booth 2026;P:;H:false;;'


@pytest.mark.parametrize('ssid', [None, '', '   '])
def test_no_network_name_means_no_payload_at_all(ssid):
    """Without an access point the QR code has to carry the address instead."""
    assert build_wifi_payload(ssid) is None


def test_the_booth_address_keeps_its_port():
    assert build_url(5000, '/remote', host='192.168.4.1') == 'http://192.168.4.1:5000/remote'


def test_a_wildcard_bind_address_is_replaced_by_a_reachable_one():
    """0.0.0.0 is where the server listens, never somewhere a phone can go."""
    url = build_url(5000, '/remote', host='0.0.0.0')

    assert '0.0.0.0' not in url
    assert url.startswith('http://')


def test_an_override_is_taken_as_the_public_address():
    assert build_url(5000, '/remote', host='0.0.0.0', override='photobooth.local:8080') == \
        'http://photobooth.local:8080/remote'


def test_an_override_may_carry_its_own_scheme():
    assert build_url(5000, '/remote', override='https://booth.example.com/') == \
        'https://booth.example.com/remote'


def test_an_ipv6_address_is_bracketed_before_the_port():
    assert build_url(5000, '/remote', host='fd00::1') == 'http://[fd00::1]:5000/remote'
