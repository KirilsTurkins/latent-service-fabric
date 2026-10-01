use super::*;
use std::sync::atomic::Ordering;
#[tokio::test]
async fn final_request_gate_refuses_native_write_and_leaves_no_receipt_or_lifecycle_slot() {
    let mut fixture = Fixture::new(false).await;
    fixture.admission.reject_after.store(1, Ordering::Relaxed);
    assert!(fixture
        .backend
        .execute_state(
            context("alice"),
            fixture
                .mutation("create-original", c::NamespaceMutationKind::Create, 0)
                .into(),
        )
        .await
        .is_err());
    assert_eq!(fixture.admission.fences.load(Ordering::Relaxed), 2);
    let empty = fixture
        .store
        .with_store(StoreIoKind::Read, 65_536, |engine| {
            let view = engine.snapshot()?;
            view.scan(latent_state::embedded::Family::Namespace, b"", 128, 65_536)
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert!(empty.is_empty());
    assert_eq!(
        fixture
            .backend
            .0
            .services
            .namespaces
            .lifecycle()
            .retained_owners(),
        0
    );
    fixture
        .admission
        .reject_after
        .store(usize::MAX, Ordering::Relaxed);
    // A rejected management admission has no durable receipt to replay; the
    // explicit original operation remains unchanged when it is submitted again.
    let original = fixture.create().await;
    drop(original);
    fixture.finish().await;
}
use latent_core::test_support::{
    block_on,
    coordination::{with_watchdog, PollProbe, Rendezvous, Stage, WATCHDOG},
};
use latent_state::{
    embedded::AtomicBatch,
    session::{SessionLimits, StateMode, StateScope, StateSession},
    store_io::StoreIoKind,
};

#[tokio::test]
async fn concurrent_original_generation_checks_have_one_native_writer_without_refresh() {
    let mut fixture = Fixture::new(false).await;
    drop(fixture.create().await);
    let first = fixture.backend.execute_state(
        context("alice"),
        fixture
            .mutation("first-quiesce", c::NamespaceMutationKind::Quiesce, 1)
            .into(),
    );
    let second = fixture.backend.execute_state(
        context("bob"),
        fixture
            .mutation("second-quiesce", c::NamespaceMutationKind::Quiesce, 1)
            .into(),
    );
    let (first, second) = tokio::join!(first, second);
    let outcomes = [first, second];
    assert_eq!(outcomes.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        outcomes
            .iter()
            .filter(|result| result
                .as_ref()
                .is_err_and(|error| error.code == PlatformErrorCode::StateConflict))
            .count(),
        1
    );
    for outcome in outcomes.into_iter().filter_map(Result::ok) {
        assert_eq!(receipt(&outcome).before_generation, Some(1));
        assert_eq!(receipt(&outcome).after_generation, 2);
        drop(outcome);
    }
    fixture.finish().await;
}

#[tokio::test]
async fn detached_namespace_waiter_retains_real_work_until_commit_and_clean_recovery() {
    let mut fixture = Fixture::new(false).await;
    let native = fixture.admission.native.clone();
    super::recovery::install(&mut fixture, native.clone());
    drop(fixture.create().await);
    let gates = Rendezvous::new(1);
    let worker_gates = gates.clone();
    let (notice, receiver) = std::sync::mpsc::channel();
    let hold = fixture
        .store
        .with_store(StoreIoKind::Write, 1024, move |_| {
            let (registration, mut tracked) = worker_gates.track(vec![0u8; 1024]).unwrap();
            tracked.commit(Stage::Entered).unwrap();
            block_on(with_watchdog(WATCHDOG, async {
                let mut pause = Box::pin(tracked.pause());
                PollProbe::default().pending(pause.as_mut());
                notice
                    .send(worker_gates.blocked(registration, Stage::Entered).unwrap())
                    .unwrap();
                pause.await;
            }));
            Ok(())
        })
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    let mut command = Box::pin(
        fixture.backend.execute_state(
            context("alice"),
            fixture
                .mutation("lost-quiesce", c::NamespaceMutationKind::Quiesce, 1)
                .into(),
        ),
    );
    PollProbe::default().pending(command.as_mut());
    assert_eq!(fixture.store.snapshot().unwrap().accepted, 2);
    assert_eq!(fixture.store.snapshot().unwrap().active_writes, 1);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    drop(command);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    gates.release(ticket).unwrap();
    hold.await.unwrap().unwrap();
    fixture.store.close();
    let drained = tokio::time::timeout(
        WATCHDOG,
        fixture
            .store
            .drain_async(deadline(), std::future::pending())
            .unwrap(),
    )
    .await
    .unwrap();
    assert!(drained.clean);
    assert!(drained.snapshot.physically_retired());
    assert!(native.snapshot().unwrap().physically_retired());
    let mut config = fixture.config.clone();
    config.create_if_missing = false;
    let reopened = Arc::new(fixture::start(config).await);
    let context = latent_state::namespace::catalog::NamespaceOperationContext {
        tenant: latent_core::TenantId("a".into()),
        actor: format!(
            "administrator:{}",
            latent_capabilities::namespace::CallerScope::derive(
                context("alice").principal(),
                &latent_capabilities::namespace::RecoverySelection::OriginalCaller
            )
            .unwrap()
            .scope
        ),
        operation_id: "lost-quiesce".into(),
    };
    let recovered = reopened
        .with_store(StoreIoKind::Read, 8192, move |engine| {
            NamespaceCatalog::outcome_in(&engine.snapshot()?, &context)
                .map_err(inspection::native_namespace)
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(recovered.record.version.generation, 2);
    assert_eq!(recovered.context.operation_id, "lost-quiesce");
    reopened.close();
    assert!(
        reopened
            .drain_async(deadline(), std::future::pending())
            .unwrap()
            .await
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn namespace_usage_is_observed_from_native_accounting_and_tombstones_remain_charged() {
    let mut fixture = Fixture::new(false).await;
    drop(fixture.create().await);
    let write = fixture
        .store
        .with_store(StoreIoKind::Write, 65536, |engine| {
            let view = engine.snapshot()?;
            let scope = StateScope {
                tenant: latent_core::TenantId("a".into()),
                namespace: StateNamespaceId("orders".into()),
                incarnation: 1,
                state_schema: fixture::schema(),
                entity: Some("order-1".into()),
                mode: StateMode::Command,
            };
            // Trusted fixture state plans exercise the real byte/accounting codec;
            // they do not stand in for production guest or command authority.
            let mut session =
                StateSession::open(&view, scope, SessionLimits::default(), |_, _| Ok(())).unwrap();
            session
                .put(
                    &view,
                    b"key".to_vec(),
                    latent_core::transaction_contract::Value {
                        bytes: b"stored bytes".to_vec(),
                        media_type: "application/octet-stream".into(),
                        metadata: vec![],
                    },
                    |_, _| Ok(()),
                )
                .unwrap();
            let plan = session.seal(&view, |_, _| Ok(())).unwrap();
            let pins = plan.pins();
            let mut batch = AtomicBatch::default();
            plan.append_to(&mut batch, pins).unwrap();
            engine.apply(batch)
        })
        .unwrap();
    write.await.unwrap().unwrap();
    let inspected = fixture
        .backend
        .execute_state(context("alice"), fixture.target().into())
        .await
        .unwrap();
    let contract::Response::InspectNamespace(value) = &inspected.response else {
        panic!("wrong response")
    };
    assert_eq!(value.namespace.as_ref().unwrap().generation, 2);
    let charged = value.namespace.as_ref().unwrap().encoded_state_bytes;
    assert!(charged >= 12);
    drop(inspected);
    let deleted = fixture
        .store
        .with_store(StoreIoKind::Write, 65536, |engine| {
            let view = engine.snapshot()?;
            let scope = StateScope {
                tenant: latent_core::TenantId("a".into()),
                namespace: StateNamespaceId("orders".into()),
                incarnation: 1,
                state_schema: fixture::schema(),
                entity: Some("order-1".into()),
                mode: StateMode::Command,
            };
            let mut session =
                StateSession::open(&view, scope, SessionLimits::default(), |_, _| Ok(())).unwrap();
            session
                .delete(&view, b"key".to_vec(), |_, _| Ok(()))
                .unwrap();
            let plan = session.seal(&view, |_, _| Ok(())).unwrap();
            let pins = plan.pins();
            let mut batch = AtomicBatch::default();
            plan.append_to(&mut batch, pins).unwrap();
            engine.apply(batch)
        })
        .unwrap();
    deleted.await.unwrap().unwrap();
    let inspected = fixture
        .backend
        .execute_state(context("alice"), fixture.target().into())
        .await
        .unwrap();
    let contract::Response::InspectNamespace(value) = &inspected.response else {
        panic!("wrong response")
    };
    assert_eq!(value.namespace.as_ref().unwrap().generation, 3);
    assert!(value.namespace.as_ref().unwrap().encoded_state_bytes > 0);
    drop(inspected);
    fixture.finish().await;
}
