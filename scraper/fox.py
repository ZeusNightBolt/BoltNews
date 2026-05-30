"""
Firefox WebDriver BiDi session manager.
Context-managed lifecycle: start → use → cleanup.
Never more than one session — OOM guard built in.
"""
import json
import subprocess
import time
import os
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError


FIREFOX_BINARY = "/usr/bin/firefox"
GECKODRIVER_BINARY = str(Path.home() / ".local/bin/geckodriver")
BIDI_PORT = 9222
FIREFOX_PROFILE = str(Path.home() / ".mozilla/firefox/firefox-remote-scrape-enable")


class FirefoxSession:
    """Manage a Firefox BiDi session for anti-bot scraping."""

    def __init__(self, headless: bool = True, port: int = BIDI_PORT):
        self.headless = headless
        self.port = port
        self._firefox_pid: int | None = None
        self._ws_url: str | None = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def start(self):
        """Start Firefox with BiDi debug port."""
        if self._is_running():
            print(f"[Fox] BiDi already running on :{self.port}")
            self._ws_url = f"ws://127.0.0.1:{self.port}/session"
            return

        # Kill any stale Firefox instances
        subprocess.run(["pkill", "-f", "firefox-remote-scrape-enable"],
                       capture_output=True)
        time.sleep(1)

        cmd = [
            FIREFOX_BINARY,
            "--remote-debugging-port", str(self.port),
            "--profile", FIREFOX_PROFILE,
            "--no-remote",
            "--new-instance",
        ]
        if self.headless:
            cmd.append("--headless")

        env = os.environ.copy()
        env["DISPLAY"] = ":0"

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        self._firefox_pid = proc.pid

        # Wait for BiDi to be ready
        for _ in range(20):
            time.sleep(0.5)
            if self._is_running():
                self._ws_url = f"ws://127.0.0.1:{self.port}/session"
                print(f"[Fox] BiDi ready on :{self.port} (PID {self._firefox_pid})")
                return

        raise RuntimeError(f"Firefox BiDi failed to start on :{self.port}")

    def stop(self):
        """Kill Firefox and free the port."""
        if self._firefox_pid:
            try:
                subprocess.run(["kill", str(self._firefox_pid)],
                               capture_output=True, timeout=5)
            except Exception:
                pass
            self._firefox_pid = None

        # Also kill any remaining by name
        subprocess.run(["pkill", "-f", "firefox-remote-scrape-enable"],
                       capture_output=True)

        # Free port
        subprocess.run(["fuser", "-k", f"{self.port}/tcp"],
                       capture_output=True)

        self._ws_url = None
        print(f"[Fox] Stopped :{self.port}")

    def _is_running(self) -> bool:
        """Check if BiDi is responding."""
        try:
            # Check via HTTP status endpoint
            req = Request(
                f"http://127.0.0.1:{self.port}/json/version",
                headers={"User-Agent": "hermes"},
            )
            with urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read())
                    self._ws_url = data.get("webSocketDebuggerUrl", "")
                    return bool(self._ws_url)
        except (URLError, OSError, json.JSONDecodeError):
            pass
        return False

    @property
    def ws_url(self) -> str:
        if not self._ws_url:
            raise RuntimeError("Firefox BiDi not running. Call start() first.")
        return self._ws_url


@contextmanager
def fox_session(headless: bool = True):
    """Convenience context manager for one-shot BiDi scraping."""
    session = FirefoxSession(headless=headless)
    try:
        session.start()
        yield session
    finally:
        session.stop()


def is_fox_running() -> bool:
    """Check if any Firefox BiDi is running — OOM guard."""
    try:
        result = subprocess.run(
            ["pgrep", "-c", "firefox"],
            capture_output=True, text=True, timeout=3,
        )
        return int(result.stdout.strip() or 0) > 0
    except Exception:
        return False
