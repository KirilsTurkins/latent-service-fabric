//! Repository association tests use the explicit test authority and the tiny
//! non-executable fixture. They do not claim cryptographic or guest qualification.
use std::sync::Arc;

use latent_core::{PlatformError, PlatformErrorCode};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use serde_json::{json, Value};

use super::super::{block_on, TempRoot};
use super::{artifact, tenant, upload, Authority, Grant};
use crate::package::{artifact_blob_digest, package_digest};
use crate::{
    AdmissionAuthority, AdmissionBinding, AdmissionStorageLimits, ArtifactRepository,
    CapsuleArtifact, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
    PackageAdmissionUpload, VerifiedAdmission, VerifiedArtifactMetadata,
};

struct Host {
    authority: Arc<Authority>,
    artifact: CapsuleArtifact,
}

impl AdmissionAuthority for Host {
    fn verify(
        &self,
        tenant: &latent_core::TenantId,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        let binding = AdmissionBinding {
            tenant: tenant.clone(),
            package: package_digest(&upload.manifest),
            release: self.artifact.descriptor.release_digest.clone(),
            receipt: b"explicit transaction storage test authority".to_vec(),
        };
        self.recover(&binding, upload)
    }

    fn recover(
        &self,
        binding: &AdmissionBinding,
        upload: PackageAdmissionUpload,
    ) -> Result<VerifiedAdmission, PlatformError> {
        Ok(VerifiedAdmission {
            artifact: self.artifact.clone(),
            upload,
            grant: Arc::new(Grant {
                binding: binding.clone(),
                authority: Arc::clone(&self.authority),
                generation: self
                    .authority
                    .generation
                    .load(std::sync::atomic::Ordering::Acquire),
            }),
        })
    }
}

fn fixture(companion: bool) -> (CapsuleArtifact, PackageAdmissionUpload) {
    let mut capsule = artifact();
    capsule
        .manifest
        .execution
        .resource_budget_ceiling
        .state_read_bytes = 4 * 1024 * 1024;
    capsule
        .manifest
        .execution
        .resource_budget_ceiling
        .state_write_bytes = 2 * 1024 * 1024;
    capsule
        .manifest
        .execution
        .resource_budget_ceiling
        .effect_count = 1;
    capsule
        .manifest
        .execution
        .resource_budget_ceiling
        .child_calls = 0;
    capsule
        .manifest
        .execution
        .resource_budget_ceiling
        .outbound_requests = 0;
    capsule
        .manifest
        .execution
        .resource_budget_ceiling
        .blob_read_bytes = 0;
    capsule
        .manifest
        .execution
        .resource_budget_ceiling
        .blob_write_bytes = 0;
    let mut input = upload();
    input.layers[1].1 = JsonManifestCodec::default()
        .encode_capsule(&capsule.manifest)
        .unwrap();
    let mut config: Value = serde_json::from_slice(&input.configuration).unwrap();
    if companion {
        let value = json!({
            "apiVersion":"latent.dev/v1", "kind":"TransactionBinding",
            "capsule":capsule.manifest.metadata.name,
            "deployment":"transaction-storage", "binding":"transaction-storage",
            "profile":latent_core::transaction_contract::PROFILE,
            "hostAbiDigest":latent_manifest::phase4_host_abi_digest(),
            "namespace":"transaction-storage", "stateSchema":format!("sha256:{}", "1".repeat(64)),
            "operations":[{"operation":"update", "mode":"strict-command",
                "inputFormat":"lsf-wit-values-v1", "resultFormat":"lsf-wit-values-v1"}]
        });
        input.layers.push((
            "transaction-binding.json".into(),
            serde_json::to_vec(&value).unwrap(),
        ));
        config["layers"].as_array_mut().unwrap().push(json!({
            "path":"transaction-binding.json", "role":"asset",
            "mediaType":"application/vnd.latent.transaction-binding.v1+json"
        }));
    }
    for (layer, (path, bytes)) in config["layers"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .zip(&input.layers)
    {
        layer["path"] = json!(path);
        layer["digest"] = json!(artifact_blob_digest(bytes).as_str());
        layer["size"] = json!(bytes.len());
    }
    input.configuration = serde_json::to_vec(&config).unwrap();
    let mut manifest: Value = serde_json::from_slice(&input.manifest).unwrap();
    manifest["config"]["digest"] = json!(artifact_blob_digest(&input.configuration).as_str());
    manifest["config"]["size"] = json!(input.configuration.len());
    manifest["layers"] = Value::Array(config["layers"].as_array().unwrap().iter().map(|layer| json!({
        "mediaType":layer["mediaType"], "digest":layer["digest"], "size":layer["size"],
        "annotations":{"org.opencontainers.image.title":layer["path"], "dev.latent.layer.role":layer["role"]}
    })).collect());
    input.manifest = serde_json::to_vec(&manifest).unwrap();
    // This test authority deliberately supplies no publisher evidence.
    input.signatures.clear();
    input.provenance.clear();
    (capsule, input)
}

fn open(root: &TempRoot, capsule: CapsuleArtifact) -> DirectoryArtifactRepository {
    DirectoryArtifactRepository::open_enforced(
        root.path(),
        DirectoryArtifactRepositoryConfig::default(),
        AdmissionStorageLimits::default(),
        Arc::new(Host {
            authority: Authority::new(),
            artifact: capsule,
        }),
    )
    .unwrap()
}

#[test]
fn exact_admitted_companion_preserves_transaction_profile_across_reopen() {
    let root = TempRoot::new();
    let (capsule, input) = fixture(true);
    let digest = capsule.descriptor.release_digest.clone();
    let raw = VerifiedArtifactMetadata::from_artifact(capsule.clone()).unwrap();
    assert!(
        !raw.is_transaction_execution_profile(),
        "bare bytes cannot select the profile"
    );
    let repo = open(&root, capsule.clone());
    block_on(repo.admit_package(&tenant(), input, &mut |_| Ok(()))).unwrap();
    let metadata = block_on(repo.fetch_verified_metadata(&digest)).unwrap();
    assert!(metadata.is_transaction_execution_profile());
    assert_eq!(metadata.manifest(), &capsule.manifest);
    drop(repo);
    let repo = open(&root, capsule.clone());
    let reopened = block_on(repo.fetch_verified_metadata(&digest)).unwrap();
    assert_eq!(reopened, metadata);
    assert_eq!(block_on(repo.fetch(&digest)).unwrap(), capsule);
}

#[test]
fn transactional_ceiling_without_exact_companion_is_rejected_before_storage() {
    let root = TempRoot::new();
    let (capsule, input) = fixture(false);
    let repo = open(&root, capsule);
    let failure = block_on(repo.admit_package(&tenant(), input, &mut |_| Ok(()))).unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::InvalidArgument);
    super::assert_no_releases(&root);
}

#[test]
fn changed_companion_bytes_cannot_select_transaction_profile() {
    let root = TempRoot::new();
    let (capsule, mut input) = fixture(true);
    let companion = input.layers.last_mut().unwrap();
    companion.1[0] ^= 1;
    let repo = open(&root, capsule);
    assert!(block_on(repo.admit_package(&tenant(), input, &mut |_| Ok(()))).is_err());
    super::assert_no_releases(&root);
}

mod data {
    use super::*;
    use crate::local_repository::transaction_profile::from_upload;

    fn binding(capsule: &CapsuleArtifact, input: &PackageAdmissionUpload) -> AdmissionBinding {
        AdmissionBinding {
            tenant: tenant(),
            package: package_digest(&input.manifest),
            release: capsule.descriptor.release_digest.clone(),
            receipt: Vec::new(),
        }
    }

    #[test]
    fn only_exact_companion_bytes_select_the_structural_profile() {
        let (capsule, input) = fixture(true);
        assert!(from_upload(&input, &binding(&capsule, &input), &capsule.manifest).unwrap());
        let (capsule, input) = fixture(false);
        assert!(!from_upload(&input, &binding(&capsule, &input), &capsule.manifest).unwrap());
    }

    #[test]
    fn changed_original_capsule_or_companion_cannot_select_the_profile() {
        let (capsule, mut input) = fixture(true);
        let mut substituted = capsule.manifest.clone();
        substituted.metadata.name.push_str("-substituted");
        assert!(from_upload(&input, &binding(&capsule, &input), &substituted).is_err());
        input.layers.last_mut().unwrap().1[0] ^= 1;
        assert!(from_upload(&input, &binding(&capsule, &input), &capsule.manifest).is_err());
    }

    #[test]
    fn package_and_tenant_associations_remain_mandatory() {
        let (capsule, input) = fixture(true);
        let mut association = binding(&capsule, &input);
        association.tenant = latent_core::TenantId("other-tenant".into());
        assert!(from_upload(&input, &association, &capsule.manifest).is_err());
        association = binding(&capsule, &input);
        association.package = package_digest(b"different immutable package");
        assert!(from_upload(&input, &association, &capsule.manifest).is_err());
    }

    #[test]
    fn data_validation_cannot_authorize_an_unmarked_transactional_deployment() {
        let (capsule, input) = fixture(true);
        let mut deployment = JsonManifestCodec::default()
            .decode_deployment(include_bytes!(
                "../../../../../examples/echo-contract/deployment.json"
            ))
            .unwrap();
        deployment.release = capsule.descriptor.release_digest.clone();
        deployment.resources = capsule.manifest.execution.resource_budget_ceiling.clone();
        deployment.grants.clear();
        latent_manifest::validate_deployment_document(&deployment).unwrap();
        let raw = VerifiedArtifactMetadata::from_artifact(capsule.clone()).unwrap();
        assert!(raw.validate_deployment(&deployment).is_err());
        let selected = from_upload(&input, &binding(&capsule, &input), &capsule.manifest).unwrap();
        let retained = raw.with_transaction_execution_profile(selected);
        retained.validate_deployment(&deployment).unwrap();
        deployment.resources.state_read_bytes += 1;
        assert!(
            retained.validate_deployment(&deployment).is_err(),
            "original signed ceiling remains binding"
        );
    }
}
