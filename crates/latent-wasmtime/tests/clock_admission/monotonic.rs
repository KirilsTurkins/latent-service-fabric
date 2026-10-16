//! Ordinary Instant compiled against the authenticated maintained std overlay.
//! This fixture selects the actual monotonic provider with its own exact grant.
#![cfg(target_os = "linux")]
#[path = "../broker/component.rs"]
#[allow(dead_code)]
mod clock_component;
mod component {
    pub const CAP: &str = "latent:clock/monotonic@0.1.0";
    pub const CONTRACT: &str = "tests:broker/api@0.1.0";
    pub const PROFILE: &str = "builtin-monotonic-v1";
    pub const OPERATION: &str = "now-nanos";
    pub fn bytes() -> Vec<u8> {
        super::clock_component::build_for(CAP, OPERATION, false)
    }
}
#[path = "../broker/fixture.rs"]
#[allow(dead_code)]
mod fixture;
#[path = "signed.rs"]
#[allow(dead_code)]
mod signed;
#[path = "../generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use fixture::*;

#[tokio::test]
#[ignore = "requires explicitly rebuilt ordinary Instant guest from the pinned std source"]
async fn ordinary_std_instant_runs_on_signed_current_grants_and_fresh_stores() {
    use sha2::{Digest, Sha256};
    let directory = std::path::PathBuf::from(
        std::env::var_os("LSF_RUST_STD_CLOCK_GUEST")
            .expect("prepare the ordinary Instant component"),
    );
    let marker: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("clock-guest.json")).unwrap())
            .unwrap();
    assert_eq!(marker["profile"], "lsf-rust-std-clock-built-source-v1");
    assert_eq!(marker["compiler"], "1.97.1");
    assert_eq!(marker["target"], "wasm32-unknown-unknown");
    assert_eq!(marker["clockKind"], "monotonic");
    assert_eq!(marker["applicationClockSdkCalled"], false);
    let bytes = std::fs::read(directory.join("component.wasm")).unwrap();
    assert!(!bytes.is_empty() && bytes.len() < 4 * 1024 * 1024);
    assert_eq!(
        marker["componentDigest"],
        format!(
            "sha256:{:x}",
            latent_core::digest::HexDigest(Sha256::digest(&bytes))
        )
    );
    let signed = signed::Fixture::with_component(true, &bytes).await;
    let f = &signed.guest;
    for id in ["ordinary-instant-first", "ordinary-instant-fresh"] {
        let (request, control) = f.request(id);
        let report = f.backend.invoke_contained(request, &control).await;
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        let GuestOutcome::Returned {
            output,
            consumption,
            ..
        } = report.outcome.unwrap()
        else {
            panic!("ordinary Instant must use the granted monotonic clock");
        };
        let values: serde_json::Value = serde_json::from_slice(&output).unwrap();
        let _elapsed = values[0].as_str().unwrap().parse::<u64>().unwrap();
        let finalization = control
            .budget
            .finalize_at(Some(&consumption), Instant::now());
        assert!(finalization.violation().is_none());
        // Two actual typed monotonic imports each charge the original budget.
        assert_eq!(
            finalization.consumption().cpu_fuel,
            consumption.cpu_fuel + 200
        );
        f.idle();
        println!(
            "{}",
            serde_json::json!({"schemaVersion":"latent.rust.std-clock-execution.v1",
            "activation":id,"clockKind":marker["clockKind"],"componentDigest":marker["componentDigest"],
            "fuel":consumption.cpu_fuel,"peakWasmBytes":consumption.peak_memory_bytes,
            "wallMicros":consumption.wall_time_micros,"sampledPhysicalOwnersRetired":true})
        );
    }
    assert_eq!(f.backend.resource_snapshot().stores_created, 2);
    assert_eq!(f.clock.calls.load(Ordering::Acquire), 0);
    fixture::revoke(&f.policies);
    let (request, control) = f.request("ordinary-instant-denied");
    let report = f.backend.invoke_contained(request, &control).await;
    assert!(!matches!(report.outcome, Ok(GuestOutcome::Returned { .. })));
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    f.idle();
}
