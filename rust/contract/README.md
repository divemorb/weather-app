# Contract suite

Proves that the Rust backend answers exactly like the Python backend (the reference). Stdlib-only Python; see the docstring of `run.py` for the details.

- `scenarios.py`: 7 scenarios (fixed "now", environment, upstream data) with about 100 request cases. List them with `python3 rust/contract/run.py --list`.
- `fakeup.py`: the fake upstream (Bright Sky, Open-Meteo, Nominatim) that replays the fixtures and logs the requests.
- `golden/`: the Python backend's normalized responses. Regenerate them (only when the Python backend or a scenario changes) inside the Python image:

      podman run --rm --init --network=none --userns=keep-id --user 1000:1000 -v "$PWD":/w -w /w localhost/wetter_weather python rust/contract/run.py --backend python --update

- `pyapp.py`: starts the Python backend with a frozen clock (patched from outside; the Python code is unchanged).
- `fixtures/live/`: real responses recorded on 2026-09-30 10:25 UTC for a neutral location (Berlin, 52.52/13.405). `fixtures/rain/` is derived from them by `make_fixtures.py` (synthetic rain for the edge cases).

Run against the Rust binary (after `cargo build`):

    python3 rust/contract/run.py --backend rust --binary /target/debug/wetter

The Rust binary reads the same environment variables as the Python app, plus `WETTER_FAKE_NOW` (frozen clock, tests only), `BIND_ADDR` (default `0.0.0.0:8000`) and `STATIC_DIR` (default `/app/static`).

## Data sources of the fixtures

- Bright Sky (`current_weather`, `radar`, `weather`): data from Deutscher Wetterdienst (DWD), via brightsky.dev.
- Open-Meteo (`forecast`, `ensemble`): weather data by Open-Meteo.com, licensed under CC BY 4.0.
- Nominatim (`nominatim_search`): © OpenStreetMap contributors, licensed under ODbL.
