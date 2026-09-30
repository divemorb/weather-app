//! Python-compatible number formatting: the JSON answers must carry exactly
//! the numbers and strings the Python app produces.

/// Python's `round(x, ndigits)` for floats: the exact binary value, rounded
/// half-to-even to `ndigits` decimals (Rust's `{:.N}` formatting does the
/// same), read back as the nearest f64.
pub fn py_round(x: f64, ndigits: usize) -> f64 {
    format!("{x:.ndigits$}").parse().unwrap_or(x)
}

/// Python's `round(x)` (no ndigits): half-to-even, as an integer.
pub fn py_round_int(x: f64) -> i64 {
    x.round_ties_even() as i64
}

/// Python's `format(x, ".0f")`.
pub fn py_fmt_0f(x: f64) -> String {
    format!("{x:.0}")
}

/// Python's `format(x, "g")`: 6 significant digits, trailing zeros removed,
/// scientific notation when the exponent is < -4 or >= 6.
pub fn py_fmt_g(x: f64) -> String {
    if x == 0.0 {
        return if x.is_sign_negative() {
            "-0".into()
        } else {
            "0".into()
        };
    }
    let sci = format!("{x:.5e}"); // e.g. "3.46939e1": the exponent after rounding to 6 digits
    let (mantissa, exp) = sci
        .split_once('e')
        .expect("output of {:e} always has an exponent");
    let exp: i32 = exp.parse().expect("exponent of {:e} output is an integer");
    if (-4..6).contains(&exp) {
        let decimals = (5 - exp) as usize;
        strip_zeros(&format!("{x:.decimals$}"))
    } else {
        let sign = if exp < 0 { '-' } else { '+' };
        format!("{}e{sign}{:02}", strip_zeros(mantissa), exp.abs())
    }
}

fn strip_zeros(s: &str) -> String {
    if s.contains('.') {
        s.trim_end_matches('0').trim_end_matches('.').to_string()
    } else {
        s.to_string()
    }
}

#[cfg(test)]
mod tests;
