#![allow(dead_code)]
#[path = "../../../../latent-packaging/tests/fixtures/mod.rs"]
mod packaging;
#[path = "../../../../latent-packaging/tests/sbom_association/support.rs"]
mod sbom;

use super::super::{SupplyChainClock, SupplyChainPolicy};
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::package::{artifact_blob_digest, PackageLimits};
use latent_artifacts::{AdmissionEvidence, PackageAdmissionUpload};
use latent_core::{PlatformError, PublisherId};
use latent_packaging::{build_package_with_sbom, PackageBundle, PackagingLimits};
use latent_signing::*;
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};

pub const NOW: u64 = 1100;
pub struct Clock(pub AtomicU64);
impl Clock {
    pub fn set(&self, now: u64) {
        self.0.store(now, Ordering::SeqCst);
    }
}
impl SupplyChainClock for Clock {
    fn now(&self) -> Result<u64, PlatformError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

pub struct Fixture {
    pub policy: Value,
    pub clock: Arc<Clock>,
    bundle: PackageBundle,
    signature: SignatureEvidence,
    provenance: ProvenanceEvidence,
}
impl Fixture {
    pub fn new() -> Self {
        Self::with_builder("builder-a")
    }
    pub fn with_builder(builder_id: &str) -> Self {
        Self::with_inventory(builder_id, true)
    }
    pub fn without_inventory() -> Self {
        Self::with_inventory("builder-a", false)
    }
    fn with_inventory(builder_id: &str, with_inventory: bool) -> Self {
        Self::configured(builder_id, with_inventory, None)
    }
    pub fn with_runtime_requirements(requirements: Value) -> Self {
        Self::configured("builder-a", true, Some(requirements))
    }
    fn configured(builder_id: &str, with_inventory: bool, requirements: Option<Value>) -> Self {
        let mut input = packaging::capsule(packaging::component::Options::default());
        if let Some(requirements) = requirements {
            packaging::mutate_json(&mut input, "capsule.json", |manifest| {
                for (key, value) in requirements.as_object().unwrap() {
                    manifest["compatibility"]
                        .as_object_mut()
                        .unwrap()
                        .insert(key.clone(), value.clone());
                }
            });
        }
        let inventory = sbom::inventory(&input);
        let bundle = if with_inventory {
            build_package_with_sbom(input, inventory, PackagingLimits::default()).unwrap()
        } else {
            latent_packaging::build_package(input, PackagingLimits::default()).unwrap()
        };
        let subject = PackageSigningSubject::from_package(
            bundle.manifest_bytes(),
            bundle.config_bytes(),
            PackageLimits::default(),
        )
        .unwrap();
        let publisher_key = generate_signing_key().unwrap();
        let publisher_public = *publisher_key.public_key();
        let publisher = LocalSigner::from_pkcs8(
            publisher_key.into_pkcs8(),
            PublisherId("publisher-a".into()),
            publisher_public,
        )
        .unwrap();
        let builder_key = generate_signing_key().unwrap();
        let builder_public = *builder_key.public_key();
        let builder = LocalBuilderSigner::from_pkcs8(
            builder_key.into_pkcs8(),
            builder_id.into(),
            builder_public,
        )
        .unwrap();
        let signature = publisher
            .sign_package(
                &subject,
                SignatureValidity {
                    issued_at: 1000,
                    expires_at: 2000,
                },
                SignatureLimits::default(),
            )
            .unwrap();
        let provenance = builder
            .sign_build(
                &subject,
                &observation(&subject),
                SignatureValidity {
                    issued_at: 1000,
                    expires_at: 2000,
                },
                ProvenanceLimits::default(),
            )
            .unwrap();
        let publisher = json!({"formatVersion":1,"scope":"tests","generation":1,"validFrom":900,"validUntil":3000,
            "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
            "keys":[{"publisherId":"publisher-a","publicKey":STANDARD.encode(publisher_public),"validFrom":900,"validUntil":3000}]});
        let builder = json!({"formatVersion":1,"scope":"tests","generation":1,"validFrom":900,"validUntil":3000,
            "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
            "keys":[{"builderId":builder_id,"publicKey":STANDARD.encode(builder_public),"validFrom":900,"validUntil":3000}],
            "requirements":[{"builderId":builder_id,"buildType":PROVENANCE_BUILD_TYPE,"sourceRepository":"https://example.com/source","requireReproducible":false}]});
        let publisher_digest = PublisherPolicy::from_json(
            &serde_json::to_vec(&publisher).unwrap(),
            SignatureLimits::default(),
        )
        .unwrap()
        .digest()
        .to_string();
        let builder_digest = BuilderPolicy::from_json(
            &serde_json::to_vec(&builder).unwrap(),
            ProvenanceLimits::default(),
        )
        .unwrap()
        .digest()
        .to_string();
        let policy = json!({"formatVersion":1,"generation":1,"scope":"tests","validFrom":900,"validUntil":3000,
            "tenants":[{"tenant":"tests","publishers":["publisher-a"]}], "publisher":publisher,"builder":builder,
            "publisherRevocations":{"formatVersion":1,"scope":"tests","policyDigest":publisher_digest,"generation":1,"validFrom":900,"validUntil":3000,"revokedKeys":[],"revokedPublishers":[]},
            "builderRevocations":{"formatVersion":1,"scope":"tests","policyDigest":builder_digest,"generation":1,"validFrom":900,"validUntil":3000,"revokedKeys":[],"revokedBuilders":[]},
            "sbom":{"formatVersion":1,"embedded":"required","detached":"optional","requireSource":[],"requireLicense":[]}});
        Self {
            policy,
            clock: Arc::new(Clock(AtomicU64::new(NOW))),
            bundle,
            signature,
            provenance,
        }
    }
    pub fn approved(&self) -> SupplyChainPolicy {
        SupplyChainPolicy::from_json(&serde_json::to_vec(&self.policy).unwrap()).unwrap()
    }
    pub fn upload(&self) -> PackageAdmissionUpload {
        PackageAdmissionUpload {
            manifest: self.bundle.manifest_bytes().to_vec(),
            configuration: self.bundle.config_bytes().to_vec(),
            layers: self
                .bundle
                .layers()
                .iter()
                .map(|blob| (blob.path().to_owned(), blob.bytes().to_vec()))
                .collect(),
            signatures: vec![AdmissionEvidence {
                manifest: self.signature.manifest_bytes().to_vec(),
                configuration: b"{}".to_vec(),
                payload: self.signature.payload_bytes().to_vec(),
            }],
            provenance: vec![AdmissionEvidence {
                manifest: self.provenance.manifest_bytes().to_vec(),
                configuration: b"{}".to_vec(),
                payload: self.provenance.payload_bytes().to_vec(),
            }],
            sboms: vec![],
        }
    }
    pub fn wrong_subject_upload(&self) -> PackageAdmissionUpload {
        let mut input = packaging::capsule(packaging::component::Options::default());
        input
            .annotations
            .insert("tests.case".into(), "other-subject".into());
        let inventory = sbom::inventory(&input);
        let bundle = build_package_with_sbom(input, inventory, PackagingLimits::default())
            .unwrap()
            .into_input();
        let mut upload = self.upload();
        upload.manifest = bundle.manifest;
        upload.configuration = bundle.configuration;
        upload.layers = bundle.layers;
        upload
    }
}
fn observation(subject: &PackageSigningSubject) -> BuildObservation {
    let digest = artifact_blob_digest(b"bounded source fixture").to_string();
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
