use super::*;
use chrono::{DateTime, Utc};
use serde_json::json;
use std::io::Write;

/// Defaults of the `make_radar_payload` helper.
const DEFAULT_BBOX: (i64, i64, i64, i64) = (10, 20, 14, 24); // top, left, bottom, right
const DEFAULT_LLP: (f64, f64) = (2.0, 2.0);

fn frame(timestamp: &str, g: Vec<Vec<u16>>) -> (&str, Vec<Vec<u16>>) {
    (timestamp, g)
}

#[test]
fn parse_radar_decodes_grid_and_unit() {
    let mut g = crate::testutil::grid(5, 5, 0);
    g[1][1] = 38; // 0.38 mm
    let payload = crate::testutil::make_radar_payload(
        &[frame("2026-09-25T06:45:00+00:00", g)],
        DEFAULT_BBOX,
        DEFAULT_LLP,
    );
    let nc = parse_radar(&payload).unwrap();
    assert_eq!(nc.frames.len(), 1);
    let f = &nc.frames[0];
    assert_eq!(f.max_mm, 38.0 * RADAR_MM_PER_UNIT);
    assert_eq!(f.cells.len(), 1);
    let cell = &f.cells[0];
    // sub-grid origin (top,left)=(10,20); row1,col1 -> y=11, x=21
    assert_eq!((cell.x, cell.y), (21, 11));
    assert_eq!(cell.mm, 38.0 * RADAR_MM_PER_UNIT);
    assert_eq!(nc.grid_width, 5);
    assert_eq!(nc.grid_height, 5);
    assert_eq!(nc.bbox, (10, 20, 14, 24));
    assert!(nc.covered);
}

#[test]
fn parse_radar_keeps_all_frames_in_window() {
    // The request window is bounded upstream (fetch_radar_payload), so the
    // parser keeps every frame it receives (oldest-first).
    let frames: Vec<(&str, Vec<Vec<u16>>)> = [
        "2026-09-25T06:00:00+00:00",
        "2026-09-25T06:05:00+00:00",
        "2026-09-25T06:10:00+00:00",
        "2026-09-25T06:15:00+00:00",
        "2026-09-25T06:20:00+00:00",
        "2026-09-25T06:25:00+00:00",
    ]
    .iter()
    .map(|t| frame(t, crate::testutil::grid(5, 5, 0)))
    .collect();
    let payload = crate::testutil::make_radar_payload(&frames, DEFAULT_BBOX, DEFAULT_LLP);
    let nc = parse_radar(&payload).unwrap();
    assert_eq!(nc.frames.len(), 6);
    let stamps: Vec<DateTime<Utc>> = nc.frames.iter().map(|f| f.time_utc).collect();
    let mut sorted = stamps.clone();
    sorted.sort();
    assert_eq!(stamps, sorted);
}

#[test]
fn parse_radar_empty_frames_raises() {
    assert!(
        parse_radar(&json!({
            "radar": [],
            "bbox": [0, 0, 1, 1],
            "latlon_position": {"x": 0, "y": 0},
        }))
        .is_err()
    );
}

#[test]
fn parse_radar_missing_bbox_raises() {
    assert!(
        parse_radar(&json!({
            "radar": [{"timestamp": "t", "precipitation_5": ""}],
        }))
        .is_err()
    );
}

#[test]
fn parse_radar_bad_frame_size_raises() {
    // grid is 4x4 but bbox implies 3x3 -> mismatch
    let g = crate::testutil::grid(4, 4, 0);
    let payload = crate::testutil::make_radar_payload(
        &[frame("2026-09-25T06:45:00+00:00", g)],
        (10, 20, 12, 22),
        DEFAULT_LLP,
    );
    assert!(parse_radar(&payload).is_err());
}

#[test]
fn parse_radar_location_outside_grid_marks_uncovered() {
    let g = crate::testutil::grid(5, 5, 0);
    let payload = crate::testutil::make_radar_payload(
        &[frame("2026-09-25T06:45:00+00:00", g)],
        DEFAULT_BBOX,
        (99.0, 99.0),
    );
    assert!(!parse_radar(&payload).unwrap().covered);
}

#[test]
fn parse_radar_non_numeric_bbox_raises_source_error() {
    // a bbox entry that is not a number: untrusted payload -> SourceError
    // (the request path only catches that), not a panic
    let g = crate::testutil::grid(5, 5, 0);
    let mut payload = crate::testutil::make_radar_payload(
        &[frame("2026-09-25T06:45:00+00:00", g)],
        DEFAULT_BBOX,
        DEFAULT_LLP,
    );
    payload["bbox"] = json!(["a", 20, 14, 24]);
    let err = parse_radar(&payload).unwrap_err();
    assert!(err.to_string().contains("malformed"));
}

#[test]
fn parse_radar_huge_bbox_raises_source_error() {
    // width * height > MAX_RADAR_CELLS must be rejected BEFORE decoding,
    // otherwise the decoder would allocate an absurd grid (10^12 cells here)
    let g = crate::testutil::grid(5, 5, 0);
    let payload = crate::testutil::make_radar_payload(
        &[frame("2026-09-25T06:45:00+00:00", g)],
        (0, 0, 1_000_000, 1_000_000),
        DEFAULT_LLP,
    );
    let err = parse_radar(&payload).unwrap_err();
    assert!(err.to_string().contains("MAX_RADAR_CELLS"));
}

fn encode_zlib(data: &[u8]) -> String {
    let mut enc = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
    enc.write_all(data).unwrap();
    base64::engine::general_purpose::STANDARD.encode(enc.finish().unwrap())
}

#[test]
fn parse_radar_zip_bomb_frame_raises_source_error() {
    // a frame whose zlib stream expands far beyond the expected grid size
    // must be aborted at the decompression cap, not fully decompressed
    let encoded = encode_zlib(&vec![0u8; 10_000_000]); // 10 MB from a few KB
    let mut payload = crate::testutil::make_radar_payload(
        &[frame(
            "2026-09-25T06:45:00+00:00",
            crate::testutil::grid(5, 5, 0),
        )],
        DEFAULT_BBOX,
        DEFAULT_LLP,
    );
    payload["radar"][0]["precipitation_5"] = json!(encoded);
    let start = std::time::Instant::now();
    assert!(parse_radar(&payload).is_err());
    // the cap (5x5x2+1 bytes here) stops the stream after ~100 bytes of the
    // 10 MB expansion — comfortably fast even on a slow machine
    assert!(start.elapsed() < std::time::Duration::from_secs(1));
}

#[test]
fn parse_radar_truncated_frame_raises_source_error() {
    // a zlib stream whose checksum trailer was cut off (right length, but
    // never finished) must be rejected like an incomplete stream
    let raw = {
        let mut enc = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
        enc.write_all(&[0u8; 50]).unwrap();
        enc.finish().unwrap()
    };
    let encoded = base64::engine::general_purpose::STANDARD.encode(&raw[..raw.len() - 4]);
    let mut payload = crate::testutil::make_radar_payload(
        &[frame(
            "2026-09-25T06:45:00+00:00",
            crate::testutil::grid(5, 5, 0),
        )],
        DEFAULT_BBOX,
        DEFAULT_LLP,
    );
    payload["radar"][0]["precipitation_5"] = json!(encoded);
    assert!(parse_radar(&payload).is_err());
}

#[test]
fn decode_grid_matches_python_cases() {
    // Every case in the fixture must agree with the Rust decoder.
    let cases: Value = serde_json::from_str(include_str!(
        "../../contract/fixtures/py_cases/radar_frames.json"
    ))
    .unwrap();
    let cases = cases["cases"].as_array().unwrap();
    assert!(!cases.is_empty());
    for case in cases {
        let name = case["name"].as_str().unwrap();
        let encoded = case["encoded"].as_str().unwrap();
        let n_cells = usize::try_from(case["n_cells"].as_u64().unwrap()).unwrap();
        match case["result"].as_str() {
            Some("error") => {
                assert!(decode_grid(encoded, n_cells).is_err(), "case {name:?}");
            }
            None => {
                let result = &case["result"];
                let grid =
                    decode_grid(encoded, n_cells).unwrap_or_else(|e| panic!("case {name:?}: {e}"));
                let sum: u64 = grid.iter().map(|v| *v as u64).sum();
                // sum of index * value modulo 1_000_000_007, computed with u64
                let weighted: u64 = grid
                    .iter()
                    .enumerate()
                    .map(|(i, v)| (i as u64) * (*v as u64))
                    .sum::<u64>()
                    % 1_000_000_007;
                assert_eq!(
                    grid.len(),
                    usize::try_from(result["len"].as_u64().unwrap()).unwrap(),
                    "case {name:?}: len"
                );
                assert_eq!(sum, result["sum"].as_u64().unwrap(), "case {name:?}: sum");
                assert_eq!(
                    weighted,
                    result["weighted"].as_u64().unwrap(),
                    "case {name:?}: weighted"
                );
            }
            Some(other) => panic!("case {name:?}: unknown result {other:?}"),
        }
    }
}
