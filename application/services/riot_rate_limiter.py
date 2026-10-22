import threading
import time
from collections import deque


class RiotRateLimiter:
    """
    Delays requests so every (count, window seconds) limit holds.

    The defaults stay below the development-key limits of 20 requests
    per second and 100 requests per two minutes. One instance is shared
    by every match history request in the process.
    """

    DEVELOPMENT_KEY_LIMITS = (
        (18, 1.0),
        (95, 120.0),
    )

    def __init__(
        self,
        limits=DEVELOPMENT_KEY_LIMITS,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.limits = tuple(limits)
        self.clock = clock
        self.sleep = sleep
        self.history = deque()
        self.longest_window = max(
            window for _, window in self.limits
        )
        self._lock = threading.Lock()

    def wait(self):
        """
        Block until one more request fits every limit, then record it.
        """

        with self._lock:
            while True:
                delay = self._required_delay(
                    self.clock()
                )

                if delay <= 0:
                    self.history.append(
                        self.clock()
                    )
                    return

                self.sleep(delay)

    def _required_delay(self, now):
        while (
            self.history
            and now - self.history[0] >= self.longest_window
        ):
            self.history.popleft()

        delay = 0.0

        for count, window in self.limits:
            recent = [
                moment
                for moment in self.history
                if now - moment < window
            ]

            if len(recent) >= count:
                delay = max(
                    delay,
                    window - (now - recent[-count]),
                )

        return delay


shared_rate_limiter = RiotRateLimiter()
