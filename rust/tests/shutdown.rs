//! The binary as a process: SIGTERM during the startup refresh and while
//! serving ends it cleanly (exit code 0).

mod common;

use common::{REPO, free_port, healthz, write_config};
use std::net::TcpListener;
use std::path::Path;
use std::process::{Child, Command, ExitStatus};
use std::time::{Duration, Instant};

const BIN: &str = env!("CARGO_BIN_EXE_wetter");

/// An upstream that accepts connections and never answers.
#[cfg(test)]
fn black_hole() -> String {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    std::thread::spawn(move || {
        // leak each accepted connection (held open, never answers)
        for stream in listener.incoming() {
            std::mem::forget(stream);
        }
    });
    base
}

#[cfg(test)]
fn start(dir: &Path, base: &str, port: u16) -> Child {
    Command::new(BIN)
        .env_clear()
        .env("WEATHER_CONFIG", write_config(dir, base))
        .env("DATABASE_PATH", dir.join("weather.db"))
        .env("LATITUDE", "52.52")
        .env("LONGITUDE", "13.405")
        .env("BIND_ADDR", format!("127.0.0.1:{port}"))
        .env("STATIC_DIR", format!("{REPO}/app/static"))
        .spawn()
        .unwrap()
}

/// Send SIGTERM via the shell builtin `kill`.
#[cfg(test)]
fn sigterm(child: &Child) {
    let ok = Command::new("sh")
        .args(["-c", &format!("kill -TERM {}", child.id())])
        .status()
        .unwrap();
    assert!(ok.success());
}

/// The exit status, or `None` (and the child killed) after `limit`.
#[cfg(test)]
fn wait(child: &mut Child, limit: Duration) -> Option<ExitStatus> {
    let end = Instant::now() + limit;
    while Instant::now() < end {
        if let Some(status) = child.try_wait().unwrap() {
            return Some(status);
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    child.kill().unwrap();
    None
}

#[test]
fn sigterm_during_startup_refresh_exits_cleanly() {
    let dir = tempfile::tempdir().unwrap();
    let mut child = start(dir.path(), &black_hole(), free_port());
    std::thread::sleep(Duration::from_millis(500)); // inside the refresh
    sigterm(&child);
    let status = wait(&mut child, Duration::from_secs(5));
    assert!(status.is_some_and(|s| s.success()), "{status:?}");
}

#[test]
fn sigterm_while_serving_exits_cleanly() {
    let dir = tempfile::tempdir().unwrap();
    let closed = format!("http://127.0.0.1:{}", free_port());
    let port = free_port();
    let mut child = start(dir.path(), &closed, port);
    let end = Instant::now() + Duration::from_secs(10);
    while !healthz(port) {
        assert!(Instant::now() < end, "app not ready");
        std::thread::sleep(Duration::from_millis(50));
    }
    sigterm(&child);
    let status = wait(&mut child, Duration::from_secs(5));
    assert!(status.is_some_and(|s| s.success()), "{status:?}");
}
