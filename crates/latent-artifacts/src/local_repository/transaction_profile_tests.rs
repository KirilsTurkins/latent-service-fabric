use super::*;
use crate::local_repository::tests::lifecycle::{accept, context};
use crate::ManagedPublicationUpload;
use latent_manifest::{ContractImport, ManifestValidationProfile, ThreadingModel};

fn configured() -> DirectoryArtifactRepositoryConfig {
    DirectoryArtifactRepositoryConfig {
        manifest_profile: ManifestValidationProfile::phase4(
            latent_core::BudgetProfile::Phase4,
            latent_core::PHASE4_HOST_ABI_V1,
            &latent_manifest::phase4_host_abi_digest(),
        )
        .unwrap(),
        ..DirectoryArtifactRepositoryConfig::default()
    }
}
fn requested() -> CapsuleArtifact {
    let mut value = artifact("transaction-profile", b"catalog-metadata-only");
    value.manifest.imports = vec![ContractImport {
        contract: ContractId("latent:state/key-value@0.2.0".into()),
        optional: false,
    }];
    value.manifest.execution.threading = ThreadingModel::SingleThreaded;
    value.manifest.execution.snapshot_eligible = false;
    value.manifest.execution.fusion_eligible = false;
    value
        .manifest
        .execution
        .resource_budget_ceiling
        .state_read_bytes = 32;
    value
        .manifest
        .execution
        .resource_budget_ceiling
        .state_write_bytes = 32;
    value
        .manifest
        .execution
        .resource_budget_ceiling
        .wall_time_limit_millis = Some(1000);
    value
}

#[test]
fn transaction_catalog_requires_explicit_profile_on_publication_and_recovery() {
    let temp = TempRoot::new();
    let value = requested();
    let release = value.descriptor.release_digest.clone();
    let default = repository(temp.path());
    assert!(block_on(default.publish_managed(
        context("default-denial", 0),
        ManagedPublicationUpload::Local(value.clone()),
        &mut accept
    ))
    .is_err());
    drop(default);
    let selected = DirectoryArtifactRepository::open(temp.path(), configured()).unwrap();
    let receipt = block_on(selected.publish_managed(
        context("explicit-publication", 0),
        ManagedPublicationUpload::Local(value),
        &mut accept,
    ))
    .unwrap();
    assert!(selected
        .execution_eligibility_selected(&release, Some(&receipt.publication.id))
        .unwrap()
        .is_some());
    drop(selected);
    // Reopening without the actual profile fails, preserving the original files.
    assert!(DirectoryArtifactRepository::open(
        temp.path(),
        DirectoryArtifactRepositoryConfig::default()
    )
    .is_err());
    let recovered = DirectoryArtifactRepository::open(temp.path(), configured()).unwrap();
    let metadata = block_on(
        recovered.fetch_verified_metadata_selected(&release, Some(&receipt.publication.id)),
    )
    .unwrap();
    assert_eq!(
        metadata
            .manifest()
            .execution
            .resource_budget_ceiling
            .state_write_bytes,
        32
    );
}

#[test]
fn transaction_catalog_selection_never_converts_unsupported_networking_into_eligibility() {
    let temp = TempRoot::new();
    let selected = DirectoryArtifactRepository::open(temp.path(), configured()).unwrap();
    let mut value = requested();
    value.manifest.imports.push(ContractImport {
        contract: ContractId("wasi:sockets/tcp@0.2.0".into()),
        optional: false,
    });
    let release = value.descriptor.release_digest.clone();
    assert!(block_on(selected.publish_managed(
        context("network-denial", 0),
        ManagedPublicationUpload::Local(value),
        &mut accept
    ))
    .is_err());
    assert!(selected.execution_eligibility(&release).is_err());
}
