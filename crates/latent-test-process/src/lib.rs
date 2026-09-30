//! Bounded test process ownership and identity-bound resource observations.
//!
//! Upstream storage and runtime foundations use this crate directly. It has no
//! dependency on a workspace runtime, provider, or node harness. Resources exist
//! only after an explicit spawn, capture, or probe binding.

#![forbid(unsafe_code)]

pub mod process;
pub mod resources;

pub use process::{CapturedProcess, OwnedProcess, ProcessHarness, ProcessLimits};
pub use resources::{CurrentProcessProbe, ProcessResources, ResourceProbe};
