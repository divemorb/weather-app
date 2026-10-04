# UI contract

Checks the web page (`app/static/`) in headless Chromium against the Rust app, with the contract suite's recorded Berlin data (`rust/contract/`: scenarios, fake upstream, frozen server clock). It asserts what the page shows through `data-test` hooks; layout only where it is the point (the kiosk view, the tile columns per width). Stdlib Python; needs `chromium` and `node` (both are in the watchdog's sandbox image `localhost/wetter-sandbox:web`).

- `run.py`: the harness. `--list` lists the checks, `--require PATTERNS` makes some of them mandatory (the others are reported only), `--scenario`/`--lang` narrow a run, `--shots DIR` saves screenshots for a design review. See its docstring.
- `expect.py`: the expected content per scenario and language.
- `probe.js`: helpers injected into the page after it has loaded (visibility, shown text, overflow, control sizes, animations, the tiles and the sky); the only changes it makes are temporary element styles for screenshots (text made transparent for the contrast check, everything but the sky hidden for the motion check).
- Contrast is measured on pixels: per text, a screenshot with the text made transparent shows what it is drawn on (translucent tiles over a moving sky included), at 3 moments; WCAG AA must hold for all but the worst 5 % of those pixels.
- The `sky` scenario runs on the `live` app with faked `/api/now` icons and radar steps: `scene-*` (`<html data-scene>`), `layout-<width>` (the tile columns), `sky-layer`, `motion-*` (the sky moves), `still-*` (not under reduced motion), `contrast-<scene>-<theme>` (desktop, phone and kiosk).
- `cdp.py`: a minimal DevTools client over `--remote-debugging-pipe` (no websocket, no chromedriver); `Page.fake()` answers chosen API requests with faked responses (the `refresh-*` checks).
- `unit/*.test.mjs`: `node --test` unit tests for the page's pure ES modules (`format.js`, `i18n.js`, `scene()` in `format.js`); `run.py` runs them as checks `unit/<file>`. Further tests can go into `unit/more/`.

Run it in the sandbox image, after `cargo build`:

    python3 rust/uitest/run.py --binary /target/debug/wetter

On the host (the image has Chromium; the binary from any `cargo build`):

    podman run --rm --network=none --read-only --tmpfs /tmp:size=4g --userns=keep-id --user 1000:1000 \
      -e HOME=/tmp -v "$PWD":/work:ro -v /path/to/bin:/bin-dir:ro -v "$PWD/../shots":/shots -w /work \
      --entrypoint python3 localhost/wetter-sandbox:web rust/uitest/run.py --binary /bin-dir/wetter --shots /shots

The browser runs in UTC with its clock frozen at the scenario's "now" (it runs on from there), in `en-US` and `de-DE`. Pages must therefore show times in the location's time zone, format them with the browser's locale, and pick their texts from `navigator.languages`.
