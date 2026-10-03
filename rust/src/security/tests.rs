use super::*;

fn extra_hosts() -> HashSet<String> {
    ["pi.fritz.box"].into_iter().map(String::from).collect()
}

#[test]
fn host_allowed_accepted() {
    let extra = extra_hosts();
    for host in [
        "192.168.1.5:8000",
        "[::1]:8000",
        "::1",
        "localhost:8000",
        "raspberrypi.local:8000",
        "PI.FRITZ.BOX:8000",
        "fe80::1%eth0",
        "[fe80::1%eth0]:8000",
    ] {
        assert!(host_allowed(host, &extra), "{host} should be accepted");
    }
}

#[test]
fn host_allowed_rejected() {
    let extra = extra_hosts();
    for host in [
        "evil.example",
        "evil.example:8000",
        "testserver",
        "",
        "localhost.evil.com",
        "1.2.3.4.nip.io",
        "fe80::1%",
        "01.1.1.1",
    ] {
        assert!(!host_allowed(host, &extra), "{host} should be rejected");
    }
}

#[test]
fn parse_allowed_hosts_strips_and_lowercases() {
    let hosts = parse_allowed_hosts(" Pi.Fritz.Box , ,x ");
    assert_eq!(
        hosts,
        ["pi.fritz.box", "x"]
            .into_iter()
            .map(String::from)
            .collect::<HashSet<_>>()
    );
}

#[test]
fn parse_allowed_hosts_empty() {
    assert!(parse_allowed_hosts("").is_empty());
}
