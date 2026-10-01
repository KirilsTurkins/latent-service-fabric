use super::*;
use crate::deployment_operations::{
    DeploymentOperationContext, DeploymentOperationLookup, DeploymentOperationRequest,
};
use latent_manifest::{ContractImport, ManifestValidationProfile, ThreadingModel};

fn profile() -> ManifestValidationProfile {
    ManifestValidationProfile::phase4(
        latent_core::BudgetProfile::Phase4,
        latent_core::PHASE4_HOST_ABI_V1,
        &latent_manifest::phase4_host_abi_digest(),
    )
    .unwrap()
}
fn limits() -> Limits {
    Limits {
        manifest_profile: profile(),
        ..Limits::default()
    }
}
fn source() -> (Arc<Releases>, latent_manifest::DeploymentManifest) {
    let releases = Arc::new(Releases::default());
    let digest = releases.add("transaction-profile");
    let mut deployment = deployment("blue", "alice", &digest);
    let mut values = releases.values.write().unwrap();
    let artifact = values.get_mut(&digest).unwrap();
    artifact.manifest.imports = vec![ContractImport {
        contract: latent_core::ContractId("latent:state/key-value@0.2.0".into()),
        optional: false,
    }];
    artifact.manifest.execution.threading = ThreadingModel::SingleThreaded;
    artifact.manifest.execution.snapshot_eligible = false;
    artifact.manifest.execution.fusion_eligible = false;
    artifact
        .manifest
        .execution
        .resource_budget_ceiling
        .state_read_bytes = 32;
    artifact
        .manifest
        .execution
        .resource_budget_ceiling
        .state_write_bytes = 32;
    deployment.resources = artifact.manifest.execution.resource_budget_ceiling.clone();
    drop(values);
    (releases, deployment)
}

#[test]
fn transaction_route_publication_and_restart_use_selected_profile_without_changing_revision_identity(
) {
    let root = TempRoot::new();
    let (releases, deployment) = source();
    let strict = open(&root, &releases);
    assert!(run(strict.apply(deployment.clone())).is_err());
    drop(strict);
    let selected = run(Store::open(&root.0, releases.clone(), limits())).unwrap();
    run(selected.apply(deployment.clone())).unwrap();
    let revision = crate::deployment_revision_id_with_profile(&deployment, profile()).unwrap();
    let pinned = selected.resolve(&target("alice", None), None).unwrap();
    assert_eq!(pinned.revision, revision);
    let mut excessive = deployment.clone();
    excessive.resources.state_write_bytes += 1;
    assert!(run(selected.apply(excessive)).is_err());
    drop(selected);
    assert!(run(Store::open(&root.0, releases.clone(), Limits::default())).is_err());
    let recovered = run(Store::open(&root.0, releases, limits())).unwrap();
    assert_eq!(
        run(DeploymentStore::get(&recovered, &deployment.id)).unwrap(),
        Some(deployment)
    );
    assert_eq!(
        recovered
            .resolve(&target("alice", None), None)
            .unwrap()
            .revision,
        revision
    );
}

#[test]
fn managed_transaction_deployment_retains_original_request_preconditions_and_replay() {
    let root = TempRoot::new();
    let (releases, manifest) = source();
    let store = run(Store::open(&root.0, releases.clone(), limits())).unwrap();
    let request = DeploymentOperationRequest::Apply {
        context: DeploymentOperationContext {
            tenant: TenantId("alice".into()),
            actor: latent_artifacts::ReleaseActor {
                subject: "original-operator".into(),
                kind: latent_artifacts::ReleaseActorKind::Host,
            },
            operation_id: "original-operation".into(),
            expected_state_version: 0,
        },
        manifest,
        expected_generation: 0,
    };
    assert!(request.validate().is_err());
    let digest = request.request_digest_with_profile(profile()).unwrap();
    let prepared = run(store.prepare_operation(request.clone())).unwrap();
    let committed = store.commit_operation(prepared).unwrap();
    assert_eq!(committed.value().receipt.request_digest, digest);
    assert_eq!(committed.value().receipt.expected_generation, 0);
    assert_eq!(committed.value().receipt.expected_state_version, 0);
    drop(committed);
    let replay = run(store.prepare_operation(request.clone())).unwrap();
    assert!(replay.replayed());
    drop(replay);
    let mut changed = request;
    let DeploymentOperationRequest::Apply {
        expected_generation,
        ..
    } = &mut changed
    else {
        unreachable!()
    };
    *expected_generation = 1;
    assert!(run(store.prepare_operation(changed)).is_err());
    drop(store);
    let recovered = run(Store::open(&root.0, releases, limits())).unwrap();
    let found =
        run(recovered.get_operation(&TenantId("alice".into()), "original-operation")).unwrap();
    assert!(
        matches!(found.value(),DeploymentOperationLookup::Found(receipt) if receipt.request_digest == digest)
    );
}
