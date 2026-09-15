//! Real cryptographic admission of compiled guests; keys live only in this test.
//! The builder signs the bounded build driver's actual input/output observation.
#![allow(dead_code)]
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::{
    package::PackageLimits, AdmissionEvidence, ArtifactRepository, DirectoryArtifactRepository,
    LifecycleScope, ManagedPublicationReceipt, ManagedPublicationUpload, PackageAdmissionUpload,
    ReleaseActor, ReleaseActorKind, ReleaseEvidenceUpload, ReleaseMutationContext,
    ReleaseOperationPrecondition,
};
use latent_core::{PublisherId, ReleaseDigest, TenantId};
use latent_packaging::{PackageBundle, PackagingLimits};
use latent_policy::supply_chain::{
    SupplyChainAuthority, SupplyChainPolicy, SystemSupplyChainClock,
};
use latent_signing::*;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    io::Read,
    path::{Path, PathBuf},
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};
#[path = "../../../latent-packaging/tests/sbom_association/support.rs"]
mod sbom;

pub type Publication = (
    Arc<DirectoryArtifactRepository>,
    ReleaseDigest,
    ManagedPublicationReceipt,
);

pub fn input(name: &str) -> PathBuf {
    let root = std::env::var_os("LSF_GUEST_CAPSULES").expect("run the guest contract gate");
    Path::new(&root).join(name)
}

pub fn observation(name: &str) -> BuildObservation {
    let directory = input(name);
    let root = directory.parent().unwrap();
    let marker: serde_json::Value =
        serde_json::from_slice(&read(&root.join("BUILD-COMPLETE.json"), 65536)).unwrap();
    assert_eq!(marker["formatVersion"], 1);
    let bytes = read(&directory.join("build-observation.json"), 65536);
    assert_eq!(
        marker["observations"][name],
        format!("sha256:{:x}", Sha256::digest(&bytes))
    );
    let observation = decode_build_observation(&bytes, ProvenanceLimits::default()).unwrap();
    let inputs = read(&root.join("source-inputs.json"), 1024 * 1024);
    assert_eq!(
        observation.source.snapshot_digest,
        format!("sha256:{:x}", Sha256::digest(inputs))
    );
    observation
}

pub fn bundle(path: &Path) -> PackageBundle {
    let limits = PackagingLimits::default();
    let source = latent_packaging::decode_package_source(
        &read(&path.join("package-source.json"), 65536),
        limits,
    )
    .unwrap();
    let input = latent_packaging::read_package_input(path, &source, limits).unwrap();
    let inventory = sbom::inventory(&input);
    latent_packaging::build_package_with_sbom(input, inventory, limits).unwrap()
}

fn read(path: &Path, maximum: usize) -> Vec<u8> {
    let mut bytes = vec![];
    std::fs::File::open(path)
        .unwrap()
        .take(maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .unwrap();
    assert!(bytes.len() <= maximum);
    bytes
}

pub struct Signers {
    publisher: LocalSigner,
    builder: LocalBuilderSigner,
    pub policy: SupplyChainPolicy,
    now: u64,
}
impl Signers {
    pub fn new(build_type: &str) -> Self {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let publisher_key = generate_signing_key().unwrap();
        let publisher_public = *publisher_key.public_key();
        let publisher = LocalSigner::from_pkcs8(
            publisher_key.into_pkcs8(),
            PublisherId("guest-publisher".into()),
            publisher_public,
        )
        .unwrap();
        let builder_key = generate_signing_key().unwrap();
        let builder_public = *builder_key.public_key();
        let builder = LocalBuilderSigner::from_pkcs8(
            builder_key.into_pkcs8(),
            "guest-builder".into(),
            builder_public,
        )
        .unwrap();
        Self {
            publisher,
            builder,
            policy: policy(now, &publisher_public, &builder_public, build_type),
            now,
        }
    }
    pub fn upload(
        &self,
        bundle: &PackageBundle,
        observation: &BuildObservation,
    ) -> PackageAdmissionUpload {
        let subject = PackageSigningSubject::from_package(
            bundle.manifest_bytes(),
            bundle.config_bytes(),
            PackageLimits::default(),
        )
        .unwrap();
        let validity = SignatureValidity {
            issued_at: self.now,
            expires_at: self.now + 1200,
        };
        let signature = self
            .publisher
            .sign_package(&subject, validity, SignatureLimits::default())
            .unwrap();
        let provenance = self
            .builder
            .sign_build(&subject, observation, validity, ProvenanceLimits::default())
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
            &self.policy,
            latent_policy::supply_chain::PackageVerificationRequest {
                tenant: &TenantId("tests".into()),
                package: bundle,
                evidence: &evidence,
                unix_seconds: self.now,
            },
        )
        .unwrap();
        PackageAdmissionUpload {
            manifest: bundle.manifest_bytes().to_vec(),
            configuration: bundle.config_bytes().to_vec(),
            layers: bundle
                .layers()
                .iter()
                .map(|b| (b.path().into(), b.bytes().to_vec()))
                .collect(),
            signatures: evidence.signatures,
            provenance: evidence.provenance,
            sboms: evidence.sboms,
        }
    }
}

pub async fn publish(root: &Path, name: &str) -> Publication {
    let bundle = bundle(&input(name));
    let observation = observation(name);
    let signers = Signers::new(&observation.build_type);
    let upload = signers.upload(&bundle, &observation);
    let release = bundle.layout().component_release().unwrap();
    let catalog = catalog(root, signers.policy);
    let receipt = catalog
        .publish_managed(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId("tests".into())),
                actor: ReleaseActor {
                    subject: "guest-sdk-contract-gate".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: "publish-guest".into(),
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

fn policy(
    now: u64,
    publisher: &[u8; 32],
    builder: &[u8; 32],
    build_type: &str,
) -> SupplyChainPolicy {
    let publisher = json!({"formatVersion":1,"scope":"tests","generation":1,"validFrom":now - 60,"validUntil":now + 3600,
            "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
            "keys":[{"publisherId":"guest-publisher","publicKey":STANDARD.encode(publisher),"validFrom":now - 60,"validUntil":now + 3600}]});
    let builder = json!({"formatVersion":1,"scope":"tests","generation":1,"validFrom":now - 60,"validUntil":now + 3600,
            "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
            "keys":[{"builderId":"guest-builder","publicKey":STANDARD.encode(builder),"validFrom":now - 60,"validUntil":now + 3600}],
            "requirements":[{"builderId":"guest-builder","buildType":build_type,"sourceRepository":"https://github.com/KirilsTurkins/latent-service-fabric","requireReproducible":false}]});
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
    let policy = json!({"formatVersion":1,"generation":1,"scope":"tests","validFrom":now - 60,"validUntil":now + 3600,
            "tenants":[{"tenant":"tests","publishers":["guest-publisher"]},{"tenant":"tenant-a","publishers":["guest-publisher"]}], "publisher":publisher,"builder":builder,
            "publisherRevocations":{"formatVersion":1,"scope":"tests","policyDigest":publisher_digest,"generation":1,"validFrom":now - 60,"validUntil":now + 3600,"revokedKeys":[],"revokedPublishers":[]},
            "builderRevocations":{"formatVersion":1,"scope":"tests","policyDigest":builder_digest,"generation":1,"validFrom":now - 60,"validUntil":now + 3600,"revokedKeys":[],"revokedBuilders":[]},
            "sbom":{"formatVersion":1,"embedded":"required","detached":"optional","requireSource":[],"requireLicense":[]}});
    SupplyChainPolicy::from_json(&serde_json::to_vec(&policy).unwrap()).unwrap()
}

pub fn catalog(root: &Path, policy: SupplyChainPolicy) -> Arc<DirectoryArtifactRepository> {
    let authority = Arc::new(
        SupplyChainAuthority::open_with_runtime(
            &root.join("trust"),
            policy,
            Arc::new(SystemSupplyChainClock),
            5,
            Arc::new(super::support::config().detected_runtime_profile().unwrap()),
        )
        .unwrap(),
    );
    let catalog = Arc::new(
        DirectoryArtifactRepository::open_enforced(
            root.join("catalog"),
            Default::default(),
            Default::default(),
            authority,
        )
        .unwrap(),
    );
    catalog
}
