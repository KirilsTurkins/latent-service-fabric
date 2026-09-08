//! Two real activations verify shutdown ownership, without a scale workload.
#![cfg(target_os = "linux")]

#[path = "standalone_shutdown/fixture.rs"]
mod fixture;
#[path = "standalone_shutdown/scenario.rs"]
mod scenario;
#[path = "standalone_shutdown/support.rs"]
mod support;

#[test]
#[ignore = "requires contracts-gate LSF_SHUTDOWN_COMPONENT; two short real activations"]
fn running_and_queued_owners_are_reclaimed_during_shutdown() {
    support::supervise(
        "running_and_queued_owners_are_reclaimed_during_shutdown",
        scenario::run,
    );
}
