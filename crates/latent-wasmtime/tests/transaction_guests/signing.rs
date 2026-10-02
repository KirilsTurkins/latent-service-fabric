//! Independent ephemeral test keys sign the actual maintained build output.
//! Public policy/evidence is retained; private keys never leave this fixture.
use super::artifact;
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::{
    package::PackageLimits, AdmissionEvidence, AdmissionStorageLimits, ArtifactRepository,
    DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig, LifecycleScope,
    ManagedPublicationReceipt, ManagedPublicationUpload, PackageAdmissionUpload, ReleaseActor,
    ReleaseActorKind, ReleaseEvidenceUpload, ReleaseMutationContext, ReleaseOperationPrecondition,
};
use latent_core::{PlatformError, PublisherId, ReleaseDigest, TenantId};
use latent_policy::supply_chain::{
    SupplyChainAuthority, SupplyChainClock, SupplyChainPolicy, SystemSupplyChainClock,
};
use latent_signing::{
    generate_signing_key, BuilderPolicy, LocalBuilderSigner, LocalSigner, PackageSigningSubject,
    ProvenanceLimits, PublisherPolicy, SignatureLimits, SignatureValidity,
};
use latent_wasmtime::WasmtimeConfig;
use serde_json::json;
use std::{fs::OpenOptions, io::Write, os::unix::fs::DirBuilderExt, path::Path, sync::Arc};

// This direct-library campaign has no Standalone control sampler. The test
// operator supplies one fixed admission instant, exactly as in the stateless
// signed SDK campaign. Production covered-clock/expiry/renewal qualification is
// separate; these component tests certify neither it nor a node installation.
struct FixtureClock(u64);
impl SupplyChainClock for FixtureClock {
    fn now(&self) -> Result<u64, PlatformError> {
        Ok(self.0)
    }
}

pub async fn publish(
    root: &Path,
    prepared: &artifact::Prepared,
    variant: &str,
    runtime: &WasmtimeConfig,
    tenant: &TenantId,
) -> (
    Arc<DirectoryArtifactRepository>,
    ReleaseDigest,
    ManagedPublicationReceipt,
) {
    let now = SystemSupplyChainClock.now().unwrap();
    assert!(now >= prepared.observation.finished_at);
    let publisher_key = generate_signing_key().unwrap();
    let publisher_public = *publisher_key.public_key();
    let publisher = LocalSigner::from_pkcs8(
        publisher_key.into_pkcs8(),
        PublisherId("native-guest-publisher".into()),
        publisher_public,
    )
    .unwrap();
    let builder_key = generate_signing_key().unwrap();
    let builder_public = *builder_key.public_key();
    assert_ne!(
        publisher_public, builder_public,
        "independently generated publisher and builder keys"
    );
    let builder = LocalBuilderSigner::from_pkcs8(
        builder_key.into_pkcs8(),
        "native-guest-builder".into(),
        builder_public,
    )
    .unwrap();
    let policy_document = policy_document(
        now,
        tenant,
        &publisher_public,
        &builder_public,
        &prepared.observation.build_type,
    );
    let policy = SupplyChainPolicy::from_json(&policy_document).unwrap();
    let subject = PackageSigningSubject::from_package(
        prepared.bundle.manifest_bytes(),
        prepared.bundle.config_bytes(),
        PackageLimits::default(),
    )
    .unwrap();
    let validity = SignatureValidity {
        issued_at: now,
        expires_at: now.checked_add(1200).unwrap(),
    };
    let signature = publisher
        .sign_package(&subject, validity, SignatureLimits::default())
        .unwrap();
    let provenance = builder
        .sign_build(
            &subject,
            &prepared.observation,
            validity,
            ProvenanceLimits::default(),
        )
        .unwrap();
    let evidence = ReleaseEvidenceUpload {
        signatures: vec![AdmissionEvidence {
            manifest: signature.manifest_bytes().to_vec(),
            configuration: b"{}".to_vec(),
            payload: signature.payload_bytes().to_vec(),
        }],
        provenance: vec![AdmissionEvidence {
            manifest: provenance.manifest_bytes().to_vec(),
            configuration: b"{}".to_vec(),
            payload: provenance.payload_bytes().to_vec(),
        }],
        sboms: vec![],
    };
    latent_policy::supply_chain::verify_package_once(
        &policy,
        latent_policy::supply_chain::PackageVerificationRequest {
            tenant,
            package: &prepared.bundle,
            evidence: &evidence,
            unix_seconds: now,
        },
    )
    .unwrap();
    retain_inputs(
        prepared,
        variant,
        &policy_document,
        &evidence,
        latent_artifacts::package::artifact_blob_digest(&publisher_public).as_str(),
    );
    let authority = Arc::new(
        SupplyChainAuthority::open_with_runtime_and_manifest_profile(
            &root.join("trust"),
            policy,
            Arc::new(FixtureClock(now)),
            5,
            Arc::new(runtime.detected_runtime_profile().unwrap()),
            artifact::profile(),
        )
        .unwrap(),
    );
    let catalog = Arc::new(
        DirectoryArtifactRepository::open_enforced(
            root.join("artifacts"),
            DirectoryArtifactRepositoryConfig {
                manifest_profile: artifact::profile(),
                ..Default::default()
            },
            AdmissionStorageLimits::default(),
            authority,
        )
        .unwrap(),
    );
    let release = prepared.bundle.layout().component_release().unwrap();
    let upload = PackageAdmissionUpload {
        manifest: prepared.bundle.manifest_bytes().to_vec(),
        configuration: prepared.bundle.config_bytes().to_vec(),
        layers: prepared
            .bundle
            .layers()
            .iter()
            .map(|row| (row.path().into(), row.bytes().to_vec()))
            .collect(),
        signatures: evidence.signatures,
        provenance: evidence.provenance,
        sboms: evidence.sboms,
    };
    let receipt = catalog
        .publish_managed(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(tenant.clone()),
                actor: ReleaseActor {
                    subject: "native-guest-test-operator".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: "signed-authored-source".into(),
                    expected_generation: 0,
                }),
            },
            ManagedPublicationUpload::Package(upload),
            &mut |_| Ok(()),
        )
        .await
        .unwrap();
    assert!(catalog
        .execution_eligibility_selected(&release, Some(&receipt.publication.id))
        .unwrap()
        .is_some());
    (catalog, release, receipt)
}

fn retain_inputs(
    prepared: &artifact::Prepared,
    variant: &str,
    policy: &[u8],
    evidence: &ReleaseEvidenceUpload,
    publisher: &str,
) {
    let input = artifact::directory(variant);
    let parent = input.parent().unwrap().join("native-evidence");
    assert!(
        parent.is_dir() && !parent.is_symlink(),
        "preparation owns the evidence directory"
    );
    let output = parent.join(format!(
        "{variant}-{}",
        publisher.strip_prefix("sha256:").unwrap()
    ));
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&output)
        .unwrap();
    let mut identities = std::collections::BTreeMap::new();
    for (name, bytes) in [
        ("policy.json", policy.to_vec()),
        ("manifest.json", prepared.bundle.manifest_bytes().to_vec()),
        ("config.json", prepared.bundle.config_bytes().to_vec()),
        (
            "sbom.json",
            prepared
                .bundle
                .blob(latent_packaging::SBOM_PATH)
                .unwrap()
                .to_vec(),
        ),
        (
            "build-observation.json",
            artifact::read(&input, "built/build-observation.json", 65536),
        ),
        (
            "source-inputs.json",
            artifact::read(&input, "built/source-inputs.json", 1024 * 1024),
        ),
        (
            "recipe-inputs.json",
            artifact::read(&input, "built/recipe-inputs.json", 1024 * 1024),
        ),
        (
            "package-inputs.json",
            artifact::read(&input, "built/package-inputs.json", 1024 * 1024),
        ),
        (
            "preparation-report.json",
            artifact::read(&input, "report.json", 65536),
        ),
    ] {
        assert!(bytes.len() <= 1024 * 1024, "finite public signing inputs");
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(output.join(name))
            .unwrap()
            .write_all(&bytes)
            .unwrap();
        identities.insert(
            name,
            json!({"digest":latent_artifacts::content_digest(&bytes).0,"size":bytes.len()}),
        );
    }
    latent_packaging::write_package_evidence(
        prepared.bundle.layout().digest(),
        evidence,
        &output.join("evidence"),
        128 * 1024,
    )
    .unwrap();
    let report = json!({"schemaVersion":"latent.transaction-guest.signing-inputs.v1", "variant":variant,
        "packageDigest":prepared.bundle.layout().digest().as_str(),
        "componentDigest":prepared.observation.component_digest,"sourceDigest":prepared.observation.source.snapshot_digest,
        "signingBoundary":"independent-ephemeral-test-keys","admissionClock":"fixed-trusted-fixture-instant",
        "signedNodeExecutionQualified":false,"compilerInputs":identities,"evidenceIndex":"evidence/index.json"});
    OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(output.join("inputs.json"))
        .unwrap()
        .write_all(&serde_json::to_vec(&report).unwrap())
        .unwrap();
}

fn policy_document(
    now: u64,
    tenant: &TenantId,
    publisher: &[u8; 32],
    builder: &[u8; 32],
    build_type: &str,
) -> Vec<u8> {
    let scope = "native-transaction-guests";
    let before = now.checked_sub(60).unwrap();
    let after = now.checked_add(3600).unwrap();
    let publisher = json!({"formatVersion":1,"scope":scope,"generation":1,"validFrom":before,"validUntil":after,
        "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
        "keys":[{"publisherId":"native-guest-publisher","publicKey":STANDARD.encode(publisher),"validFrom":before,"validUntil":after}]});
    let builder = json!({"formatVersion":1,"scope":scope,"generation":1,"validFrom":before,"validUntil":after,
        "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
        "keys":[{"builderId":"native-guest-builder","publicKey":STANDARD.encode(builder),"validFrom":before,"validUntil":after}],
        "requirements":[{"builderId":"native-guest-builder","buildType":build_type,
            "sourceRepository":"https://github.com/KirilsTurkins/latent-service-fabric","requireReproducible":false}]});
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
    serde_json::to_vec(&json!({"formatVersion":1,"generation":1,"scope":scope,"validFrom":before,"validUntil":after,
        "tenants":[{"tenant":tenant.0,"publishers":["native-guest-publisher"]}],"publisher":publisher,"builder":builder,
        "publisherRevocations":{"formatVersion":1,"scope":scope,"policyDigest":publisher_digest,"generation":1,
            "validFrom":before,"validUntil":after,"revokedKeys":[],"revokedPublishers":[]},
        "builderRevocations":{"formatVersion":1,"scope":scope,"policyDigest":builder_digest,"generation":1,
            "validFrom":before,"validUntil":after,"revokedKeys":[],"revokedBuilders":[]},
        "sbom":{"formatVersion":1,"embedded":"required","detached":"optional","requireSource":[],"requireLicense":[]}
    })).unwrap()
}
