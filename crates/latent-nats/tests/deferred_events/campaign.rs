use super::{proxy, support::*};
use latent_commit::atomic::{
    inspect, AdmissionDecision, CommandTime, CompleteEnvelope, Outcome, PreparedAdmission,
    PreparedDisposition, StagedIntent,
};
use latent_effects::{
    dispatch::Disposition, dispatch_store::DispatchCatalog, runtime::DispatcherOwner,
};
use latent_nats::deferred::JetStreamQualification;
use latent_state::{
    embedded::Family,
    protected_store::ProtectedStoreOwner,
    session::{SessionLimits, StateSession},
    store_io::StoreIoKind,
};
use std::{
    sync::{atomic::Ordering, Arc},
    time::Instant,
};

fn reset() -> JetStreamQualification {
    serde_json::from_value(control("reset")).unwrap()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires tools/run_nats_deferred_tests.py owned pinned real JetStream"]
async fn real_deferred_atomic_state_result_payload_and_broker_receipt_agree() {
    let fixture = Fixture::new(config(), reset()).await;
    let effect = fixture.commit("success").await;
    assert_eq!(control("info")["state"]["messages"], 0);
    fixture.owner.as_ref().unwrap().resume().unwrap();
    let record = fixture
        .settled(&effect, Disposition::ProviderAcknowledged)
        .await;
    assert_eq!(record.attempts(), 1);
    assert!(record
        .latest()
        .unwrap()
        .provider_receipt
        .as_ref()
        .unwrap()
        .contains(":1:duplicate=0"));
    assert_eq!(control("info")["state"]["messages"], 1);
    let actual = control("message");
    assert_eq!(actual["payload"], "updated");
    assert_eq!(actual["subject"], "lsf.deferred.allowed");
    let headers = actual["headers"].as_str().unwrap();
    assert!(headers.contains(&format!(
        "Nats-Msg-Id: lsf-effect-{}\r\n",
        effect.link().effect
    )));
    assert!(headers.contains("Content-Type: text/plain\r\n"));
    assert!(headers.contains("Lsf-Attr-event-kind: updated\r\n"));
    call(&fixture.store, StoreIoKind::Read, |db| {
        let view = db.snapshot().unwrap();
        validate(&view).unwrap();
        let (command, result) = inspect(
            &view,
            &input("success", 1).key,
            CommandTime {
                unix_millis: 100,
                continuity_proven: true,
            },
            permission,
        )
        .unwrap();
        assert_eq!(command.outcome(), Outcome::Committed);
        assert_eq!(result.unwrap().value().unwrap().bytes, b"committed");
        let mut state =
            StateSession::open(&view, scope(), SessionLimits::default(), state_permission).unwrap();
        assert_eq!(
            state
                .get(&view, b"aggregate/count", state_permission)
                .unwrap()
                .unwrap()
                .value
                .bytes,
            1u64.to_le_bytes()
        );
    })
    .await;
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires tools/run_nats_deferred_tests.py owned pinned real JetStream"]
async fn real_deferred_declared_rejection_and_positive_technical_abort_publish_nothing() {
    let fixture = Fixture::new(config(), reset()).await;
    for technical in [false, true] {
        terminal_without_delivery(&fixture, technical).await;
    }
    fixture.owner.as_ref().unwrap().resume().unwrap();
    call(&fixture.store, StoreIoKind::Read, |db| {
        let view = db.snapshot().unwrap();
        validate(&view).unwrap();
        for (key, outcome) in [("reject", Outcome::Rejected), ("abort", Outcome::Aborted)] {
            let (command, result) = inspect(
                &view,
                &input(key, 1).key,
                CommandTime {
                    unix_millis: 100,
                    continuity_proven: true,
                },
                permission,
            )
            .unwrap();
            assert_eq!(command.outcome(), outcome);
            assert!(result.is_some());
            assert!(command.effect_ids().is_empty());
        }
        assert!(view
            .scan(Family::Outbox, b"", 16, 65536)
            .unwrap()
            .is_empty());
        assert!(view.scan(Family::State, b"", 16, 65536).unwrap().is_empty());
    })
    .await;
    assert_eq!(control("info")["state"]["messages"], 0);
    assert_eq!(fixture.publisher.snapshot().connection_attempts, 0);
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires tools/run_nats_deferred_tests.py owned pinned real JetStream"]
async fn real_deferred_committed_presend_restart_uses_same_payload_and_advanced_physical_epoch() {
    let mut fixture = Fixture::new(config(), reset()).await;
    let effect = fixture.commit("restart").await;
    assert_eq!(control("info")["state"]["messages"], 0);
    fixture.stop_dispatcher().await;
    fixture.stop_store().await;
    fixture.store = Arc::new(
        ProtectedStoreOwner::start_validated_view(fixture.store_config.clone(), 0, validate)
            .unwrap()
            .await
            .unwrap(),
    );
    fixture
        .store
        .bind_native_capacity(&fixture.native_capacity)
        .unwrap();
    fixture.start(false, Some((1, 100))).await;
    let record = fixture
        .settled(&effect, Disposition::ProviderAcknowledged)
        .await;
    assert_eq!(record.owner_epoch(), 2);
    assert_eq!(record.attempts(), 1);
    assert_eq!(control("message")["payload"], "updated");
    assert_eq!(control("info")["state"]["messages"], 1);
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires tools/run_nats_deferred_tests.py owned pinned real JetStream"]
async fn real_deferred_lost_acknowledgement_retries_exact_id_once_with_one_broker_message() {
    let qualification = reset();
    let proxy = proxy::Proxy::new(config()).await;
    proxy.mode.store(proxy::DROP_ACK, Ordering::Release);
    let fixture = Fixture::new(proxy.config.clone(), qualification).await;
    let effect = fixture.commit("lost-ack").await;
    fixture.owner.as_ref().unwrap().resume().unwrap();
    tokio::time::timeout(WATCHDOG, proxy.seen.notified())
        .await
        .unwrap();
    let retry = fixture.settled(&effect, Disposition::RetryScheduled).await;
    assert_eq!(retry.latest().unwrap().disposition, Disposition::Uncertain);
    assert_eq!(control("info")["state"]["messages"], 1);
    fixture
        .clock
        .0
        .store(retry.retry_at_millis(), Ordering::Release);
    let ack = fixture
        .settled(&effect, Disposition::ProviderAcknowledged)
        .await;
    assert_eq!(ack.attempts(), 2);
    assert!(ack
        .latest()
        .unwrap()
        .provider_receipt
        .as_ref()
        .unwrap()
        .contains(":1:duplicate=1"));
    assert_eq!(control("info")["state"]["messages"], 1);
    let identity = effect.link().effect.clone();
    call(&fixture.store, StoreIoKind::Read, move |db| {
        let page =
            DispatchCatalog::history_page(&db.snapshot().unwrap(), &identity, None, 16, 65536)
                .unwrap();
        assert_eq!(page.pending_slots, 0);
        assert_eq!(page.rows.len(), 2);
        assert_eq!(page.rows[0].receipt.disposition, Disposition::Uncertain);
        assert_eq!(
            page.rows[1].receipt.disposition,
            Disposition::ProviderAcknowledged
        );
    })
    .await;
    fixture.finish().await;
    proxy.close().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires tools/run_nats_deferred_tests.py owned pinned real JetStream"]
async fn real_deferred_horizon_expiry_revocation_and_recreated_stream_stop_delivery() {
    // Revocation is checked before accepting provider work.
    let fixture = Fixture::new(config(), reset()).await;
    let effect = fixture.commit("revoked").await;
    let mut revoked = fixture.rule.clone();
    revoked.policy_revision = 2;
    revoked.enabled = false;
    fixture.authority.publish(revoked).unwrap();
    fixture.owner.as_ref().unwrap().resume().unwrap();
    fixture.settled(&effect, Disposition::PolicyBlocked).await;
    assert_eq!(control("info")["state"]["messages"], 0);
    assert_eq!(fixture.publisher.snapshot().connection_attempts, 0);
    fixture.finish().await;
    // An explicit stream replacement cannot satisfy the sealed original incarnation.
    let qualification = reset();
    let fixture = Fixture::new(config(), qualification.clone()).await;
    let effect = fixture.commit("recreated").await;
    let replacement = control("recreate");
    assert_ne!(replacement["streamCreated"], qualification.stream_created);
    fixture.owner.as_ref().unwrap().resume().unwrap();
    fixture.settled(&effect, Disposition::PolicyBlocked).await;
    assert_eq!(control("info")["state"]["messages"], 0);
    fixture.finish().await;
    // A possible send has a qualified, finite retry horizon, never a permanent dedup grant.
    let qualification = reset();
    let proxy = proxy::Proxy::new(config()).await;
    proxy.mode.store(proxy::DROP_ACK, Ordering::Release);
    let fixture = Fixture::new(proxy.config.clone(), qualification).await;
    let effect = fixture.commit("horizon").await;
    fixture.owner.as_ref().unwrap().resume().unwrap();
    tokio::time::timeout(WATCHDOG, proxy.seen.notified())
        .await
        .unwrap();
    fixture.settled(&effect, Disposition::RetryScheduled).await;
    fixture.clock.0.store(30_101, Ordering::Release);
    fixture.settled(&effect, Disposition::PolicyBlocked).await;
    assert_eq!(control("info")["state"]["messages"], 1);
    assert_eq!(fixture.publisher.snapshot().connection_attempts, 1);
    fixture.finish().await;
    proxy.close().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires tools/run_nats_deferred_tests.py owned pinned real JetStream"]
async fn real_deferred_malformed_and_oversized_replies_preserve_send_uncertainty() {
    for mode in [
        proxy::MALFORMED_INFO,
        proxy::OVERSIZED_INFO,
        proxy::MALFORMED_ACK,
        proxy::OVERSIZED_ACK,
    ] {
        let qualification = reset();
        let proxy = proxy::Proxy::new(config()).await;
        proxy.mode.store(mode, Ordering::Release);
        let mut fixture = Fixture::new(proxy.config.clone(), qualification).await;
        let effect = fixture.commit("bad-receipt").await;
        fixture.owner.as_ref().unwrap().resume().unwrap();
        tokio::time::timeout(WATCHDOG, proxy.seen.notified())
            .await
            .unwrap();
        let expected = if matches!(mode, proxy::MALFORMED_INFO | proxy::OVERSIZED_INFO) {
            Disposition::KnownFailed
        } else {
            Disposition::RetryScheduled
        };
        let record = fixture.settled(&effect, expected).await;
        assert_eq!(
            record.latest().unwrap().disposition,
            if expected == Disposition::KnownFailed {
                Disposition::KnownFailed
            } else {
                Disposition::Uncertain
            }
        );
        assert_eq!(
            control("info")["state"]["messages"],
            usize::from(expected == Disposition::RetryScheduled)
        );
        fixture.stop_dispatcher().await;
        fixture.stop_store().await;
        fixture.secrets.close();
        assert!(fixture
            .pools
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .is_clean());
        proxy.close().await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires tools/run_nats_deferred_tests.py owned pinned real JetStream"]
async fn real_deferred_live_publication_keeps_actual_root_role_and_buffers_after_shutdown_cutoff() {
    let qualification = reset();
    let proxy = proxy::Proxy::new(config()).await;
    proxy.mode.store(proxy::HOLD_ACK, Ordering::Release);
    let mut fixture = Fixture::new(proxy.config.clone(), qualification).await;
    let effect = fixture.commit("live-shutdown").await;
    fixture.owner.as_ref().unwrap().resume().unwrap();
    tokio::time::timeout(WATCHDOG, proxy.seen.notified())
        .await
        .unwrap();
    assert_eq!(control("info")["state"]["messages"], 1);
    assert_eq!(fixture.publisher.snapshot().active_publishes, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 1);
    let report = fixture
        .owner
        .as_mut()
        .unwrap()
        .shutdown(Instant::now())
        .await
        .unwrap();
    assert!(!report.clean);
    assert!(!report.physically_retired);
    assert!(report.snapshot.physical_owners > 0);
    assert!(DispatcherOwner::start(
        latent_effects::runtime::DispatcherConfig::default(),
        fixture.store.clone(),
        fixture.authority.clone(),
        vec![fixture.adapter.clone()],
        fixture.clock.clone(),
        Some((1, 100))
    )
    .await
    .is_err());
    assert_eq!(fixture.record(&effect).await.attempts(), 1);
    assert_eq!(fixture.publisher.snapshot().active_publishes, 1);
    proxy.release.notify_one();
    tokio::time::timeout(WATCHDOG, async {
        loop {
            if fixture.publisher.snapshot().active_publishes == 0
                && fixture
                    .owner
                    .as_ref()
                    .unwrap()
                    .snapshot()
                    .unwrap()
                    .physical_owners
                    == 0
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 0);
    let late = fixture
        .owner
        .as_mut()
        .unwrap()
        .shutdown(Instant::now() + WATCHDOG)
        .await
        .unwrap();
    assert!(!late.clean); // Actual late retirement cannot revise the original cutoff.
    fixture.stop_store().await;
    fixture.secrets.close();
    assert!(fixture
        .pools
        .shutdown(Instant::now() + WATCHDOG)
        .await
        .unwrap()
        .is_clean());
    proxy.close().await;
}

async fn terminal_without_delivery(fixture: &Fixture, technical: bool) {
    let role = fixture.owner.as_ref().unwrap().command_admission().unwrap();
    let effects = fixture.authority.clone();
    call(&fixture.store, StoreIoKind::Write, move |db| {
        let view = db.snapshot().unwrap();
        let time = CommandTime {
            unix_millis: 100,
            continuity_proven: true,
        };
        let AdmissionDecision::New(prepared) = PreparedAdmission::prepare(
            &view,
            input(
                if technical { "abort" } else { "reject" },
                role.owner_epoch(),
            ),
            time,
            permission,
        )
        .unwrap() else {
            panic!("new claim")
        };
        let claim = prepared
            .publish(db, || role.with_current(|_, _| Ok(())).unwrap())
            .unwrap();
        drop(view);
        let view = db.snapshot().unwrap();
        let work = claim.physical_work().unwrap();
        let retirement = claim.retirement();
        let captured = claim
            .intent_capture_context()
            .capture(
                0,
                StagedIntent {
                    binding: "approved-event".into(),
                    operation: "event".into(),
                    payload: value(b"discarded"),
                    expires_at_millis: None,
                },
                &effects,
                time,
            )
            .unwrap();
        let mut session =
            StateSession::open(&view, scope(), SessionLimits::default(), state_permission).unwrap();
        session
            .put(
                &view,
                b"aggregate/count".to_vec(),
                value(b"discarded"),
                state_permission,
            )
            .unwrap();
        drop(session);
        drop(captured);
        let envelope = if technical {
            drop(claim);
            work.retire();
            CompleteEnvelope::technical_abort(
                &view,
                retirement.proven_noncommit().unwrap(),
                "guest-trap".into(),
                time,
            )
            .unwrap()
        } else {
            work.retire();
            CompleteEnvelope::rejection(
                &view,
                claim,
                "declared-rejection".into(),
                value(b"rejected"),
                time,
            )
            .unwrap()
        };
        assert!(envelope.authorities().is_empty());
        let disposition = envelope.publish(db, |_| role.with_current(|_, _| Ok(())).unwrap());
        assert!(matches!(disposition, PreparedDisposition::Confirmed { .. }));
        drop(view);
        role.retire();
    })
    .await;
}
