"""
Parser profile registry for Telegram signal sources.

New provider formats can be added here without changing the listener.
"""

from typing import Optional

from core.signal import Signal


def parse_with_profile(profile: str, text: str) -> Optional[Signal]:
    """Route a Telegram message through the parser configured for its source."""
    normalized = (profile or "default").lower()
    if normalized == "geom5":
        from core.parsers.geom5 import parse_signal as parse_geom5_signal

        return parse_geom5_signal(text)
    if normalized in {"default", "flexible"}:
        from core.parsers.flexible import parse_signal as parse_flexible_signal

        return parse_flexible_signal(text)
    return None