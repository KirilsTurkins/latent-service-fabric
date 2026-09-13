use super::*;
use crate::{PublisherPolicy, PublisherPolicyConfig, RevocationSnapshot, RevocationSnapshotConfig};
use std::{sync::mpsc, thread, time::Duration};

fn deny_all(generation: u64) -> PublisherTrust {
    let limits = SignatureLimits::default();
    let policy = PublisherPolicy::new(
        PublisherPolicyConfig {
            format_version: 1,
            scope: "node/publishers".into(),
            generation,
            valid_from: 0,
            valid_until: 1000,
            max_signature_lifetime_seconds: 100,
            max_proof_age_seconds: 10,
            keys: vec![],
        },
        limits,
    )
    .unwrap();
    let revocations = RevocationSnapshot::new(
        RevocationSnapshotConfig {
            format_version: 1,
            scope: "node/publishers".into(),
            policy_digest: policy.digest().to_string(),
            generation,
            valid_from: 0,
            valid_until: 1000,
            revoked_keys: vec![],
            revoked_publishers: vec![],
        },
        limits,
    )
    .unwrap();
    PublisherTrust::new(policy, revocations).unwrap()
}

#[test]
fn contended_owner_rejects_without_queuing_and_preserves_observed_time() {
    let verifier =
        Arc::new(PublisherVerifier::new(deny_all(1), SignatureLimits::default(), 10).unwrap());
    let expected = verifier.state_id().unwrap();
    let guard = verifier.state.lock().unwrap();
    let worker_verifier = verifier.clone();
    let worker_expected = expected.clone();
    let (sender, receiver) = mpsc::sync_channel(1);
    let worker = thread::spawn(move || {
        sender
            .send(worker_verifier.replace_trust(&worker_expected, deny_all(2), 20))
            .unwrap();
    });
    // Release the lock even if a future implementation accidentally waits, so a
    // failed assertion cannot strand the test's worker indefinitely.
    let before_unlock = receiver.recv_timeout(Duration::from_secs(1));
    drop(guard);
    worker.join().unwrap();
    assert_eq!(
        before_unlock.unwrap().unwrap_err().reason(),
        SignatureFailure::ResourceLimit
    );
    assert_eq!(verifier.clock_floor(), 20);
    assert_eq!(verifier.state_id().unwrap(), expected);
    assert_eq!(
        verifier
            .replace_trust(&expected, deny_all(2), 19)
            .unwrap_err()
            .reason(),
        SignatureFailure::ClockRegression
    );
    verifier.replace_trust(&expected, deny_all(2), 20).unwrap();
}
