use std::sync::Arc;
use std::time::Duration;

use latent_core::ActivationId;
use latent_scheduler::CellClass;
use latent_wire::invocation::{
    ActivationCleanupHandle, ActivationCleanupOwner, InvocationLimits, InvocationService,
    InvocationServiceAdapter, InvocationServiceServices, LocalInvocationRuntime,
};
use tokio::time::Instant;
use tonic::Code;

#[tokio::test(start_paused = true)]
async fn native_adapter_retention_survives_drop_until_real_lifecycle_cleanup() {
    use std::sync::atomic::{AtomicBool, Ordering};
    struct Retention {
        manager: latent_node::LocalActivationManager,
        gone: Arc<AtomicBool>,
    }
    impl Drop for Retention {
        fn drop(&mut self) {
            assert_eq!(
                self.manager.journal().snapshot().active,
                0,
                "lifecycle must retire before adapter bytes"
            );
            self.gone.store(true, Ordering::Release);
        }
    }
    let h = Harness::standard();
    let (_, owner) = supervised(&h, 1);
    h.backend.gate.close();
    let slot = owner.handle().reserve_activation().unwrap();
    let handle = h
        .manager
        .start(super::model::request("retained-native"))
        .unwrap();
    let gone = Arc::new(AtomicBool::new(false));
    let mut active = Box::pin(slot.own(
        handle,
        Retention {
            manager: h.manager.clone(),
            gone: gone.clone(),
        },
    ));
    pending(active.as_mut()).await;
    assert_eq!(h.manager.journal().snapshot().active, 1);
    drop(active);
    tokio::task::yield_now().await;
    assert!(!gone.load(Ordering::Acquire));
    assert_eq!(owner.snapshot().running, 1);
    assert!(owner.handle().reserve_activation().is_err());
    h.backend.gate.open();
    completed(&owner.handle(), 1).await;
    assert!(gone.load(Ordering::Acquire));
    h.assert_idle();
    owner
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
}

use super::support::{
    authenticated, cancel, finish, pending, request, status, tenant, Adapter, Harness,
};

fn supervised(harness: &Harness, capacity: usize) -> (Adapter, ActivationCleanupOwner) {
    let owner = ActivationCleanupOwner::start(
        capacity,
        Duration::from_millis(100),
        &tokio::runtime::Handle::current(),
    )
    .unwrap();
    let runtime = LocalInvocationRuntime::with_cleanup(
        harness.manager.clone(),
        InvocationLimits::default(),
        owner.handle(),
    )
    .unwrap();
    let adapter = InvocationServiceAdapter::with_services(
        Arc::new(runtime),
        InvocationLimits::default(),
        InvocationServiceServices {
            clock: harness.clock.clone(),
            ..InvocationServiceServices::default()
        },
    )
    .unwrap();
    (adapter, owner)
}

async fn completed(port: &ActivationCleanupHandle, count: u64) {
    finish(async {
        while port.snapshot().completed < count {
            tokio::task::yield_now().await;
        }
    })
    .await;
}

#[tokio::test(start_paused = true)]
async fn transient_tracking_retains_real_quota_refusal_without_guest_or_cleanup_ownership() {
    use latent_core::diagnostic::{DiagnosticReason, DiagnosticStage};
    use std::sync::atomic::Ordering;

    let harness = Harness::with_transient_tracking();
    let (adapter, owner) = supervised(&harness, 4);
    harness.backend.gate.close();
    let mut first = Box::pin(adapter.invoke(authenticated(request("tracking-first"))));
    let mut second = Box::pin(adapter.invoke(authenticated(request("tracking-second"))));
    let mut queued = Box::pin(adapter.invoke(authenticated(request("tracking-queued"))));
    pending(first.as_mut()).await;
    pending(second.as_mut()).await;
    pending(queued.as_mut()).await;
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 2);
    assert_eq!(
        harness.scheduler.observations(CellClass::Tiny).queue_depth,
        1
    );
    let before = harness.quotas.snapshot_now(&tenant()).unwrap();
    assert_eq!(before.active_activations, 3);
    assert_eq!(owner.snapshot().reserved, 3);
    let refused = finish(adapter.invoke(authenticated(request("tracking-refused"))))
        .await
        .expect("known platform outcome, not a transport error")
        .into_inner();
    let Some(latent_wire::invocation::proto::invoke_response::Result::PlatformFailure(failure)) =
        refused.result
    else {
        panic!("the unchanged admission quota must refuse this request");
    };
    assert_eq!(failure.code, "resource-exhausted");
    let retained = harness
        .manager
        .journal()
        .inspect_tree(&tenant(), &ActivationId("tracking-refused".into()), 8, None)
        .unwrap();
    assert_eq!(retained.nodes.len(), 1);
    let root = &retained.nodes[0];
    assert!(root.parent_activation_id.is_none());
    assert!(root.diagnostic_is_terminal);
    let diagnostic = root
        .diagnostic
        .as_ref()
        .expect("closed producer pressure reason");
    assert_eq!(diagnostic.stage, DiagnosticStage::Admission);
    assert_eq!(diagnostic.reason, DiagnosticReason::QueuePressure);
    assert_eq!(harness.backend.entered.load(Ordering::Relaxed), 2);
    assert_eq!(harness.quotas.snapshot_now(&tenant()).unwrap(), before);
    assert_eq!(harness.manager.journal().snapshot().active, 3);
    assert_eq!(
        harness.manager.cancellation_snapshot().active_registrations,
        3
    );
    assert_eq!(
        owner.snapshot().reserved,
        3,
        "transient cleanup slot was refunded"
    );
    assert_eq!(owner.snapshot().queued, 0);
    assert_eq!(owner.snapshot().running, 0);
    harness.backend.gate.open();
    finish(first).await.unwrap();
    finish(second).await.unwrap();
    finish(queued).await.unwrap();
    harness.assert_idle();
    assert_eq!(owner.snapshot().reserved, 0);
    owner
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
}

#[tokio::test(start_paused = true)]
async fn running_drop_retains_real_lifecycle_until_ack_then_recovers_same_cell() {
    let harness = Harness::new(1, 8);
    let (adapter, owner) = supervised(&harness, 8);
    let port = owner.handle();
    for ordinal in 0..3 {
        let id = format!("supervised-drop-{ordinal}");
        harness.backend.gate.close();
        let mut invocation = Box::pin(adapter.invoke(authenticated(request(&id))));
        pending(invocation.as_mut()).await;
        assert_eq!(status(&adapter, &id).await.phase, "running");
        drop(invocation);
        tokio::task::yield_now().await;
        assert_eq!(port.snapshot().running, 1);
        assert_eq!(harness.manager.journal().snapshot().active, 1);
        assert_eq!(
            harness.manager.cancellation_snapshot().active_registrations,
            1
        );
        assert_eq!(
            harness
                .quotas
                .snapshot_now(&tenant())
                .unwrap()
                .active_activations,
            1
        );
        assert_eq!(
            harness
                .scheduler
                .observations(CellClass::Tiny)
                .active_leases,
            1
        );
        assert_eq!(status(&adapter, &id).await.terminal_state, None);
        harness.backend.gate.open();
        completed(&port, ordinal + 1).await;
        assert_eq!(
            status(&adapter, &id).await.terminal_state.as_deref(),
            Some("cancelled")
        );
        assert_eq!(
            harness.scheduler.observations(CellClass::Tiny).quarantined,
            0
        );
        finish(adapter.invoke(authenticated(request(&format!("recovered-{ordinal}")))))
            .await
            .unwrap();
        harness.assert_idle();
    }
    let snapshot = owner
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
    assert_eq!(snapshot.handoffs, 3);
    assert_eq!(snapshot.completed, 3);
    assert!(snapshot.driver_joined);
}

#[tokio::test(start_paused = true)]
async fn full_cleanup_capacity_rejects_before_identity_and_ordinary_completion_refunds() {
    let harness = Harness::new(2, 8);
    let (adapter, owner) = supervised(&harness, 2);
    harness.backend.gate.close();
    let mut first = Box::pin(adapter.invoke(authenticated(request("slot-first"))));
    let mut second = Box::pin(adapter.invoke(authenticated(request("slot-second"))));
    pending(first.as_mut()).await;
    pending(second.as_mut()).await;
    assert_eq!(owner.snapshot().reserved, 2);
    let error = finish(adapter.invoke(authenticated(request("slot-rejected"))))
        .await
        .unwrap_err();
    assert_eq!(error.code(), Code::ResourceExhausted);
    assert!(harness
        .manager
        .status(&tenant(), &ActivationId("slot-rejected".to_owned()))
        .unwrap()
        .is_none());
    assert_eq!(harness.manager.journal().snapshot().active, 2);
    harness.backend.gate.open();
    finish(first).await.unwrap();
    assert_eq!(owner.snapshot().reserved, 1);
    finish(adapter.invoke(authenticated(request("slot-rejected"))))
        .await
        .unwrap();
    finish(second).await.unwrap();
    assert_eq!(owner.snapshot().reserved, 0);
    assert_eq!(owner.snapshot().handoffs, 0);
    harness.assert_idle();
    owner
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
}

#[tokio::test(start_paused = true)]
async fn deadline_handoff_preserves_explicit_cancel_priority_and_original_expiry() {
    for explicit in [false, true] {
        let harness = Harness::new(1, 8);
        let (adapter, owner) = supervised(&harness, 8);
        let port = owner.handle();
        harness.backend.gate.close();
        let mut input = authenticated(request("deadline-handoff"));
        input.set_timeout(Duration::from_millis(20));
        let mut invocation = Box::pin(adapter.invoke(input));
        pending(invocation.as_mut()).await;
        assert_eq!(status(&adapter, "deadline-handoff").await.phase, "running");
        let original_deadline = harness.backend.deadlines.lock().unwrap()[0];
        if explicit {
            cancel(&adapter, "deadline-handoff").await;
        }
        harness.clock.advance(Duration::from_millis(21));
        let result = finish(invocation).await.unwrap_err();
        assert_eq!(result.code(), Code::DeadlineExceeded);
        tokio::task::yield_now().await;
        assert_eq!(port.snapshot().running, 1);
        harness.backend.gate.open();
        completed(&port, 1).await;
        let terminal = status(&adapter, "deadline-handoff").await;
        assert_eq!(
            terminal.terminal_state.as_deref(),
            Some(if explicit {
                "cancelled"
            } else {
                "deadline_exceeded"
            })
        );
        assert_eq!(
            harness.backend.deadlines.lock().unwrap().as_slice(),
            &[original_deadline]
        );
        assert_eq!(
            harness.scheduler.observations(CellClass::Tiny).quarantined,
            0
        );
        harness.assert_idle();
        owner
            .shutdown(Instant::now() + Duration::from_secs(1))
            .await
            .unwrap();
    }
}
