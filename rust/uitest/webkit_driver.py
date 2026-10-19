"""The WebKit driver: the driver table of page.UIPage for WebKitGTK's
WebDriver, one browser process per page (the theme is fixed per process).
Behind `run.py --browser webkit`, never in the gate (the Chromium run
stays exactly as it is); the checks that need what WebDriver classic
cannot see (console errors, requests, faked API answers) are reported
as SKIP, never as passed.

    python3 rust/uitest/webkit_driver.py --self-test
"""

from __future__ import annotations

import base64
import fnmatch
import http.server
import sys
import threading
import time

from webdriver import WebKit, leftovers, wait_for

# evaluates the expression in the page (inlined: the page's CSP allows no
# eval or Function, unlike Chromium's CDP), awaits a Promise, reports errors
EVAL = ("const cb = arguments[arguments.length - 1]; "
        "Promise.resolve((() => (%s))())"
        ".then((v) => cb({ok: v === undefined ? null : v}), (e) => cb({err: String(e)}));")

def webkit_skip(name: str) -> str | None:
    """Why a check is skipped on WebKit (the pattern without the
    scenario/lang/ prefix), or None when the check runs like on Chromium."""
    for pattern, reason in WEBKIT_SKIP.items():
        if fnmatch.fnmatch(name, pattern):
            return reason
    return None


# The checks WebKit cannot run (the reason, per pattern without the
# scenario/lang/ prefix), reported as SKIP, never as passed:
WEBKIT_SKIP = {
    # no console or request capture in WebDriver classic
    "console": "no console capture in WebDriver classic",
    "requests": "no request capture in WebDriver classic",
    # the window is at least 447 px wide (MiniBrowser's minimum), no phone view
    "*-360": "window is at least 447 px wide, no phone view",
    "*-390": "window is at least 447 px wide, no phone view",
    "overflow-360": "window is at least 447 px wide, no phone view",
    "details-fit": "window is at least 447 px wide, no phone view",
    "view-phone": "window is at least 447 px wide, no phone view",
    "view-details-only": "window is at least 447 px wide, no phone view",
    # its 390 px (phone) part asserts the page is no wider than 390 px; at the
    # 447 px minimum the page is wider, so that part cannot run (the label
    # text itself is fine at both widths)
    "view-label": "window is at least 447 px wide, no phone view",
    "location-long": "window is at least 447 px wide, no phone view",
    "location-lines": "window is at least 447 px wide, no phone view",
    # no media emulation (prefers-reduced-motion cannot be turned on); the
    # track checks freeze the sky with it, so their measured glass colour is a
    # snapshot of a drifting animation, not a stable page property
    "reduced-motion": "no media emulation for prefers-reduced-motion",
    "report-still": "no media emulation for prefers-reduced-motion",
    "big-tracks": "no media emulation for prefers-reduced-motion (the check freezes the sky)",
    "rain-tracks": "no media emulation for prefers-reduced-motion (the check freezes the sky)",
    # the faked API answers need request interception, which WebDriver classic cannot do
    "reason-*": "no request interception in WebDriver classic, which the faked API answers need",
    "refresh-*": "no request interception in WebDriver classic, which the faked API answers need",
    "reload-fires": "no request interception in WebDriver classic, which the faked API answers need",
    "chart-single-point": "no request interception in WebDriver classic, which the faked API answers need",
    "dst-*": "no request interception in WebDriver classic, which the faked API answers need",
    "search-failed": "no request interception in WebDriver classic, which the faked API answers need",
    "report-error": "no request interception in WebDriver classic, which the faked API answers need",
    "report-line-fresh": "no request interception in WebDriver classic, which the faked API answers need",
    "report-undo-failed": "no request interception in WebDriver classic, which the faked API answers need",
    "report-night": "no request interception in WebDriver classic, which the faked API answers need",
    "sky-report-*": "no request interception in WebDriver classic, which the faked API answers need",
    "sky-report-none": "no request interception in WebDriver classic, which the faked API answers need",
    "sky-layer": "no request interception in WebDriver classic, which the faked API answers need",
    "scene-*": "no request interception in WebDriver classic, which the faked API answers need",
    "motion-*": "no request interception in WebDriver classic, which the faked API answers need",
    "still-*": "no request interception in WebDriver classic, which the faked API answers need",
    "glass-*": "no request interception in WebDriver classic, which the faked API answers need",
    "contrast-*-light": "no request interception in WebDriver classic, which the faked API answers need",
    "contrast-*-dark": "no request interception in WebDriver classic, which the faked API answers need",
}


class WebKitBrowser:
    """One browser (one language) for the driver seam; each page runs in its
    own WebKit process and is closed with the browser."""

    def __init__(self, lang: str = "en"):
        self.lang = lang
        self.pages: list[WebKitPage] = []

    def new_page(self) -> "WebKitPage":
        """A page of this browser (its WebKit starts in the page's setup)."""
        page = WebKitPage(self.lang)
        self.pages.append(page)
        return page

    def close(self):
        """Close the pages it still has open (closing a closed page is a no-op)."""
        for page in self.pages:
            page.close()
        self.pages = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class WebKitPage:
    """One page on its own WebKit process, the driver table of page.UIPage
    (setup, goto, reload, _loaded, eval, wait_idle, pump, errors, requests,
    fake, fakes_left, mouse_click, insert_text, press_key, screenshot_b64,
    screenshot, close)."""

    KEYS = {"Escape": "\ue00c"}  # the W3C values of the named keys

    def __init__(self, lang: str):
        self.lang = lang
        self.wk: WebKit | None = None
        self.reduced = False
        self.init_script = ""
        self._loaded = False
        self._cleared = False  # the localStorage cleanup after the first goto
        self.errors: list[str] = []  # WebDriver classic cannot see console errors
        self.requests: list[str] = []  # ... nor the requests (their checks are skipped)

    def setup(self, locale: str, width: int, height: int, scheme: str, reduced: bool, init_script: str):
        """Start the page's own WebKit (the theme is fixed per process) at the
        given viewport size (at least 447 px wide, the browser's minimum; the
        window is taller by its title bar's offset, see _calibrate); the frozen
        clock cannot run before the page's own scripts, so init_script is only
        remembered here."""
        self.wk = WebKit(self.lang, dark=(scheme == "dark"))
        self.wk.start()
        self._calibrate(max(width, 447), height)
        self.reduced, self.init_script = reduced, init_script

    def _calibrate(self, width: int, height: int):
        """The window at the size whose viewport is width x height (the window's
        title bar eats the difference, so ask for more height, then measure)."""
        self.wk.window(width, height)
        for _ in range(3):
            w, h = self.wk.js("return [innerWidth, innerHeight]")
            if w == width and h == height:
                return
            self.wk.window(width, height + (height - h))

    def goto(self, url: str):
        """Navigate and wait until the page is idle (at most 20 s)."""
        self._loaded = False
        self.wk.goto(url)
        self._idle(20.0, 0.5)
        if not self._cleared:  # the WebKit profile keeps localStorage between
            self._cleared = True  # pages (Chromium starts empty); the view
            try:                  # checks need that (the app's pages are http)
                n = self.wk.js("return localStorage.length")
            except (OSError, RuntimeError):
                n = 0
            if n > 0:
                self.wk.js("localStorage.clear(); return null")
                self._loaded = False
                self.wk.goto(url)
                self._idle(20.0, 0.5)
        self._loaded = True

    def reload(self):
        """Reload the page: a goto of the page's current URL."""
        self.goto(self.wk.js("return location.href"))

    def eval(self, expression: str):
        """Evaluate a JavaScript expression (awaiting a Promise), return the
        JSON value; RuntimeError with the error text on a page error."""
        expr = expression.rstrip()
        if expr.endswith(";"):  # the inlined body is one expression
            expr = expr[:-1].rstrip()
        r = self.wk.js_async(EVAL % expr)
        if isinstance(r, dict) and "err" in r:
            raise RuntimeError(r["err"])
        return r.get("ok")

    def _idle(self, timeout: float, idle: float):
        """Poll every 0.1 s until the document is complete and the count of
        loaded resources has not changed for `idle` seconds (the page's API
        calls still run after readyState turns complete); `timeout` at most."""
        last, since = None, 0.0
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            now = time.monotonic()
            try:
                state, n = self.wk.js("return [document.readyState, "
                                      "performance.getEntriesByType('resource').length]")
            except (OSError, RuntimeError):
                state, n = None, None
            if n != last:
                last, since = n, now
            elif state == "complete" and now - since >= idle:
                return
            time.sleep(0.1)
        raise RuntimeError(f"page not idle after {timeout:.0f} s")

    def wait_idle(self, timeout: float = 20.0, idle: float = 0.5):
        """Wait until the page is quiet (the resource count is stable for
        `idle` seconds, `timeout` at most)."""
        self._idle(timeout, idle)

    def pump(self):
        """Collect pending events: there is none (WebDriver classic has no
        event stream)."""

    def fake(self, responses):
        """Answer API paths with given responses: not possible here."""
        raise NotImplementedError("webkit: no request interception in WebDriver classic")

    def fakes_left(self) -> int:
        """How many faked answers are still waiting: none, they are impossible."""
        raise NotImplementedError("webkit: no request interception in WebDriver classic")

    def mouse_click(self, x: float, y: float):
        """A real mouse click at x, y (move, press, release)."""
        self.wk.actions([{"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"},
                          "actions": [{"type": "pointerMove", "duration": 0, "origin": "viewport",
                                       "x": int(round(x)), "y": int(round(y))},
                                      {"type": "pointerDown", "duration": 0, "button": 0},
                                      {"type": "pointerUp", "duration": 0, "button": 0}]}])

    def insert_text(self, text: str):
        """Insert the text at the cursor: key down and up per character."""
        self.wk.actions([{"type": "key", "id": "keyboard",
                          "actions": [{"type": "keyDown", "value": c} for c in text] +
                                     [{"type": "keyUp", "value": c} for c in text]}])

    def press_key(self, key: str):
        """Press and release one named key (the keys in KEYS are known)."""
        self.wk.actions([{"type": "key", "id": "keyboard",
                          "actions": [{"type": "keyDown", "value": self.KEYS[key]},
                                      {"type": "keyUp", "value": self.KEYS[key]}]}])

    def screenshot_b64(self) -> str:
        """The viewport as a base64 PNG (what the user sees now)."""
        return base64.b64encode(self.wk.screenshot()).decode()

    def screenshot(self, path: str, full_page: bool = True):
        """Write the viewport as a PNG file (the browser has no full-page shot)."""
        with open(path, "wb") as f:
            f.write(self.wk.screenshot())

    def close(self):
        """End the page's session and stop its WebKit and Xvfb."""
        if self.wk is not None:
            self.wk.close()
            self.wk = None


def _serve(page: str) -> tuple[int, http.server.HTTPServer]:
    """Serve one page on a free port (a stdlib server in a daemon thread)."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1], server


def _self_test_page() -> str:
    """The self-test page: the title and a button that sets it on click."""
    return ("<!doctype html><html><head><title>wk-self-test</title></head><body>"
            "<button id=b style='width:120px;height:40px'>go</button>"
            "<script>document.getElementById('b')?.addEventListener('click', "
            "() => { document.title = 'clicked'; });</script></body></html>")


def self_test() -> int:
    """Serve a page with a button; the driver must load it, evaluate (a value,
    a promise, an error), click the button, and leave no process behind."""
    port, server = _serve(_self_test_page())
    problems = []
    try:
        browser = WebKitBrowser("en")
        try:
            page = browser.new_page()
            page.setup("en-US", 1280, 800, "light", False, "")
            page.goto(f"http://127.0.0.1:{port}/")
            got = page.eval("document.title")
            if got != "wk-self-test":
                problems.append(f"the title is {got!r}, expected 'wk-self-test'")
            got = page.eval("Promise.resolve(41 + 1)")
            if got != 42:
                problems.append(f"the promise resolved to {got!r}, expected 42")
            try:
                page.eval("(() => { throw new Error('x') })()")
                problems.append("the throwing expression did not raise")
            except RuntimeError as e:
                if "x" not in str(e):
                    problems.append(f"the error text is {str(e)!r}, expected 'Error: x'")
            r = page.eval("(() => { const b = document.getElementById('b').getBoundingClientRect(); "
                          "return {x: b.x, y: b.y, w: b.width, h: b.height}; })()")
            page.mouse_click(r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)
            time.sleep(0.3)
            got = page.eval("document.title")
            if got != "clicked":
                problems.append(f"after the click the title is {got!r}, expected 'clicked'")
        finally:
            browser.close()
    except Exception as e:  # noqa: BLE001 - report it, go on to the leftovers
        problems.append(f"the self-test raised {e!r}")
    finally:
        server.shutdown()
    problems += [f"left over: {p}" for p in leftovers()]
    for p in problems:
        print(p)
    print("self-test: ok" if not problems else f"self-test: {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--self-test"]:
        sys.exit(__doc__)
    sys.exit(self_test())
