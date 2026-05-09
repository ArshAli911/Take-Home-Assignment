"""Filename sanitization for user-supplied uploads.

We never trust a user-provided filename on disk — every stored video is
named after its UUID. This helper exists purely to produce a safe
`original_filename` value for display and for the Content-Disposition
header on download.
"""

import os
import re

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_filename(name: str | None) -> str:
    """Strip any path component and reject characters outside [A-Za-z0-9._-].

    Falls back to "upload.mp4" if nothing usable remains.
    """
    if not name:
        return "upload.mp4"
    # `os.path.basename` defends against `../etc/passwd`-style payloads.
    base = os.path.basename(name).strip()
    cleaned = _SAFE.sub("_", base)
    # Collapse runs of dots so `..` and friends become a single dot.
    cleaned = re.sub(r"\.{2,}", ".", cleaned).strip("._-")
    return cleaned or "upload.mp4"
