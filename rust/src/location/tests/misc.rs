//! `valid_timezone`, `same_origin` (Python `app.location.same_origin`) and
//! the JSON shapes of `errors_json` / `location_payload`.

use super::*;

// ---------------------------------------------------------------------------
// valid_timezone
// ---------------------------------------------------------------------------

#[test]
fn valid_timezone_accepts_iana_names() {
    for name in [
        "Europe/Berlin",
        "UTC",
        "GMT",
        "Etc/GMT+1",
        "Europe/Kyiv",
        "Europe/Kiev",
        "US/Pacific",
        "EST5EDT",
    ] {
        assert!(valid_timezone(name), "{name}");
    }
}

#[test]
fn valid_timezone_rejects_garbage_and_paths() {
    for name in [
        "utc",
        "Europe/berlin",
        "localtime",
        "posixrules",
        "Factory",
        "posix/Europe/Berlin",
        "right/UTC",
        "/Europe/Berlin",
        "Europe//Berlin",
        "zone.tab",
        "Europe/Berlin ",
        "../../etc/passwd",
        "Mars/Olympus_Mons",
        "",
    ] {
        assert!(!valid_timezone(name), "{name:?}");
    }
}

// ---------------------------------------------------------------------------
// same_origin
// ---------------------------------------------------------------------------

fn hdrs(pairs: &[(&str, &str)]) -> HeaderMap {
    let mut headers = HeaderMap::new();
    for (name, value) in pairs {
        headers.insert(
            name.parse::<axum::http::HeaderName>().unwrap(),
            value.parse().unwrap(),
        );
    }
    headers
}

#[test]
fn same_origin_with_origin() {
    let host = "127.0.0.1:8000";
    assert!(same_origin(&hdrs(&[
        ("host", host),
        ("origin", "http://127.0.0.1:8000")
    ])));
    assert!(same_origin(&hdrs(&[
        ("host", host),
        ("origin", "HTTP://127.0.0.1:8000")
    ])));
    assert!(!same_origin(&hdrs(&[
        ("host", host),
        ("origin", "https://evil.example")
    ])));
    assert!(!same_origin(&hdrs(&[("host", host), ("origin", "null")])));
}

#[test]
fn same_origin_without_origin() {
    let host = "127.0.0.1:8000";
    assert!(!same_origin(&hdrs(&[
        ("host", host),
        ("sec-fetch-site", "cross-site")
    ])));
    assert!(same_origin(&hdrs(&[
        ("host", host),
        ("sec-fetch-site", "same-origin")
    ])));
    assert!(same_origin(&hdrs(&[("host", host)])));
}

// ---------------------------------------------------------------------------
// errors_json / location_payload
// ---------------------------------------------------------------------------

#[test]
fn errors_json_shape() {
    let errors = vec![
        FieldError {
            loc: vec![LocPart::Name("body"), LocPart::Name("latitude")],
            msg: "Field required",
        },
        FieldError {
            loc: vec![LocPart::Name("body"), LocPart::Pos(6)],
            msg: "JSON decode error",
        },
    ];
    assert_eq!(
        errors_json(&errors),
        json!({
            "detail": [
                {"loc": ["body", "latitude"], "msg": "Field required"},
                {"loc": ["body", 6], "msg": "JSON decode error"}
            ]
        })
    );
}

#[test]
fn location_payload_shape() {
    let l = loc(52.52, 13.405, "Europe/Berlin", "Berlin");
    assert_eq!(
        location_payload(&l),
        json!({
            "latitude": 52.52,
            "longitude": 13.405,
            "timezone": "Europe/Berlin",
            "label": "Berlin"
        })
    );
}
