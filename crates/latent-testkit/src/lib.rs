//! Conformance harness, invariant probes, and deterministic test utilities.
//!
//! Use `default-features = false` for clocks and coordination without the node harness.
//! Upstream crates use `latent-core/test-support` directly to keep the workspace acyclic.
//! Process helpers likewise come from the neutral `latent-test-process` crate.

#![forbid(unsafe_code)]

pub mod async_runtime;
#[cfg(feature = "runtime")]
pub mod conformance;
#[cfg(feature = "runtime")]
pub mod harness;
#[cfg(feature = "runtime")]
mod runtime_contract;

pub use latent_core::test_support::{clocks, coordination, deterministic};
pub use latent_test_process::{process, resources};

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
