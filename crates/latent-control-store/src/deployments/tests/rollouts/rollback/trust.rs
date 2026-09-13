use super::*;
use crate::deployments::tests::{lifecycle, supply_chain::authority};
use latent_artifacts::{
    AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, ReleaseLifecycleAction,
    ReleaseLifecycleReason, ReleaseMutationContext, ReleaseOperationPrecondition,
};
use latent_core::ReleaseDigest;

struct Fixture {
    store: Store,
    releases: Arc<DirectoryArtifactRepository>,
    base: ReleaseDigest,
    candidate: ReleaseDigest,
    roots: [TempRoot; 2],
}
impl Fixture {
    fn new() -> Self {
        let roots = [TempRoot::new(), TempRoot::new()];
        let releases = Arc::new(
            DirectoryArtifactRepository::open(
                &roots[0].0,
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        );
        let base = run(releases.publish(artifact("rollback-base")))
            .unwrap()
            .release_digest;
        let candidate = run(releases.publish(artifact("rollback-candidate")))
            .unwrap()
            .release_digest;
        let store = run(Store::open_with_catalog(
            &roots[1].0,
            releases.clone(),
            Limits::default(),
            releases.lifecycle_authority(),
            lifecycle::profile("47.0.3"),
        ))
        .unwrap();
        run(store.apply(deployment("base", "alice", &base))).unwrap();
        let mut proposed = deployment("candidate", "alice", &candidate);
        proposed.route_weight = 2500;
        execute(
            &store,
            RolloutRequest::Start {
                context: context("start", 0),
                spec: StartRolloutSpec {
                    id: id(),
                    base: DeploymentExpectation {
                        id: DeploymentId("base".into()),
                        generation: 1,
                    },
                    candidate: proposed,
                    candidate_weights: vec![2500, 10000],
                    canary_policy: None,
                },
            },
        );
        execute(
            &store,
            change("complete", 1, RolloutCommand::Advance { next_step: 1 }),
        );
        Self {
            store,
            releases,
            base,
            candidate,
            roots,
        }
    }
}

#[test]
fn revoked_candidate_can_restore_current_base_and_replay_never_revives_revoked_target() {
    let Fixture {
        store,
        releases,
        base,
        candidate,
        roots,
    } = Fixture::new();
    let held = store.pin().unwrap();
    lifecycle::revoke(&releases, &candidate);
    assert_code(
        held.resolve(&target("alice", None), None),
        Code::PermissionDenied,
    );
    let rollback = request("restore", 2);
    let restored = execute(&store, rollback.clone());
    assert_eq!(
        store.resolve(&target("alice", None), None).unwrap().release,
        base
    );
    assert_code(
        held.resolve(&target("alice", None), None),
        Code::PermissionDenied,
    );
    // A distinct operation id is needed because catalog lifecycle ids are scoped
    // to the tenant, not merely to one release.
    revoke(
        &releases,
        LifecycleScope::LocalUnscoped,
        &base,
        "revoke-base",
    );
    assert_eq!(execute(&store, rollback.clone()).receipt, restored.receipt);
    assert_code(
        store.resolve(&target("alice", None), None),
        Code::PermissionDenied,
    );
    drop(store);
    let store = run(Store::open_with_catalog(
        &roots[1].0,
        releases.clone(),
        Limits::default(),
        releases.lifecycle_authority(),
        lifecycle::profile("47.0.3"),
    ))
    .unwrap();
    assert_eq!(
        store.get_rollout(&alice(), &id()).unwrap().unwrap().state,
        RolloutState::RolledBack
    );
    assert_eq!(execute(&store, rollback).receipt, restored.receipt);
    assert_code(
        store.resolve(&target("alice", None), None),
        Code::PermissionDenied,
    );
}

#[test]
fn revoked_target_fails_both_preparation_and_final_commit_without_catalog_mutation() {
    for after_prepare in [false, true] {
        let fixture = Fixture::new();
        let before = std::fs::read(fixture.roots[1].0.join("catalog.json")).unwrap();
        let pending = after_prepare
            .then(|| run(fixture.store.prepare_rollout(request("restore", 2))).unwrap());
        lifecycle::revoke(&fixture.releases, &fixture.base);
        if let Some(pending) = pending {
            assert_code(
                fixture.store.commit_rollout(pending),
                Code::PermissionDenied,
            );
        } else {
            assert_code(
                run(fixture.store.prepare_rollout(request("restore", 2))),
                Code::PermissionDenied,
            );
        }
        assert_eq!(
            std::fs::read(fixture.roots[1].0.join("catalog.json")).unwrap(),
            before
        );
        assert_eq!(
            fixture
                .store
                .get_rollout_operation(&alice(), &id(), "restore")
                .unwrap(),
            RolloutOperationLookup::Unknown
        );
        assert_eq!(
            fixture
                .store
                .resolve(&target("alice", None), None)
                .unwrap()
                .release,
            fixture.candidate
        );
    }
}

fn revoke(
    repository: &DirectoryArtifactRepository,
    scope: LifecycleScope,
    release: &ReleaseDigest,
    operation: &str,
) {
    run(repository.change_release_lifecycle(
        ReleaseMutationContext {
            scope,
            actor: ReleaseActor {
                subject: "rollback-test".into(),
                kind: ReleaseActorKind::Host,
            },
            operation: Some(ReleaseOperationPrecondition {
                operation_id: operation.into(),
                expected_generation: 1,
            }),
        },
        release,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    ))
    .unwrap();
}

#[test]
fn legacy_enforced_store_compares_real_retained_packages_after_candidate_revocation() {
    let tenant = TenantId("tests".into());
    let old = super::super::compatibility::package(false, false);
    let candidate = super::super::compatibility::package(false, true);
    let artifacts = [
        super::super::compatibility::artifact_for(&old),
        super::super::compatibility::artifact_for(&candidate),
    ];
    let authority = authority::Authority::new_many(artifacts.to_vec());
    let roots = [TempRoot::new(), TempRoot::new()];
    let repository = Arc::new(
        DirectoryArtifactRepository::open_enforced(
            &roots[0].0,
            DirectoryArtifactRepositoryConfig::default(),
            AdmissionStorageLimits::default(),
            authority.clone(),
        )
        .unwrap(),
    );
    for bundle in [&old, &candidate] {
        run(repository.admit_package(
            &tenant,
            super::super::compatibility::upload(bundle),
            &mut |_| Ok(()),
        ))
        .unwrap();
    }
    let store = run(Store::open_enforced(
        &roots[1].0,
        repository.clone(),
        Limits::default(),
        authority,
    ))
    .unwrap();
    let mut base = deployment("base", &tenant.0, &artifacts[0].descriptor.release_digest);
    base.service
        .0
        .clone_from(&artifacts[0].manifest.metadata.name);
    run(store.apply(base.clone())).unwrap();
    let mut proposed = deployment(
        "candidate",
        &tenant.0,
        &artifacts[1].descriptor.release_digest,
    );
    proposed.service = base.service.clone();
    proposed.route_weight = 2500;
    let mut start_context = context("start", 0);
    start_context.tenant = tenant.clone();
    execute(
        &store,
        RolloutRequest::Start {
            context: start_context,
            spec: StartRolloutSpec {
                id: id(),
                base: DeploymentExpectation {
                    id: base.id.clone(),
                    generation: 1,
                },
                candidate: proposed,
                candidate_weights: vec![2500, 10000],
                canary_policy: None,
            },
        },
    );
    revoke(
        &repository,
        LifecycleScope::Tenant(tenant.clone()),
        &artifacts[1].descriptor.release_digest,
        "revoke-candidate",
    );
    let mut rollback = request("restore", 1);
    let RolloutRequest::Change { context, .. } = &mut rollback else {
        unreachable!()
    };
    context.tenant = tenant.clone();
    let receipt = execute(&store, rollback).receipt;
    assert_eq!(receipt.state, RolloutState::RolledBack);
    assert_eq!(run(store.list()).unwrap(), vec![base]);
    let row = store.get_rollout(&tenant, &id()).unwrap().unwrap();
    assert_eq!(row.base.package.as_ref(), Some(old.layout().digest()));
    assert_eq!(
        row.candidate.package.as_ref(),
        Some(candidate.layout().digest())
    );
}
