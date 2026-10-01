//! Python-compatible number formatting: the JSON answers must carry exactly
//! the numbers and strings the Python app produces.

/// Python's `round(x, ndigits)` for floats: the exact binary value, rounded
/// half-to-even to `ndigits` decimals (Rust's `{:.N}` formatting does the
/// same), read back as the nearest f64.
pub fn py_round(x: f64, ndigits: usize) -> f64 {
    format!("{x:.ndigits$}").parse().unwrap_or(x)
}

/// The only f64 -> i64 conversion in the crate: `Some(n)` exactly when the
/// truncated value fits in an i64.
#[expect(clippy::cast_possible_truncation, reason = "range checked just above")]
pub fn f64_to_i64(x: f64) -> Option<i64> {
    const TWO_POW_63: f64 = 9_223_372_036_854_775_808.0;
    (x.is_finite() && (-TWO_POW_63..TWO_POW_63).contains(&x)).then(|| x.trunc() as i64)
}

/// Python's `round(x)` (no ndigits): half-to-even, as an integer.
pub fn py_round_int(x: f64) -> i64 {
    let r = x.round_ties_even();
    match f64_to_i64(r) {
        Some(n) => n,
        // Keep the old saturating-cast results where the conversion is
        // not possible: NaN -> 0, above the i64 range -> i64::MAX,
        // below it -> i64::MIN.
        None if r.is_nan() => 0,
        None if r < 0.0 => i64::MIN,
        None => i64::MAX,
    }
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
    let Some((mantissa, exp)) = sci.split_once('e') else {
        return format!("{x}");
    };
    let Ok(exp) = exp.parse::<i32>() else {
        return format!("{x}");
    };
    if (-4..6).contains(&exp) {
        let decimals = usize::try_from(5 - exp).unwrap_or(0);
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

/// Python 3.12's `sum()` over floats: Neumaier's compensated summation
/// (CPython's builtin_sum), not plain left-to-right addition.
pub fn py_sum(values: impl IntoIterator<Item = f64>) -> f64 {
    let mut total = 0.0_f64;
    let mut c = 0.0_f64;
    for x in values {
        let t = total + x;
        if total.abs() >= x.abs() {
            c += (total - t) + x;
        } else {
            c += (x - t) + total;
        }
        total = t;
    }
    if c != 0.0 && c.is_finite() {
        total += c;
    }
    total
}

/// Python 3.12's `math.hypot(x, y)`: CPython's `vector_norm` (exact scaling,
/// fused multiply-add squaring, one correction step). `f64::hypot` (the C
/// library's) differs from it by one ulp in about 0.6 % of the cases.
pub fn py_hypot(x: f64, y: f64) -> f64 {
    let (ax, ay) = (x.abs(), y.abs());
    if ax.is_infinite() || ay.is_infinite() {
        return f64::INFINITY;
    }
    if ax.is_nan() || ay.is_nan() {
        return f64::NAN;
    }
    let max = ax.max(ay);
    if max == 0.0 {
        return 0.0;
    }
    if max < f64::MIN_POSITIVE {
        return x.hypot(y); // subnormal: never happens for radar distances
    }
    // frexp: max = m * 2^e with 0.5 <= m < 1
    let max_e = ((max.to_bits() >> 52) & 0x7ff) as i32 - 1022;
    let scale = f64::powi(2.0, -max_e);
    let mut csum = 1.0_f64;
    let (mut frac1, mut frac2) = (0.0_f64, 0.0_f64);
    for v in [ax, ay] {
        let v = v * scale;
        let (hi, lo) = dl_mul(v, v);
        let (s_hi, s_lo) = dl_fast_sum(csum, hi);
        csum = s_hi;
        frac1 += lo;
        frac2 += s_lo;
    }
    let mut h = (csum - 1.0 + (frac1 + frac2)).sqrt();
    let (hi, lo) = dl_mul(-h, h);
    let (s_hi, s_lo) = dl_fast_sum(csum, hi);
    csum = s_hi;
    frac1 += lo;
    frac2 += s_lo;
    let x = csum - 1.0 + (frac1 + frac2);
    h += x / (2.0 * h);
    h / scale
}

fn dl_mul(x: f64, y: f64) -> (f64, f64) {
    let z = x * y;
    (z, x.mul_add(y, -z))
}

fn dl_fast_sum(a: f64, b: f64) -> (f64, f64) {
    let x = a + b;
    let z = x - a;
    (x, b - z)
}

#[cfg(test)]
mod tests;
