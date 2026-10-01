//! A fake upstream HTTP server for tests (the Rust version of
//! `rust/contract/fakeup.py`): canned answers per path, and a log of every
//! request (path, decoded query pairs, User-Agent).

use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::{Arc, Mutex};

use serde_json::Value;

#[derive(Clone, Debug, PartialEq)]
pub struct FakeRequest {
    pub path: String,
    pub query: Vec<(String, String)>,
    pub user_agent: String,
}

impl FakeRequest {
    /// The value of query parameter `key` (last one wins).
    pub fn param(&self, key: &str) -> Option<&str> {
        self.query
            .iter()
            .rev()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.as_str())
    }
}

#[derive(Clone, Debug)]
pub enum FakeResponse {
    /// 200 with this JSON body.
    Json(Value),
    /// This status with a short text body.
    Status(u16),
    /// 200 with this exact body (e.g. broken JSON).
    Raw(String),
    /// 200 with a body of at least `bytes` bytes; with `declare` the
    /// Content-Length says so, without it the body is close-delimited.
    Oversize { bytes: usize, declare: bool },
}

#[derive(Clone)]
pub struct FakeUpstream {
    /// `http://127.0.0.1:<port>`
    pub base: String,
    routes: Arc<Mutex<HashMap<String, FakeResponse>>>,
    log: Arc<Mutex<Vec<FakeRequest>>>,
}

impl FakeUpstream {
    /// Start the server on a free port. Unknown paths answer 404.
    pub fn start() -> FakeUpstream {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind");
        let base = format!("http://{}", listener.local_addr().expect("addr"));
        let fake = FakeUpstream {
            base,
            routes: Arc::new(Mutex::new(HashMap::new())),
            log: Arc::new(Mutex::new(Vec::new())),
        };
        let server = fake.clone();
        std::thread::spawn(move || {
            for stream in listener.incoming().flatten() {
                let server = server.clone();
                std::thread::spawn(move || server.serve(stream));
            }
        });
        fake
    }

    /// Answer requests to `path` (no query string) with `response`.
    pub fn set(&self, path: &str, response: FakeResponse) {
        self.routes
            .lock()
            .unwrap()
            .insert(path.to_string(), response);
    }

    /// Every request so far, in arrival order.
    pub fn requests(&self) -> Vec<FakeRequest> {
        self.log.lock().unwrap().clone()
    }

    /// The requests to one path.
    pub fn requests_to(&self, path: &str) -> Vec<FakeRequest> {
        self.requests()
            .into_iter()
            .filter(|r| r.path == path)
            .collect()
    }

    fn serve(&self, mut stream: TcpStream) {
        let mut head = Vec::new();
        let mut buf = [0u8; 4096];
        while !head.windows(4).any(|w| w == b"\r\n\r\n") {
            match stream.read(&mut buf) {
                Ok(0) | Err(_) => return,
                Ok(n) => head.extend_from_slice(&buf[..n]),
            }
        }
        let head = String::from_utf8_lossy(&head).to_string();
        let target = head.split(' ').nth(1).unwrap_or("/");
        let uri: axum::http::Uri = target.parse().unwrap_or_default();
        let query = axum::extract::Query::<Vec<(String, String)>>::try_from_uri(&uri)
            .map(|q| q.0)
            .unwrap_or_default();
        let user_agent = head
            .lines()
            .find_map(|l| {
                let (k, v) = l.split_once(':')?;
                k.eq_ignore_ascii_case("user-agent")
                    .then(|| v.trim().to_string())
            })
            .unwrap_or_default();
        self.log.lock().unwrap().push(FakeRequest {
            path: uri.path().to_string(),
            query,
            user_agent,
        });
        let response = self.routes.lock().unwrap().get(uri.path()).cloned();
        let _ = match response {
            None => respond(&mut stream, 404, b"not found"),
            Some(FakeResponse::Json(v)) => respond(&mut stream, 200, v.to_string().as_bytes()),
            Some(FakeResponse::Status(code)) => respond(&mut stream, code, b"upstream failure"),
            Some(FakeResponse::Raw(text)) => respond(&mut stream, 200, text.as_bytes()),
            Some(FakeResponse::Oversize { bytes, declare }) => {
                oversize(&mut stream, bytes, declare)
            }
        };
    }
}

fn respond(stream: &mut TcpStream, status: u16, body: &[u8]) -> std::io::Result<()> {
    write!(
        stream,
        "HTTP/1.0 {status} X\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n",
        body.len()
    )?;
    stream.write_all(body)
}

fn oversize(stream: &mut TcpStream, bytes: usize, declare: bool) -> std::io::Result<()> {
    let length = if declare {
        format!("Content-Length: {bytes}\r\n")
    } else {
        String::new()
    };
    write!(
        stream,
        "HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n{length}\r\n"
    )?;
    let chunk = [b'0'; 65536];
    let mut sent = 0;
    while sent < bytes {
        stream.write_all(&chunk)?;
        sent += chunk.len();
    }
    Ok(())
}
