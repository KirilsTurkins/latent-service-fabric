use super::*;
fn publication(action: AuditControlAction) -> AuditOperationAttempt {
    let mut v = attempt();
    v.action = action;
    v.expected_generation = None;
    v
}
#[test]
fn publication_audit_requires_preview_bound_batch_identity_without_fake_single_target() {
    for action in [
        AuditControlAction::PublicationPin,
        AuditControlAction::PublicationUnpin,
        AuditControlAction::PublicationDelete,
        AuditControlAction::PublicationReclaim,
    ] {
        let a = publication(action);
        codec::attempt(&a).unwrap();
        let bytes = codec::encode(&a, 4096).unwrap();
        assert_eq!(
            codec::decode::<AuditOperationAttempt>(&bytes, 4096).unwrap(),
            a
        );
        let mut bad = a.clone();
        bad.preview_receipt_digest = None;
        assert!(codec::attempt(&bad).is_err());
        let mut bad = a.clone();
        bad.expected_generation = Some(1);
        assert!(codec::attempt(&bad).is_err());
        let mut bad = a;
        bad.identities.component = Some(latent_core::ReleaseDigest(digest().to_string()));
        assert!(codec::attempt(&bad).is_err());
    }
}
#[test]
fn publication_audit_rejects_mismatched_receipt_replay_and_canary_without_admission() {
    let directory = Directory::new();
    let (handle, _worker) = open(directory.0.join("journal"), AuditLimits::default()).unwrap();
    let a = publication(AuditControlAction::PublicationDelete);
    let mut done = conclusion();
    handle.preflight_conclusion(&a, &done).unwrap();
    done.receipt_digest = Some(format!("sha256:{}", "b".repeat(64)).parse().unwrap());
    assert!(handle.preflight_conclusion(&a, &done).is_err());
    let mut done = conclusion();
    done.replay = true;
    assert!(handle.preflight_conclusion(&a, &done).is_err());
    let mut done = conclusion();
    done.identities.lifecycle_generation = Some(1);
    assert!(handle.preflight_conclusion(&a, &done).is_err());
    assert_eq!(handle.snapshot().retained_records, 0);
}
