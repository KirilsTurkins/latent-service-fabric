//! Conformance harness, invariant probes, and deterministic test utilities.
//!
//! Use `default-features = false` for clocks and coordination without the node harness.

#![forbid(unsafe_code)]

pub mod async_runtime;
pub mod clocks;
#[cfg(feature = "runtime")]
pub mod conformance;
pub mod coordination;
pub mod deterministic;
#[cfg(feature = "runtime")]
pub mod harness;
pub mod process;
pub mod resources;
#[cfg(feature = "runtime")]
mod runtime_contract;

pub use async_runtime::AsyncTestRuntime;
pub use clocks::TestClock;
pub use deterministic::{block_on, DeterministicIds, ManualClock, TempWorkspace};
#[cfg(feature = "runtime")]
pub use harness::{
    BorrowedBackendHarness, ExpectedOutcome, IdleScalingMeasurement, InvocationCase,
    InvocationConformanceSuite, NodeHarness, ObservedInvariantProbe, ScopedNodeHarness,
};
pub use process::{CapturedProcess, ProcessHarness};
pub use resources::{CurrentProcessProbe, ProcessResources, ResourceProbe};
#[cfg(feature = "runtime")]
pub use runtime_contract::*;
