use super::*;
use std::collections::HashMap;

/// The shared YAML config fixture.
fn base_yaml() -> String {
    [
        "location:",
        "  latitude: 52.0",
        "  longitude: 13.0",
        "  timezone: Europe/Berlin",
        "probability:",
        "  weights:",
        "    radar: 0.5",
        "    models: 0.3",
        "    ensemble: 0.2",
        "  model_rain_threshold_mm: 0.1",
        "  radar_cell_rain_threshold_mm: 0.05",
        "models:",
        "  forecast:",
        "    - icon_d2",
        "    - icon_eu",
        "  ensemble_model: ecmwf_ifs025",
        "scheduling:",
        "  radar_interval_minutes: 5",
        "  models_interval_minutes: 60",
        "  stale_after_minutes:",
        "    radar: 10",
        "    models: 120",
    ]
    .join("\n")
        + "\n"
}

/// The environment lookup over the given pairs.
pub(super) fn env_lookup(pairs: &[(&str, &str)]) -> HashMap<String, String> {
    pairs
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

/// The config from the file at `path` (None: no file) and the environment `env`.
pub(super) fn load(
    path: Option<&Path>,
    env: &HashMap<String, String>,
) -> Result<AppConfig, String> {
    load_config(path, &|k| env.get(k).cloned())
}

/// Writes `yaml` as `weather.yaml` into `dir`; its path.
pub(super) fn make_config(dir: &Path, yaml: &str) -> PathBuf {
    let path = dir.join("weather.yaml");
    std::fs::write(&path, yaml).unwrap();
    path
}

#[test]
fn defaults_from_yaml() {
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(dir.path(), &base_yaml());
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    let loc = cfg.location.as_ref().unwrap();
    assert_eq!(loc.latitude, 52.0);
    assert_eq!(loc.longitude, 13.0);
    assert_eq!(loc.timezone, "Europe/Berlin");
    assert_eq!(cfg.probability.weight_radar, 0.5);
    assert_eq!(
        cfg.models.forecast,
        vec!["icon_d2".to_string(), "icon_eu".to_string()]
    );
    assert_eq!(cfg.models.ensemble_model, "ecmwf_ifs025");
    assert_eq!(cfg.scheduling.radar_interval_minutes, 5);
    assert_eq!(cfg.scheduling.models_interval_minutes, 60);
}

#[test]
fn missing_file_uses_builtin_defaults() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("does_not_exist.yaml");
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    // Builtin defaults so the app still boots without a config file.
    assert!(0.0 < cfg.probability.weight_radar && cfg.probability.weight_radar < 1.0);
    assert_eq!(cfg.radar.radius_km, 5.0);
}

#[test]
fn removed_radar_keys_still_load() {
    // An old config with the removed `step_minutes` key must still load:
    // the parser ignores keys it does not read.
    let dir = tempfile::tempdir().unwrap();
    let yaml = base_yaml() + "radar:\n  step_minutes: 5\n";
    let path = make_config(dir.path(), &yaml);
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    assert_eq!(cfg.radar.radius_km, 5.0);
    assert_eq!(cfg.radar.grid_size_km, 1.0);
}

#[test]
fn env_overrides_yaml() {
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(dir.path(), &base_yaml());
    let env = env_lookup(&[
        ("LATITUDE", "52.52"),
        ("LONGITUDE", "13.40"),
        ("RADAR_RADIUS_KM", "3"),
        ("WEIGHT_RADAR", "0.7"),
        ("RADAR_INTERVAL_MINUTES", "10"),
    ]);
    let cfg = load(Some(&path), &env).unwrap();
    let loc = cfg.location.as_ref().unwrap();
    assert_eq!(loc.latitude, 52.52);
    assert_eq!(loc.longitude, 13.40);
    assert_eq!(cfg.radar.radius_km, 3.0);
    assert_eq!(cfg.probability.weight_radar, 0.7);
    assert_eq!(cfg.scheduling.radar_interval_minutes, 10);
}

#[test]
fn accuracy_defaults() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("does_not_exist.yaml");
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    // Builtin defaults so the app still boots without a config file.
    assert_eq!(cfg.accuracy.window_days, 30);
    assert_eq!(cfg.accuracy.min_samples, 48);
}

#[test]
fn accuracy_from_yaml() {
    let dir = tempfile::tempdir().unwrap();
    let yaml = format!(
        "accuracy:\n  window_days: 14\n  min_samples: 24\n{}",
        base_yaml()
    );
    let path = make_config(dir.path(), &yaml);
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    assert_eq!(cfg.accuracy.window_days, 14);
    assert_eq!(cfg.accuracy.min_samples, 24);
}

#[test]
fn weight_normalization_with_radar() {
    // The default path (/app/weather.yaml) may be absent, so the builtin
    // defaults apply — the assertions hold either way.
    let cfg = load(None, &env_lookup(&[])).unwrap();
    let w = cfg.probability.weights(true).unwrap();
    assert!((w.iter().map(|(_, v)| *v).sum::<f64>() - 1.0).abs() < 1e-9);
    let names: Vec<&str> = w.iter().map(|(k, _)| *k).collect();
    assert_eq!(names, vec!["radar", "models", "ensemble"]);
}

#[test]
fn weight_fallback_without_radar() {
    let cfg = load(None, &env_lookup(&[])).unwrap();
    let w = cfg.probability.weights(false).unwrap();
    assert!(!w.iter().any(|(k, _)| *k == "radar"));
    assert!((w.iter().map(|(_, v)| *v).sum::<f64>() - 1.0).abs() < 1e-9);
    // models:ensemble ratio must be preserved (0.3 : 0.2 -> 0.6 : 0.4)
    let models = w.iter().find(|(k, _)| *k == "models").unwrap().1;
    let ensemble = w.iter().find(|(k, _)| *k == "ensemble").unwrap().1;
    assert!((models - 0.6).abs() < 1e-9);
    assert!((ensemble - 0.4).abs() < 1e-9);
}

#[test]
fn env_bool_false_values() {
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(dir.path(), "{}\n");
    for (value, expected) in [("0", false), ("no", false), ("TRUE", true)] {
        let env = env_lookup(&[("USE_ACCURACY_WEIGHTS", value)]);
        let cfg = load(Some(&path), &env).unwrap();
        assert_eq!(cfg.use_accuracy_weights, expected, "{value}");
    }
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    assert!(!cfg.use_accuracy_weights);
}

#[test]
fn yaml_numbers_as_strings_and_bools() {
    let dir = tempfile::tempdir().unwrap();
    let yaml = [
        "radar:",
        "  radius_km: '7.5'",
        "  grid_size_km: true",
        "scheduling:",
        "  radar_interval_minutes: '7'",
        "  models_interval_minutes: true",
    ]
    .join("\n")
        + "\n";
    let path = make_config(dir.path(), &yaml);
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    assert_eq!(cfg.radar.radius_km, 7.5);
    assert_eq!(cfg.radar.grid_size_km, 1.0);
    assert_eq!(cfg.scheduling.radar_interval_minutes, 7);
    assert_eq!(cfg.scheduling.models_interval_minutes, 1);
}

#[test]
fn yaml_subsections_are_read() {
    // The subsections override the defaults (0.5 / 0.3 / 0.2 and 10 / 120),
    // so a parser that ignores them would fail these assertions.
    let dir = tempfile::tempdir().unwrap();
    let yaml = [
        "probability:",
        "  weights:",
        "    radar: 0.6",
        "    models: 0.3",
        "    ensemble: 0.1",
        "scheduling:",
        "  stale_after_minutes:",
        "    radar: 7",
        "    models: 90",
    ]
    .join("\n")
        + "\n";
    let path = make_config(dir.path(), &yaml);
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    assert_eq!(cfg.probability.weight_radar, 0.6);
    assert_eq!(cfg.probability.weight_models, 0.3);
    assert_eq!(cfg.probability.weight_ensemble, 0.1);
    assert_eq!(cfg.scheduling.stale_radar_minutes, 7);
    assert_eq!(cfg.scheduling.stale_models_minutes, 90);
}

#[test]
fn falsy_yaml_documents_load_defaults() {
    // Every falsy document (null, false, 0, 0.0, "", []) loads as `{}`,
    // i.e. all builtin defaults.
    let dir = tempfile::tempdir().unwrap();
    for doc in [
        "false",
        "0",
        "0.0",
        "[]",
        "\"\"",
        "{}",
        "",
        "# just a comment\n",
    ] {
        let path = make_config(dir.path(), doc);
        let cfg = load(Some(&path), &env_lookup(&[]))
            .unwrap_or_else(|err| panic!("falsy document {doc:?} should load: {err}"));
        assert!(cfg.location.is_none(), "{doc:?}");
        assert_eq!(cfg.radar, RadarConfig::default(), "{doc:?}");
        assert_eq!(cfg.probability, ProbabilityConfig::default(), "{doc:?}");
        // `load_config` takes `forecast` from the YAML (`()` when absent),
        // not from the dataclass default.
        assert!(cfg.models.forecast.is_empty(), "{doc:?}");
        assert_eq!(cfg.models.ensemble_model, "ecmwf_ifs025", "{doc:?}");
        assert_eq!(cfg.scheduling, SchedulingConfig::default(), "{doc:?}");
        assert_eq!(cfg.accuracy, AccuracyConfig::default(), "{doc:?}");
        assert_eq!(cfg.api, ApiConfig::default(), "{doc:?}");
    }
}

#[test]
fn non_falsy_non_mapping_yaml_is_an_error() {
    // A non-empty list, a non-empty string or `true` is a truthy
    // non-mapping: rejected.
    let dir = tempfile::tempdir().unwrap();
    for doc in ["[1]", "\"text\"", "true"] {
        let path = make_config(dir.path(), doc);
        let err = load(Some(&path), &env_lookup(&[])).unwrap_err();
        assert!(err.contains("must contain a mapping"), "{doc:?}: {err}");
    }
}

#[test]
fn env_f64_error_has_plain_digits_hint() {
    // `1_000` is rejected on purpose (no underscores).
    let env = env_lookup(&[("RADAR_RADIUS_KM", "1_000")]);
    let err = values::env_f64(&|k| env.get(k).cloned(), "RADAR_RADIUS_KM", 5.0).unwrap_err();
    assert_eq!(
        err,
        "RADAR_RADIUS_KM: not a number: \"1_000\" (write plain digits, e.g. 10 or 0.5)"
    );
}

#[test]
fn env_i64_error_has_plain_digits_hint() {
    let env = env_lookup(&[("RADAR_INTERVAL_MINUTES", "1.5")]);
    let err = values::env_i64(&|k| env.get(k).cloned(), "RADAR_INTERVAL_MINUTES", 5).unwrap_err();
    assert_eq!(
        err,
        "RADAR_INTERVAL_MINUTES: not an integer: \"1.5\" (write plain digits, e.g. 10)"
    );
}

#[test]
fn weights_01_02_03_normalized_by_py_sum() {
    let prob = ProbabilityConfig {
        weight_radar: 0.1,
        weight_models: 0.2,
        weight_ensemble: 0.3,
        model_rain_threshold_mm: 0.1,
        radar_cell_rain_threshold_mm: 0.05,
    };
    let w = prob.weights(true).unwrap();
    // py_sum's compensated addition gives exactly 0.6 for 0.1 + 0.2 + 0.3,
    // so the normalized weights are exactly 0.1 / 0.6 etc.; plain addition
    // would give a total of 0.6000000000000001 and different bits.
    assert_eq!(w.len(), 3);
    assert_eq!(w[0], ("radar", 0.1 / 0.6));
    assert_eq!(w[1], ("models", 0.2 / 0.6));
    assert_eq!(w[2], ("ensemble", 0.3 / 0.6));
}

#[test]
fn config_defaults_match_python_dataclasses() {
    assert_eq!(
        RadarConfig::default(),
        RadarConfig {
            radius_km: 5.0,
            grid_size_km: 1.0,
        }
    );
    assert_eq!(
        ProbabilityConfig::default(),
        ProbabilityConfig {
            weight_radar: 0.5,
            weight_models: 0.3,
            weight_ensemble: 0.2,
            model_rain_threshold_mm: 0.1,
            radar_cell_rain_threshold_mm: 0.05,
        }
    );
    assert_eq!(
        ModelsConfig::default(),
        ModelsConfig {
            forecast: vec![
                "icon_d2".to_string(),
                "icon_eu".to_string(),
                "ecmwf_ifs025".to_string(),
                "gfs_seamless".to_string(),
                "arome_france".to_string(),
                "ukmo_seamless".to_string(),
            ],
            ensemble_model: "ecmwf_ifs025".to_string(),
        }
    );
    assert_eq!(
        SchedulingConfig::default(),
        SchedulingConfig {
            radar_interval_minutes: 5,
            models_interval_minutes: 60,
            stale_radar_minutes: 10,
            stale_models_minutes: 120,
        }
    );
    assert_eq!(
        AccuracyConfig::default(),
        AccuracyConfig {
            window_days: 30,
            min_samples: 48,
        }
    );
    assert_eq!(
        ApiConfig::default(),
        ApiConfig {
            brightsky_base_url: "https://api.brightsky.dev".to_string(),
            open_meteo_base_url: "https://api.open-meteo.com/v1".to_string(),
            ensemble_base_url: "https://ensemble-api.open-meteo.com/v1".to_string(),
            nominatim_base_url: "https://nominatim.openstreetmap.org".to_string(),
            timeout_seconds: 20.0,
        }
    );
}
