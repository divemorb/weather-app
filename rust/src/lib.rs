//! Weather app backend (axum): configuration, upstream clients, the SQLite
//! cache, and the JSON API the page talks to.

mod accuracy;
mod aggregator;
mod brightsky;
mod clients;
mod config;
mod geocode;
mod location;
mod models;
mod openmeteo;
mod probability;
mod pyfmt;
mod radar;
mod reports;
mod routes;
mod scheduler;
mod security;
mod serializers;
mod series;
mod snapshot;
mod static_files;
mod stations;
mod store;
mod times;
mod upstream;

#[cfg(test)]
mod testutil;

pub use aggregator::Aggregator;
pub use clients::{BrightSkyClient, OpenMeteoClient};
pub use config::{AppConfig, load_config};
pub use geocode::Geocoder;
pub use location::resolve_startup_location;
pub use routes::{AppState, build_router};
pub use scheduler::{Scheduler, initial_refresh};
pub use security::parse_allowed_hosts;
pub use snapshot::{report as snapshot_report, snapshot};
pub use static_files::load as load_static;
pub use store::Store;
pub use times::{Clock, to_iso};
pub use upstream::http_client;
