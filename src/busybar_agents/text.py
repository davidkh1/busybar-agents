"""Text that is safe for the bar's bitmap fonts."""

from __future__ import annotations

import re

_SPACES = re.compile(r"\s+")


def sanitize(text: str, limit: int = 48) -> str:
    """Printable ASCII only, single spaces, trimmed to ``limit`` characters.

    The firmware refuses anything outside 0x20-0x7E, and hook messages arrive
    with curly quotes, emoji and newlines. Long text is cut rather than
    ellipsised, because the tiny font scrolls anything that does not fit.
    """
    ascii_only = text.encode("ascii", "ignore").decode("ascii")
    printable = "".join(ch for ch in ascii_only if 0x20 <= ord(ch) <= 0x7E)
    collapsed = _SPACES.sub(" ", printable).strip()
    return collapsed[:limit].rstrip()
