//! The hourly observation backfill: it fills `observed_mm` in
//! `forecast_history` from DWD observations (the last 48 h of Bright Sky
//! `/weather` records). Never runs on a page load; failures are logged and
//! swallowed, so `run_backfill` carries the errors and
//! `backfill_observations` the error and result logs.

use chrono::{DateTime, TimeDelta, Utc};

use crate::brightsky::{parse_hourly_observations, parse_station_info};
use crate::pyfmt::py_repr;
use crate::stations;
use crate::store::StoreError;
use crate::times::to_iso;
use crate::upstream::SourceError;

use super::Aggregator;

/// The error of `run_backfill`, carrying the message to log.
enum BackfillError {
    /// "observation backfill fetch failed: {err}"
    Fetch(SourceError),
    /// "observation backfill: writing observations failed: {err}"
    Write(StoreError),
}

impl BackfillError {
    fn message(&self) -> String {
        match self {
            Self::Fetch(err) => format!("observation backfill fetch failed: {err}"),
            Self::Write(err) => {
                format!("observation backfill: writing observations failed: {err}")
            }
        }
    }
}

impl Aggregator {
    /// Fetch the last 48 h of hourly records, write every real observation
    /// and record the stations it came from. The station is logged as soon
    /// as the payload parses (before the observations parse, as before);
    /// the result is the number of written observations, `None` when there
    /// are no records (so the stored station list stays untouched).
    async fn run_backfill(&self, now: DateTime<Utc>) -> Result<Option<usize>, BackfillError> {
        let payload = self
            .brightsky
            .fetch_weather_payload(now - TimeDelta::hours(48), now)
            .await
            .map_err(BackfillError::Fetch)?;
        let station = parse_station_info(&payload).map_err(BackfillError::Fetch)?;
        if let Some((name, distance)) = station {
            tracing::info!(
                "observation backfill: station {name} ({} m away)",
                py_repr(distance)
            );
        }
        let observations =
            parse_hourly_observations(&payload, now).map_err(BackfillError::Fetch)?;
        if observations.is_empty() {
            return Ok(None);
        }
        for (hour_start, mm) in &observations {
            self.store
                .set_observation(&to_iso(*hour_start), *mm)
                .map_err(BackfillError::Write)?;
        }
        // Remember which stations the observations came from; the value is
        // canonical JSON, byte-identical across backends.
        let station_list = stations::observation_stations(&payload, now);
        self.store
            .set_meta(
                stations::OBSERVATION_STATIONS_KEY,
                &stations::stations_to_json(&station_list),
            )
            .map_err(BackfillError::Write)?;
        Ok(Some(observations.len()))
    }

    /// Fill `observed_mm` in `forecast_history` from DWD observations:
    /// fetch the last 48 h of Bright Sky `/weather` hourly records and
    /// write each real observation (`observation_type != "forecast"`) for
    /// its hour start (`timestamp - 1h`). Never runs on a page load;
    /// failures are logged and swallowed.
    pub async fn backfill_observations(&self) {
        match self.run_backfill(self.now()).await {
            Err(err) => tracing::error!("{}", err.message()),
            Ok(Some(count)) => {
                tracing::info!("observation backfill: {count} hourly observations written");
            }
            Ok(None) => {
                tracing::info!("observation backfill: no observation records in the last 48 h");
            }
        }
    }
}
