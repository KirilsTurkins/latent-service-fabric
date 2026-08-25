//! Lint boundary for the executable Phase 0 acceptance matrix.
//!
//! The ignored integration test intentionally keeps every required executable
//! outcome in one scenario so post-failure recovery is demonstrated in order.

#![forbid(unsafe_code)]
#![allow(
    clippy::format_collect,
    clippy::needless_pass_by_value,
    clippy::too_many_lines,
)]

#[path = "phase0_spike_e2e.rs"]
mod cases;
