//! Bright Sky radar frame decoding and the `/radar` parser (Python
//! `app/brightsky_client.py`: `_decode_grid`, `parse_radar`).
//!
//! Pure functions: raw upstream JSON in, normalized data out. Upstream data
//! is untrusted, so a wrong type or a missing key becomes a `SourceError`
//! (never a panic).

use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use flate2::read::ZlibDecoder;
use serde_json::{Map, Value};
use std::io::Read;

use crate::models::{RadarCell, RadarFrame, RadarNowcast};
use crate::pyfmt::f64_to_i64;
use crate::times::parse_iso;
use crate::upstream::SourceError;

/// Multiplier converting a raw radar uint16 value to millimetres (5-min step).
pub const RADAR_MM_PER_UNIT: f64 = 0.01;

/// Max radar sub-grid size in cells; the real grid is only a few hundred.
pub const MAX_RADAR_CELLS: i64 = 250_000;

/// The Python `malformed_is_source_error` decorator: a payload-shape error
/// (wrong type, missing key) becomes a `SourceError` with this wording.
fn malformed(label: &str, exc: SourceError) -> SourceError {
    SourceError::new(format!("{label}: malformed payload ({exc})"))
}

/// Python `_decode_grid`: base64 (characters outside the alphabet are
/// skipped, like `base64.b64decode`), then zlib, capped at the expected
/// size so a malicious frame can't expand in memory (zip bomb).
pub fn decode_grid(encoded: &str, n_cells: usize) -> Result<Vec<u16>, SourceError> {
    let cleaned: Vec<u8> = encoded
        .bytes()
        .filter(|b| b.is_ascii_alphanumeric() || matches!(b, b'+' | b'/' | b'='))
        .collect();
    let raw = STANDARD
        .decode(&cleaned)
        .map_err(|e| SourceError::new(format!("Bright Sky radar: cannot decode frame ({e})")))?;
    let expected = n_cells * 2;
    let mut data = Vec::with_capacity(expected + 1);
    ZlibDecoder::new(raw.as_slice())
        .take(expected as u64 + 1)
        .read_to_end(&mut data)
        .map_err(|e| SourceError::new(format!("Bright Sky radar: cannot decode frame ({e})")))?;
    if data.len() != expected {
        return Err(SourceError::new(format!(
            "Bright Sky radar: truncated or oversized frame ({} bytes, expected exactly {expected})",
            data.len()
        )));
    }
    let (pairs, _) = data.as_chunks::<2>();
    Ok(pairs.iter().map(|p| u16::from_le_bytes(*p)).collect())
}

/// Python `int(v)` for a bbox entry: a JSON integer, or a float truncated
/// toward zero; anything else is a malformed payload.
fn bbox_int(v: &Value) -> Result<i64, SourceError> {
    let number = v.as_i64().or_else(|| v.as_f64().and_then(f64_to_i64));
    number.ok_or_else(|| {
        malformed(
            "Bright Sky radar",
            SourceError::new(format!("bbox entry {v} is not a number")),
        )
    })
}

/// One numeric member of `latlon_position`; anything but a JSON number is a
/// malformed payload.
fn position_num(llp: &Map<String, Value>, key: &str) -> Result<f64, SourceError> {
    match llp.get(key) {
        Some(Value::Number(n)) => n.as_f64().ok_or_else(|| {
            malformed(
                "Bright Sky radar",
                SourceError::new(format!("latlon_position {key} is not a number")),
            )
        }),
        _ => Err(malformed(
            "Bright Sky radar",
            SourceError::new(format!("latlon_position {key} is not a number")),
        )),
    }
}

/// Parse a `/radar` payload into a `RadarNowcast` (Python `parse_radar`).
///
/// The response covers a sub-grid around the location with `bbox` =
/// (top, left, bottom, right) in full-grid cell coordinates and
/// `latlon_position` = (x, y) of the requested position within the
/// sub-grid. Grid cells are ~1 km. Raw values are 0.01 mm units, converted
/// to millimetres here.
///
/// The request window is bounded upstream (`fetch_radar_payload`), so every
/// frame that comes back is kept (oldest-first); the time-aware callers
/// (probability layer, UI bar) select the subset within `[now, now + 1h)`.
pub fn parse_radar(payload: &Value) -> Result<RadarNowcast, SourceError> {
    let label = "Bright Sky radar";

    let frames_raw = payload
        .get("radar")
        .and_then(Value::as_array)
        .filter(|list| !list.is_empty())
        .ok_or_else(|| SourceError::new(format!("{label}: missing/empty 'radar' list")))?;

    let bbox = payload
        .get("bbox")
        .and_then(Value::as_array)
        .filter(|list| list.len() == 4)
        .ok_or_else(|| SourceError::new(format!("{label}: missing bbox/latlon_position")))?;
    let llp = payload
        .get("latlon_position")
        .and_then(Value::as_object)
        .ok_or_else(|| SourceError::new(format!("{label}: missing bbox/latlon_position")))?;
    let [top, left, bottom, right] = bbox.as_slice() else {
        return Err(SourceError::new(format!(
            "{label}: missing bbox/latlon_position"
        )));
    };
    let (top, left, bottom, right) = (
        bbox_int(top)?,
        bbox_int(left)?,
        bbox_int(bottom)?,
        bbox_int(right)?,
    );

    let width = right
        .checked_sub(left)
        .and_then(|w| w.checked_add(1))
        .ok_or_else(|| SourceError::new(format!("{label}: bbox arithmetic overflow")))?;
    let height = bottom
        .checked_sub(top)
        .and_then(|h| h.checked_add(1))
        .ok_or_else(|| SourceError::new(format!("{label}: bbox arithmetic overflow")))?;
    let n_cells = width
        .checked_mul(height)
        .ok_or_else(|| SourceError::new(format!("{label}: bbox arithmetic overflow")))?;
    // Reject absurd grids (bogus or malicious bbox) before any decoding.
    if width <= 0 || height <= 0 || n_cells > MAX_RADAR_CELLS {
        return Err(SourceError::new(format!(
            "{label}: bbox implies {n_cells} cells ({width}x{height}), more than MAX_RADAR_CELLS={MAX_RADAR_CELLS}"
        )));
    }

    let px = position_num(llp, "x")?;
    let py = position_num(llp, "y")?;
    let covered = 0.0 <= px && px < width as f64 && 0.0 <= py && py < height as f64;

    let n_cells = usize::try_from(n_cells)
        .map_err(|_| SourceError::new(format!("{label}: bad grid size {n_cells}")))?;
    let mut frames: Vec<RadarFrame> = Vec::with_capacity(frames_raw.len());
    for rec in frames_raw {
        let rec = rec
            .as_object()
            .ok_or_else(|| malformed(label, SourceError::new("frame is not an object")))?;
        let encoded = rec
            .get("precipitation_5")
            .and_then(Value::as_str)
            .ok_or_else(|| {
                malformed(
                    label,
                    SourceError::new("frame has no string 'precipitation_5'"),
                )
            })?;
        let grid = decode_grid(encoded, n_cells)?;
        let ts = rec
            .get("timestamp")
            .and_then(Value::as_str)
            .ok_or_else(|| malformed(label, SourceError::new("frame has no string 'timestamp'")))?;
        let time_utc = parse_iso(ts).map_err(|e| malformed(label, SourceError::new(e)))?;

        let mut cells: Vec<RadarCell> = Vec::new();
        let mut max_mm = 0.0_f64;
        for row in 0..height {
            let y = top + row;
            for col in 0..width {
                // decode_grid guarantees the size; .get keeps this panic-free.
                let index = usize::try_from(row * width + col).ok();
                let Some(&value) = index.and_then(|i| grid.get(i)) else {
                    return Err(SourceError::new(format!("{label}: frame size mismatch")));
                };
                let mm = value as f64 * RADAR_MM_PER_UNIT;
                if mm > 0.0 {
                    if mm > max_mm {
                        max_mm = mm;
                    }
                    cells.push(RadarCell {
                        x: left + col,
                        y,
                        mm,
                    });
                }
            }
        }
        frames.push(RadarFrame {
            time_utc,
            cells,
            max_mm,
        });
    }

    Ok(RadarNowcast {
        frames,
        covered,
        grid_width: width,
        grid_height: height,
        bbox: (top, left, bottom, right),
        location_xy: (px, py),
    })
}

#[cfg(test)]
mod tests;
