from __future__ import annotations

import random


def retry_delay(attempt: int, *, base: float = 1.0, maximum: float = 60.0) -> float:
    """Exponential backoff with full jitter."""
    ceiling = min(maximum, base * (2**attempt))
    return random.uniform(0, ceiling)
