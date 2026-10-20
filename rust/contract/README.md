# Contract suite

Proves that the Rust backend answers exactly as the goldens record. Stdlib-only Python; see the docstring of `run.py` for the details.

- `scenarios.py`: 7 scenarios (fixed "now", environment, upstream data) with about 100 request cases. List them with `python3 rust/contract/run.py --list`.
- `fakeup.py`: the fake upstream (Bright Sky, Open-Meteo, Nominatim) that replays the fixtures and logs the requests.
- `trace.py`: checks that every requirement in `docs/REQUIREMENTS.md` names, in a `*Proof:*` line under its bullet, the tests that prove it and that every link resolves; `--strict` fails a missing Proof line, `--report` prints the Markdown overview.
- `mutant_check.py` + `mutants.json`: code changes found by cargo-mutants that no test caught (a mutation run of the backend's unit tests); the check applies each one to a copy of the crate and fails if `cargo test --lib` still passes. `python3 rust/contract/mutant_check.py --list` names the groups; `python3 rust/contract/mutant_check.py GROUP` checks one. A test that catches a mutant keeps it caught.
- `golden/`: the normalized responses. They were recorded from the Python app (v1, the reference until v2.0; its code is at the git tag `python-last`) and are frozen. When a change is intended, record them from the Rust backend and review every changed line in `git diff rust/contract/golden` before committing:

      python3 rust/contract/run.py --backend rust --binary /target/debug/wetter --update

- `fixtures/live/`: real responses recorded on 2026-09-30 10:25 UTC for a neutral location (Berlin, 52.52/13.405). `fixtures/rain/` is derived from them by `make_fixtures.py` (synthetic rain for the edge cases).
- `fixtures/python_schema_v3.sql`: the v1 database schema, frozen at `python-last`; `run.py` seeds a v1 database with it (the takeover test).
- `fixtures/py_cases/`, `fixtures/pyfmt_cases.json`, `fixtures/geocode_labels.json`: reference results from the v1 app for the Rust unit tests (recorded once, frozen).

Run against the Rust binary (after `cargo build`):

    python3 rust/contract/run.py --backend rust --binary /target/debug/wetter

The Rust binary reads the same environment variables as the v1 app, plus `WETTER_FAKE_NOW` (frozen clock, tests only), `BIND_ADDR` (default `0.0.0.0:8000`) and `STATIC_DIR` (default `/app/static`).

## Data sources of the fixtures

- Bright Sky (`current_weather`, `radar`, `weather`): data from Deutscher Wetterdienst (DWD), via brightsky.dev.
- Open-Meteo (`forecast`, `ensemble`): weather data by Open-Meteo.com, licensed under CC BY 4.0.
- Nominatim (`nominatim_search`): © OpenStreetMap contributors, licensed under ODbL.
