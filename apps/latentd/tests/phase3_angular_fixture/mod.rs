use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::{
    package::PackageLimits, AdmissionAuthority, AdmissionEvidence, PackageAdmissionUpload,
    ReleaseEvidenceUpload,
};
use latent_core::{PlatformError, PublisherId, TenantId};
use latent_packaging::PackageBundle;
use latent_policy::supply_chain::{
    SupplyChainAuthority, SupplyChainPolicy, SystemSupplyChainClock,
};
use latent_signing::{
    generate_signing_key, BuilderPolicy, LocalBuilderSigner, LocalSigner, PackageSigningSubject,
    ProvenanceLimits, PublisherPolicy, SignatureLimits, SignatureValidity, WebBuildObservation,
    ANGULAR_BUILD_TYPE,
};
use serde_json::json;
use std::{
    sync::Arc,
    time::{SystemTime, UNIX_EPOCH},
};

pub struct Signers {
    publisher: LocalSigner,
    builder: LocalBuilderSigner,
    pub policy_document: Vec<u8>,
    now: u64,
}

impl Signers {
    pub fn new(build_finished: u64, repository: &str) -> Self {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        assert!(build_finished <= now);
        let publisher_key = generate_signing_key().unwrap();
        let publisher_public = *publisher_key.public_key();
        let publisher = LocalSigner::from_pkcs8(
            publisher_key.into_pkcs8(),
            PublisherId("angular-publisher".into()),
            publisher_public,
        )
        .unwrap();
        let builder_key = generate_signing_key().unwrap();
        let builder_public = *builder_key.public_key();
        let builder = LocalBuilderSigner::from_pkcs8(
            builder_key.into_pkcs8(),
            "angular-builder".into(),
            builder_public,
        )
        .unwrap();
        let policy_document = policy(now, &publisher_public, &builder_public, repository);
        SupplyChainPolicy::from_json(&policy_document).unwrap();
        Self {
            publisher,
            builder,
            policy_document,
            now,
        }
    }

    pub fn evidence(
        &self,
        bundle: &PackageBundle,
        observed: &WebBuildObservation,
        lifetime: u64,
    ) -> ReleaseEvidenceUpload {
        let subject = PackageSigningSubject::from_package(
            bundle.manifest_bytes(),
            bundle.config_bytes(),
            PackageLimits::default(),
        )
        .unwrap();
        let validity = SignatureValidity {
            issued_at: self.now,
            expires_at: self.now + lifetime,
        };
        let signature = self
            .publisher
            .sign_package(&subject, validity, SignatureLimits::default())
            .unwrap();
        let provenance = self
            .builder
            .sign_web_build(&subject, observed, validity, ProvenanceLimits::default())
            .unwrap();
        ReleaseEvidenceUpload {
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
            sboms: Vec::new(),
        }
    }

    pub fn verify(
        &self,
        package: &PackageBundle,
        evidence: ReleaseEvidenceUpload,
    ) -> Result<(), PlatformError> {
        let directory = tempfile::tempdir().unwrap();
        let owner = SupplyChainAuthority::open(
            directory.path(),
            SupplyChainPolicy::from_json(&self.policy_document).unwrap(),
            Arc::new(SystemSupplyChainClock),
            5,
        )?;
        owner
            .verify_web(
                &TenantId("tests".into()),
                PackageAdmissionUpload {
                    manifest: package.manifest_bytes().to_vec(),
                    configuration: package.config_bytes().to_vec(),
                    layers: package
                        .layers()
                        .iter()
                        .map(|layer| (layer.path().to_owned(), layer.bytes().to_vec()))
                        .collect(),
                    signatures: evidence.signatures,
                    provenance: evidence.provenance,
                    sboms: evidence.sboms,
                },
            )
            .map(|_| ())
    }
}

fn policy(now: u64, publisher_key: &[u8; 32], builder_key: &[u8; 32], repository: &str) -> Vec<u8> {
    let publisher = json!({"formatVersion":1,"scope":"tests","generation":1,"validFrom":now - 60,"validUntil":now + 86400,
        "maxSignatureLifetimeSeconds":7200,"maxProofAgeSeconds":900,
        "keys":[{"publisherId":"angular-publisher","publicKey":STANDARD.encode(publisher_key),"validFrom":now - 60,"validUntil":now + 86400}]});
    let builder = json!({"formatVersion":1,"scope":"tests","generation":1,"validFrom":now - 60,"validUntil":now + 86400,
        "maxSignatureLifetimeSeconds":7200,"maxProofAgeSeconds":900,
        "keys":[{"builderId":"angular-builder","publicKey":STANDARD.encode(builder_key),"validFrom":now - 60,"validUntil":now + 86400}],
        "requirements":[{"builderId":"angular-builder","buildType":ANGULAR_BUILD_TYPE,"sourceRepository":repository,"requireReproducible":false}]});
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
    serde_json::to_vec(&json!({"formatVersion":1,"scope":"tests","generation":1,"validFrom":now - 60,"validUntil":now + 86400,
        "tenants":[{"tenant":"tests","publishers":["angular-publisher"]}],"publisher":publisher,"builder":builder,
        "publisherRevocations":{"formatVersion":1,"scope":"tests","policyDigest":publisher_digest,"generation":1,"validFrom":now - 60,"validUntil":now + 86400,"revokedKeys":[],"revokedPublishers":[]},
        "builderRevocations":{"formatVersion":1,"scope":"tests","policyDigest":builder_digest,"generation":1,"validFrom":now - 60,"validUntil":now + 86400,"revokedKeys":[],"revokedBuilders":[]},
        "sbom":{"formatVersion":1,"embedded":"required","detached":"optional","requireSource":[],"requireLicense":[]}
    })).unwrap()
}
