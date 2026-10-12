//! Actual affine response accounting. No fake store retirement is asserted.
use super::*;
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeCapacityOwner, NativeReservationRequest,
};

fn report() -> (NativeCapacityOwner, NativeRecoveryReport) {
    let owner = NativeCapacityOwner::with_clock(
        latent_core::native_capacity::NativeCapacityLimits::default(),
        Arc::new(latent_core::SystemActivationClock),
    )
    .unwrap();
    let original = owner
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                response_bytes: 4 * 1024 * 1024,
                ..NativeReservationRequest::default()
            },
            Instant::now() + std::time::Duration::from_secs(5),
        )
        .unwrap();
    let metadata = original
        .reserve_buffer(NativeBufferClass::Response, 2 * 1024 * 1024)
        .unwrap();
    let encoded = original
        .reserve_buffer(NativeBufferClass::Response, 2 * 1024 * 1024)
        .unwrap();
    (
        owner,
        NativeRecoveryReport {
            schema_version: "latent.native-transaction-recovery.v2",
            operation_succeeded: false,
            failure: Some(Failure {
                code: "unavailable",
                message: "current-owner-refusal".into(),
                retryable: false,
            }),
            result: None,
            retirement: Retirement {
                clean: false,
                physically_retired: false,
                live_workers: 0,
                accepted_jobs: 0,
                threads_joined: None,
            },
            catalogs_retired: false,
            pins: None,
            _response: metadata,
            encoded,
        },
    )
}

#[test]
fn encoded_refusal_retains_the_original_affine_response_after_admission_close_until_frame_drop() {
    let (owner, report) = report();
    owner.close();
    let frame = report.encode().unwrap();
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(frame.reserved_bytes(), 2 * 1024 * 1024);
    let value: serde_json::Value = serde_json::from_slice(frame.get()).unwrap();
    assert_eq!(
        value["failure"],
        serde_json::json!({"code":"unavailable","message":"current-owner-refusal","retryable":false})
    );
    assert_eq!(value["retirement"]["physicallyRetired"], false);
    drop(frame);
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 0);
    assert_eq!(owner.snapshot().unwrap().recovery.bytes, 0);
}

#[test]
fn oversized_output_refuses_without_refunding_a_live_original_response() {
    let (owner, mut report) = report();
    report.result = Some(serde_json::Value::String("x".repeat(2 * 1024 * 1024)));
    owner.close();
    assert!(report.encode().is_err());
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 0);
    assert_eq!(owner.snapshot().unwrap().recovery.bytes, 0);
}
