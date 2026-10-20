//! Helpers shared by the integration tests that start the binary (shutdown.rs, restore.rs).

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};

/// The repository root.
pub const REPO: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/..");

/// The repo's weather.yaml with the api block pointing at `base`.
#[cfg(test)]
pub fn write_config(dir: &Path, base: &str) -> PathBuf {
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
pub fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port()
}

#[cfg(test)]
pub fn healthz(port: u16) -> bool {
    let Ok(mut s) = TcpStream::connect(("127.0.0.1", port)) else {
        return false;
    };
    s.write_all(b"GET /healthz HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        .unwrap();
    let mut out = String::new();
    s.read_to_string(&mut out).is_ok() && out.starts_with("HTTP/1.0 200")
}
