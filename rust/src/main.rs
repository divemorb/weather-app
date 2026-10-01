use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;

use wetter::routes::{AppState, build_router};
use wetter::security::parse_allowed_hosts;

#[tokio::main(flavor = "current_thread")]
async fn main() {
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
    // which is only adopted on first start (written to the DB).
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
    // first refresh is done (a failing source must not block startup).
    wetter::scheduler::initial_refresh(&agg).await;
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
        .with_graceful_shutdown(shutdown_signal())
        .await
    {
        eprintln!("server error: {err}");
        std::process::exit(1);
    }
}

async fn shutdown_signal() {
    use tokio::signal::unix::{SignalKind, signal};
    let mut term = match signal(SignalKind::terminate()) {
        Ok(term) => term,
        Err(err) => {
            eprintln!("cannot install SIGTERM handler: {err}");
            std::process::exit(1);
        }
    };
    tokio::select! {
        _ = term.recv() => {},
        _ = tokio::signal::ctrl_c() => {},
    }
}
