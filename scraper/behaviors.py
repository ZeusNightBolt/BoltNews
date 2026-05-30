"""
Human-like anti-detection behaviors for web scraping.
Gaussian jitter on dwell times, chunked scrolling, session pacing.
"""
import random
import time


def human_delay(min_ms: int = 500, max_ms: int = 3000):
    """Random delay mimicking human reading/scanning time."""
    time.sleep(random.uniform(min_ms, max_ms) / 1000)


def gaussian_dwell(mu_s: float = 8.0, sigma_s: float = 2.0) -> float:
    """Gaussian-distributed dwell time per page."""
    return max(1.0, random.gauss(mu_s, sigma_s))


def scroll_chunked(min_px: int = 300, max_px: int = 800):
    """Return a scroll amount mimicking human chunked scrolling."""
    return random.randint(min_px, max_px)


def should_revisit(probability: float = 0.10) -> bool:
    """10% chance of 'double-take' revisit (professional scanning behavior)."""
    return random.random() < probability


def session_gap(min_m: float = 2.0, max_m: float = 8.0):
    """Wait between scraping sessions to avoid rate-limit triggering."""
    time.sleep(random.uniform(min_m, max_m) * 60)


class RateLimiter:
    """Token-bucket rate limiter for scraping sessions."""

    def __init__(self, max_pages: int = 15, per_seconds: int = 60):
        self.max_pages = max_pages
        self.per_seconds = per_seconds
        self.pages_this_window = 0
        self.window_start = time.time()

    def acquire(self) -> bool:
        """Try to acquire a page slot. Returns True if allowed."""
        now = time.time()
        if now - self.window_start > self.per_seconds:
            self.window_start = now
            self.pages_this_window = 0

        if self.pages_this_window < self.max_pages:
            self.pages_this_window += 1
            return True

        # Rate limited — wait for next window
        wait_time = self.per_seconds - (now - self.window_start) + 1
        time.sleep(max(0, wait_time))
        self.window_start = time.time()
        self.pages_this_window = 1
        return True
