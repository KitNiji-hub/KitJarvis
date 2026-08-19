"""Debug logging utilities for Jarvis."""
import sys
import time
from typing import Optional
from .config import load_settings


_last_check_time: float = 0.0
_cached_voice_debug: Optional[bool] = None
_CACHE_TTL_SECONDS: float = 2.0


def _is_debug_enabled() -> bool:
    global _last_check_time, _cached_voice_debug
    now = time.time()
    if _cached_voice_debug is None or (now - _last_check_time) > _CACHE_TTL_SECONDS:
        try:
            _cached_voice_debug = bool(load_settings().voice_debug)
        except Exception:
            _cached_voice_debug = False
        _last_check_time = now
    return bool(_cached_voice_debug)


def debug_log(message: str, category: str = "debug") -> None:
    """Unified debug logging function for Jarvis.

    Args:
        message: The debug message to log
        category: The log category (e.g., "debug", "voice", "echo", "tts", etc.)
    """
    if not _is_debug_enabled():
        return
    try:
        # Debug output can include tool results, exception text, URLs, or
        # request metadata. Apply the same structural secret scrubber used
        # elsewhere before anything reaches stderr so debug mode cannot
        # accidentally disclose credentials.
        from .utils.redact import scrub_secrets

        safe_message = scrub_secrets(str(message))
        print(f"[{category:^10}] {safe_message}", file=sys.stderr)
    except Exception:
        pass
