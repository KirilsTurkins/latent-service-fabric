//! Real callback bookkeeping and response custody, not native-thread shutdown.
use super::*;
mod fixture;
use fixture::{exercise, kind_name};

#[test]
fn ready_delivery_retires_callback_kind_before_exclusive_custody_without_early_refund() {
    let cutoff = Instant::now() + WATCHDOG;
    for kind in [
        StoreIoKind::RecoveryRead,
        StoreIoKind::Read,
        StoreIoKind::RecoveryWrite,
        StoreIoKind::Write,
    ] {
        let report = exercise(kind, false, cutoff);
        let observed = &report.observed;
        // The original-source control reaches this marker and fails only after
        // the worker wake is released and the real owner has drained/joined.
        eprintln!(
            "store-io-ready-handoff-control: {}",
            serde_json::json!({
                "kind": kind_name(kind), "ready": observed.delivered.is_some(),
                "activeAtDelivery": observed.active,
                "unclaimedAccepted": observed.unclaimed.accepted,
                "unclaimedBytes": observed.unclaimed.retained_operation_bytes,
                "keeperHeldUntilClaim": observed.unclaimed_keeper,
                "custodyAccepted": observed.custody.is_ok(),
                "physicallyRetired": report.physically_retired,
                "threadsJoined": report.threads_joined,
            })
        );
        assert!(report.clean && report.physically_retired && report.store_destroyed);
        assert_eq!(report.threads_joined, 3);
        assert_eq!(report.callbacks, 1);
        assert!(observed.initially_pending);
        assert_eq!(observed.unclaimed.accepted, 1);
        assert!(observed.unclaimed.retained_operation_bytes >= 128);
        assert!(observed.unclaimed_keeper && observed.unclaimed_result);
        assert_eq!(observed.unclaimed_custody, Err(StoreIoError::CustodyBusy));
        assert_eq!(observed.delivered, Some(Ok(128)));
        assert_eq!(observed.accepted, 0);
        assert_eq!(observed.operation_bytes, 0);
        assert!(observed.keeper_released && observed.result_released);
        assert_eq!(observed.active, [0; 4], "{}", kind_name(kind));
        assert_eq!(observed.custody, Ok(()), "{}", kind_name(kind));
    }
}

#[test]
fn panicking_callback_retires_its_kind_before_error_delivery_without_reopening_quarantine() {
    let report = exercise(StoreIoKind::RecoveryRead, true, Instant::now() + WATCHDOG);
    let observed = report.observed;
    assert!(!report.clean && report.physically_retired && report.store_destroyed);
    assert_eq!(report.threads_joined, 3);
    assert_eq!(report.callbacks, 1);
    assert!(observed.initially_pending);
    assert_eq!(observed.unclaimed.accepted, 1);
    assert!(observed.unclaimed.retained_operation_bytes >= 128);
    assert!(observed.unclaimed_keeper && !observed.unclaimed_result);
    assert_eq!(
        observed.delivered,
        Some(Err(StoreIoError::RecoveryRequired))
    );
    assert_eq!(observed.accepted, 0);
    assert_eq!(observed.operation_bytes, 0);
    assert!(observed.keeper_released && observed.result_released);
    assert_eq!(observed.active, [0; 4]);
    assert!(observed.unclaimed.admission_closed && observed.unclaimed.quarantined);
    assert_eq!(
        observed.unclaimed.failure,
        Some(StoreIoError::RecoveryRequired)
    );
    assert_eq!(
        observed.unclaimed_custody,
        Err(StoreIoError::AdmissionClosed)
    );
    assert_eq!(observed.custody, Err(StoreIoError::AdmissionClosed));
}
