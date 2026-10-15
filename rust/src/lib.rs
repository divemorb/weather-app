//! Weather app backend (axum): configuration, upstream clients, the SQLite
//! cache, and the JSON API the page talks to.

pub mod accuracy;
pub mod aggregator;
pub mod brightsky;
pub mod clients;
pub mod config;
pub mod geocode;
pub mod location;
pub mod models;
pub mod openmeteo;
pub mod probability;
pub mod pyfmt;
pub mod radar;
pub mod reports;
pub mod routes;
pub mod scheduler;
pub mod security;
pub mod serializers;
pub mod series;
pub mod snapshot;
pub mod static_files;
pub mod stations;
pub mod store;
pub mod times;
pub mod upstream;

#[cfg(test)]
pub mod testutil;
