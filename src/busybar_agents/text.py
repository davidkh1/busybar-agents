"""Text the bar's bitmap fonts can show."""

from __future__ import annotations

import re

_SPACES = re.compile(r"\s+")


def sanitize(text: str, limit: int = 48) -> str:
    """Printable ASCII, single spaces, at most ``limit`` characters."""
    ascii_only = text.encode("ascii", "ignore").decode("ascii")
    printable = "".join(ch for ch in ascii_only if 0x20 <= ord(ch) <= 0x7E)
    return _SPACES.sub(" ", printable).strip()[:limit].rstrip()
