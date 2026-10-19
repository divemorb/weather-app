# Development

Working on the app: the full configuration reference (every `weather.yaml` key and every environment variable), building and running without Docker, the checks, and the code rules.

## Configuration

All runtime settings live in **`weather.yaml`** (repo root). A missing file is all code defaults; the file ships without a `location:` block, with a commented-out Berlin example. Every key:

| Key | Meaning | Default |
| --- | --- | --- |
| `location.latitude` / `location.longitude` | seed the home location on first start (below) | — |
| `location.timezone` | display timezone (the backend stays UTC) | `Europe/Berlin` |
| `radar.radius_km` | "local rain" radius for the next-hour probability (km) | `5.0` (the file sets `1.0`) |
| `radar.grid_size_km` | radar grid cell size (km) | `1.0` |
| `probability.weights.radar` / `.models` / `.ensemble` | weights of the combined rain probability (normalized) | `0.5` / `0.3` / `0.2` |
| `probability.model_rain_threshold_mm` | a model "votes rain" above this precipitation in the next hour (mm) | `0.1` |
| `probability.radar_cell_rain_threshold_mm` | a radar cell counts as rain above this per 5-minute step (mm) | `0.05` |
| `models.forecast` | Open-Meteo models compared for the next 24 h | none (the file sets the list) |
| `models.ensemble_model` | Open-Meteo ensemble model for the precipitation probability | `ecmwf_ifs025` |
| `scheduling.radar_interval_minutes` | radar cache refresh interval (minutes) | `5` |
| `scheduling.models_interval_minutes` | model cache refresh interval (minutes) | `60` |
| `scheduling.stale_after_minutes.radar` | radar shown as stale after this age (minutes) | `10` |
| `scheduling.stale_after_minutes.models` | models shown as stale after this age (minutes) | `120` |
| `accuracy.window_days` | days of forecasts compared against observations | `30` |
| `accuracy.min_samples` | compared hours before a model counts as "enough data" | `48` |
| `api.brightsky_base_url` | Bright Sky endpoint | `https://api.brightsky.dev` |
| `api.open_meteo_base_url` | Open-Meteo forecast endpoint | `https://api.open-meteo.com/v1` |
| `api.ensemble_base_url` | Open-Meteo ensemble endpoint | `https://ensemble-api.open-meteo.com/v1` |
| `api.nominatim_base_url` | address search for the setup wizard | `https://nominatim.openstreetmap.org` |
| `api.timeout_seconds` | per-request upstream timeout (seconds) | `20` |

**Location.** The home location is *runtime state*: it is stored in the app's database (`DATABASE_PATH`), not in the repo. On first run the page shows a setup wizard — search an address (OpenStreetMap Nominatim) or type latitude/longitude — and the app starts fetching. From then on the map-pin button in the header changes the location (the cached data and the accuracy history of the old location are deleted). `LATITUDE`/`LONGITUDE` env vars or a `location:` block in `weather.yaml` only *seed* the location on first start (adopted into the database); afterwards the stored value wins. The display timezone defaults to `Europe/Berlin` and can be set via `TIMEZONE` / `location.timezone`.

The file is read at startup; a change takes effect on the next restart.

Environment variables (read in `rust/src/config.rs`, `main.rs` and `times.rs`) override the file. Each with its default:

| Variable | Meaning | Default |
| --- | --- | --- |
| `WEATHER_CONFIG` | path to an alternative config file | `/app/weather.yaml` |
| `LATITUDE` / `LONGITUDE` | seed the home location on first start (both must be set) | — |
| `TIMEZONE` | display timezone | `Europe/Berlin` |
| `RADAR_RADIUS_KM` | overrides `radar.radius_km` | `5.0` |
| `WEIGHT_RADAR` / `WEIGHT_MODELS` / `WEIGHT_ENSEMBLE` | override the probability weights | `0.5` / `0.3` / `0.2` |
| `RADAR_INTERVAL_MINUTES` / `MODELS_INTERVAL_MINUTES` | override the refresh intervals | `5` / `60` |
| `DATABASE_PATH` | the SQLite database | `/data/weather.db` |
| `USE_ACCURACY_WEIGHTS` | boolean, accuracy weighting (see [ARCHITECTURE.md](ARCHITECTURE.md)) | `false` |
| `BIND_ADDR` | the address the server listens on | `0.0.0.0:8000` |
| `STATIC_DIR` | the directory of the page files | `/app/static` |
| `ALLOWED_HOSTS` | extra allowed `Host` values (see [SECURITY.md](SECURITY.md)) | none |
| `WETTER_FAKE_NOW` | frozen clock, an ISO-8601 timestamp (tests only) | the system clock |

## Without Docker (development)

The app is the Rust crate in `rust/` (Rust 1.99, see `rust/Dockerfile`). From the repo root:

```bash
cd rust && cargo build && cd ..
mkdir -p data
WEATHER_CONFIG=./weather.yaml DATABASE_PATH=./data/weather.db STATIC_DIR=./app/static \
  BIND_ADDR=127.0.0.1:8000 rust/target/debug/wetter
```

The binary has one subcommand: `wetter snapshot PATH` copies the live database to `PATH` and prints a short report to stdout.

## The checks

All from the repo root, after `cargo build`:

```bash
cd rust && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test && cd ..
```

The contract suite checks the API against the frozen goldens (Python 3 stdlib only; see [rust/contract/README.md](../rust/contract/README.md)):

```bash
python3 rust/contract/run.py --backend rust --binary rust/target/debug/wetter
python3 rust/contract/run.py --backend rust --binary rust/target/debug/wetter --list            # the cases
python3 rust/contract/run.py --backend rust --binary rust/target/debug/wetter --require 'unconfigured:static/*'
python3 rust/contract/run.py --backend rust --binary rust/target/debug/wetter --update          # record the goldens (an intended change)
```

`--require PATTERNS` makes some cases mandatory (`!pattern` excludes), `--budget-mb MB` fails a scenario whose peak memory is above the limit.

The UI suite checks the page in headless Chromium (needs `chromium` and `node`; see [rust/uitest/README.md](../rust/uitest/README.md)):

```bash
python3 rust/uitest/run.py --binary rust/target/debug/wetter
python3 rust/uitest/run.py --binary rust/target/debug/wetter --list                       # the checks
python3 rust/uitest/run.py --binary rust/target/debug/wetter --scenario sky               # a scenario
python3 rust/uitest/run.py --binary rust/target/debug/wetter --only 'sky/en/<check>'      # one check
python3 rust/uitest/run.py --binary rust/target/debug/wetter --shots /tmp/shots           # screenshots
```

A Safari-like run on WebKit (from time to time, not part of the checks above): `--browser webkit --scenario live`; what it needs and what it skips is in [rust/uitest/README.md](../rust/uitest/README.md#webkit-safari-like-run).

The fault suite plants defects in a copy of the page and proves the checks still see them (`--gaps` runs the defects the checks don't see yet):

```bash
python3 rust/uitest/faults.py --binary rust/target/debug/wetter --require '*'
```

The coverage report lists the page code no check runs (a report, not a gate; code run only by the node unit tests shows up too):

```bash
WETTER_UITEST_COVERAGE=/tmp/cov python3 rust/uitest/run.py --binary rust/target/debug/wetter
python3 rust/uitest/coverage_report.py /tmp/cov
```

The docs gate: every relative link in the docs leads to a file, and [ARCHITECTURE.md](ARCHITECTURE.md) names every page file and every Rust module:

```bash
python3 rust/contract/doc_check.py
```

### Traceability

Every requirement in [REQUIREMENTS.md](REQUIREMENTS.md) names the tests that prove it in a `*Proof:*` line under its bullet; the item kinds and the marks are described in the header of [REQUIREMENTS.md](REQUIREMENTS.md). The check:

```bash
python3 rust/contract/trace.py --strict
python3 rust/contract/trace.py --report
```

`--strict` fails a requirement without a Proof line; `--report` prints the Markdown overview instead. A new or changed requirement gets its Proof line checked again, and a renamed test fails the check until the line is updated.

## Code rules

- **Lints** in `rust/Cargo.toml` (`[lints]`): `unsafe_code` is forbidden; Clippy denies `unwrap`, `expect`, `panic`, index and string slicing, `todo!`/`unimplemented!`/`dbg!`, lossy casts, and `allow` without a reason, plus a curated list of pedantic and nursery lints (for example `too_many_lines`, `unreadable_literal`, `use_self`). `rust/clippy.toml` relaxes `unwrap`, `expect`, `panic` and indexing in test code.
- **Comments**, checked by `rust/contract/comment_rules.py AREA` (`rust-app`, `rust-tests`, `page`, `harness`): no build-step IDs and no dates (git keeps history), no mention of Python, the module header at most 10 lines, every other comment block at most 12, and a comment right above every public item.
- **Function size**, checked by `rust/contract/sizes.py --max-lines 80 --max-args 6 <files>`: no function longer than 80 lines or with more than 6 parameters (the docstring's example sizes the harness, `rust/uitest/*.py` and `rust/uitest/probe.js`). In Rust, Clippy holds the same line: `too_many_lines` (100), `too_many_arguments` (7), `cognitive_complexity` (25) and the two bool lints.
- **File length**, checked by `rust/contract/sizes.py --file-lines 400 600 rust app`: a code file over 400 lines is a warning (split it when you next add to it), over 600 an error. Data files are not counted.

## Where to start reading

- [ARCHITECTURE.md](ARCHITECTURE.md): the design, the modules, the data conventions.
- [REQUIREMENTS.md](REQUIREMENTS.md): what the app does, one entry per requirement with an ID.
- [API.md](API.md): the HTTP API.

## Working with an AI coding agent

This project is developed with a local model (opencode, run step by step in a sandbox). The project rules the agent follows (container and test commands, what it must not touch, backend and frontend conventions, and one sub-step per run with `Step Nx:` commits) are in [`.continue/rules/weather-projectrules.md`](../.continue/rules/weather-projectrules.md); `opencode.json` loads them, and so does the Continue extension in this workspace. Contributors using a different agent should give it the same rules.

## Development history

The history is in `git log --oneline` (one `Step Nx:` commit per sub-step). The Python app (v1) is retired; its code is at the git tag `python-last`.
