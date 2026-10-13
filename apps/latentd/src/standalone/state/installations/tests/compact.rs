//! Actual current signed capture with the unchanged finite recovery declarations.
use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_signed_compact_installation_fits_eight_mib_job_and_retires_original_owners() {
    let setup = Setup::configured_profile(None, false, true).await;
    let before = setup.kernel.native.snapshot().unwrap();
    let limits = setup.fixture.settings.store.io.recovery.unwrap();
    assert_eq!(
        (limits.job_bytes, limits.retained_bytes),
        (8 * 1024 * 1024 + 8192, 16 * 1024 * 1024)
    );
    let installed = load(
        &setup.kernel,
        &setup.fixture.settings,
        &setup.owners,
        Arc::clone(&setup.policy),
        setup.services(),
        &setup.effects,
    )
    .await
    .unwrap();
    assert!(installed.management.is_some());
    assert!(!installed.http_rules);
    drop(installed);
    let after = setup.kernel.native.snapshot().unwrap();
    assert_eq!(after.recovery.slots, before.recovery.slots);
    assert_eq!(after.recovery.bytes, before.recovery.bytes);
    setup.finish().await;
}

#[test]
fn operation_selection_does_not_change_the_exact_store_profile_proposal() {
    let root = tempfile::tempdir().unwrap();
    let input = crate::config::state::tests::input();
    let full =
        crate::config::state::derive(&serde_json::from_value(input.clone()).unwrap(), root.path())
            .unwrap();
    let mut empty = input;
    empty["operations"] = serde_json::json!([]);
    let empty =
        crate::config::state::derive(&serde_json::from_value(empty).unwrap(), root.path()).unwrap();
    assert_eq!(
        full.store.inspection_profile().unwrap(),
        empty.store.inspection_profile().unwrap()
    );
    assert_eq!(full.configuration_epoch, empty.configuration_epoch);
}
