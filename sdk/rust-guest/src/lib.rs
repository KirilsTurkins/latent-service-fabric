//! Typed guest capabilities for the current LSF Component Model host profile.
//!
//! These APIs exist on wasm32. They do not implement an external client or
//! install providers, grants, an executor, retry policy or ambient WASI access.
//! Application WIT imports and deployment policy must authorize each operation.
#![cfg(target_arch = "wasm32")]
#![forbid(unsafe_code)]

// The explicit compiler profile links the fixed std PAL bridge. No application
// callback is registered and no import declaration becomes a provider/grant.
#[cfg(feature = "standard-logging")]
extern crate latent_standard_stdio as _;

pub mod bindings;
pub mod blob;
pub mod http;
#[cfg(feature = "transaction")]
pub mod intents;
pub mod secrets;
#[cfg(feature = "transaction")]
pub mod state;
pub mod streaming;

/// Authoritative context, logging and clocks, without ambient process state.
pub use bindings::{context, log, monotonic, wall};
/// Exact typed random, metric, event and service operations. No retry is added.
pub use bindings::{events, metrics, random, service};
