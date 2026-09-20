//! Neutral test-only clocks, identities and owner-lifetime coordination.
//!
//! Enable `latent-core/test-support` only for test infrastructure. Implementations
//! use only the standard library and never depend on node/runtime harnesses.
//! `latent-testkit` re-exports these same modules for existing harness callers.

#![deny(clippy::all, clippy::pedantic)]

pub mod clocks;
pub mod coordination;
pub mod deterministic;

pub use clocks::TestClock;
pub use deterministic::{block_on, DeterministicIds, ManualClock, TempWorkspace};
