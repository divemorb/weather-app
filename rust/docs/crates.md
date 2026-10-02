# Pinned crates: what differs from what you may remember

Verified on 2026-09-30 against the exact versions in `rust/Cargo.toml` (Rust 1.98.1, edition 2024). Use these forms; don't reason about older APIs. The crate sources are in the sandbox under `/vendor/<crate>-<version>/` (for example `/vendor/axum-0.8.9/src/`). Search them with `rg` when you need a signature, instead of guessing.

## Language and lints (edition 2024)

- `std::env::set_var` / `remove_var` are `unsafe` now. Never call them, not even in tests. Code that reads the environment takes a lookup function instead, e.g. `env: &dyn Fn(&str) -> Option<String>`. Production passes `&|k| std::env::var(k).ok()`, and tests pass a closure over a `HashMap`.
- `cargo clippy -- -D warnings` rejects nested `if let` + `if` (`collapsible_if`). Write a let-chain:

  ```rust
  if let Some((addr, zone)) = host.split_once('%')
      && !zone.is_empty()
      && addr.parse::<std::net::Ipv6Addr>().is_ok()
  {
      return true;
  }
  ```

- The crate is a library plus a thin binary: `src/lib.rs` declares the modules (`pub mod …;`), and `src/main.rs` uses them as `wetter::…`. Public items in the library don't trigger dead-code warnings while the port is incomplete.
- Clippy 1.98 rejects `chunks_exact(2)` with a constant size (`chunks_exact_to_as_chunks`). Write `let (pairs, _) = data.as_chunks::<2>();`, where `pairs` is a `&[[u8; 2]]`.
- Unit tests live next to the module: `src/foo.rs` ends with `#[cfg(test)] mod tests;`, and the tests are in `src/foo/tests.rs`, starting with `use super::*;`.

## axum 0.8.9

- Serve: `axum::serve(listener, router).with_graceful_shutdown(signal).await`, with a `tokio::net::TcpListener`.
- State: `Router::new().route(...).with_state(state)`. Handlers take `State(state): State<AppState>` as their first argument, and `AppState` is `#[derive(Clone)]`.
- Middleware: `.layer(axum::middleware::from_fn_with_state(state.clone(), guard))`, with `async fn guard(State(state): State<AppState>, req: axum::extract::Request, next: axum::middleware::Next) -> axum::response::Response`.
- Responses: `(StatusCode::NOT_FOUND, Json(json!({"detail": "Not Found"}))).into_response()`. `Json(...)` sets `content-type: application/json`. A `[(header::CONTENT_TYPE, "..."), ...]` array in a tuple sets headers.
- **405 without `Allow`:** axum adds an `Allow` header to its own 405 answers at the router's top level, after every layer, and the Python app sends none. So routes are built as `any(method_not_allowed).get(handler)` (or `.post(handler)`); routes that start from `any(...)` skip the `Allow` header.
- `.fallback(handler)` gets every request no route matched (any method).
- Tests without a server (`tower` is a dev-dependency):

  ```rust
  use axum::body::Body;
  use axum::http::Request;
  use tower::ServiceExt; // for .oneshot

  let res = router.oneshot(Request::builder().uri("/healthz").header("host", "127.0.0.1:8000")
      .body(Body::empty()).unwrap()).await.unwrap();
  let bytes = axum::body::to_bytes(res.into_body(), usize::MAX).await.unwrap();
  ```

  Async tests use `#[tokio::test]`.

## tokio 1.53.1

- Runtime: `#[tokio::main(flavor = "current_thread")]`. One thread keeps the memory low on the Pi Zero, and the app is I/O-bound.
- SIGTERM (container stop): `tokio::signal::unix::signal(SignalKind::terminate())`, then `.recv().await`.

## chrono 0.4.45

- Parse: `DateTime::parse_from_rfc3339(s)` handles `Z`, offsets and fractions. For naive stamps use `NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f")` or `"%Y-%m-%dT%H:%M"`, then `.and_utc()`.
- Format: `t.format("%Y-%m-%dT%H:%M:%SZ").to_string()`.
- Durations: `(a - b).as_seconds_f64()`. Offsets: `t - TimeDelta::hours(1)` (`chrono::TimeDelta`).
- Floor to a 5-minute grid: `use chrono::DurationRound;` then `now.duration_trunc(TimeDelta::minutes(5)).unwrap_or(now)`.

## serde-saphyr 1.3.0 (YAML)

- `serde_saphyr::from_str::<serde_json::Value>(text)`. An empty file or one with only comments gives `Value::Null` (like PyYAML's `None`). Ints stay ints (`1`), floats stay floats (`1.0`). `on`/`yes` are `true`, as in PyYAML.

## serde_json 1.0.151

- Without the `preserve_order` feature (not enabled), `serde_json::Map` is sorted by key: iterating an upstream object does not give the upstream's order. Where Python's order matters, the prompt says how to get it.
- `json!({...})` writes `f64` as a float (`5.0`), integers as integers, and `None` as `null`, the same as Python's `json.dumps` as far as the parsed JSON goes.
- The `float_roundtrip` feature is on (step R35): floats parse exactly, like Python's `json.loads`. Without it, long mantissas such as Open-Meteo's `0.40209293365478516` came out one bit off (found by the lockstep).

## base64 0.23.1 and flate2 1.1.10

- Decode: `use base64::Engine; base64::engine::general_purpose::STANDARD.decode(bytes)`. It is strict: characters outside the alphabet are errors (Python's `b64decode` skips them, so filter them first; see the radar step).
- zlib with a size cap: `flate2::read::ZlibDecoder::new(raw.as_slice()).take(limit).read_to_end(&mut out)` (`use std::io::Read;`). A truncated or corrupt stream is an `Err`, and bytes after the end of the stream are ignored (like Python's `decompressobj`).
- Encode (tests): `flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default())`, then `write_all`, then `finish()`.

## reqwest 0.13.5 (upstream HTTP)

Features: `rustls`, `gzip`, `query` (no `json`, no `stream`, no `blocking`).

- Client: `reqwest::Client::builder().timeout(d).user_agent(ua).redirect(reqwest::redirect::Policy::none()).build()`. It returns a `Result`. Build it once and clone it (a clone shares the connection pool). `Policy::none()` matters: httpx doesn't follow redirects, so a 3xx must be an error, not a second request.
- Request: `client.get(url).query(&[("lat", "52.52".to_string())]).send().await`. `.query` takes `&[(&str, String)]` and percent-encodes (`+` becomes `%2B`, a space becomes `+`).
- Status: `resp.status().is_success()`. reqwest doesn't turn 4xx/5xx into errors by itself.
- Body with a cap: check `resp.content_length()` (an `Option<u64>`; `None` for chunked or close-delimited bodies), then read with `while let Some(chunk) = resp.chunk().await? { ... }` (`chunk` is `bytes::Bytes`, use it as `&[u8]`). There is no `.json()` (feature off): parse with `serde_json::from_slice::<Value>(&body)`. serde_json stops at 128 nesting levels with an error ("recursion limit exceeded"), so deeply nested JSON is an error, not a crash.
- `std::time::Duration::try_from_secs_f64(x)` instead of `from_secs_f64` (which panics on a negative or NaN value from the config).

## rusqlite 0.40.2 (bundled SQLite 3.53.2)

- Open: `Connection::open(path)` (file) or `Connection::open_in_memory()`. The parent directory must exist (`std::fs::create_dir_all`).
- Many statements at once (Python `executescript`): `conn.execute_batch(SQL)`.
- One statement: `conn.execute(sql, params)` with positional `(a, b)` tuples or `rusqlite::params![a, b]`, or named `rusqlite::named_params! {":model": m, ":precip_mm": x}` for `:name` placeholders.
- One row or none: `use rusqlite::OptionalExtension;` then `conn.query_row(sql, [key], |r| r.get(0)).optional()?`, giving an `Option<T>`. A nullable column is `Option<T>`: a row whose `value` is NULL reads as `Some(None)` with `Option<Option<String>>`.
- Many rows: `let mut stmt = conn.prepare(sql)?; let rows = stmt.query_map([x], |r| Ok((r.get(0)?, r.get(1)?)))?.collect::<Result<Vec<_>, _>>()?;`. Drop `stmt` (end its block) before you move or reuse the connection.
- `r.get::<_, f64>(i)` also reads an INTEGER column (as `3.0`), but `i64` doesn't read a REAL column (error).
- `Connection` is `Send` but not `Sync`: share it as `std::sync::Mutex<Connection>` and never hold the guard across an `.await` (clippy fails on `await_holding_lock`).

## Shared state and locks

- App-wide objects live in an `Arc` (`Arc<Aggregator>`) and use `std::sync::Mutex`/`RwLock` inside for the few fields that change. Lock, copy or change, release, and only then `.await`.
- No `unwrap()` on a lock: `self.x.lock().unwrap_or_else(std::sync::PoisonError::into_inner)` (same for `.read()`/`.write()`).
- Locks that must be held across an `.await` (the geocoder throttle) are `tokio::sync::Mutex` (`.lock().await`).
- Background work: `tokio::spawn(async move { agg.refresh().await })` with a cloned `Arc`. Two things at once: `tokio::join!(a(), b())`.
- Timers: `tokio::time::interval_at(tokio::time::Instant::now() + period, period)` (first tick one period after start), with `.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip)`. `tokio::time::sleep(d).await` waits.

## axum extras for phase 3

- Raw query pairs (all of them, in order, percent-decoded, invalid UTF-8 becomes U+FFFD): handler argument `axum::extract::Query(pairs): Query<Vec<(String, String)>>`. Don't deserialize into a struct: a repeated key is then an error, while Python takes the last value.
- Raw body plus headers: handler arguments `headers: axum::http::HeaderMap, body: axum::body::Bytes` (the body must be the last argument). axum's default body limit is 2 MB (bigger bodies get 413).
- Outside a handler (tests, the fake upstream): `Query::<Vec<(String, String)>>::try_from_uri(&uri)`.
