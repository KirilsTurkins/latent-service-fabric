use super::policy_file_ceiling;
use latent_policy::capability::CapabilityCeiling;

#[test]
fn streamed_snapshot_remaining_passes_real_policy_validation_before_intersection() {
    let physical = latent_state::recovery::snapshot::SNAPSHOT_FILE_BYTES;
    assert_eq!(physical, 160 * 1024 * 1024);
    let remaining = policy_file_ceiling(physical);
    remaining.validate().unwrap();
    assert_eq!(remaining.operations, 1);
    assert_eq!(remaining.wall_time_millis, 60_000);
    // The policy API still rejects any descriptor above its original cap.
    let above = CapabilityCeiling {
        input_bytes: 64 * 1024 * 1024 + 1,
        ..remaining
    };
    assert!(above.validate().is_err());
}

#[test]
fn original_smaller_file_and_policy_allowances_are_never_widened() {
    for bytes in [0, 1, 16_384] {
        let remaining = policy_file_ceiling(bytes);
        remaining.validate().unwrap();
        assert_eq!(remaining.input_bytes, bytes);
        assert_eq!(remaining.output_bytes, bytes);
    }
    let remaining = policy_file_ceiling(latent_state::recovery::snapshot::SNAPSHOT_FILE_BYTES);
    let granted = CapabilityCeiling {
        operations: 1,
        input_bytes: 8192,
        output_bytes: 4096,
        wall_time_millis: 5000,
    };
    let narrowed = remaining.intersect(granted);
    narrowed.validate().unwrap();
    assert_eq!(narrowed, granted);
}
