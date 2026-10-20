//! A snapshot restored into a fresh volume: the app reads the location the
//! backup stored; a fresh volume without a backup stays unconfigured.

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::Path;
use std::process::{Child, Command};
use std::time::{Duration, Instant};

const BIN: &str = env!("CARGO_BIN_EXE_wetter");
const REPO: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

/// The repo's weather.yaml with the api block pointing at `base`.
#[cfg(test)]
fn write_config(dir: &Path, base: &str) -> std::path::PathBuf {
    let text = std::fs::read_to_string(format!("{REPO}/weather.yaml")).unwrap();
    let (head, _) = text.split_once("\napi:").unwrap();
    let path = dir.join("weather.yaml");
    std::fs::write(
        &path,
        format!(
            "{head}\napi:\n  brightsky_base_url: \"{base}/bs\"\n  open_meteo_base_url: \"{base}/om/v1\"\n  ensemble_base_url: \"{base}/ens/v1\"\n  nominatim_base_url: \"{base}/nom\"\n  timeout_seconds: 20\n"
        ),
    )
    .unwrap();
    path
}

#[cfg(test)]
fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port()
}

#[cfg(test)]
fn healthz(port: u16) -> bool {
    let Ok(mut s) = TcpStream::connect(("127.0.0.1", port)) else {
        return false;
    };
    s.write_all(b"GET /healthz HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        .unwrap();
    let mut out = String::new();
    s.read_to_string(&mut out).is_ok() && out.starts_with("HTTP/1.0 200")
}

/// The JSON body of `GET /api/config` (HTTP/1.0, the body after the first
/// blank line; the status line must start with `HTTP/1.0 200`).
#[cfg(test)]
fn get_config(port: u16) -> serde_json::Value {
    let mut s = TcpStream::connect(("127.0.0.1", port)).unwrap();
    s.write_all(b"GET /api/config HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        .unwrap();
    let mut out = String::new();
    s.read_to_string(&mut out).unwrap();
    assert!(out.starts_with("HTTP/1.0 200"), "{out}");
    serde_json::from_str(out.split_once("\r\n\r\n").unwrap().1).unwrap()
}

/// Start the app with `db` as the database and no LATITUDE/LONGITUDE; the
/// upstream base is a closed port, so the startup refresh fails fast.
#[cfg(test)]
fn start_on(db: &Path, config_dir: &Path, port: u16) -> Child {
    let closed = format!("http://127.0.0.1:{}", free_port());
    Command::new(BIN)
        .env_clear()
        .env("WEATHER_CONFIG", write_config(config_dir, &closed))
        .env("DATABASE_PATH", db)
        .env("BIND_ADDR", format!("127.0.0.1:{port}"))
        .env("STATIC_DIR", format!("{REPO}/app/static"))
        .spawn()
        .unwrap()
}

/// Wait until `/healthz` answers (10 s at most).
#[cfg(test)]
fn wait_ready(port: u16) {
    let end = Instant::now() + Duration::from_secs(10);
    while !healthz(port) {
        assert!(Instant::now() < end, "app not ready");
        std::thread::sleep(Duration::from_millis(50));
    }
}

/// Stop the app: kill it and reap it.
#[cfg(test)]
fn stop(child: &mut Child) {
    child.kill().unwrap();
    child.wait().unwrap();
}

/// `wetter` with a clean environment (as `run` in snapshot_cli.rs).
#[cfg(test)]
fn run(db: &Path, args: &[&str]) -> std::process::Output {
    Command::new(BIN)
        .env_clear()
        .env("WEATHER_CONFIG", format!("{REPO}/weather.yaml"))
        .env("DATABASE_PATH", db)
        .args(args)
        .output()
        .unwrap()
}

#[test]
fn restored_backup_is_read_by_the_app() {
    let a = tempfile::tempdir().unwrap();
    let b = tempfile::tempdir().unwrap();
    let c = tempfile::tempdir().unwrap();
    // dir A: a database with a stored location
    let db_a = a.path().join("weather.db");
    let store = wetter::Store::open(db_a.to_str().unwrap()).unwrap();
    let location = r#"{"latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin",
        "label": "Backup test"}"#;
    store.set_meta("location", location).unwrap();
    drop(store);
    // the snapshot, then dir A is gone: only the backup is left
    let backup = b.path().join("backup.db");
    let out = run(&db_a, &["snapshot", backup.to_str().unwrap()]);
    assert_eq!(out.status.code(), Some(0));
    std::fs::remove_dir_all(a.path()).unwrap();
    // the fresh, empty volume C gets the backup's database
    let db_c = c.path().join("weather.db");
    std::fs::copy(&backup, &db_c).unwrap();
    // the app on the fresh volume reads the restored location
    let port = free_port();
    let mut child = start_on(&db_c, c.path(), port);
    wait_ready(port);
    let cfg = get_config(port);
    assert_eq!(cfg["configured"], serde_json::Value::Bool(true));
    assert_eq!(cfg["location"]["label"], serde_json::json!("Backup test"));
    assert_eq!(
        cfg["location"]["timezone"],
        serde_json::json!("Europe/Berlin")
    );
    stop(&mut child);
}

#[test]
fn fresh_volume_without_backup_is_unconfigured() {
    let c = tempfile::tempdir().unwrap();
    let db_c = c.path().join("weather.db");
    let port = free_port();
    let mut child = start_on(&db_c, c.path(), port);
    wait_ready(port);
    let cfg = get_config(port);
    assert_eq!(cfg["configured"], serde_json::Value::Bool(false));
    stop(&mut child);
}
