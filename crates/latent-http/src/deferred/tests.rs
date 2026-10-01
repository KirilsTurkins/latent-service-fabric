//! Native protected-store/captured-intent/real-TLS conformance schedules.
//! The remote store is a bounded test endpoint, never a production backend.
mod campaign;
mod endpoint;
mod fixture;
mod locks;
mod proxy;

use latent_effects::dispatch::Disposition;
use std::sync::atomic::Ordering;
use std::time::Instant;
