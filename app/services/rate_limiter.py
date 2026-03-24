import asyncio
import time


class RateLimiter:
    def __init__(self, delay_seconds: float = 1.0):
        self._delay = delay_seconds
        self._last_call = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._delay:
                await asyncio.sleep(self._delay - elapsed)
            self._last_call = time.monotonic()
