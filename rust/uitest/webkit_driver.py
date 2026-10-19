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
import http.server
import sys
import threading
import time

from webdriver import WebKit, leftovers, wait_for

# evaluates the expression in the page, awaits a Promise, reports errors
EVAL = ("const cb = arguments[arguments.length - 1]; "
        "Promise.resolve().then(() => (0, eval)(arguments[0]))"
        ".then((v) => cb({ok: v === undefined ? null : v}), (e) => cb({err: String(e)}));")


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
        self.errors: list[str] = []  # WebDriver classic cannot see console errors
        self.requests: list[str] = []  # ... nor the requests (their checks are skipped)

    def setup(self, locale: str, width: int, height: int, scheme: str, reduced: bool, init_script: str):
        """Start the page's own WebKit (the theme is fixed per process) at the
        given size (at least 447 px wide, the browser's minimum); the frozen
        clock cannot run before the page's own scripts, so init_script is only
        remembered here."""
        self.wk = WebKit(self.lang, dark=(scheme == "dark"))
        self.wk.start()
        self.wk.window(max(width, 447), height)
        self.reduced, self.init_script = reduced, init_script

    def goto(self, url: str):
        """Navigate and wait until the document is complete (at most 20 s)."""
        self._loaded = False
        self.wk.goto(url)
        wait_for(lambda: self.wk.js("return document.readyState") == "complete",
                 20, f"page {url} not complete after 20 s")
        self._loaded = True

    def reload(self):
        """Reload the page: a goto of the page's current URL."""
        self.goto(self.wk.js("return location.href"))

    def eval(self, expression: str):
        """Evaluate a JavaScript expression (awaiting a Promise), return the
        JSON value; RuntimeError with the error text on a page error."""
        r = self.wk.js_async(EVAL, expression)
        if isinstance(r, dict) and "err" in r:
            raise RuntimeError(r["err"])
        return r.get("ok")

    def wait_idle(self, timeout: float = 20.0, idle: float = 0.5):
        """Wait until the page is quiet: there is nothing to observe, so a
        fixed pause (timeout is accepted for the interface and not used)."""
        time.sleep(idle)

    def pump(self):
        """Collect pending events: there is none (WebDriver classic has no
        event stream)."""

    def fake(self, responses):
        """Answer API paths with given responses: not possible here."""
        raise NotImplementedError("webkit: no request interception yet (W2)")

    def fakes_left(self) -> int:
        """How many faked answers are still waiting: none, they are impossible."""
        raise NotImplementedError("webkit: no request interception yet (W2)")

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
