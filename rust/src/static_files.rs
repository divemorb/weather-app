use std::collections::HashMap;
use std::hash::{DefaultHasher, Hash, Hasher};
use std::path::Path;

use axum::body::Bytes;
use axum::http::header::{self, HeaderMap};
use axum::http::{Method, StatusCode, Uri};
use axum::response::{IntoResponse, Response};

pub struct StaticFile {
    pub body: Bytes,
    pub content_type: &'static str,
    pub etag: String,
}

/// Starlette's content types for the files in app/static.
pub fn content_type(name: &str) -> &'static str {
    match name.rsplit_once('.').map(|(_, ext)| ext) {
        Some("html") => "text/html; charset=utf-8",
        Some("js") => "text/javascript; charset=utf-8",
        Some("css") => "text/css; charset=utf-8",
        _ => "application/octet-stream",
    }
}

/// Read every regular file in `dir` (not recursive) into memory once, at
/// startup. Subdirectories are skipped; the file set is fixed for the life
/// of the process.
pub fn load(dir: &Path) -> std::io::Result<HashMap<String, StaticFile>> {
    let mut files = HashMap::new();
    for entry in std::fs::read_dir(dir)? {
        let entry = entry?;
        if !entry.file_type()?.is_file() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().into_owned();
        let body = Bytes::from(std::fs::read(entry.path())?);
        let mut hasher = DefaultHasher::new();
        body.hash(&mut hasher);
        let etag = format!("\"{:016x}\"", hasher.finish());
        files.insert(
            name.clone(),
            StaticFile {
                body,
                content_type: content_type(&name),
                etag,
            },
        );
    }
    Ok(files)
}

/// The fallback for everything no route matched: like Starlette's
/// StaticFiles mount, a method other than GET/HEAD is 405, an unknown path
/// is 404 (both JSON), `/` is index.html, and a matching `If-None-Match`
/// is 304. Only files loaded from STATIC_DIR exist, so no path can escape.
pub fn respond(
    files: &HashMap<String, StaticFile>,
    method: &Method,
    uri: &Uri,
    headers: &HeaderMap,
) -> Response {
    if method != Method::GET && method != Method::HEAD {
        return crate::security::json_error(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed");
    }
    let name = match uri.path() {
        "/" => "index.html",
        p => p.trim_start_matches('/'),
    };
    let Some(file) = files.get(name) else {
        return crate::security::json_error(StatusCode::NOT_FOUND, "Not Found");
    };
    let matches = headers
        .get(header::IF_NONE_MATCH)
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.split(',').any(|tag| tag.trim() == file.etag));
    if matches {
        return (
            StatusCode::NOT_MODIFIED,
            [(header::ETAG, file.etag.clone())],
        )
            .into_response();
    }
    (
        [
            (header::CONTENT_TYPE, file.content_type.to_string()),
            (header::ETAG, file.etag.clone()),
        ],
        file.body.clone(),
    )
        .into_response()
}

#[cfg(test)]
mod tests;
