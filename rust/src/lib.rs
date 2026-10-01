//! Rust port of the weather app backend (axum); the Python app is the spec.

pub mod accuracy;
pub mod brightsky;
pub mod config;
pub mod models;
pub mod openmeteo;
pub mod probability;
pub mod pyfmt;
pub mod radar;
pub mod routes;
pub mod security;
pub mod static_files;
pub mod times;
pub mod upstream;

#[cfg(test)]
pub mod testutil;
