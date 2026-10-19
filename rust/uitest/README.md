# UI contract

Checks the web page (`app/static/`) in headless Chromium against the Rust app, with the contract suite's recorded Berlin data (`rust/contract/`: scenarios, fake upstream, frozen server clock). It asserts what the page shows through `data-test` hooks; layout only where it is the point (the kiosk view, the tile columns per width). Stdlib Python; needs `chromium` and `node` (both are in the watchdog's sandbox image `localhost/wetter-sandbox:web`).

- `run.py`: the harness. `--list` lists the checks, `--require PATTERNS` makes some of them mandatory (the others are reported only), `--scenario`/`--lang` narrow a run, `--shots DIR` saves screenshots for a design review. See its docstring. `--only PATTERNS` runs only the matching checks (the `sky` scenario then skips the work of the others), `--static DIR` serves another copy of `app/static`. With `WETTER_UITEST_SANDBOX` set (the watchdog sets it in Qwen's sandbox only), a run covers at most 3 scenarios: the full suite is the watchdog's.
- `faults.py` + `faults.json`: planted faults, the proof that the harness still sees known defects. Each fault edits a copy of `app/static` and names the checks that must fail; `faults.py` exits 1 when a required fault is missed. `--gaps` runs the defects today's checks don't see yet (to be covered by new checks).
- `expect.py`: the expected content per scenario and language.
- `probe.js`: helpers injected into the page after it has loaded (visibility, shown text, overflow, control sizes, animations, the tiles and the sky); the only changes it makes are temporary element styles for screenshots (text made transparent for the contrast check, everything but the sky hidden for the motion check).
- Contrast is measured on pixels: per text, a screenshot with the text made transparent shows what it is drawn on (translucent tiles over a moving sky included), at 3 moments; WCAG AA must hold for all but the worst 5 % of those pixels.
- The `sky` scenario runs on the `live` app with faked `/api/now` icons and radar steps: `scene-*` (`<html data-scene>`), `layout-<width>` (the tile columns), `sky-layer`, `motion-*` (the sky moves), `still-*` (not under reduced motion), `contrast-<scene>-<theme>` (desktop, phone and kiosk).
- `cdp.py`: a minimal DevTools client over `--remote-debugging-pipe` (no websocket, no chromedriver); `Page.fake()` answers chosen API requests with faked responses (the `refresh-*` checks).
- `webdriver.py` + `webkit_driver.py`: the WebKit run (below): a minimal W3C WebDriver client for WebKitGTK, and the driver that gives the checks the same interface as `cdp.Page` (`pg.p` is the driver; see `UIPage`).
- `unit/*.test.mjs`: `node --test` unit tests for the page's pure ES modules (`format.js`, `i18n.js`, `scene()` in `format.js`); `run.py` runs them as checks `unit/<file>`. Further tests can go into `unit/more/`.

Run it in the sandbox image, after `cargo build`:

    python3 rust/uitest/run.py --binary /target/debug/wetter

On the host (the image has Chromium; the binary from any `cargo build`):

    podman run --rm --network=none --read-only --tmpfs /tmp:size=4g --userns=keep-id --user 1000:1000 \
      -e HOME=/tmp -v "$PWD":/work:ro -v /path/to/bin:/bin-dir:ro -v "$PWD/../shots":/shots -w /work \
      --entrypoint python3 localhost/wetter-sandbox:web rust/uitest/run.py --binary /bin-dir/wetter --shots /shots

The browser runs in UTC with its clock frozen at the scenario's "now" (it runs on from there), in `en-US` and `de-DE`. Pages must therefore show times in the location's time zone, format them with the browser's locale, and pick their texts from `navigator.languages`.

## WebKit (Safari-like) run

From time to time, never in the gate: the same checks on WebKit, the engine of Safari on iPhone and iPad.

    python3 rust/uitest/run.py --binary /target/debug/wetter --browser webkit --scenario live

It needs `WebKitWebDriver` (Debian: `webkit2gtk-driver`), `Xvfb` and the `en_US`/`de_DE` locales; run it where those are installed (in a container like the sandbox image above, plus these packages). Only the scenarios given with `--scenario` run, one page after the other, each page in its own WebKit. The summary line is `uitest (webkit): N passed, M failed, K skipped`.

Checks WebKit can't run are reported as `SKIP <name> (webkit: <reason>)`, never as passed; the list with the reasons is `WEBKIT_SKIP` in `webkit_driver.py`. WebDriver classic has no console or request capture, no request interception (the checks with faked API answers), no media emulation (reduced motion, so the sky can't be frozen for the colour checks), and the window is at least 447 px wide (no phone views). A FAIL line in a WebKit run is a real difference from Chromium: a finding, not something to skip.
