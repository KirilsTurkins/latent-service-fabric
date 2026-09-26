//! Typed guest capabilities for the current LSF Component Model host profile.
//!
//! These APIs exist on wasm32. They do not implement an external client or
//! install providers, grants, an executor, retry policy or ambient WASI access.
//! Application WIT imports and deployment policy must authorize each operation.
#![cfg(target_arch = "wasm32")]
#![forbid(unsafe_code)]

pub mod bindings;
pub mod blob;
pub mod http;
pub mod secrets;
pub mod streaming;

/// Authoritative context, logging and clocks, without ambient process state.
pub use bindings::{context, log, monotonic, wall};
/// Exact typed random, metric, event and service operations. No retry is added.
pub use bindings::{events, metrics, random, service};
