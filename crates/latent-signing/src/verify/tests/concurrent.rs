use super::*;
use crate::SignatureEvidence;
use latent_artifacts::package::PackageLimits;
use serde_json::json;

const NOW: u64 = 1_100;

fn subject() -> PackageSigningSubject {
    PackageSigningSubject::from_package(
        include_bytes!("../../../../../examples/package-format/browser-assets/manifest.json"),
        include_bytes!("../../../../../examples/package-format/browser-assets/config.json"),
        PackageLimits::default(),
    )
    .unwrap()
}

fn evidence() -> SignatureEvidence {
    SignatureEvidence::from_envelope(
        &subject(),
        include_bytes!("../../../tests/fixtures/openssl-envelope.json"),
        SignatureLimits::default(),
    )
    .unwrap()
}

fn trust(generation: u64) -> PublisherTrust {
    let limits = SignatureLimits::default();
    let public = include_str!("../../../tests/fixtures/openssl-public-key.txt").trim();
    let policy = PublisherPolicy::from_json(
        &serde_json::to_vec(&json!({
            "formatVersion": 1, "scope": "test:publisher", "generation": generation,
            "validFrom": 900, "validUntil": 3_000,
            "maxSignatureLifetimeSeconds": 2_000, "maxProofAgeSeconds": 60,
            "keys": [{"publisherId": "openssl-test-publisher", "publicKey": public,
                "validFrom": 900, "validUntil": 3_000}],
        }))
        .unwrap(),
        limits,
    )
    .unwrap();
    let revocations = RevocationSnapshot::from_json(
        &serde_json::to_vec(&json!({
            "formatVersion": 1, "scope": "test:publisher", "generation": generation,
            "policyDigest": policy.digest().as_str(), "validFrom": 900, "validUntil": 3_000,
            "revokedKeys": [], "revokedPublishers": [],
        }))
        .unwrap(),
        limits,
    )
    .unwrap();
    PublisherTrust::new(policy, revocations).unwrap()
}

#[test]
fn currentness_readers_share_trust_without_spurious_resource_exhaustion() {
    let verifier =
        Arc::new(PublisherVerifier::new(trust(1), SignatureLimits::default(), NOW).unwrap());
    let proof = verifier
        .verify_package(&subject(), evidence().as_ref(), NOW)
        .unwrap();
    let expected = verifier.state_id().unwrap();
    let guard = verifier.state.read().unwrap();
    let worker_verifier = verifier.clone();
    let (sender, receiver) = mpsc::sync_channel(1);
    let worker = thread::spawn(move || {
        let result = worker_verifier
            .check_current(&proof, NOW)
            .and_then(|()| worker_verifier.state_id())
            .and_then(|id| {
                worker_verifier
                    .verify_package(&subject(), evidence().as_ref(), NOW)
                    .map(|fresh| (id, fresh.state_id().clone(), fresh.valid_until()))
            });
        sender.send(result).unwrap();
    });
    let before_unlock = receiver.recv_timeout(Duration::from_secs(1));
    drop(guard);
    worker.join().unwrap();
    let (id, fresh_id, expiry) = before_unlock.unwrap().unwrap();
    assert_eq!(id, expected);
    assert_eq!(fresh_id, expected);
    assert_eq!(expiry, NOW + 60);
    assert_eq!(verifier.clock_floor(), NOW);
}

#[test]
fn exclusive_writer_refuses_currentness_without_queuing_or_renewing_proof() {
    let verifier =
        Arc::new(PublisherVerifier::new(trust(1), SignatureLimits::default(), NOW).unwrap());
    let proof = verifier
        .verify_package(&subject(), evidence().as_ref(), NOW)
        .unwrap();
    let initial = verifier.state_id().unwrap();
    let guard = verifier.state.write().unwrap();
    let worker_verifier = verifier.clone();
    let (sender, receiver) = mpsc::sync_channel(1);
    let worker = thread::spawn(move || {
        sender
            .send(worker_verifier.check_current(&proof, NOW + 1))
            .unwrap();
    });
    let before_unlock = receiver.recv_timeout(Duration::from_secs(1));
    drop(guard);
    worker.join().unwrap();
    assert_eq!(
        before_unlock.unwrap().unwrap_err().reason(),
        SignatureFailure::ResourceLimit
    );
    assert_eq!(verifier.clock_floor(), NOW + 1);
    assert_eq!(verifier.state_id().unwrap(), initial);
    let proof = verifier
        .verify_package(&subject(), evidence().as_ref(), NOW + 1)
        .unwrap();
    let next = verifier.replace_trust(&initial, trust(2), NOW + 1).unwrap();
    assert_ne!(next, initial);
    assert_eq!(
        verifier
            .check_current(&proof, NOW + 1)
            .unwrap_err()
            .reason(),
        SignatureFailure::StaleProof
    );
    assert_eq!(
        verifier
            .replace_trust(&initial, trust(3), NOW + 1)
            .unwrap_err()
            .reason(),
        SignatureFailure::TrustConflict
    );
}

#[test]
fn poisoned_writer_keeps_proof_reads_and_trust_replacement_closed() {
    let verifier =
        Arc::new(PublisherVerifier::new(trust(1), SignatureLimits::default(), NOW).unwrap());
    let proof = verifier
        .verify_package(&subject(), evidence().as_ref(), NOW)
        .unwrap();
    let initial = verifier.state_id().unwrap();
    let worker_verifier = verifier.clone();
    let worker = thread::spawn(move || {
        let _guard = worker_verifier.state.write().unwrap();
        panic!("poison the exclusive trust replacement owner");
    });
    assert!(worker.join().is_err());
    assert_eq!(
        verifier.check_current(&proof, NOW).unwrap_err().reason(),
        SignatureFailure::Internal
    );
    assert_eq!(
        verifier.state_id().unwrap_err().reason(),
        SignatureFailure::Internal
    );
    assert_eq!(
        verifier
            .replace_trust(&initial, trust(2), NOW + 1)
            .unwrap_err()
            .reason(),
        SignatureFailure::Internal
    );
    assert_eq!(verifier.clock_floor(), NOW + 1);
}
