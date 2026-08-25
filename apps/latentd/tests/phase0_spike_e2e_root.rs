//! Lint boundary for the executable Phase 0 acceptance matrix.
//!
//! The ignored integration test intentionally keeps every required executable
//! outcome in one scenario. Its `verify-recovery` invocation proves recovery
//! through one retained runtime composition rather than separate processes.

#![forbid(unsafe_code)]
#![allow(
    clippy::format_collect,
    clippy::needless_pass_by_value,
    clippy::too_many_lines
)]

#[path = "phase0_spike_e2e.rs"]
mod cases;
