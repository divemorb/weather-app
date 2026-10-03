use std::sync::Arc;
use std::time::Duration;

use chrono::TimeDelta;
use serde_json::json;

use super::*;
use crate::aggregator::testkit::{self, *};
use crate::store::Source;

#[tokio::test]
async fn scheduled_jobs_run_refreshes_on_event_loop() {
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let agg = Arc::new(make_aggregator(
        make_cfg(&fake, CfgOpts::default()),
        memory_store(),
    ));
    let scheduler = Arc::new(Scheduler::new());
    scheduler.start_with_periods(
        agg.clone(),
        Duration::from_millis(50),
        Duration::from_millis(50),
    );
    for _ in 0..100 {
        let bs = !fake.requests_to("/bs/current_weather").is_empty();
        let om = !fake.requests_to("/om/v1/forecast").is_empty();
        if bs && om {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert!(
        !fake.requests_to("/bs/current_weather").is_empty(),
        "the radar job ran a refresh"
    );
    assert!(
        !fake.requests_to("/om/v1/forecast").is_empty(),
        "the models job ran a refresh"
    );
}

#[tokio::test]
async fn schedule_status_reports_next_runs() {
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let cfg = make_cfg(&fake, CfgOpts::default());
    let agg = Arc::new(make_aggregator(cfg.clone(), memory_store()));
    let scheduler = Arc::new(Scheduler::new());
    scheduler.start(agg.clone());
    let status = schedule_status(Some(&scheduler), &cfg, agg.now());
    let radar = &status["jobs"]["radar"];
    let models = &status["jobs"]["models"];
    assert_eq!(radar["sources"], json!(["radar", "current"]));
    assert_eq!(models["sources"], json!(["forecast", "ensemble"]));
    assert_eq!(
        radar["interval_minutes"],
        json!(cfg.scheduling.radar_interval_minutes)
    );
    assert_eq!(
        models["interval_minutes"],
        json!(cfg.scheduling.models_interval_minutes)
    );
    // first run is one interval after start (the test clock is fixed)
    let now = agg.now();
    assert_eq!(
        radar["next_run_utc"],
        json!(to_iso(
            now + TimeDelta::minutes(cfg.scheduling.radar_interval_minutes)
        ))
    );
    assert_eq!(
        models["next_run_utc"],
        json!(to_iso(
            now + TimeDelta::minutes(cfg.scheduling.models_interval_minutes)
        ))
    );
}

#[test]
fn schedule_status_without_running_scheduler() {
    let fake = FakeUpstream::start();
    let cfg = make_cfg(&fake, CfgOpts::default());
    // not started: the jobs have no next run time yet
    let scheduler = Scheduler::new();
    let status = schedule_status(Some(&scheduler), &cfg, testkit::now());
    assert_eq!(status["jobs"]["radar"]["next_run_utc"], json!(null));
    // no scheduler at all (e.g. API tests without the lifespan)
    let status = schedule_status(None, &cfg, testkit::now());
    assert_eq!(status["jobs"]["models"]["next_run_utc"], json!(null));
}

// A failed models refresh is retried after the radar interval, not an hour later.
async fn failing_models() -> (FakeUpstream, Payloads, Arc<Aggregator>, Arc<Scheduler>) {
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[Source::Forecast]);
    let agg = Arc::new(make_aggregator(
        make_cfg(&fake, CfgOpts::default()),
        memory_store(),
    ));
    agg.refresh_models().await;
    let scheduler = Arc::new(Scheduler::new());
    scheduler.start(agg.clone());
    (fake, payloads, agg, scheduler)
}

#[tokio::test]
async fn failed_models_refresh_is_retried_after_the_radar_interval() {
    let (_fake, _payloads, agg, scheduler) = failing_models().await;
    assert!(agg.models_failed());
    scheduler.schedule_models_retry(&agg);
    let minutes = agg.cfg().scheduling.radar_interval_minutes;
    assert_eq!(
        scheduler.next_run(Job::Models),
        Some(agg.now() + TimeDelta::minutes(minutes))
    );
}

#[tokio::test]
async fn no_retry_after_a_good_refresh_or_when_the_regular_run_is_sooner() {
    let (fake, payloads, agg, scheduler) = failing_models().await;
    let regular = agg.now() + TimeDelta::minutes(1);
    scheduler.set_next_run(Job::Models, regular);
    scheduler.schedule_models_retry(&agg);
    assert_eq!(scheduler.next_run(Job::Models), Some(regular));
    serve(&fake, &payloads, &[]);
    agg.refresh_models().await;
    assert!(!agg.models_failed());
    scheduler.set_next_run(Job::Models, agg.now() + TimeDelta::minutes(60));
    scheduler.schedule_models_retry(&agg);
    assert_eq!(
        scheduler.next_run(Job::Models),
        Some(agg.now() + TimeDelta::minutes(60))
    );
}

#[tokio::test]
async fn retry_repeats_while_failing_and_stops_after_success() {
    let (fake, payloads, agg, scheduler) = failing_models().await;
    let before = fake.requests_to("/om/v1/forecast").len();
    scheduler.schedule_models_retry_after(&agg, Duration::from_millis(30));
    tokio::time::sleep(Duration::from_millis(200)).await;
    assert!(
        fake.requests_to("/om/v1/forecast").len() > before + 1,
        "the retry ran and, still failing, ran again"
    );
    serve(&fake, &payloads, &[]);
    for _ in 0..50 {
        if !agg.models_failed() {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    tokio::time::sleep(Duration::from_millis(50)).await;
    assert!(!agg.models_failed());
    assert_eq!(
        scheduler.next_run(Job::Models),
        Some(agg.now() + TimeDelta::minutes(agg.cfg().scheduling.models_interval_minutes)),
        "back to the regular run"
    );
}
