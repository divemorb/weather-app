"""A minimal Chrome DevTools Protocol client over ``--remote-debugging-pipe``.

Stdlib only: Chromium reads commands from fd 3 and writes replies and
events to fd 4, each message a JSON object followed by a NUL byte. No
websocket and no chromedriver are needed.

    with Browser(lang="de-DE") as b:
        page = b.new_page()          # own browser context: fresh storage
        page.send("Page.navigate", {"url": "http://127.0.0.1:8000/"})
"""
from __future__ import annotations

import fcntl
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time

# Opt-in coverage report (coverage_report.py): every page records JS block
# coverage and CSS rule usage and writes them here when it closes.
COVERAGE_DIR = os.environ.get("WETTER_UITEST_COVERAGE")

CHROMIUM_FLAGS = [
    "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
    "--no-first-run", "--no-default-browser-check", "--disable-extensions",
    "--disable-background-networking", "--disable-component-update", "--disable-sync",
    "--disable-features=Translate,MediaRouter,OptimizationHints", "--mute-audio",
    "--hide-scrollbars", "--remote-debugging-pipe",
]


class CDPError(RuntimeError):
    """A protocol error: the browser gave no reply in time, or answered with an error."""
    pass


class Browser:
    """A headless Chromium driven over CDP; each page lives in its own context (fresh storage)."""

    def __init__(self, lang: str = "en-US", binary: str = "chromium"):
        self.profile = tempfile.mkdtemp(prefix="uitest-chromium-")
        to_child_r, self._to_child = os.pipe()
        self._from_child, from_child_w = os.pipe()
        # Above 4 first, so the dup2 calls in the child can't clobber each other.
        high_r = fcntl.fcntl(to_child_r, fcntl.F_DUPFD, 10)
        high_w = fcntl.fcntl(from_child_w, fcntl.F_DUPFD, 10)
        os.close(to_child_r)
        os.close(from_child_w)

        def move_fds():  # the child's fd 3 reads commands, fd 4 writes replies
            os.dup2(high_r, 3)
            os.dup2(high_w, 4)

        env = {**os.environ, "TZ": "UTC", "LANG": lang.replace("-", "_") + ".UTF-8",
               "LANGUAGE": lang.replace("-", "_")}
        self.proc = subprocess.Popen(
            [shutil.which(binary) or binary, *CHROMIUM_FLAGS, f"--lang={lang}",
             f"--accept-lang={lang},{lang.split('-')[0]}", f"--user-data-dir={self.profile}", "about:blank"],
            # fds 3 and 4 are kept: CPython closes the others after preexec_fn
            preexec_fn=move_fds, pass_fds=(3, 4), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(high_r)
        os.close(high_w)
        self._next_id = 0
        self._lock = threading.Lock()
        self._waiting: dict[int, queue.Queue] = {}
        self._events: dict[str | None, queue.Queue] = {}
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.send("Target.setDiscoverTargets", {"discover": True})

    # --- transport -------------------------------------------------------

    def _read_loop(self):
        buf = b""
        while True:
            chunk = os.read(self._from_child, 1 << 20)
            if not chunk:
                break
            buf += chunk
            while b"\0" in buf:
                raw, buf = buf.split(b"\0", 1)
                msg = json.loads(raw)
                if "id" in msg:
                    q = self._waiting.pop(msg["id"], None)
                    if q is not None:
                        q.put(msg)
                else:
                    self._event_queue(msg.get("sessionId")).put(msg)
        for q in list(self._waiting.values()):
            q.put({"error": {"message": "browser closed the pipe"}})

    def _event_queue(self, session):
        with self._lock:
            return self._events.setdefault(session, queue.Queue())

    def send(self, method: str, params: dict | None = None, session: str | None = None,
             timeout: float = 30.0) -> dict:
        with self._lock:
            self._next_id += 1
            msg_id = self._next_id
            q: queue.Queue = queue.Queue()
            self._waiting[msg_id] = q
        msg = {"id": msg_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        data = json.dumps(msg).encode() + b"\0"
        while data:
            data = data[os.write(self._to_child, data):]
        try:
            reply = q.get(timeout=timeout)
        except queue.Empty:
            raise CDPError(f"{method}: no reply after {timeout:.0f} s") from None
        if "error" in reply:
            raise CDPError(f"{method}: {reply['error'].get('message')}")
        return reply.get("result", {})

    def events(self, session: str | None) -> list[dict]:
        """All events received so far for a session (drains the queue)."""
        q = self._event_queue(session)
        out = []
        while True:
            try:
                out.append(q.get_nowait())
            except queue.Empty:
                return out

    # --- pages -----------------------------------------------------------

    def new_page(self) -> "Page":
        ctx = self.send("Target.createBrowserContext", {"disposeOnDetach": True})["browserContextId"]
        target = self.send("Target.createTarget", {"url": "about:blank", "browserContextId": ctx})["targetId"]
        session = self.send("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        return Page(self, session, target, ctx)

    def close(self):
        try:
            self.send("Browser.close", timeout=5)
        except CDPError:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        for fd in (self._to_child, self._from_child):
            try:
                os.close(fd)
            except OSError:
                pass
        shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Page:
    """One tab in its own browser context; collects errors and network activity."""

    KEYS = {"Escape": ("Escape", 27)}  # key name -> (code, windowsVirtualKeyCode)

    def __init__(self, browser: Browser, session: str, target: str, context: str):
        self.b, self.session, self.target, self.context = browser, session, target, context
        self.errors: list[str] = []
        self.requests: list[str] = []
        self._inflight: set[str] = set()
        self._last_net = time.monotonic()
        self._loaded = False
        self._fakes: dict[str, list[tuple[int, str]]] = {}
        for domain in ("Page", "Runtime", "Log", "Network"):
            self.send(f"{domain}.enable")
        self._sheets: dict[str, str] = {}
        self._coverage: list[dict] = []
        if COVERAGE_DIR:
            for method, params in (("Profiler.enable", {}), ("DOM.enable", {}), ("CSS.enable", {}),
                                   ("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True}),
                                   ("CSS.startRuleUsageTracking", {})):
                self.send(method, params)

    def _take_coverage(self, final: bool):
        """Collect the coverage so far (before a navigation drops the scripts)."""
        self.pump()
        js = self.send("Profiler.takePreciseCoverage")["result"]
        css = self.send("CSS.stopRuleUsageTracking" if final else "CSS.takeCoverageDelta")
        rules = [{"url": self._sheets.get(r["styleSheetId"], ""), "start": r["startOffset"],
                  "end": r["endOffset"], "used": r["used"]} for r in css.get("ruleUsage", css.get("coverage", []))]
        self._coverage.append({"js": js, "css": rules})
        if final:
            name = f"{os.getpid()}-{self.target}.json"
            os.makedirs(COVERAGE_DIR, exist_ok=True)  # parallel workers: any may be first
            with open(os.path.join(COVERAGE_DIR, name), "w") as f:
                json.dump(self._coverage, f)

    def fake(self, responses: dict[str, list[tuple[int, str]]]):
        """Answer the next requests to these paths with (status, JSON body), in
        order; once a path's list is used up, its requests reach the app again.
        A key ending in * is a path prefix; a key starting with a method word
        ("DELETE /api/reports/*") also matches the request's method. Call
        before goto(); the fakes are served while the page is pumped."""
        self._fakes = {path: list(seq) for path, seq in responses.items()}
        self.send("Fetch.enable", {"patterns": [{"urlPattern": f"*{self._fake_pattern(key)}*"}
                                                for key in responses]})

    def fakes_left(self) -> int:
        """How many faked answers are still waiting to be served."""
        return sum(len(seq) for seq in self._fakes.values())

    @staticmethod
    def _fake_pattern(key: str) -> str:
        """The urlPattern for a fake key: the path part (after an optional method word)."""
        return key.split(" ", 1)[1] if " " in key else key

    def _fake_key(self, path: str, method: str) -> str | None:
        """The key of the fake that answers this request: the exact path first,
        then a "METHOD prefix*" or "prefix*" key (a * matches the rest of the path)."""
        if path in self._fakes:
            return path
        for key in self._fakes:
            if not self._fakes[key]:
                continue
            m, pat = (key.split(" ", 1) + [""])[:2] if " " in key else ("", key)
            if (m == method if m else True) and path.startswith(pat.rstrip("*")):
                return key
        return None

    def _paused(self, p: dict):
        import base64
        import urllib.parse
        path = urllib.parse.urlsplit(p["request"]["url"]).path
        key = self._fake_key(path, p["request"].get("method", "GET"))
        seq = self._fakes.get(key) if key else None
        if not seq:
            self.send("Fetch.continueRequest", {"requestId": p["requestId"]})
            return
        status, body = seq.pop(0)
        self.send("Fetch.fulfillRequest", {
            "requestId": p["requestId"], "responseCode": status,
            "responseHeaders": [{"name": "Content-Type", "value": "application/json"}],
            "body": base64.b64encode(body.encode()).decode()})

    def send(self, method, params=None, timeout=30.0):
        return self.b.send(method, params, self.session, timeout)

    def setup(self, locale: str, width: int, height: int, scheme: str, reduced: bool, init_script: str):
        """Prepare the page before the first goto: the locale and the UTC zone,
        the size and touch (mobile under 600 px wide), the colour scheme and the
        motion, and a script for every new document."""
        mobile = width < 600
        self.send("Emulation.setLocaleOverride", {"locale": locale})
        self.send("Emulation.setTimezoneOverride", {"timezoneId": "UTC"})
        self.send("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": mobile})
        if mobile:
            self.send("Emulation.setTouchEmulationEnabled", {"enabled": True})
        self.send("Emulation.setEmulatedMedia", {"features": [
            {"name": "prefers-color-scheme", "value": scheme},
            {"name": "prefers-reduced-motion", "value": "reduce" if reduced else "no-preference"}]})
        self.send("Page.addScriptToEvaluateOnNewDocument", {"source": init_script})

    def pump(self):
        for ev in self.b.events(self.session):
            m, p = ev.get("method"), ev.get("params", {})
            if m == "Runtime.exceptionThrown":
                d = p["exceptionDetails"]
                self.errors.append("exception: " + (d.get("exception", {}).get("description") or d.get("text", "")))
            elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "assert"):
                args = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
                self.errors.append(f"console.{p['type']}: {args}")
            elif m == "Log.entryAdded" and p["entry"]["level"] == "error":
                e = p["entry"]
                self.errors.append(f"log ({e.get('source')}): {e.get('text')} {e.get('url', '')}".strip())
            elif m == "Network.requestWillBeSent":
                self._inflight.add(p["requestId"])
                self.requests.append(p["request"]["url"])
                self._last_net = time.monotonic()
            elif m in ("Network.loadingFinished", "Network.loadingFailed"):
                self._inflight.discard(p["requestId"])
                self._last_net = time.monotonic()
            elif m == "Page.loadEventFired":
                self._loaded = True
            elif m == "Fetch.requestPaused":
                self._paused(p)
            elif m == "CSS.styleSheetAdded":
                self._sheets[p["header"]["styleSheetId"]] = p["header"].get("sourceURL", "")

    def reload(self):
        """Reload the page (its coverage so far is kept)."""
        if COVERAGE_DIR:
            self._take_coverage(final=False)
        self.send("Page.reload")

    def resize(self, width: int, height: int):
        """A new viewport size on the open page (a turned tablet)."""
        self.send("Emulation.setDeviceMetricsOverride",
                  {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})

    def goto(self, url: str, timeout: float = 20.0, idle: float = 0.5):
        """Navigate and wait for the load event plus `idle` seconds without network activity."""
        self._loaded = False
        if COVERAGE_DIR:
            self._take_coverage(final=False)
        self.send("Page.navigate", {"url": url})
        self.wait_idle(timeout, idle)

    def wait_idle(self, timeout: float = 20.0, idle: float = 0.5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.pump()
            if self._loaded and not self._inflight and time.monotonic() - self._last_net >= idle:
                return
            time.sleep(0.05)
        raise CDPError(f"page not idle after {timeout:.0f} s ({len(self._inflight)} requests in flight)")

    def eval(self, expression: str, timeout: float = 15.0):
        """Evaluate a JS expression (awaits promises); returns its JSON value."""
        r = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                           "awaitPromise": True, "userGesture": True}, timeout)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise CDPError("evaluate: " + (d.get("exception", {}).get("description") or d.get("text", "")))
        return r["result"].get("value")

    def mouse_click(self, x: float, y: float):
        """A real mouse click at x, y (pressed, then released)."""
        for kind in ("mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y,
                                                   "button": "left", "clickCount": 1})

    def insert_text(self, text: str):
        """Insert the text at the cursor (the focused element gets it)."""
        self.send("Input.insertText", {"text": text})

    def press_key(self, key: str):
        """Press and release one named key (only the keys in KEYS are known)."""
        code, vk = self.KEYS[key]
        for kind in ("keyDown", "keyUp"):
            self.send("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code,
                                                 "windowsVirtualKeyCode": vk})

    def screenshot_b64(self) -> str:
        """The viewport as a base64 PNG (what the user sees now)."""
        return self.send("Page.captureScreenshot", {"format": "png"}, timeout=60)["data"]

    def screenshot(self, path: str, full_page: bool = True):
        import base64
        params: dict = {"format": "png"}
        if full_page:
            m = self.send("Page.getLayoutMetrics")["cssContentSize"]
            params.update(captureBeyondViewport=True,
                          clip={"x": 0, "y": 0, "width": m["width"], "height": m["height"], "scale": 1})
        data = self.send("Page.captureScreenshot", params, timeout=60)["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))

    def close(self):
        if COVERAGE_DIR:
            try:
                self._take_coverage(final=True)
            except CDPError:
                pass
        try:
            self.b.send("Target.disposeBrowserContext", {"browserContextId": self.context})
        except CDPError:
            pass
