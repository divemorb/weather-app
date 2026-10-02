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

CHROMIUM_FLAGS = [
    "--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
    "--no-first-run", "--no-default-browser-check", "--disable-extensions",
    "--disable-background-networking", "--disable-component-update", "--disable-sync",
    "--disable-features=Translate,MediaRouter,OptimizationHints", "--mute-audio",
    "--hide-scrollbars", "--remote-debugging-pipe",
]


class CDPError(RuntimeError):
    pass


class Browser:
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

    def __init__(self, browser: Browser, session: str, target: str, context: str):
        self.b, self.session, self.target, self.context = browser, session, target, context
        self.errors: list[str] = []
        self.requests: list[str] = []
        self._inflight: set[str] = set()
        self._last_net = time.monotonic()
        self._loaded = False
        for domain in ("Page", "Runtime", "Log", "Network"):
            self.send(f"{domain}.enable")

    def send(self, method, params=None, timeout=30.0):
        return self.b.send(method, params, self.session, timeout)

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

    def goto(self, url: str, timeout: float = 20.0, idle: float = 0.5):
        """Navigate and wait for the load event plus `idle` seconds without network activity."""
        self._loaded = False
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
        try:
            self.b.send("Target.disposeBrowserContext", {"browserContextId": self.context})
        except CDPError:
            pass
