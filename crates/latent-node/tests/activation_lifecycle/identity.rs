use std::sync::atomic::Ordering;
use std::time::Duration;

use latent_core::{
    ActivationId, ActivationPhase, ActivationTerminalState, CancelDisposition, PlatformErrorCode,
    RouteGeneration, TenantId,
};

use super::model::request;
use super::support::{finish, pending, tenant, Harness};

#[tokio::test]
async fn assigns_absent_identity_and_preserves_explicit_correlation_without_local_ancestry() {
    let harness = Harness::standard();
    let mut input = request("unused");
    input.activation_id = None;
    let handle = harness.manager.start(input).expect("start generated");
    assert_eq!(handle.activation_id().0, "generated-1");
    assert_eq!(
        harness.status("generated-1").phase,
        ActivationPhase::Received
    );
    let receipt = finish(handle).await;
    assert_eq!(receipt.activation_id.0, "generated-1");
    let first = harness.backend.requests.lock().expect("requests")[0].clone();
    assert_eq!(
        first.activation.root_activation_id,
        first.activation.activation_id
    );
    assert_eq!(first.activation.parent_activation_id, None);

    for (id, parent) in [("child", Some("unknown-parent")), ("root-only", None)] {
        let mut input = request(id);
        input.root_activation_id = Some(ActivationId("unknown-root".to_owned()));
        input.parent_activation_id = parent.map(|value| ActivationId(value.to_owned()));
        let expected = input.clone();
        let receipt = finish(harness.manager.start(input).expect("opaque lineage")).await;
        assert_eq!(receipt.activation_id.0, id);
        let requests = harness.backend.requests.lock().expect("requests");
        let observed = &requests.last().expect("invocation").activation;
        assert_eq!(
            observed.root_activation_id,
            expected.root_activation_id.unwrap()
        );
        assert_eq!(observed.parent_activation_id, expected.parent_activation_id);
        assert_eq!(observed.principal, expected.principal);
        assert_eq!(observed.trace, expected.trace);
        assert_eq!(observed.idempotency_key, expected.idempotency_key);
        assert_eq!(observed.metadata, expected.metadata);
    }
    assert_eq!(harness.ids.0.load(Ordering::Relaxed), 1);
    harness.assert_idle();
}

#[tokio::test]
async fn malformed_identity_and_foreign_principal_fail_without_lifecycle_or_backend_work() {
    let harness = Harness::standard();
    for (activation, root, parent) in [
        (Some(""), None, None),
        (Some("bad id"), None, None),
        (Some("bad\nid"), None, None),
        (Some("child"), Some(""), None),
        (Some("child"), Some("root"), Some("")),
        (Some("child"), None, Some("parent")),
    ] {
        let mut input = request("ignored");
        input.activation_id = activation.map(|value| ActivationId(value.to_owned()));
        input.root_activation_id = root.map(|value| ActivationId(value.to_owned()));
        input.parent_activation_id = parent.map(|value| ActivationId(value.to_owned()));
        let error = harness.manager.start(input).err().expect("invalid request");
        assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
    }
    let mut input = request("tenant-conflict");
    input.principal.tenant = Some(TenantId("tenant-b".to_owned()));
    assert_eq!(
        harness
            .manager
            .start(input)
            .err()
            .expect("scope rejection")
            .code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
    assert_eq!(harness.artifacts.entered.load(Ordering::Relaxed), 0);
    assert_eq!(
        harness
            .manager
            .cancel_for(&tenant(), &ActivationId(String::new()), "invalid")
            .expect_err("malformed cancellation is not a not-found disposition")
            .code,
        PlatformErrorCode::InvalidArgument
    );
    assert_eq!(harness.manager.journal().snapshot().begun, 0);
    let oversized_id = ActivationId("x".repeat(513));
    let oversized_tenant = TenantId("x".repeat(513));
    for (scope, id) in [
        (&tenant(), &oversized_id),
        (&oversized_tenant, &ActivationId("valid".to_owned())),
    ] {
        assert_eq!(
            harness
                .manager
                .status(scope, id)
                .expect_err("bounded status")
                .code,
            PlatformErrorCode::InvalidArgument
        );
        assert_eq!(
            harness
                .manager
                .events(scope, id)
                .expect_err("bounded events")
                .code,
            PlatformErrorCode::InvalidArgument
        );
        assert_eq!(
            harness
                .manager
                .cancel_for(scope, id, "cancel")
                .expect_err("bounded cancel")
                .code,
            PlatformErrorCode::InvalidArgument
        );
    }
    harness.assert_idle();
}

#[test]
fn spare_input_and_context_capacity_is_rejected_before_accepting_an_owner() {
    let harness = Harness::standard();
    for context in [false, true] {
        let mut input = request("spare-capacity");
        input.activation_id = None;
        if context {
            input.principal.subject.reserve(2 * 1024 * 1024);
        } else {
            input.input.reserve(2 * 1024 * 1024);
        }
        assert_eq!(
            harness
                .manager
                .start(input)
                .err()
                .expect("bounded retained allocation")
                .code,
            PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(harness.ids.0.load(Ordering::Relaxed), 0);
        assert_eq!(harness.manager.journal().snapshot().begun, 0);
        assert_eq!(
            harness.manager.cancellation_snapshot().active_registrations,
            0
        );
        harness.assert_idle();
    }
}

#[tokio::test]
async fn caller_id_is_available_before_poll_and_foreign_status_cancel_reveal_nothing() {
    let harness = Harness::standard();
    let handle = harness.manager.start(request("pending-id")).expect("start");
    let id = handle.activation_id().clone();
    assert_eq!(
        harness.status("pending-id").phase,
        ActivationPhase::Received
    );
    let foreign = TenantId("tenant-b".to_owned());
    assert!(harness
        .manager
        .status(&foreign, &id)
        .expect("foreign status")
        .is_none());
    assert!(harness
        .manager
        .events(&foreign, &id)
        .expect("foreign events")
        .is_empty());
    assert_eq!(
        harness
            .manager
            .cancel_for(&foreign, &id, "foreign")
            .expect("cancel"),
        CancelDisposition::NotFound
    );
    assert_eq!(
        harness
            .manager
            .cancel_for(&tenant(), &id, "before poll")
            .expect("cancel"),
        CancelDisposition::Accepted
    );
    assert_eq!(
        harness
            .manager
            .cancel_for(&tenant(), &id, "repeat")
            .expect("repeat cancel"),
        CancelDisposition::Accepted
    );
    let _receipt = finish(handle).await;
    assert_eq!(
        harness.status("pending-id").terminal_state,
        Some(ActivationTerminalState::Cancelled)
    );
    assert_eq!(
        harness
            .manager
            .cancel_for(&tenant(), &id, "late")
            .expect("late cancel"),
        CancelDisposition::AlreadyTerminal(ActivationTerminalState::Cancelled)
    );
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 0);
    harness.assert_idle();
}

#[tokio::test]
async fn duplicate_ids_and_bounded_terminal_eviction_never_replace_an_active_invocation() {
    let harness = Harness::new(1, 2);
    let active = harness.manager.start(request("active")).expect("active");
    assert_eq!(
        harness
            .manager
            .start(request("active"))
            .err()
            .expect("duplicate")
            .code,
        PlatformErrorCode::AlreadyExists
    );
    for id in ["oldest", "middle", "newest"] {
        let _receipt = finish(harness.manager.start(request(id)).expect("start")).await;
    }
    assert!(harness
        .manager
        .status(&tenant(), &ActivationId("oldest".to_owned()))
        .expect("old status")
        .is_none());
    assert_eq!(harness.status("active").phase, ActivationPhase::Received);
    assert_eq!(
        harness
            .manager
            .start(request("newest"))
            .err()
            .expect("retained collision")
            .code,
        PlatformErrorCode::AlreadyExists
    );
    let snapshot = harness.manager.journal().snapshot();
    assert_eq!(snapshot.active, 1);
    assert_eq!(snapshot.terminal, 2);
    assert!(snapshot.evicted >= 1);
    harness.clock.advance(Duration::from_secs(61));
    assert!(harness
        .manager
        .status(&tenant(), &ActivationId("newest".to_owned()))
        .expect("expired status")
        .is_none());
    assert_eq!(harness.status("active").phase, ActivationPhase::Received);
    drop(active);
    harness.assert_idle();
}

#[tokio::test]
async fn effective_ids_drive_deterministic_selection_and_catalog_state_stays_pinned() {
    let harness = Harness::standard();
    harness.artifacts.gate.close();
    let mut first = Box::pin(harness.manager.start(request("route-a")).expect("first"));
    pending(first.as_mut()).await;
    assert_eq!(
        harness.status("route-a").phase,
        ActivationPhase::Materializing
    );
    harness.catalog.generation.store(2, Ordering::Release);
    harness.artifacts.gate.open();
    let first = finish(first).await;
    let revision = first.resolved_revision.expect("pinned revision");
    assert_eq!(revision.route_generation, RouteGeneration(1));
    let observed = harness.backend.requests.lock().expect("requests")[0].clone();
    assert_eq!(
        observed.activation.resolved_revision.as_ref(),
        Some(&revision)
    );
    assert_eq!(observed.prepared.key.release, revision.release);
    assert_eq!(*harness.catalog.keys.lock().expect("keys"), ["route-a"]);
    let second = finish(harness.manager.start(request("route-b")).expect("second")).await;
    assert_eq!(
        second
            .resolved_revision
            .expect("new revision")
            .route_generation,
        RouteGeneration(2)
    );

    let other = Harness::standard();
    let repeated = finish(
        other
            .manager
            .start(request("route-a"))
            .expect("repeated key"),
    )
    .await;
    assert_eq!(
        repeated.resolved_revision.expect("repeat revision"),
        revision
    );
    let distinct = finish(
        other
            .manager
            .start(request("route-b"))
            .expect("distinct key"),
    )
    .await;
    assert_ne!(
        distinct
            .resolved_revision
            .expect("distinct revision")
            .release,
        revision.release
    );
    harness.assert_idle();
    other.assert_idle();
}
