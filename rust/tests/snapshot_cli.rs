//! `wetter snapshot PATH` as a process: exit codes and output.

use std::process::{Command, Output};

const BIN: &str = env!("CARGO_BIN_EXE_wetter");
const REPO: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../");

#[cfg(test)]
fn run(db: &std::path::Path, args: &[&str]) -> Output {
    Command::new(BIN)
        .env_clear()
        .env("WEATHER_CONFIG", format!("{REPO}/weather.yaml"))
        .env("DATABASE_PATH", db)
        .args(args)
        .output()
        .unwrap()
}

#[test]
fn snapshot_command() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("weather.db");
    wetter::store::Store::open(db.to_str().unwrap()).unwrap();
    let target = dir.path().join("copy.db");
    let out = run(&db, &["snapshot", target.to_str().unwrap()]);
    assert_eq!(out.status.code(), Some(0));
    assert!(String::from_utf8_lossy(&out.stdout).starts_with("  integrity:        ok\n"));
    assert!(target.exists());
    let again = run(&db, &["snapshot", target.to_str().unwrap()]);
    assert_eq!(again.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&again.stderr).starts_with("snapshot failed: "));
    assert_eq!(run(&db, &["snapshot"]).status.code(), Some(2));
    assert_eq!(run(&db, &["bogus", "x"]).status.code(), Some(2));
}
