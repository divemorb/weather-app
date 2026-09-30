use axum::http::Request;

use super::*;

fn make_files() -> (tempfile::TempDir, HashMap<String, StaticFile>) {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("index.html"), "<html></html>").unwrap();
    std::fs::write(dir.path().join("app.js"), "console.log(1)").unwrap();
    std::fs::write(dir.path().join("style.css"), "body {}").unwrap();
    std::fs::write(dir.path().join("data.bin"), [0u8, 1]).unwrap();
    std::fs::create_dir(dir.path().join("subdir")).unwrap();
    std::fs::write(dir.path().join("subdir").join("hidden.js"), "x").unwrap();
    let files = load(dir.path()).unwrap();
    (dir, files)
}

async fn call(
    files: &HashMap<String, StaticFile>,
    method: &str,
    uri: &str,
    if_none_match: Option<&str>,
) -> (StatusCode, HeaderMap, String) {
    let req = Request::builder()
        .method(method)
        .uri(uri)
        .body(axum::body::Body::empty())
        .unwrap();
    let method = req.method().clone();
    let uri = req.uri().clone();
    let mut headers = HeaderMap::new();
    if let Some(tag) = if_none_match {
        headers.insert(header::IF_NONE_MATCH, tag.parse().unwrap());
    }
    let res = respond(files, &method, &uri, &headers);
    let status = res.status();
    let headers = res.headers().clone();
    let bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
        .await
        .unwrap();
    (status, headers, String::from_utf8(bytes.to_vec()).unwrap())
}

#[test]
fn load_reads_regular_files_and_skips_directories() {
    let (_dir, files) = make_files();
    assert_eq!(files.len(), 4);
    assert!(files.contains_key("index.html"));
    assert!(files.contains_key("app.js"));
    assert!(files.contains_key("style.css"));
    assert!(files.contains_key("data.bin"));
}

#[test]
fn content_types_match_starlette() {
    assert_eq!(content_type("index.html"), "text/html; charset=utf-8");
    assert_eq!(content_type("app.js"), "text/javascript; charset=utf-8");
    assert_eq!(content_type("style.css"), "text/css; charset=utf-8");
    assert_eq!(content_type("data.bin"), "application/octet-stream");
    assert_eq!(content_type("README"), "application/octet-stream");
}

#[tokio::test]
async fn root_serves_index_html() {
    let (_dir, files) = make_files();
    let (status, headers, body) = call(&files, "GET", "/", None).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, "<html></html>");
    assert_eq!(
        headers
            .get(header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok()),
        Some("text/html; charset=utf-8")
    );
    let etag = files.get("index.html").unwrap().etag.clone();
    assert_eq!(
        headers.get(header::ETAG).and_then(|v| v.to_str().ok()),
        Some(etag.as_str())
    );
}

#[tokio::test]
async fn unknown_path_is_json_404() {
    let (_dir, files) = make_files();
    let (status, headers, body) = call(&files, "GET", "/nope.js", None).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body, r#"{"detail":"Not Found"}"#);
    assert_eq!(
        headers
            .get(header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok()),
        Some("application/json")
    );
}

#[tokio::test]
async fn traversal_path_is_json_404() {
    let (_dir, files) = make_files();
    let (status, _headers, body) = call(&files, "GET", "/../x", None).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body, r#"{"detail":"Not Found"}"#);
}

#[tokio::test]
async fn post_is_json_405() {
    let (_dir, files) = make_files();
    let (status, _headers, body) = call(&files, "POST", "/app.js", None).await;
    assert_eq!(status, StatusCode::METHOD_NOT_ALLOWED);
    assert_eq!(body, r#"{"detail":"Method Not Allowed"}"#);
}

#[tokio::test]
async fn matching_etag_is_304_with_empty_body() {
    let (_dir, files) = make_files();
    let etag = files.get("app.js").unwrap().etag.clone();
    let (status, headers, body) = call(&files, "GET", "/app.js", Some(etag.as_str())).await;
    assert_eq!(status, StatusCode::NOT_MODIFIED);
    assert_eq!(
        headers.get(header::ETAG).and_then(|v| v.to_str().ok()),
        Some(etag.as_str())
    );
    assert!(!headers.contains_key(header::CONTENT_TYPE));
    assert!(body.is_empty());
}

#[tokio::test]
async fn different_tag_is_200() {
    let (_dir, files) = make_files();
    let (status, _headers, body) = call(&files, "GET", "/app.js", Some("\"other\"")).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, "console.log(1)");
}

#[tokio::test]
async fn etag_list_match_is_304() {
    let (_dir, files) = make_files();
    let etag = files.get("app.js").unwrap().etag.clone();
    let list = format!("\"x\", {etag}");
    let (status, _headers, body) = call(&files, "GET", "/app.js", Some(list.as_str())).await;
    assert_eq!(status, StatusCode::NOT_MODIFIED);
    assert!(body.is_empty());
}
