use super::fixture::Fixture;
use latent_activation::ActivationOutcome;
use latent_core::{ActivationId, PlatformErrorCode, TenantId};
use latent_routing::RouteResolver;
use std::time::Duration;

const ANSWER: u32 = u32::from_le_bytes(*b"[42]");
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn oversized_input_unknown_targets_and_expired_deadline_never_start_children() {
    let f = Fixture::new(2, false, true).await;
    for (mode, expected) in [(4, 2003), (5, 2004), (6, 2004), (7, 2001)] {
        assert_eq!(
            value(
                f.manager
                    .start(f.request(&format!("invalid-{mode}"), mode))
                    .unwrap()
                    .await
            ),
            expected
        );
        f.idle().await;
    }
    assert_eq!(f.observations.starts.lock().unwrap().len(), 4);
    // Fresh Store memory must not retain the previous call's mutated arguments.
    assert_eq!(
        value(f.manager.start(f.request("fresh-memory", 0)).unwrap().await),
        ANSWER
    );
    f.idle().await;
}
// The injected verifier deliberately has a nonblocking exclusive start fence.
// One executor thread avoids unrelated verifier contention while both canonical
// async imports retain separate live child grants before either is awaited.
#[tokio::test]
async fn concurrent_imports_reserve_distinct_children_and_cannot_reuse_a_spent_call_grant() {
    let f = Fixture::new(3, false, true).await;
    let receipt = f.manager.start(f.request("concurrent", 3)).unwrap().await;
    let ActivationOutcome::Succeeded(success) = &receipt.outcome else {
        panic!("{:?}", receipt.outcome)
    };
    assert_eq!(success.consumption.child_calls, 2);
    assert!(success.consumption.cpu_fuel < super::packages::budget().cpu_fuel);
    assert!(success.consumption.peak_memory_bytes <= super::packages::budget().memory_bytes);
    assert_eq!(value(receipt), ANSWER);
    assert_eq!(f.observations.starts.lock().unwrap().len(), 3);
    f.idle().await;
    let mut request = f.request("one-child-grant", 3);
    request.budget.child_calls = 1;
    let receipt = f.manager.start(request).unwrap().await;
    let ActivationOutcome::Succeeded(success) = &receipt.outcome else {
        panic!("{:?}", receipt.outcome)
    };
    assert_eq!(success.consumption.child_calls, 1);
    assert_eq!(value(receipt), 2003);
    assert_eq!(f.observations.starts.lock().unwrap().len(), 5);
    f.idle().await;
}

fn value(receipt: latent_node::ActivationReceipt) -> u32 {
    match receipt.outcome {
        ActivationOutcome::Succeeded(success) => {
            serde_json::from_slice::<Vec<u32>>(&success.output).unwrap()[0]
        }
        outcome => panic!("{outcome:?}"),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn denied_service_publication_never_starts_a_child() {
    for foreign in [false, true] {
        let f = Fixture::new(2, foreign, false).await;
        let receipt = f.manager.start(f.request("denied", 0)).unwrap().await;
        assert_eq!(value(receipt), 2004); // WIT permission-denied
        assert_eq!(f.observations.starts.lock().unwrap().len(), 1);
        f.idle().await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn explicit_cross_tenant_policy_and_fresh_activation_identity() {
    let f = Fixture::new(2, true, true).await;
    for root in ["first-root", "second-root"] {
        let mut request = f.request(root, 0);
        request
            .principal
            .claims
            .insert("operator".into(), "true".into());
        request
            .metadata
            .insert("root-activation-id".into(), "forged-root".into());
        assert_eq!(value(f.manager.start(request).unwrap().await), ANSWER);
        f.idle().await;
    }
    let starts = f.observations.starts.lock().unwrap();
    assert_eq!(starts.len(), 4);
    for (index, root) in ["first-root", "second-root"].into_iter().enumerate() {
        let child = &starts[index * 2 + 1];
        assert_eq!(child.parent_activation_id.as_ref().unwrap().0, root);
        assert_eq!(child.root_activation_id.0, root);
        assert_eq!(child.trace_id.0, root);
        assert_eq!(child.tenant.0, "tenant-b");
        assert_eq!(child.service.0, "callee");
    }
    assert_ne!(starts[1].activation_id, starts[3].activation_id);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn declared_failure_is_distinct_from_a_platform_failure() {
    let f = Fixture::new(2, false, true).await;
    assert_eq!(
        value(f.manager.start(f.request("declared", 1)).unwrap().await),
        1000
    );
    let events = f
        .manager
        .events(
            &TenantId("tenant-a".into()),
            &ActivationId("child-1".into()),
        )
        .unwrap();
    assert!(!events.is_empty());
    f.idle().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn parent_occupying_the_only_cell_rejects_children_promptly_and_keeps_running() {
    let f = Fixture::new(1, false, true).await;
    for id in ["saturated-first", "saturated-again"] {
        let receipt = tokio::time::timeout(
            Duration::from_secs(2),
            f.manager.start(f.request(id, 0)).unwrap(),
        )
        .await
        .expect("child must not queue behind its parent");
        assert_eq!(value(receipt), 2003); // WIT resource-exhausted
        f.idle().await;
    }
    assert_eq!(f.backend.resource_snapshot().stores_created, 2);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancellation_during_child_execution_reclaims_both_stores_and_reservations() {
    let f = Fixture::new(2, false, true).await;
    let parent = tokio::spawn(f.manager.start(f.request("cancel-root", 2)).unwrap());
    tokio::time::timeout(
        Duration::from_secs(2),
        f.observations.child_running.notified(),
    )
    .await
    .expect("real child reached execution");
    assert_eq!(
        f.manager
            .cancel_for(
                &TenantId("tenant-a".into()),
                &ActivationId("cancel-root".into()),
                "test"
            )
            .unwrap(),
        latent_core::CancelDisposition::Accepted
    );
    let receipt = tokio::time::timeout(Duration::from_secs(2), parent)
        .await
        .unwrap()
        .unwrap();
    assert!(
        matches!(receipt.outcome, ActivationOutcome::Failed { error, .. } if error.code == PlatformErrorCode::Cancelled)
    );
    f.idle().await;
    assert_eq!(
        value(f.manager.start(f.request("after-cancel", 0)).unwrap().await),
        ANSWER
    );
    f.idle().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn abandoning_parent_awaiter_still_drives_child_cleanup() {
    let f = Fixture::new(2, false, true).await;
    let parent = tokio::spawn(f.manager.start(f.request("abandoned", 2)).unwrap());
    tokio::time::timeout(
        Duration::from_secs(2),
        f.observations.child_running.notified(),
    )
    .await
    .unwrap();
    parent.abort();
    assert!(parent.await.unwrap_err().is_cancelled());
    f.idle().await;
    // Dropping an executing root without a cleanup receipt quarantines its
    // cell. The node-owned child completes cleanup and leaves its cell usable.
    let mut request = f.request("after-abandon", 0);
    request.target.service = latent_core::ServiceId("callee".into());
    request.target.contract = latent_core::ContractId(super::component::CALLEE.into());
    request.target.function = latent_core::FunctionId("answer".into());
    request.input = b"[]".to_vec();
    assert_eq!(value(f.manager.start(request).unwrap().await), 42);
    f.idle().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn changed_route_requires_a_new_plan_and_revocation_denies_cached_target() {
    use latent_capabilities::broker::CapabilityPlanSource;
    use latent_control_store::DeploymentStore;
    let f = Fixture::new(2, false, true).await;
    let old_revision = f
        .store
        .pin()
        .unwrap()
        .resolve(&f.request("pin", 0).target, None)
        .unwrap();
    let old = f.store.plan(&old_revision).unwrap();
    assert_eq!(
        value(f.manager.start(f.request("warm", 0)).unwrap().await),
        ANSWER
    );
    let mut changed = f.target.clone();
    changed.resources.cpu_fuel -= 1;
    f.store.apply(changed).await.unwrap();
    assert!(old.check_eligible().is_err());
    assert_eq!(
        value(f.manager.start(f.request("new-plan", 0)).unwrap().await),
        ANSWER
    );
    f.revoke_target();
    let receipt = f.manager.start(f.request("revoked", 0)).unwrap().await;
    match receipt.outcome {
        ActivationOutcome::Succeeded(success) => assert_eq!(
            serde_json::from_slice::<Vec<u32>>(&success.output).unwrap(),
            [2004]
        ),
        ActivationOutcome::Failed { error, .. } => assert!(matches!(
            error.code,
            PlatformErrorCode::PermissionDenied
                | PlatformErrorCode::Unavailable
                | PlatformErrorCode::RouteUnavailable
        )),
        outcome @ ActivationOutcome::DeclaredError { .. } => panic!("{outcome:?}"),
    }
    assert_eq!(
        f.observations
            .starts
            .lock()
            .unwrap()
            .iter()
            .filter(|c| c.parent_activation_id.is_some())
            .count(),
        2
    );
    f.idle().await;
}
