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

#[test]
fn py_sum_reference_matches_python() {
    // Reference values produced by Python 3.12's builtin sum() for 3011
    // lists; `values` and `sum` are f64 bit patterns.
    let data: serde_json::Value =
        serde_json::from_str(include_str!("../../contract/fixtures/py_cases/sum.json")).unwrap();
    let cases = data["cases"].as_array().expect("fixture has a cases array");
    let mut mismatches = 0;
    let mut first: Vec<String> = Vec::new();
    for c in cases {
        let values: Vec<f64> = c["values"]
            .as_array()
            .expect("values is a list of bit patterns")
            .iter()
            .map(|bits| f64::from_bits(bits.as_u64().expect("bits is an unsigned integer")))
            .collect();
        let want = f64::from_bits(c["sum"].as_u64().expect("sum is a bit pattern"));
        let got = py_sum(values.iter().copied());
        if got.to_bits() != want.to_bits() {
            mismatches += 1;
            if first.len() < 5 {
                first.push(format!("values={values:?} got={got:?} want={want:?}"));
            }
        }
    }
    assert_eq!(mismatches, 0, "first mismatches: {first:?}");
}

#[test]
fn py_hypot_reference_matches_python() {
    // Reference values produced by Python 3.12's math.hypot for 4006 pairs;
    // `dx`, `dy` and `hypot` are f64 bit patterns.
    let data: serde_json::Value =
        serde_json::from_str(include_str!("../../contract/fixtures/py_cases/hypot.json")).unwrap();
    let cases = data["cases"].as_array().expect("fixture has a cases array");
    let mut mismatches = 0;
    let mut first: Vec<String> = Vec::new();
    for c in cases {
        let dx = f64::from_bits(c["dx"].as_u64().expect("dx is a bit pattern"));
        let dy = f64::from_bits(c["dy"].as_u64().expect("dy is a bit pattern"));
        let want = f64::from_bits(c["hypot"].as_u64().expect("hypot is a bit pattern"));
        let got = py_hypot(dx, dy);
        if got.to_bits() != want.to_bits() {
            mismatches += 1;
            if first.len() < 5 {
                first.push(format!("dx={dx:?} dy={dy:?} got={got:?} want={want:?}"));
            }
        }
    }
    assert_eq!(mismatches, 0, "first mismatches: {first:?}");
}

#[test]
fn py_sum_01_02_03_is_exactly_06() {
    // Python's sum([0.1, 0.2, 0.3]) is exactly 0.6; plain addition gives
    // 0.6000000000000001.
    assert_eq!(py_sum([0.1, 0.2, 0.3]), 0.6);
}

#[test]
fn py_sum_empty_is_zero() {
    assert_eq!(py_sum([]), 0.0);
}

#[test]
fn py_hypot_3_4_is_5() {
    assert_eq!(py_hypot(3.0, 4.0), 5.0);
}

#[test]
fn f64_to_i64() {
    assert_eq!(super::f64_to_i64(2.9), Some(2));
    assert_eq!(super::f64_to_i64(-2.9), Some(-2));
    assert_eq!(super::f64_to_i64(f64::NAN), None);
    assert_eq!(super::f64_to_i64(9.3e18), None);
    assert_eq!(
        super::f64_to_i64(-9_223_372_036_854_775_808.0),
        Some(i64::MIN)
    );
}
