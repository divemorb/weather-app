use super::*;

#[test]
fn reference_cases_match_python() {
    // Reference values produced by Python 3.14's round/format for 3036 inputs.
    let data: serde_json::Value =
        serde_json::from_str(include_str!("../../contract/fixtures/pyfmt_cases.json")).unwrap();
    let cases = data["cases"].as_array().expect("fixture has a cases array");
    let mut mismatches = 0;
    let mut first: Vec<String> = Vec::new();
    let note = |first: &mut Vec<String>, what: &str, x: f64, got: String, want: String| {
        if first.len() < 5 {
            first.push(format!("{what} x={x:?} got={got:?} want={want:?}"));
        }
    };
    for c in cases {
        let x = f64::from_bits(c["bits"].as_u64().expect("bits is an unsigned integer"));

        let want = c["r1"].as_f64().expect("r1 is a number");
        let got = py_round(x, 1);
        if got.to_bits() != want.to_bits() {
            mismatches += 1;
            note(&mut first, "r1", x, format!("{got:?}"), format!("{want:?}"));
        }
        let want = c["r2"].as_f64().expect("r2 is a number");
        let got = py_round(x, 2);
        if got.to_bits() != want.to_bits() {
            mismatches += 1;
            note(&mut first, "r2", x, format!("{got:?}"), format!("{want:?}"));
        }
        let want = c["r3"].as_f64().expect("r3 is a number");
        let got = py_round(x, 3);
        if got.to_bits() != want.to_bits() {
            mismatches += 1;
            note(&mut first, "r3", x, format!("{got:?}"), format!("{want:?}"));
        }

        if !c["r0"].is_null() {
            let want = c["r0"].as_i64().expect("r0 is an integer");
            let got = py_round_int(x);
            if got != want {
                mismatches += 1;
                note(&mut first, "r0", x, got.to_string(), want.to_string());
            }
        }
        if !c["f0"].is_null() {
            let want = c["f0"].as_str().expect("f0 is a string");
            let got = py_fmt_0f(x);
            if got != want {
                mismatches += 1;
                note(&mut first, "f0", x, got.to_string(), want.to_string());
            }
        }
        let want = c["g"].as_str().expect("g is a string");
        let got = py_fmt_g(x);
        if got != want {
            mismatches += 1;
            note(&mut first, "g", x, got.to_string(), want.to_string());
        }
    }
    assert_eq!(mismatches, 0, "first mismatches: {first:?}");
}

#[test]
fn py_round_2675_two_digits() {
    assert_eq!(py_round(2.675, 2), 2.67);
}

#[test]
fn py_round_0125_two_digits() {
    assert_eq!(py_round(0.125, 2), 0.12);
}

#[test]
fn py_round_int_25_halves_even() {
    assert_eq!(py_round_int(2.5), 2);
}

#[test]
fn py_round_int_35_halves_even() {
    assert_eq!(py_round_int(3.5), 4);
}

#[test]
fn py_fmt_g_tenth() {
    assert_eq!(py_fmt_g(0.1), "0.1");
}

#[test]
fn py_fmt_g_scientific_small() {
    assert_eq!(py_fmt_g(1e-5), "1e-05");
}

#[test]
fn py_fmt_g_scientific_large() {
    assert_eq!(py_fmt_g(1234567.0), "1.23457e+06");
}

#[test]
fn py_fmt_0f_rounds_to_35() {
    assert_eq!(py_fmt_0f(34.69387755102041), "35");
}

#[test]
fn py_fmt_0f_125_halves_even() {
    assert_eq!(py_fmt_0f(12.5), "12");
}
