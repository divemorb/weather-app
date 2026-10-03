use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;

use tokio::signal::unix::{Signal, SignalKind, signal};
use wetter::routes::{AppState, build_router};
use wetter::security::parse_allowed_hosts;

/// `wetter` runs the server; `wetter snapshot PATH` copies the live
/// database and prints its report to stdout (no logging, so it is parseable).
fn main() {
    let args: Vec<String> = std::env::args().collect();
    match args.as_slice() {
        [_] => server(),
        [_, sub, target] if sub == "snapshot" => snapshot_command(target),
        _ => {
            eprintln!("usage: wetter [snapshot PATH]");
            std::process::exit(2);
        }
    }
}

/// `wetter snapshot PATH`: consistent copy of the live database plus a
/// short report on stdout (see `wetter::snapshot`).
fn snapshot_command(target: &str) {
    let config = match wetter::config::load_config(None, &|k| std::env::var(k).ok()) {
        Ok(config) => config,
        Err(err) => {
            eprintln!("config error: {err}");
            std::process::exit(1);
        }
    };
    match wetter::snapshot::snapshot(Path::new(&config.database_path), Path::new(target)) {
        Ok(stats) => println!("{}", wetter::snapshot::report(&stats)),
        Err(err) => {
            eprintln!("snapshot failed: {err}");
            std::process::exit(1);
        }
    }
}

#[tokio::main(flavor = "current_thread")]
async fn server() {
    // The SIGTERM stream is created first (it needs the runtime): as PID 1,
    // an unhandled SIGTERM is ignored, so a stop during the startup refresh
    // would otherwise end in a kill (exit code 137).
    let mut term = match signal(SignalKind::terminate()) {
        Ok(term) => term,
        Err(err) => {
            eprintln!("cannot install SIGTERM handler: {err}");
            std::process::exit(1);
        }
    };
    tracing_subscriber::fmt().with_target(false).init();
    let clock = match wetter::times::Clock::from_env(&|k| std::env::var(k).ok()) {
        Ok(clock) => clock,
        Err(err) => {
            eprintln!("WETTER_FAKE_NOW must be an ISO-8601 timestamp: {err}");
            std::process::exit(1);
        }
    };
    if clock.is_fixed() {
        tracing::warn!(
            "WETTER_FAKE_NOW is set: the clock is frozen at {}",
            wetter::times::to_iso(clock.now())
        );
    }
    let mut config = match wetter::config::load_config(None, &|k| std::env::var(k).ok()) {
        Ok(config) => config,
        Err(err) => {
            eprintln!("config error: {err}");
            std::process::exit(1);
        }
    };
    tracing::info!("config loaded (database: {})", config.database_path);
    let store = match wetter::store::Store::open(&config.database_path) {
        Ok(store) => store,
        Err(err) => {
            eprintln!(
                "cannot open the database at {}: {err}",
                config.database_path
            );
            std::process::exit(1);
        }
    };
    // The location is runtime state: the stored value wins over env/YAML,
    // which is adopted only on first start (then written to the DB).
    config.location = match wetter::location::resolve_startup_location(&store, &config) {
        Ok(location) => location,
        Err(err) => {
            eprintln!("cannot resolve the startup location: {err}");
            std::process::exit(1);
        }
    };
    let http = match wetter::upstream::http_client(config.api.timeout_seconds) {
        Ok(http) => http,
        Err(err) => {
            eprintln!("{err}");
            std::process::exit(1);
        }
    };
    // The geocoder gets its own client: Nominatim's 10 s timeout is fixed
    // by its usage policy, whatever the app's upstream timeout is.
    let geocode_http = match wetter::upstream::http_client(10.0) {
        Ok(client) => client,
        Err(err) => {
            eprintln!("{err}");
            std::process::exit(1);
        }
    };
    let brightsky = wetter::clients::BrightSkyClient::new(&config, http.clone());
    let openmeteo = wetter::clients::OpenMeteoClient::new(&config, http);
    let agg = Arc::new(wetter::aggregator::Aggregator::new(
        config.clone(),
        store,
        brightsky,
        openmeteo,
        clock,
    ));
    let geocoder = Arc::new(wetter::geocode::Geocoder::new(
        &config.api.nominatim_base_url,
        geocode_http,
    ));
    let scheduler = Arc::new(wetter::scheduler::Scheduler::new());
    scheduler.start(agg.clone());
    // Warm the cache before the listener binds: /healthz answering means the
    // first refresh is done (a failing source must not block startup). A
    // stop request during the refresh exits cleanly: the spawned scheduler
    // tasks end with the runtime, and database writes are synchronous calls
    // between the .awaits, so no half-done write survives.
    tokio::select! {
        _ = wetter::scheduler::initial_refresh(&agg) => {},
        _ = shutdown_requested(&mut term) => {
            tracing::info!("shutdown requested during startup");
            return;
        }
    }
    tracing::info!("weather app started (db={})", config.database_path);
    let extra_hosts = parse_allowed_hosts(&std::env::var("ALLOWED_HOSTS").unwrap_or_default());
    let static_dir = std::env::var("STATIC_DIR").unwrap_or_else(|_| "/app/static".to_string());
    let static_files = match wetter::static_files::load(Path::new(&static_dir)) {
        Ok(files) => files,
        Err(err) => {
            tracing::warn!("static files unavailable from {static_dir}: {err}");
            HashMap::new()
        }
    };
    let state = AppState {
        extra_hosts: Arc::new(extra_hosts),
        static_files: Arc::new(static_files),
        aggregator: agg,
        scheduler: Some(scheduler),
        geocoder,
    };
    let bind = std::env::var("BIND_ADDR").unwrap_or_else(|_| "0.0.0.0:8000".to_string());
    let listener = match tokio::net::TcpListener::bind(&bind).await {
        Ok(listener) => listener,
        Err(err) => {
            eprintln!("cannot bind BIND_ADDR={bind}: {err}");
            std::process::exit(1);
        }
    };
    tracing::info!("listening on {bind}");
    if let Err(err) = axum::serve(listener, build_router(state))
        .with_graceful_shutdown(async move { shutdown_requested(&mut term).await })
        .await
    {
        eprintln!("server error: {err}");
        std::process::exit(1);
    }
}

/// SIGTERM (on the stream registered at the start of `server`) or Ctrl-C.
async fn shutdown_requested(term: &mut Signal) {
    tokio::select! {
        _ = term.recv() => {},
        _ = tokio::signal::ctrl_c() => {},
    }
}
