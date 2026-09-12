use crate::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::package::{artifact_blob_digest, PackageLimits};
use serde_json::{json, Value};

pub const NOW: u64 = 1100;
pub const BUILDER: &str = "builder-a";

pub fn subject() -> PackageSigningSubject {
    PackageSigningSubject::from_package(
        include_bytes!("../../../../../examples/package-format/capsule/manifest.json"),
        include_bytes!("../../../../../examples/package-format/capsule/config.json"),
        PackageLimits::default(),
    )
    .unwrap()
}

pub fn observation() -> BuildObservation {
    let subject = subject();
    let digest = format!("sha256:{}", "b".repeat(64));
    BuildObservation {
        format_version: 1,
        build_type: PROVENANCE_BUILD_TYPE.into(),
        source: BuildSource {
            repository: "https://example.com/source".into(),
            revision: "a".repeat(40),
            snapshot_digest: digest.clone(),
            repository_trust: "operator-asserted".into(),
            capture: "git-archive-allowlist".into(),
        },
        component_digest: subject.component_digest().unwrap().to_string(),
        component_size: subject.component_size().unwrap(),
        materials: [
            "build-recipe",
            "cargo",
            "dependency-lock",
            "rustc",
            "source-snapshot",
            "toolchain-config",
            "wasm-tools",
        ]
        .into_iter()
        .map(|name| BuildMaterial {
            name: name.into(),
            digest: digest.clone(),
            size: 1,
        })
        .collect(),
        parameters: BuildParameters {
            cargo_package: "latent-toolchain-smoke".into(),
            cargo_example: "echo-capsule".into(),
            target: "wasm32-unknown-unknown".into(),
            profile: "release".into(),
            locked: true,
            incremental: false,
        },
        started_at: 900,
        finished_at: 1000,
        reproducibility: "not-checked".into(),
        hermetic: false,
        dependency_completeness: "lockfile-only".into(),
    }
}

pub fn signer(builder: &str) -> (LocalBuilderSigner, String, String) {
    let generated = generate_signing_key().unwrap();
    let public = *generated.public_key();
    let fingerprint = artifact_blob_digest(&public).to_string();
    (
        LocalBuilderSigner::from_pkcs8(generated.into_pkcs8(), builder.into(), public).unwrap(),
        STANDARD.encode(public),
        fingerprint,
    )
}

pub fn signed(signer: &LocalBuilderSigner, observation: &BuildObservation) -> ProvenanceEvidence {
    signer
        .sign_build(
            &subject(),
            observation,
            SignatureValidity {
                issued_at: 1000,
                expires_at: 2000,
            },
            ProvenanceLimits::default(),
        )
        .unwrap()
}

pub fn policy_value(public: &str) -> Value {
    json!({"formatVersion":1,"scope":"test/builders","generation":1,
        "validFrom":900,"validUntil":3000,"maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
        "keys":[{"builderId":BUILDER,"publicKey":public,"validFrom":900,"validUntil":3000}],
        "requirements":[{"builderId":BUILDER,"buildType":PROVENANCE_BUILD_TYPE,
            "sourceRepository":"https://example.com/source","requireReproducible":false}]})
}

pub fn trust(value: &Value, update: impl FnOnce(&mut Value)) -> BuilderTrust {
    let limits = ProvenanceLimits::default();
    let policy = BuilderPolicy::from_json(&serde_json::to_vec(value).unwrap(), limits).unwrap();
    let mut revocations = json!({"formatVersion":1,"scope":"test/builders",
        "policyDigest":policy.digest().as_str(),"generation":value["generation"],
        "validFrom":900,"validUntil":3000,"revokedKeys":[],"revokedBuilders":[]});
    update(&mut revocations);
    BuilderTrust::new(
        policy,
        BuilderRevocationSnapshot::from_json(&serde_json::to_vec(&revocations).unwrap(), limits)
            .unwrap(),
    )
    .unwrap()
}

pub fn verifier(value: &Value) -> BuilderVerifier {
    BuilderVerifier::new(trust(value, |_| {}), ProvenanceLimits::default(), NOW).unwrap()
}
