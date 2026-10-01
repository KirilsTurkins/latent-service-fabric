use super::{fixture::*, proxy::Fault, Disposition, Instant, Ordering};
use latent_commit::atomic::{inspect, CommandTime, Outcome};
use latent_effects::runtime::{
    DeferredEffectAdapter, EffectTimeSource, ProviderReconciliationOutcome,
    ProviderReconciliationReason, ProviderReconciliationRequest,
};
use latent_effects::runtime::{DispatcherConfig, DispatcherOwner};
use latent_state::{
    protected_store::ProtectedStoreOwner,
    session::{SessionLimits, StateSession},
    store_io::StoreIoKind,
};

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn declared_rejection_and_positive_abort_commit_no_http_intent_or_mutation() {
    let fixture = Fixture::new(Fault::Normal).await;
    terminal_without_delivery(&fixture, false).await;
    terminal_without_delivery(&fixture, true).await;
    fixture.owner.as_ref().unwrap().resume().unwrap();
    call(&fixture.store, StoreIoKind::Read, |db| {
        let view = db.snapshot().unwrap();
        validate(&view).unwrap();
        for (key, outcome) in [("reject", Outcome::Rejected), ("abort", Outcome::Aborted)] {
            let (record, result) = inspect(
                &view,
                &input(key, 1).key,
                CommandTime {
                    unix_millis: 100,
                    continuity_proven: true,
                },
                permission,
            )
            .unwrap();
            assert_eq!(record.outcome(), outcome);
            assert!(result.is_some());
            assert!(record.effect_ids().is_empty());
        }
        assert!(view
            .scan(latent_state::embedded::Family::Outbox, b"", 16, 65536)
            .unwrap()
            .is_empty());
        assert!(view
            .scan(latent_state::embedded::Family::State, b"", 16, 65536)
            .unwrap()
            .is_empty());
    })
    .await;
    assert_eq!(fixture.endpoint.counter().await, 0);
    assert!(fixture.proxy.requests.lock().unwrap().is_empty());
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn provider_cancellation_during_tls_or_reply_retires_actual_socket_before_refund() {
    for after_mutation in [false, true] {
        let fixture = Fixture::new(if after_mutation {
            Fault::HoldPostReply
        } else {
            Fault::HoldSecondTls
        })
        .await;
        let effect = fixture.commit("provider-cancel").await;
        fixture.owner.as_ref().unwrap().resume().unwrap();
        fixture.proxy.wait_gate().await;
        assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 1);
        assert_eq!(fixture.endpoint.counter().await, u64::from(after_mutation));
        fixture.pools.retire();
        let record = fixture
            .settled(
                &effect,
                if after_mutation {
                    Disposition::RetryScheduled
                } else {
                    Disposition::PolicyBlocked
                },
            )
            .await;
        assert_eq!(
            record.latest().unwrap().disposition,
            if after_mutation {
                Disposition::Uncertain
            } else {
                Disposition::PolicyBlocked
            }
        );
        assert_eq!(record.attempts(), 1);
        assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
        assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 0);
        fixture.proxy.release();
        assert_eq!(
            fixture.proxy.posts.load(Ordering::Acquire),
            u64::from(after_mutation)
        );
        fixture.finish().await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn operator_lookup_confirms_exact_original_history_and_row_version_without_another_post() {
    for absent in [false, true] {
        let fixture = Fixture::new(Fault::LosePostReply).await;
        let effect = fixture.commit("operator-confirm").await;
        fixture.owner.as_ref().unwrap().resume().unwrap();
        fixture.settled(&effect, Disposition::RetryScheduled).await;
        fixture.owner.as_ref().unwrap().pause();
        if absent {
            fixture.endpoint.erase_receipts().await;
        }
        let effect_id = effect.link().effect.clone();
        let (payload, attempt, version) = call(&fixture.store, StoreIoKind::Read, move |db| {
            let view = db.snapshot().unwrap();
            let bytes = view
                .get(&latent_effects::dispatch_store::effect_row_key(&effect_id).unwrap())
                .unwrap()
                .unwrap();
            let version = latent_effects::dispatch::effect_record_version(&bytes).unwrap();
            let attempt = latent_effects::dispatch_store::DispatchCatalog::last_completed_attempt(
                &view, &effect_id,
            )
            .unwrap()
            .unwrap();
            let payload = latent_effects::payload::PayloadRecord::decode(
                &view
                    .get(&latent_effects::dispatch_store::effect_payload_key(&effect_id).unwrap())
                    .unwrap()
                    .unwrap(),
            )
            .unwrap();
            (payload, attempt, version)
        })
        .await;
        let original = attempt.clone();
        let request =
            ProviderReconciliationRequest::new(effect.clone(), payload, attempt, version).unwrap();
        let mut physical = fixture
            .authority
            .accept(&effect, original.attempt(), fixture.clock.observe())
            .unwrap();
        let lookup = physical
            .accept_with(
                &effect,
                original.attempt(),
                fixture.clock.observe(),
                |grant| fixture.adapter.accept_reconciliation(grant, request),
            )
            .unwrap()
            .unwrap();
        let outcome = lookup.await;
        assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 0);
        assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
        physical.retire().unwrap();
        match outcome {
            ProviderReconciliationOutcome::Confirmed(confirmation) => {
                assert!(!absent);
                confirmation.validate_for(&original, version).unwrap();
                assert!(confirmation.validate_for(&original, [1; 32]).is_err());
                assert!(confirmation.provider_receipt().ends_with(":1:duplicate=1"));
            }
            ProviderReconciliationOutcome::Uncertain(reason) => {
                assert!(absent);
                assert_eq!(reason, ProviderReconciliationReason::NotFound);
            }
        }
        assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 1);
        assert_eq!(fixture.proxy.lookups.load(Ordering::Acquire), 1);
        assert_eq!(fixture.endpoint.counter().await, 1);
        assert_eq!(
            fixture.record(&effect).await.disposition(),
            Disposition::RetryScheduled
        );
        fixture.finish().await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn committed_state_result_payload_and_remote_counter_agree_after_real_tls() {
    let fixture = Fixture::new(Fault::Normal).await;
    let effect = fixture.commit("success").await;
    assert_eq!(fixture.endpoint.counter().await, 0);
    assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 0);
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
        .ends_with(":1:duplicate=0"));
    let remote = fixture
        .endpoint
        .record(&format!("lsf-effect-{}", effect.link().effect))
        .await;
    assert_eq!(remote["sequence"], 1);
    assert_eq!(remote["endpointIncarnation"], "c".repeat(64));
    assert_eq!(fixture.endpoint.counter().await, 1);
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
        let mut session =
            StateSession::open(&view, scope(), SessionLimits::default(), state_permission).unwrap();
        assert_eq!(
            session
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
async fn committed_presend_restart_advances_physical_epoch_without_changing_request() {
    let mut fixture = Fixture::new(Fault::Normal).await;
    let effect = fixture.commit("restart").await;
    assert_eq!(fixture.endpoint.counter().await, 0);
    fixture.stop_dispatcher().await;
    fixture.stop_store().await;
    fixture.store = std::sync::Arc::new(
        ProtectedStoreOwner::start_validated_view(fixture.store_config.clone(), 0, validate)
            .unwrap()
            .await
            .unwrap(),
    );
    fixture.start(false, Some((1, 100))).await;
    let record = fixture
        .settled(&effect, Disposition::ProviderAcknowledged)
        .await;
    assert_eq!(record.owner_epoch(), 2);
    assert_eq!(record.attempts(), 1);
    assert_eq!(fixture.endpoint.counter().await, 1);
    assert_eq!(
        fixture.proxy.requests.lock().unwrap()[1].1,
        format!("lsf-effect-{}", effect.link().effect)
    );
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lost_mutation_reply_recovers_only_by_lookup_with_one_durable_remote_mutation() {
    let fixture = Fixture::new(Fault::LosePostReply).await;
    let effect = fixture.commit("lost").await;
    fixture.owner.as_ref().unwrap().resume().unwrap();
    let first = fixture.settled(&effect, Disposition::RetryScheduled).await;
    assert_eq!(first.latest().unwrap().disposition, Disposition::Uncertain);
    assert_eq!(fixture.endpoint.counter().await, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 0);
    fixture.clock.0.store(200, Ordering::Release);
    let recovered = fixture
        .settled(&effect, Disposition::ProviderAcknowledged)
        .await;
    assert_eq!(recovered.attempts(), 2);
    assert!(recovered
        .latest()
        .unwrap()
        .provider_receipt
        .as_ref()
        .unwrap()
        .ends_with(":1:duplicate=1"));
    assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 1);
    assert_eq!(fixture.proxy.lookups.load(Ordering::Acquire), 1);
    assert_eq!(fixture.endpoint.counter().await, 1);
    let requests = fixture.proxy.requests.lock().unwrap().clone();
    assert!(requests
        .iter()
        .all(|(_, key, digest)| key == &requests[0].1 && digest == &requests[0].2));
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn absent_or_expired_lookup_retains_uncertainty_and_never_performs_another_post() {
    for expired in [false, true] {
        let fixture = Fixture::new(Fault::LosePostReply).await;
        let effect = fixture
            .commit(if expired {
                "expired-record"
            } else {
                "absent-record"
            })
            .await;
        fixture.owner.as_ref().unwrap().resume().unwrap();
        fixture.settled(&effect, Disposition::RetryScheduled).await;
        if expired {
            fixture.endpoint.clock.store(20_000, Ordering::Release);
        } else {
            fixture.endpoint.erase_receipts().await;
        }
        fixture.clock.0.store(200, Ordering::Release);
        let record = fixture.settled(&effect, Disposition::Uncertain).await;
        assert_eq!(record.attempts(), 2);
        assert_eq!(
            record.latest().unwrap().reason,
            if expired {
                "http-lookup-expired"
            } else {
                "http-lookup-absent"
            }
        );
        assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 1);
        assert_eq!(fixture.proxy.lookups.load(Ordering::Acquire), 1);
        assert_eq!(fixture.endpoint.counter().await, 1);
        fixture.clock.0.store(300, Ordering::Release);
        fixture.owner.as_ref().unwrap().pause();
        assert_eq!(fixture.record(&effect).await.attempts(), 2);
        fixture.finish().await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn qualified_endpoint_equal_key_replay_is_one_mutation_and_changed_body_is_conflict() {
    let fixture = Fixture::new(Fault::Normal).await;
    let effect = fixture.commit("equal-key").await;
    fixture.owner.as_ref().unwrap().resume().unwrap();
    fixture
        .settled(&effect, Disposition::ProviderAcknowledged)
        .await;
    let key = format!("lsf-effect-{}", effect.link().effect);
    let equal = fixture
        .proxy
        .operator_post(fixture.provider.inner.tls.clone(), &key, b"updated")
        .await;
    assert_eq!(equal["outcome"], "accepted");
    assert_eq!(equal["duplicate"], true);
    assert_eq!(equal["sequence"], 1);
    let conflict = fixture
        .proxy
        .operator_post(fixture.provider.inner.tls.clone(), &key, b"changed-body")
        .await;
    assert_eq!(conflict["outcome"], "conflict");
    assert_eq!(conflict["sequence"], 0);
    assert_eq!(fixture.endpoint.counter().await, 1);
    assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 3);
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn malformed_oversized_redirect_and_http_error_replies_preserve_mutation_uncertainty() {
    for fault in [
        Fault::MalformedPost,
        Fault::OversizedPost,
        Fault::RedirectPost,
        Fault::StatusPost(400),
        Fault::StatusPost(500),
    ] {
        let fixture = Fixture::new(fault).await;
        let effect = fixture.commit("reply-fault").await;
        fixture.owner.as_ref().unwrap().resume().unwrap();
        let uncertain = fixture.settled(&effect, Disposition::RetryScheduled).await;
        assert_eq!(
            uncertain.latest().unwrap().disposition,
            Disposition::Uncertain
        );
        assert_eq!(uncertain.latest().unwrap().reason, "http-reply-unknown");
        assert!(uncertain.latest().unwrap().provider_receipt.is_none());
        assert_eq!(fixture.endpoint.counter().await, 1);
        fixture.clock.0.store(200, Ordering::Release);
        fixture
            .settled(&effect, Disposition::ProviderAcknowledged)
            .await;
        assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 1);
        assert_eq!(fixture.proxy.lookups.load(Ordering::Acquire), 1);
        assert_eq!(fixture.endpoint.counter().await, 1);
        fixture.finish().await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn qualified_remote_rejection_is_known_failure_without_counter_mutation() {
    let fixture = Fixture::new(Fault::Normal).await;
    fixture.endpoint.reject.store(true, Ordering::Release);
    let effect = fixture.commit("remote-reject").await;
    fixture.owner.as_ref().unwrap().resume().unwrap();
    let rejected = fixture.settled(&effect, Disposition::KnownFailed).await;
    assert_eq!(rejected.latest().unwrap().reason, "http-operation-rejected");
    assert!(rejected.latest().unwrap().provider_receipt.is_none());
    assert_eq!(fixture.endpoint.counter().await, 0);
    assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 1);
    assert_eq!(fixture.proxy.lookups.load(Ordering::Acquire), 0);
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_expiry_and_endpoint_recreation_stop_before_any_business_request() {
    for expired in [false, true] {
        let fixture = Fixture::new(Fault::Normal).await;
        let effect = fixture.commit("expired-or-recreated").await;
        if expired {
            fixture.clock.0.store(10_100, Ordering::Release);
        } else {
            fixture.endpoint.recreate().await;
        }
        fixture.owner.as_ref().unwrap().resume().unwrap();
        fixture
            .settled(
                &effect,
                if expired {
                    Disposition::Expired
                } else {
                    Disposition::PolicyBlocked
                },
            )
            .await;
        assert_eq!(fixture.endpoint.counter().await, 0);
        assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 0);
        assert_eq!(fixture.proxy.lookups.load(Ordering::Acquire), 0);
        fixture.finish().await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn credential_rotation_and_current_revocation_after_connect_reject_before_http_write() {
    for rotation in [false, true] {
        let fixture = Fixture::new(Fault::HoldSecondTls).await;
        let effect = fixture.commit("rotation-or-revocation").await;
        fixture.owner.as_ref().unwrap().resume().unwrap();
        fixture.proxy.wait_gate().await;
        if rotation {
            write_credential(
                &fixture.root.path().join("secrets"),
                b"Bearer synthetic-rotated",
            );
            fixture
                .secrets
                .reload(1, credential_specs(&fixture.proxy.config(), "2"))
                .unwrap()
                .await
                .unwrap();
        } else {
            let mut rule = fixture.rule.clone();
            rule.policy_revision = 2;
            rule.enabled = false;
            fixture.authority.publish(rule).unwrap();
        }
        fixture.proxy.release();
        fixture.settled(&effect, Disposition::PolicyBlocked).await;
        assert_eq!(fixture.endpoint.counter().await, 0);
        assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 0);
        assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
        fixture.finish().await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_shutdown_cutoff_retains_real_request_root_role_and_buffers_until_retirement() {
    let mut fixture = Fixture::new(Fault::HoldPostReply).await;
    let effect = fixture.commit("live-shutdown").await;
    fixture.owner.as_ref().unwrap().resume().unwrap();
    fixture.proxy.wait_gate().await;
    assert_eq!(fixture.endpoint.counter().await, 1);
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
        DispatcherConfig::default(),
        fixture.store.clone(),
        fixture.authority.clone(),
        vec![fixture.adapter.clone()],
        fixture.clock.clone(),
        Some((1, 100))
    )
    .await
    .is_err());
    assert_eq!(fixture.record(&effect).await.attempts(), 1);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 1);
    fixture.proxy.release();
    tokio::time::timeout(WATCHDOG, async {
        while fixture.pools.snapshot().unwrap().running_requests != 0
            || fixture
                .owner
                .as_ref()
                .unwrap()
                .snapshot()
                .unwrap()
                .physical_owners
                != 0
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 1);
    assert_eq!(fixture.endpoint.counter().await, 1);
    fixture.finish_late().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unsafe_or_generic_endpoint_profiles_cannot_open_a_provider_connection() {
    let fixture = Fixture::new(Fault::Normal).await;
    let valid = qualification(&fixture.proxy.config());
    let mut unsafe_origin = valid.clone();
    unsafe_origin.origin.host = "169.254.169.254".into();
    let mut escape = valid.clone();
    escape.operation_path = "/effect/../metadata".into();
    let mut query = valid.clone();
    query.lookup_prefix = "/receipts/?url=".into();
    let mut unversioned = valid.clone();
    unversioned.endpoint_incarnation.clear();
    let mut noncanonical_lookup = valid.clone();
    noncanonical_lookup.lookup_prefix = "/receipts///".into();
    for endpoint in [
        unsafe_origin,
        escape,
        query,
        unversioned,
        noncanonical_lookup,
    ] {
        assert!(fixture
            .provider
            .deferred_adapter("tests", endpoint, fixture.clock.clone())
            .is_err());
    }
    let mut dns = fixture.proxy.config();
    dns.destinations[0].resolution = crate::HttpResolution::Dns {
        server: "127.0.0.1:53".parse().unwrap(),
        maximum_ttl_seconds: 30,
    };
    assert!(valid.validate(&dns).is_err());
    let mut unsafe_peer = fixture.proxy.config();
    unsafe_peer.destinations[0].resolution = crate::HttpResolution::Static {
        addresses: vec!["169.254.169.254".parse().unwrap()],
    };
    assert!(valid.validate(&unsafe_peer).is_err());
    assert!(fixture.proxy.requests.lock().unwrap().is_empty());
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    fixture.finish().await;
}

async fn terminal_without_delivery(fixture: &Fixture, technical: bool) {
    use latent_commit::atomic::{
        AdmissionDecision, CompleteEnvelope, PreparedAdmission, PreparedDisposition, StagedIntent,
    };
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
                    binding: "approved-http".into(),
                    operation: "http".into(),
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
