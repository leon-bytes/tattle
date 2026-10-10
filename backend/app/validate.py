"""Checks for what arrives from outside. Phones choose their own DNS names and DHCP names, and a
model writes company names: none of it is trusted, all of it ends up on a screen."""
from __future__ import annotations

import ipaddress
import re

# A name we are willing to keep and show: dot-separated labels of letters, digits, "-" and "_".
# Real host names fit; names carrying other bytes (DNS allows any) are counted as malformed and dropped.
_HOSTNAME = re.compile(r"(?=.{1,253}$)[a-z0-9_-]{1,63}(\.[a-z0-9_-]{1,63})*")


def is_hostname(name: str) -> bool:
    return _HOSTNAME.fullmatch(name) is not None


def is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def plain(text: object, limit: int) -> str | None:
    """Free text (a device name, an app label, a model's sentence) cut down to printable characters and a
    sane length. None if nothing is left. It is still only ever shown as text, never as markup."""
    if not isinstance(text, str):
        return None
    return "".join(ch for ch in text if ch.isprintable()).strip()[:limit] or None
