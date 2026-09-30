use super::*;
use std::collections::HashMap;

/// The `base_data` fixture from tests/test_config.py, as YAML text.
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

fn env_lookup(pairs: &[(&str, &str)]) -> HashMap<String, String> {
    pairs
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

fn load(path: Option<&Path>, env: &HashMap<String, String>) -> Result<AppConfig, String> {
    load_config(path, &|k| env.get(k).cloned())
}

/// The `make_config` fixture: write a YAML config into a temp dir.
fn make_config(dir: &Path, yaml: &str) -> PathBuf {
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
    // Python reads the deployment's weather.yaml here; the default path
    // (/app/weather.yaml) is absent in the sandbox, so the builtin defaults
    // apply — the assertions hold either way.
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

// ---------------------------------------------------------------------------
// location is optional (step 8b: the app runs unconfigured)
// ---------------------------------------------------------------------------

#[test]
fn no_location_in_yaml_and_no_env_is_unconfigured() {
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(dir.path(), "{}\n");
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    assert!(cfg.location.is_none());
}

#[test]
fn yaml_location_needs_both_coordinates() {
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(dir.path(), "location:\n  latitude: 52.0\n");
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    assert!(cfg.location.is_none());
}

#[test]
fn partial_env_falls_back_to_yaml() {
    // env only counts when BOTH vars are set (they are one source); with
    // only LATITUDE the YAML block is the source (no mixing of coordinates)
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(
        dir.path(),
        "location:\n  latitude: 52.0\n  longitude: 13.0\n",
    );
    let env = env_lookup(&[("LATITUDE", "52.52")]);
    let cfg = load(Some(&path), &env).unwrap();
    let loc = cfg.location.as_ref().unwrap();
    assert_eq!(loc.latitude, 52.0);
}

#[test]
fn yaml_location_defaults_timezone() {
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(
        dir.path(),
        "location:\n  latitude: 52.0\n  longitude: 13.0\n",
    );
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    let loc = cfg.location.as_ref().unwrap();
    assert_eq!(loc.timezone, "Europe/Berlin");
}

#[test]
fn env_location_without_yaml() {
    // env vars are a source by themselves; the YAML block is not needed
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(dir.path(), "{}\n");
    let env = env_lookup(&[("LATITUDE", "52.52"), ("LONGITUDE", "13.40")]);
    let cfg = load(Some(&path), &env).unwrap();
    let loc = cfg.location.as_ref().unwrap();
    assert_eq!((loc.latitude, loc.longitude), (52.52, 13.40));
    assert_eq!(loc.timezone, "Europe/Berlin");
}
