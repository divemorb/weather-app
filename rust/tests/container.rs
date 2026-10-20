//! The container settings (REQ_SEC_7): both compose files keep the
//! hardened `weather` service, and the Dockerfile ends as a non-root user.

use serde_json::Value;

/// Hardening problems of the `weather` service in a compose text: one
/// string per finding, or one if the text does not parse or has no
/// `services.weather`.
#[cfg(test)]
fn compose_problems(text: &str) -> Vec<String> {
    let Ok(doc) = serde_saphyr::from_str::<Value>(text) else {
        return vec!["does not parse as YAML".to_string()];
    };
    let Some(weather) = doc["services"]["weather"].as_object() else {
        return vec!["no services.weather".to_string()];
    };
    let mut problems: Vec<String> = Vec::new();
    if weather
        .get("read_only")
        .is_none_or(|v| v.as_bool() != Some(true))
    {
        problems.push("read_only is not true".to_string());
    }
    let caps = weather.get("cap_drop").and_then(Value::as_array);
    if !caps.is_some_and(|c| c.len() == 1 && c[0].as_str() == Some("ALL")) {
        problems.push("cap_drop is not exactly [\"ALL\"]".to_string());
    }
    if !weather
        .get("pids_limit")
        .and_then(Value::as_i64)
        .is_some_and(|n| (1..=1000).contains(&n))
    {
        problems.push("pids_limit is missing, not an integer, or not in 1..=1000".to_string());
    }
    if !weather
        .get("security_opt")
        .and_then(Value::as_array)
        .is_some_and(|s| {
            s.iter()
                .any(|v| v.as_str() == Some("no-new-privileges:true"))
        })
    {
        problems.push("security_opt has no no-new-privileges:true".to_string());
    }
    for entry in weather
        .get("tmpfs")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        if !entry.as_str().is_some_and(|t| t.contains("noexec")) {
            problems.push(format!("tmpfs entry {entry} has no noexec"));
        }
    }
    problems
}

/// Dockerfile problems: one if the last `USER` after the last `FROM` is
/// missing or names the user `0` or `root`.
#[cfg(test)]
fn dockerfile_problems(text: &str) -> Vec<String> {
    let lines: Vec<&str> = text.lines().collect();
    let Some(from) = lines
        .iter()
        .rposition(|l| l.trim_start().starts_with("FROM"))
    else {
        return vec!["no FROM instruction".to_string()];
    };
    let Some(user) = lines[from + 1..]
        .iter()
        .rposition(|l| l.trim_start().starts_with("USER"))
        .map(|i| lines[from + 1 + i])
    else {
        return vec!["no USER after the last FROM".to_string()];
    };
    let rest = user.trim_start().trim_start_matches("USER").trim();
    let name = rest.split(':').next().unwrap_or_default();
    if name == "0" || name == "root" {
        vec![format!("runs as user {name}")]
    } else {
        Vec::new()
    }
}

#[test]
fn compose_files_are_hardened() {
    for path in [
        concat!(env!("CARGO_MANIFEST_DIR"), "/../docker-compose.yml"),
        concat!(env!("CARGO_MANIFEST_DIR"), "/docker-compose.yml"),
    ] {
        let text = std::fs::read_to_string(path).unwrap();
        let problems = compose_problems(&text);
        assert!(problems.is_empty(), "{path}: {problems:?}");
    }
}

#[test]
fn dockerfile_runs_as_non_root() {
    let text = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/Dockerfile")).unwrap();
    let problems = dockerfile_problems(&text);
    assert!(problems.is_empty(), "{problems:?}");
}

#[test]
fn weakened_compose_is_reported() {
    let text = std::fs::read_to_string(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../docker-compose.yml"
    ))
    .unwrap();
    let weakened = [
        (
            "read_only false",
            text.replace("read_only: true", "read_only: false"),
        ),
        (
            "cap drop NET_RAW",
            text.replace("      - ALL", "      - NET_RAW"),
        ),
        (
            "pids limit removed",
            text.replace("    pids_limit: 200\n", ""),
        ),
        (
            "no new privileges false",
            text.replace("no-new-privileges:true", "no-new-privileges:false"),
        ),
        ("tmpfs without noexec", text.replace("noexec,", "")),
    ];
    for (name, copy) in weakened {
        assert_ne!(copy, text, "{name}: the text did not change");
        let problems = compose_problems(&copy);
        assert_eq!(problems.len(), 1, "{name}: {problems:?}");
    }
}

#[test]
fn root_user_is_reported() {
    let text = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/Dockerfile")).unwrap();
    let weakened = [
        ("user 0", text.replace("USER 1000:1000", "USER 0:0")),
        ("user root", text.replace("USER 1000:1000", "USER root")),
        ("user removed", text.replace("USER 1000:1000\n", "")),
    ];
    for (name, copy) in weakened {
        assert_ne!(copy, text, "{name}: the text did not change");
        let problems = dockerfile_problems(&copy);
        assert_eq!(problems.len(), 1, "{name}: {problems:?}");
    }
}
