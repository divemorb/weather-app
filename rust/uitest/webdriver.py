"""WebKit (Safari-like) for the UI suite: WebKitGTK's WebDriver in a virtual
display, behind `run.py --browser webkit`, never in the gate; needs the
`localhost/wetter-sandbox:station-webkit` image. Xvfb and WebKitWebDriver each
start in a session of their own (WebKit's browser processes join the
driver's group) and are stopped only through that group, never the caller's:
the harness shares its container, user and group with the agent running it.

    python3 rust/uitest/webdriver.py --self-test
"""

from __future__ import annotations

import base64
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DRIVER = "/usr/bin/WebKitWebDriver"
BROWSER = "/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/MiniBrowser"
LOCALES = {"en": "en_US.UTF-8", "de": "de_DE.UTF-8"}
PROCESS_NAMES = ("Xvfb", "WebKitWebDriver", "MiniBrowser", "WebKitWebProcess", "WebKitNetworkProcess",
                 "WebKitGPUProcess")


def free_port() -> int:
    """A TCP port nobody listens on right now."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def free_display() -> int:
    """An X display number with neither a socket nor a lock file."""
    for n in range(90, 190):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}") and not os.path.exists(f"/tmp/.X{n}-lock"):
            return n
    raise RuntimeError("no free X display in :90-:189")


def start_group(cmd: list[str], env: dict | None = None) -> subprocess.Popen:
    """Start cmd as the leader of a new session (its own process group)."""
    return subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def stop_group(proc: subprocess.Popen | None) -> None:
    """Stop proc's process group (TERM, then KILL after 5 s), also when the
    leader has exited and its children live on. Refuses the caller's group."""
    if proc is None:
        return
    pgid = proc.pid  # start_new_session: the leader's pid is the group id
    if pgid == os.getpgrp():
        raise RuntimeError("refusing to signal the caller's own process group")
    for sig, wait in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 5.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            break
        end = time.monotonic() + wait
        while time.monotonic() < end and group_alive(pgid):
            proc.poll()
            time.sleep(0.05)
        if not group_alive(pgid):
            break
    proc.poll()


def group_alive(pgid: int) -> bool:
    """Whether any process of the group still exists (zombies don't count)."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            stat = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if stat[0] != "Z" and int(stat[2]) == pgid:
            return True
    return False


class WebKit:
    """One WebKit browser (one language, one theme) driven over WebDriver."""

    def __init__(self, lang: str = "en", dark: bool = False):
        self.lang, self.dark = lang, dark
        self.xvfb = self.driver = None
        self.port = self.session = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    def start(self) -> None:
        """Xvfb, then WebKitWebDriver on it, then a session (closed again on failure)."""
        try:
            display = free_display()
            self.xvfb = start_group(["Xvfb", f":{display}", "-screen", "0", "1280x1024x24", "-nolisten", "tcp"])
            wait_for(lambda: os.path.exists(f"/tmp/.X11-unix/X{display}"), 10, "Xvfb did not start")
            # LC_ALL, not LANG alone: Python started in the C locale puts LC_CTYPE=C.UTF-8
            # into its children's environment (PEP 538), and WebKit takes the page's
            # language (navigator.language) from it
            env = {**os.environ, "DISPLAY": f":{display}", "LANG": LOCALES[self.lang],
                   "LC_ALL": LOCALES[self.lang], "TZ": "UTC",
                   "WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS": "1", "WEBKIT_DISABLE_COMPOSITING_MODE": "1"}
            env.pop("LC_CTYPE", None)
            if self.dark:
                env["GTK_THEME"] = "Adwaita:dark"
            self.port = free_port()
            self.driver = start_group([DRIVER, f"--port={self.port}"], env)
            wait_for(self._ready, 15, "WebKitWebDriver did not answer")
            caps = {"capabilities": {"alwaysMatch": {"browserName": "MiniBrowser", "webkitgtk:browserOptions": {
                "binary": BROWSER, "args": ["--automation"]}}}}
            self.session = self._call("POST", "/session", caps)["sessionId"]
        except Exception:
            self.close()
            raise

    def _ready(self) -> bool:
        try:
            return bool(self._call("GET", "/status").get("ready"))
        except OSError:
            return False

    def _call(self, method: str, path: str, body=None):
        """One WebDriver request; returns the answer's value (raises on an error)."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())["value"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"WebDriver {method} {path}: {e.code} {e.read().decode()[:300]}") from None

    def _sess(self, method: str, path: str, body=None):
        return self._call(method, f"/session/{self.session}{path}", body)

    def goto(self, url: str) -> None:
        """Open url and wait until it has loaded (WebDriver's page load strategy)."""
        self._sess("POST", "/url", {"url": url})

    def js(self, script: str, *args):
        """Run script (a function body: `return ...`) and return its value."""
        return self._sess("POST", "/execute/sync", {"script": script, "args": list(args)})

    def js_async(self, script: str, *args):
        """Run script; it calls its last argument with the result."""
        return self._sess("POST", "/execute/async", {"script": script, "args": list(args)})

    def window(self, width: int, height: int) -> dict:
        """Resize the window (at least 447 px wide: MiniBrowser's minimum)."""
        return self._sess("POST", "/window/rect", {"width": width, "height": height})

    def screenshot(self) -> bytes:
        """The viewport as PNG bytes."""
        return base64.b64decode(self._sess("GET", "/screenshot"))

    def close(self) -> None:
        """End the session, then stop the driver's and Xvfb's process groups."""
        if self.session:
            try:
                self._sess("DELETE", "")
            except (OSError, RuntimeError):
                pass
            self.session = None
        stop_group(self.driver)
        stop_group(self.xvfb)
        self.driver = self.xvfb = None


def wait_for(ok, seconds: float, message: str) -> None:
    """Poll ok() every 0.1 s until it is true; RuntimeError(message) after seconds."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if ok():
            return
        time.sleep(0.1)
    raise RuntimeError(message)


def leftovers() -> list[str]:
    """Xvfb or WebKit processes of this user that still exist (not zombies)."""
    found = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            name = open(f"/proc/{pid}/comm").read().strip()
            state = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0]
        except OSError:
            continue
        if state != "Z" and name.startswith(PROCESS_NAMES):
            found.append(f"{pid} {name}")
    return found


def self_test() -> int:
    """Three start/stop rounds (de dark, en light, de light): language, theme,
    window size and a screenshot each time; afterwards no process left over."""
    page = "data:text/html," + urllib.parse.quote("<body>ok</body>")
    problems = []
    for lang, dark in (("de", True), ("en", False), ("de", False)):
        with WebKit(lang, dark) as wk:
            wk.goto(page)
            got = wk.js("return [navigator.language, matchMedia('(prefers-color-scheme: dark)').matches,"
                        " document.body.textContent]")
            want = [{"de": "de-DE", "en": "en-US"}[lang], dark, "ok"]
            if got != want:
                problems.append(f"{lang} dark={dark}: page reports {got}, expected {want}")
            if wk.window(800, 600).get("width") != 800:
                problems.append(f"{lang}: the window did not take 800 px")
            if not wk.screenshot().startswith(b"\x89PNG"):
                problems.append(f"{lang}: the screenshot is not a PNG")
    problems += [f"left over: {p}" for p in leftovers()]
    for p in problems:
        print(p)
    print(f"webdriver self-test: {'OK' if not problems else f'{len(problems)} problems'}")
    return 1 if problems else 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--self-test"]:
        sys.exit(__doc__)
    sys.exit(self_test())
