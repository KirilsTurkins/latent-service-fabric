use super::*;
use latent_artifacts::web::WebRenderMode;
use latent_artifacts::{
    ArtifactRepository, DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig,
    LifecycleScope, PublicationRef, ReleaseLifecycleAction, ReleaseLifecycleReason,
};
use latent_routing::InvocationTarget;

mod fixture;
use fixture::*;

fn start(
    store: &Store,
    artifacts: &DirectoryArtifactRepository,
    base: &PublicationRef,
    candidate: &PublicationRef,
) -> RolloutRequest {
    run(store.apply(selected(artifacts, base, "base"))).unwrap();
    let mut proposed = selected(artifacts, candidate, "candidate");
    proposed.route_weight = 2500;
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
    }
}

fn web_target() -> InvocationTarget {
    InvocationTarget {
        tenant: alice(),
        service: latent_core::ServiceId("web-rollout".into()),
        contract: latent_core::ContractId(latent_artifacts::web::WEB_CONTRACT.into()),
        function: latent_core::FunctionId("handle".into()),
        route: None,
    }
}

fn revoke(artifacts: &DirectoryArtifactRepository, publication: &PublicationRef, operation: &str) {
    artifacts
        .transition_web_publication(
            mutation(operation, 1),
            publication,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
}

fn rollback(operation: &str, revision: u64) -> RolloutRequest {
    change(
        operation,
        revision,
        RolloutCommand::Rollback {
            target_generation: RouteGeneration(1),
        },
    )
}

#[test]
fn web_canary_preserves_pinned_assets_and_restarts_with_revoked_candidate_identity_only() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let artifacts = open_artifacts(&roots[0]);
    let base = publish(&artifacts, "green", |_| {});
    let candidate = publish(&artifacts, "blue", |_| {});
    let store = open_store(&roots[1], &artifacts);
    let request = start(&store, &artifacts, &base, &candidate);
    let pin = store.pin().unwrap();
    let old = pin.resolve(&web_target(), Some("held-render")).unwrap();
    let assets = artifacts.read_web_asset(&base, "/index.html").unwrap();
    let first = execute(&store, request.clone());
    let status = store.get_rollout(&alice(), &id()).unwrap().unwrap();
    assert_eq!(
        status.base.package.as_ref(),
        Some(
            artifacts
                .select_web_publication(&base)
                .unwrap()
                .eligibility()
                .layout()
                .package()
        )
    );
    assert_ne!(status.base.component, status.candidate.component);
    assert_ne!(status.base.package, status.candidate.package);
    assert_eq!(
        pin.resolve(&web_target(), Some("held-render")).unwrap(),
        old
    );
    execute(
        &store,
        change("complete", 1, RolloutCommand::Advance { next_step: 1 }),
    );
    assert_eq!(
        store.resolve(&web_target(), None).unwrap().publication,
        Some(candidate.id.clone())
    );
    assert_eq!(
        assets.bytes(),
        artifacts
            .read_web_asset(&base, "/index.html")
            .unwrap()
            .bytes()
    );
    revoke(&artifacts, &candidate, "revoke-blue");
    assert_code(store.resolve(&web_target(), None), Code::PermissionDenied);
    drop(assets);
    drop(pin);
    drop(store);
    drop(artifacts);
    let artifacts = open_artifacts(&roots[0]);
    let store = open_store(&roots[1], &artifacts);
    assert_eq!(execute(&store, request).receipt, first.receipt);
    assert_code(store.resolve(&web_target(), None), Code::PermissionDenied);
    let restored = execute(&store, rollback("restore", 2));
    assert_eq!(restored.receipt.state, RolloutState::RolledBack);
    assert_eq!(
        store.resolve(&web_target(), None).unwrap().publication,
        Some(base.id.clone())
    );
    revoke(&artifacts, &base, "revoke-green");
    assert_eq!(
        execute(&store, rollback("restore", 2)).receipt,
        restored.receipt
    );
    assert_code(store.resolve(&web_target(), None), Code::PermissionDenied);
    drop(store);
    drop(artifacts);
    let artifacts = open_artifacts(&roots[0]);
    let store = open_store(&roots[1], &artifacts);
    assert_eq!(
        store.get_rollout(&alice(), &id()).unwrap().unwrap().state,
        RolloutState::RolledBack
    );
    assert_code(store.resolve(&web_target(), None), Code::PermissionDenied);
}

#[test]
fn web_rollout_rejects_route_removal_mode_change_and_backend_expansion_without_mutation() {
    for variant in ["removed", "mode", "backend", "profile"] {
        let roots = [TempRoot::new(), TempRoot::new()];
        let artifacts = open_artifacts(&roots[0]);
        let base = publish(&artifacts, "green", |_| {});
        let candidate = publish(&artifacts, variant, |manifest| match variant {
            "removed" => manifest.routes[0].path = "/new".into(),
            "mode" => {
                manifest.routes[0].mode = WebRenderMode::Prerender;
                manifest.routes[0].asset = Some("/index.html".into());
            }
            "backend" => {
                manifest.renderer.as_mut().unwrap().backend_profile =
                    latent_artifacts::web::WebBackendProfile::ScopedHttpGetV1
            }
            _ => {
                let renderer = manifest.renderer.as_mut().unwrap();
                renderer.profile = latent_artifacts::web::WebRendererProfile::WasmWebBufferedV1;
                renderer.profile_digest =
                    latent_manifest::renderer_profile_digest(renderer.profile).to_string();
            }
        });
        let store = open_store(&roots[1], &artifacts);
        let request = start(&store, &artifacts, &base, &candidate);
        let before = std::fs::read(roots[1].0.join("catalog.json")).unwrap();
        assert_code(
            run(store.prepare_rollout(request)),
            Code::IncompatibleContract,
        );
        assert_eq!(
            std::fs::read(roots[1].0.join("catalog.json")).unwrap(),
            before
        );
        assert!(store.get_rollout(&alice(), &id()).unwrap().is_none());
    }
}

#[test]
fn revoked_web_rollback_target_is_rejected_before_preparation_and_after_preflight() {
    for after_prepare in [false, true] {
        let roots = [TempRoot::new(), TempRoot::new()];
        let artifacts = open_artifacts(&roots[0]);
        let base = publish(&artifacts, "green", |_| {});
        let candidate = publish(&artifacts, "blue", |_| {});
        let store = open_store(&roots[1], &artifacts);
        let request = start(&store, &artifacts, &base, &candidate);
        execute(&store, request);
        execute(
            &store,
            change("complete", 1, RolloutCommand::Advance { next_step: 1 }),
        );
        let before = std::fs::read(roots[1].0.join("catalog.json")).unwrap();
        let prepared =
            after_prepare.then(|| run(store.prepare_rollout(rollback("restore", 2))).unwrap());
        revoke(&artifacts, &base, "revoke-base");
        if let Some(prepared) = prepared {
            assert_code(store.commit_rollout(prepared), Code::PermissionDenied);
        } else {
            assert_code(
                run(store.prepare_rollout(rollback("restore", 2))),
                Code::PermissionDenied,
            );
        }
        assert_eq!(
            std::fs::read(roots[1].0.join("catalog.json")).unwrap(),
            before
        );
        assert_eq!(
            store
                .get_rollout_operation(&alice(), &id(), "restore")
                .unwrap(),
            RolloutOperationLookup::Unknown
        );
    }
}
