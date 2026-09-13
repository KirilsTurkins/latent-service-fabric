use base64::{engine::general_purpose::STANDARD, Engine};

use super::{
    PublisherKeyConfig, PublisherPolicy, PublisherPolicyConfig, RevocationSnapshot,
    RevocationSnapshotConfig,
};
use crate::{generate_signing_key, SignatureLimits};

fn oversized_capacity(value: &str) -> String {
    let mut owned = String::with_capacity(8192);
    owned.push_str(value);
    owned
}

#[test]
fn policy_discards_caller_spare_capacity_before_retaining_config() {
    let generated = generate_signing_key().unwrap();
    let mut keys = Vec::with_capacity(1024);
    keys.push(PublisherKeyConfig {
        publisher_id: oversized_capacity("publisher:test"),
        public_key: oversized_capacity(&STANDARD.encode(generated.public_key())),
        valid_from: 10,
        valid_until: 1000,
    });
    let policy = PublisherPolicy::new(
        PublisherPolicyConfig {
            format_version: 1,
            scope: oversized_capacity("test"),
            generation: 1,
            valid_from: 10,
            valid_until: 1000,
            max_signature_lifetime_seconds: 900,
            max_proof_age_seconds: 60,
            keys,
        },
        SignatureLimits::default(),
    )
    .unwrap();
    assert!(policy.config.scope.capacity() <= 128);
    assert!(policy.config.keys.capacity() <= 256);
    assert!(policy.config.keys[0].publisher_id.capacity() <= 128);
    assert!(policy.config.keys[0].public_key.capacity() <= 128);
    assert!(policy.keys.values().next().unwrap().publisher.0.capacity() <= 128);
}

#[test]
fn revocation_snapshot_discards_caller_spare_capacity() {
    let digest = latent_artifacts::package::artifact_blob_digest(b"test policy");
    let mut revoked_keys = Vec::with_capacity(1024);
    revoked_keys.push(oversized_capacity(digest.as_str()));
    let mut revoked_publishers = Vec::with_capacity(1024);
    revoked_publishers.push(oversized_capacity("publisher:test"));
    let snapshot = RevocationSnapshot::new(
        RevocationSnapshotConfig {
            format_version: 1,
            scope: oversized_capacity("test"),
            policy_digest: oversized_capacity(digest.as_str()),
            generation: 1,
            valid_from: 10,
            valid_until: 1000,
            revoked_keys,
            revoked_publishers,
        },
        SignatureLimits::default(),
    )
    .unwrap();
    assert!(snapshot.config.scope.capacity() <= 128);
    assert!(snapshot.config.policy_digest.capacity() <= 128);
    assert!(snapshot.config.revoked_keys.capacity() <= 256);
    assert!(snapshot.config.revoked_publishers.capacity() <= 256);
    assert!(snapshot.config.revoked_keys[0].capacity() <= 128);
    assert!(snapshot.config.revoked_publishers[0].capacity() <= 128);
    assert!(snapshot.publishers.iter().next().unwrap().capacity() <= 128);
}
