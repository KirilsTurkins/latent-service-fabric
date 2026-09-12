use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::package::PackageLimits;
use latent_core::PublisherId;
use latent_signing::{
    generate_signing_key, LocalSigner, PackageSigningSubject, PublisherPolicy, PublisherTrust,
    RevocationSnapshot, SignatureEvidence, SignatureLimits, SignatureValidity,
};
use serde_json::{json, Value};

pub const ENVELOPE: &[u8] = include_bytes!("../fixtures/openssl-envelope.json");
pub const CLAIMS: &[u8] = include_bytes!("../fixtures/openssl-claims.json");
pub const PUBLIC_KEY: &str = include_str!("../fixtures/openssl-public-key.txt");
pub const PUBLISHER: &str = "openssl-test-publisher";
pub const NOW: u64 = 1_100;

pub fn browser() -> PackageSigningSubject {
    PackageSigningSubject::from_package(
        include_bytes!("../../../../examples/package-format/browser-assets/manifest.json"),
        include_bytes!("../../../../examples/package-format/browser-assets/config.json"),
        PackageLimits::default(),
    )
    .unwrap()
}

pub fn evidence() -> SignatureEvidence {
    SignatureEvidence::from_envelope(&browser(), ENVELOPE, SignatureLimits::default()).unwrap()
}

pub fn key(public_key: &str, publisher: &str) -> Value {
    json!({
        "publisherId": publisher, "publicKey": public_key,
        "validFrom": 900, "validUntil": 3_000,
    })
}

pub fn policy_value() -> Value {
    json!({
        "formatVersion": 1, "scope": "test:publisher", "generation": 1,
        "validFrom": 900, "validUntil": 3_000,
        "maxSignatureLifetimeSeconds": 2_000, "maxProofAgeSeconds": 60,
        "keys": [key(PUBLIC_KEY.trim(), PUBLISHER)],
    })
}

pub fn policy(value: &Value) -> PublisherPolicy {
    PublisherPolicy::from_json(
        &serde_json::to_vec(value).unwrap(),
        SignatureLimits::default(),
    )
    .unwrap()
}

pub fn revocation_value(policy: &PublisherPolicy) -> Value {
    json!({
        "formatVersion": 1, "scope": "test:publisher", "generation": 1,
        "policyDigest": policy.digest().as_str(),
        "validFrom": 900, "validUntil": 3_000,
        "revokedKeys": [], "revokedPublishers": [],
    })
}

pub fn trust_values(
    policy_value: &Value,
    change_revocations: impl FnOnce(&mut Value),
) -> PublisherTrust {
    let policy = policy(policy_value);
    let mut value = revocation_value(&policy);
    change_revocations(&mut value);
    let revocations = RevocationSnapshot::from_json(
        &serde_json::to_vec(&value).unwrap(),
        SignatureLimits::default(),
    )
    .unwrap();
    PublisherTrust::new(policy, revocations).unwrap()
}

pub fn trust() -> PublisherTrust {
    trust_values(&policy_value(), |_| {})
}

pub fn signer(publisher: &str) -> (LocalSigner, String) {
    let generated = generate_signing_key().unwrap();
    let public_key = *generated.public_key();
    let signer = LocalSigner::from_pkcs8(
        generated.into_pkcs8(),
        PublisherId(publisher.into()),
        public_key,
    )
    .unwrap();
    (signer, STANDARD.encode(public_key))
}

pub fn signed(signer: &LocalSigner, subject: &PackageSigningSubject) -> SignatureEvidence {
    signer
        .sign_package(
            subject,
            SignatureValidity {
                issued_at: 1_000,
                expires_at: 2_000,
            },
            SignatureLimits::default(),
        )
        .unwrap()
}
