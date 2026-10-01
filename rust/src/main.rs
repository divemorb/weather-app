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
    let config = match wetter::config::load_config(None, &|k| std::env::var(k).ok()) {
        Ok(config) => config,
        Err(err) => {
            eprintln!("config error: {err}");
            std::process::exit(1);
        }
    };
    tracing::info!("config loaded (database: {})", config.database_path);
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
