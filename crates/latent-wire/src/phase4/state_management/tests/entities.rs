use super::*;
use http_body::Body as HttpBody;
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeCapacityLimits, NativeCapacityOwner, NativeReservationRequest,
    },
    test_support::{
        block_on,
        coordination::{with_watchdog, PollProbe, Rendezvous, Stage, WATCHDOG},
    },
};
use latent_state::{
    embedded::{AtomicBatch, Family, RowMutation},
    session::{SessionLimits, StateMode, StateScope, StateSession},
    store_io::StoreIoKind,
};
use prost::Message;
use std::{future::poll_fn, pin::Pin, sync::mpsc};

fn selection(fixture: &Fixture, limit: u32) -> c::SelectEntityRequest {
    c::SelectEntityRequest {
        namespace: Some(fixture.target()),
        prefix: None,
        page: Some(latent_rpc::transaction::v1::PageRequest {
            limit,
            cursor: None,
        }),
    }
}
fn selected(response: &OwnedPhase4Response) -> &c::SelectEntityResponse {
    let contract::Response::SelectEntity(value) = &response.response else {
        panic!("wrong entity response")
    };
    value
}
async fn write_entity(fixture: &Fixture, entity: Option<&str>, tombstone: bool) {
    let entity = entity.map(str::to_owned);
    fixture
        .store
        .with_store(StoreIoKind::RecoveryWrite, 65536, move |engine| {
            let view = engine.snapshot()?;
            let scope = StateScope {
                tenant: latent_core::TenantId("a".into()),
                namespace: StateNamespaceId("orders".into()),
                incarnation: 1,
                state_schema: fixture::schema(),
                entity,
                mode: StateMode::Command,
            };
            let mut session =
                StateSession::open(&view, scope, SessionLimits::default(), |_, _| Ok(())).unwrap();
            if tombstone {
                session
                    .delete(&view, b"value".to_vec(), |_, _| Ok(()))
                    .unwrap();
            } else {
                for key in [b"value".as_slice(), b"second".as_slice()] {
                    session
                        .put(
                            &view,
                            key.to_vec(),
                            latent_core::transaction_contract::Value {
                                bytes: b"persisted".to_vec(),
                                media_type: "application/octet-stream".into(),
                                metadata: vec![],
                            },
                            |_, _| Ok(()),
                        )
                        .unwrap();
                }
            }
            let plan = session.seal(&view, |_, _| Ok(())).unwrap();
            let mut batch = AtomicBatch::default();
            let pins = plan.pins();
            plan.append_to(&mut batch, pins).unwrap();
            engine.apply(batch)
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}
async fn retired(fixture: &Fixture) {
    with_watchdog(WATCHDOG, async {
        while fixture.store.snapshot().unwrap().physical_owners != 0 {
            tokio::task::yield_now().await;
        }
    })
    .await;
    assert_eq!(
        fixture.admission.native.snapshot().unwrap().recovery.slots,
        0
    );
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
}

#[tokio::test]
async fn authenticated_entity_discovery_observes_real_cells_tombstones_and_critical_audit() {
    let mut fixture = Fixture::new(true).await;
    drop(fixture.create().await);
    write_entity(&fixture, None, false).await;
    write_entity(&fixture, Some("alpha"), false).await;
    write_entity(&fixture, Some("zeta"), true).await;
    let original = selection(&fixture, 128);
    let reply = fixture
        .backend
        .execute_state(context("alice"), original.clone().into())
        .await
        .unwrap();
    let value = selected(&reply);
    assert_eq!(
        value
            .entities
            .iter()
            .map(|item| item.entity.as_str())
            .collect::<Vec<_>>(),
        ["alpha", "zeta"]
    );
    assert!(value
        .entities
        .iter()
        .all(|item| item.version.len() == latent_state::session::version::VIEW_TOKEN_BYTES));
    assert_eq!(value.page.as_ref().unwrap().returned_count, 2);
    assert_eq!(
        value.page.as_ref().unwrap().encoded_bytes,
        value.encoded_len() as u64
    );
    assert!(value.page.as_ref().unwrap().next_cursor.is_none());
    reply.response.validate_for(&original.into()).unwrap();
    let rows = fixture
        .store
        .with_store(StoreIoKind::RecoveryRead, 65536, |engine| {
            let view = engine.snapshot()?;
            Ok((
                view.scan(Family::Command, b"", 128, 65536)?,
                view.scan(Family::Outbox, b"", 128, 65536)?,
            ))
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert!(rows.0.is_empty() && rows.1.is_empty());
    assert_eq!(fixture.store.snapshot().unwrap().physical_owners, 1);
    assert_eq!(
        fixture
            .backend
            .0
            .services
            .namespaces
            .lifecycle()
            .retained_owners(),
        1
    );
    assert_eq!(
        fixture.admission.native.snapshot().unwrap().recovery.slots,
        1
    );
    drop(reply);
    retired(&fixture).await;
    fixture.finish().await;
}

#[tokio::test]
async fn namespace_inspection_permission_cannot_supply_entity_listing_or_revive_old_reply() {
    let mut fixture = Fixture::new(false).await;
    drop(fixture.create().await);
    write_entity(&fixture, Some("alpha"), false).await;
    let original = fixture
        .backend
        .execute_state(context("alice"), selection(&fixture, 128).into())
        .await
        .unwrap();
    let mut document = fixture.document.clone();
    for rule in document["rules"].as_array_mut().unwrap() {
        rule["operations"]
            .as_array_mut()
            .unwrap()
            .retain(|operation| operation != "namespace-list");
    }
    fixture.update(Some(&document), "withdraw-listing-only");
    let inspected = fixture
        .backend
        .execute_state(context("alice"), fixture.target().into())
        .await
        .unwrap();
    drop(inspected);
    assert_eq!(
        fixture
            .backend
            .execute_state(context("alice"), selection(&fixture, 128).into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    let mut disclosed = false;
    assert!(original
        .owner
        .with_current(&mut || disclosed = true)
        .is_err());
    assert!(!disclosed);
    let document = fixture.document.clone();
    fixture.update(Some(&document), "approve-current-new-listing");
    assert!(original
        .owner
        .with_current(&mut || disclosed = true)
        .is_err());
    let current = fixture
        .backend
        .execute_state(context("alice"), selection(&fixture, 128).into())
        .await
        .unwrap();
    assert_eq!(selected(&current).entities[0].entity, "alpha");
    drop(original);
    drop(current);
    retired(&fixture).await;
    fixture.finish().await;
}

#[tokio::test]
async fn rpc_entity_cursor_binds_caller_prefix_and_fresh_exact_namespace_generation() {
    let mut fixture = Fixture::new(false).await;
    drop(fixture.create().await);
    for entity in ["alpha", "beta", "gamma"] {
        write_entity(&fixture, Some(entity), false).await;
    }
    let mut next = selection(&fixture, 1);
    let first = fixture
        .backend
        .execute_state(context("alice"), next.clone().into())
        .await
        .unwrap();
    assert_eq!(selected(&first).entities[0].entity, "alpha");
    let cursor = selected(&first)
        .page
        .as_ref()
        .unwrap()
        .next_cursor
        .clone()
        .unwrap();
    assert_eq!(cursor.len(), 134);
    next.page.as_mut().unwrap().cursor = Some(cursor);
    drop(first);
    let second = fixture
        .backend
        .execute_state(context("alice"), next.clone().into())
        .await
        .unwrap();
    assert_eq!(selected(&second).entities[0].entity, "beta");
    drop(second);
    assert_eq!(
        fixture
            .backend
            .execute_state(context("bob"), next.clone().into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::InvalidArgument
    );
    let mut changed = next.clone();
    changed.prefix = Some(b"beta".to_vec());
    assert_eq!(
        fixture
            .backend
            .execute_state(context("alice"), changed.into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::InvalidArgument
    );
    write_entity(&fixture, Some("alpha"), true).await;
    assert_eq!(
        fixture
            .backend
            .execute_state(context("alice"), next.into())
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::InvalidArgument
    );
    retired(&fixture).await;
    assert!(fixture.store.failure().is_none());
    fixture.finish().await;
}

#[tokio::test]
async fn rpc_entity_cursor_refuses_schema_and_restored_history_without_quarantining_store() {
    use latent_state::namespace::history::{history_key, HistoryEpochs, NamespaceHistory};
    let mut fixture = Fixture::new(false).await;
    drop(fixture.create().await);
    for entity in ["alpha", "beta"] {
        write_entity(&fixture, Some(entity), false).await;
    }
    let mut original = selection(&fixture, 1);
    let first = fixture
        .backend
        .execute_state(context("alice"), original.clone().into())
        .await
        .unwrap();
    original.page.as_mut().unwrap().cursor =
        selected(&first).page.as_ref().unwrap().next_cursor.clone();
    drop(first);
    for epochs in [
        HistoryEpochs {
            schema: 2,
            recovery: 1,
        },
        HistoryEpochs {
            schema: 2,
            recovery: 2,
        },
    ] {
        fixture
            .store
            .with_store(StoreIoKind::RecoveryWrite, 65536, move |engine| {
                let view = engine.snapshot()?;
                let row = NamespaceCatalog::read_in(
                    &view,
                    &latent_core::TenantId("a".into()),
                    &StateNamespaceId("orders".into()),
                )
                .map_err(inspection::native_namespace)?
                .unwrap();
                let mut history = NamespaceHistory::initial(row.record());
                history.epochs = epochs;
                engine.apply(AtomicBatch {
                    expectations: vec![],
                    mutations: vec![RowMutation {
                        key: history_key(
                            &row.record().tenant,
                            &row.record().id,
                            row.record().version.incarnation,
                        )
                        .unwrap(),
                        value: Some(history.encode().unwrap()),
                    }],
                })
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            fixture
                .backend
                .execute_state(context("alice"), original.clone().into())
                .await
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::InvalidArgument
        );
        let fresh = fixture
            .backend
            .execute_state(context("alice"), selection(&fixture, 1).into())
            .await
            .unwrap();
        assert_eq!(selected(&fresh).entities[0].entity, "alpha");
        drop(fresh);
        retired(&fixture).await;
        assert!(fixture.store.failure().is_none());
    }
    fixture.finish().await;
}

#[tokio::test]
async fn actual_entity_rpc_frame_and_snapshot_progress_through_reserved_recovery_capacity() {
    let mut limits = NativeCapacityLimits::default();
    limits.ordinary.slots = 1;
    let owner = NativeCapacityOwner::new(limits).unwrap();
    let mut fixture = Fixture::with_io_and_native(false, None, owner.clone()).await;
    super::recovery::install(&mut fixture, owner.clone());
    drop(fixture.create().await);
    write_entity(&fixture, Some("alpha"), false).await;
    let ordinary = owner
        .reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest::default(),
            deadline(),
        )
        .unwrap();
    let gates = Rendezvous::new(3);
    let (notice, receiver) = mpsc::channel();
    let mut jobs = Vec::new();
    let mut tickets = Vec::new();
    for kind in [StoreIoKind::Read, StoreIoKind::Read, StoreIoKind::Write] {
        let worker = gates.clone();
        let notice = notice.clone();
        jobs.push(
            fixture
                .store
                .with_store(kind, 512, move |_| {
                    let (registration, mut tracked) = worker.track(vec![0_u8; 512]).unwrap();
                    tracked.commit(Stage::Entered).unwrap();
                    let mut waiting = Box::pin(tracked.pause());
                    PollProbe::default().pending(waiting.as_mut());
                    notice
                        .send(worker.blocked(registration, Stage::Entered).unwrap())
                        .unwrap();
                    block_on(with_watchdog(WATCHDOG, waiting));
                    Ok(())
                })
                .unwrap(),
        );
        tickets.push(receiver.recv_timeout(WATCHDOG).unwrap());
    }
    let mut body = super::recovery::response_body_for(
        &fixture,
        "/latent.control.v1.StateService/SelectEntity",
        selection(&fixture, 128).encode_to_vec(),
    )
    .await;
    let frame = with_watchdog(WATCHDOG, poll_fn(|cx| Pin::new(&mut body).poll_frame(cx)))
        .await
        .unwrap()
        .unwrap();
    let bytes = frame.into_data().unwrap();
    let response = c::SelectEntityResponse::decode(&bytes[5..]).unwrap();
    assert_eq!(response.entities[0].entity, "alpha");
    assert_eq!(fixture.store.snapshot().unwrap().physical_owners, 1);
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(
        fixture
            .backend
            .0
            .services
            .namespaces
            .lifecycle()
            .retained_owners(),
        1
    );
    drop(body);
    let held = bytes.clone();
    drop(bytes);
    assert_eq!(fixture.store.snapshot().unwrap().physical_owners, 1);
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(
        fixture
            .backend
            .0
            .services
            .namespaces
            .lifecycle()
            .retained_owners(),
        1
    );
    drop(held);
    retired(&fixture).await;
    assert_eq!(fixture.store.snapshot().unwrap().active_reads, 2);
    assert_eq!(fixture.store.snapshot().unwrap().active_writes, 1);
    assert_eq!(owner.snapshot().unwrap().ordinary.slots, 1);
    for ticket in tickets {
        gates.release(ticket).unwrap();
    }
    for job in jobs {
        with_watchdog(WATCHDOG, job).await.unwrap().unwrap();
    }
    drop(ordinary);
    fixture.finish().await;
    assert!(owner.snapshot().unwrap().physically_retired());
}

#[tokio::test]
async fn entity_reply_revocation_before_encoding_keeps_snapshot_until_native_cleanup() {
    let mut fixture = Fixture::new(false).await;
    drop(fixture.create().await);
    write_entity(&fixture, Some("private"), false).await;
    let mut body = super::recovery::response_body_for(
        &fixture,
        "/latent.control.v1.StateService/SelectEntity",
        selection(&fixture, 128).encode_to_vec(),
    )
    .await;
    assert_eq!(fixture.store.snapshot().unwrap().physical_owners, 1);
    assert_eq!(
        fixture.admission.native.snapshot().unwrap().recovery.slots,
        1
    );
    fixture.update(None, "withdraw-before-entity-frame");
    let result = with_watchdog(WATCHDOG, poll_fn(|cx| Pin::new(&mut body).poll_frame(cx)))
        .await
        .unwrap();
    assert_eq!(result.unwrap_err().code(), tonic::Code::PermissionDenied);
    drop(body);
    retired(&fixture).await;
    fixture.finish().await;
}

#[tokio::test]
async fn retained_entity_data_frame_blocks_namespace_drain_until_physical_view_retirement() {
    let mut fixture = Fixture::new(false).await;
    drop(fixture.create().await);
    write_entity(&fixture, Some("alpha"), false).await;
    let generation = fixture
        .store
        .with_store(StoreIoKind::RecoveryRead, 65536, |engine| {
            let read = NamespaceCatalog::read_in(
                &engine.snapshot()?,
                &latent_core::TenantId("a".into()),
                &StateNamespaceId("orders".into()),
            )
            .unwrap()
            .unwrap();
            Ok(read.record().version.generation)
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    let mut body = super::recovery::response_body_for(
        &fixture,
        "/latent.control.v1.StateService/SelectEntity",
        selection(&fixture, 128).encode_to_vec(),
    )
    .await;
    let frame = with_watchdog(WATCHDOG, poll_fn(|cx| Pin::new(&mut body).poll_frame(cx)))
        .await
        .unwrap()
        .unwrap();
    let bytes = frame.into_data().unwrap();
    assert_eq!(
        fixture
            .backend
            .0
            .services
            .namespaces
            .lifecycle()
            .retained_owners(),
        1
    );
    let quiesced = fixture
        .backend
        .execute_state(
            context("alice"),
            fixture
                .mutation(
                    "quiesce-with-entity-frame",
                    c::NamespaceMutationKind::Quiesce,
                    generation,
                )
                .into(),
        )
        .await
        .unwrap();
    let after = super::receipt(&quiesced).after_generation;
    drop(quiesced);
    drop(body);
    assert_eq!(
        fixture
            .backend
            .execute_state(
                context("alice"),
                fixture
                    .mutation(
                        "retire-while-entity-frame-held",
                        c::NamespaceMutationKind::Retire,
                        after
                    )
                    .into(),
            )
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::StateConflict
    );
    assert_eq!(fixture.store.snapshot().unwrap().physical_owners, 1);
    assert_eq!(
        fixture
            .backend
            .0
            .services
            .namespaces
            .lifecycle()
            .retained_owners(),
        1
    );
    drop(bytes);
    retired(&fixture).await;
    let changed = fixture
        .backend
        .execute_state(
            context("alice"),
            fixture
                .mutation(
                    "retire-after-entity-frame-retirement",
                    c::NamespaceMutationKind::Retire,
                    after,
                )
                .into(),
        )
        .await
        .unwrap();
    assert_eq!(
        super::receipt(&changed).status,
        c::NamespaceStatus::Retired as i32
    );
    drop(changed);
    fixture.finish().await;
}
