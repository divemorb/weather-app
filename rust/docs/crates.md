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

## base64 0.23.1 and flate2 1.1.10

- Decode: `use base64::Engine; base64::engine::general_purpose::STANDARD.decode(bytes)`. It is strict: characters outside the alphabet are errors (Python's `b64decode` skips them, so filter them first; see the radar step).
- zlib with a size cap: `flate2::read::ZlibDecoder::new(raw.as_slice()).take(limit).read_to_end(&mut out)` (`use std::io::Read;`). A truncated or corrupt stream is an `Err`, and bytes after the end of the stream are ignored (like Python's `decompressobj`).
- Encode (tests): `flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default())`, then `write_all`, then `finish()`.

## reqwest 0.13.5, rusqlite 0.40.2

Added with the phase that uses them (phase 3).
