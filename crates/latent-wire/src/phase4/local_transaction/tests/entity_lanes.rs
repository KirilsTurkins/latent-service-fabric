//! Real guest and authenticated RPC evidence for entity ownership.
use super::*;
use latent_policy::capability::{MutationRequest, RecordKind};

fn authorize_entity(f: &Fixture, entity: &str) {
    authorize_entities(f, &[entity]);
}

fn authorize_entities(f: &Fixture, entities: &[&str]) {
    use latent_effects::authority::{DispatchCeiling, DispatchProfile, EffectRule, EffectScope};
    for id in ["state", "intents"] {
        let deadline = Instant::now() + Duration::from_secs(10);
        let current = f
            .policy
            .get(
                publication::TENANT,
                RecordKind::Policy,
                id,
                64 * 1024,
                deadline,
            )
            .unwrap();
        let record = current.value().as_ref().unwrap();
        let revision = record.revision;
        let mut document: serde_json::Value =
            serde_json::from_str(record.document.as_ref().unwrap()).unwrap();
        drop(current);
        for rule in document["rules"].as_array_mut().unwrap() {
            let scopes = rule["resources"]["scopes"].as_array_mut().unwrap();
            for entity in entities {
                let mut selected = scopes[0].clone();
                selected["entity"] = (*entity).into();
                scopes.push(selected);
            }
        }
        let encoded = serde_json::to_vec(&document).unwrap();
        f.policy
            .mutate(
                MutationRequest {
                    tenant: publication::TENANT,
                    actor: "compiled-guest-test-operator",
                    id,
                    kind: RecordKind::Policy,
                    operation_id: &format!("entity-{id}"),
                    expected_revision: revision,
                    document: Some(&encoded),
                },
                deadline,
                |_| Ok(()),
            )
            .unwrap();
    }
    // Policy replacement rejects the previously installed effect grant. The
    // test operator explicitly publishes a newer grant after its policy update.
    f.effects
        .publish(EffectRule {
            scope: EffectScope {
                tenant: publication::TENANT.into(),
                namespace: publication::NAMESPACE.into(),
                incarnation: 1,
                publication: f.publication.publication().as_str().into(),
                binding: "approved-event".into(),
                operation: "event".into(),
            },
            profile: DispatchProfile {
                provider: "event-provider".into(),
                destination: "approved-events".into(),
                adapter: "test-event-v1".into(),
                intent_format: 1,
                payload_format: "lsf-aggregate-v1".into(),
                idempotency_profile: "stable-effect-v1".into(),
            },
            policy_revision: 2,
            credential_epoch: 1,
            protected_credential_reference: "event-credential-reference".into(),
            ceiling: DispatchCeiling {
                maximum_payload_bytes: 4096,
                maximum_response_bytes: 4096,
                maximum_attempts: 3,
                maximum_age_millis: 60_000,
                attempt_timeout_millis: 1000,
            },
            enabled: true,
        })
        .unwrap();
}

fn entity_command(key: &str, delta: u32) -> t::InvokeCommandRequest {
    command_for_entity(key, delta, "hot")
}

fn command_for_entity(key: &str, delta: u32, entity: &str) -> t::InvokeCommandRequest {
    let mut request = command(key, delta, false);
    request.command.as_mut().unwrap().entity = Some(entity.into());
    request
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_entity_guest_serializes_before_cell_and_replays_in_progress_duplicate() {
    let f = Fixture::with_concurrent_commands(true).await;
    authorize_entity(&f, "hot");
    let forbidden = f
        .adapter()
        .invoke_command(context("alice").request(command_for_entity(
            "forbidden-entity",
            1,
            "unapproved",
        )))
        .await;
    assert!(matches!(forbidden, Err(error) if error.code() == tonic::Code::PermissionDenied));
    assert_eq!(f.executions(), 0);
    assert_eq!(
        f.owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .keys,
        0
    );
    let first_adapter = f.adapter();
    let first = tokio::spawn(async move {
        first_adapter
            .invoke_command(context("alice").request(entity_command("entity-first", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    assert_eq!(f.executions(), 1);
    let duplicate = tokio::time::timeout(
        Duration::from_secs(5),
        f.adapter()
            .invoke_command(context("alice").request(entity_command("entity-first", 1))),
    )
    .await
    .unwrap()
    .unwrap()
    .into_inner();
    assert!(duplicate.replayed);
    assert_eq!(
        duplicate.command.unwrap().outcome,
        t::CommandOutcome::InProgress as i32
    );
    let second_adapter = f.adapter();
    let second = tokio::spawn(async move {
        second_adapter
            .invoke_command(context("alice").request(entity_command("entity-second", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), async {
        while f
            .owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .queued
            != 1
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(f.executions(), 1);
    assert_eq!(f.backend.real.resource_snapshot().stores_created, 1);
    assert!(!second.is_finished());
    f.backend.imports.release.notify_one();
    let first = tokio::time::timeout(Duration::from_secs(10), first)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    success(&first);
    let second = tokio::time::timeout(Duration::from_secs(10), second)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    success(&second);
    assert_eq!(f.executions(), 2);
    assert_eq!(f.rows(Family::Command).await, 2);
    assert_eq!(
        f.owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .keys,
        0
    );
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn revoked_queued_entity_never_starts_a_guest() {
    let f = Fixture::with_concurrent_commands(true).await;
    authorize_entity(&f, "hot");
    let first_adapter = f.adapter();
    let first = tokio::spawn(async move {
        first_adapter
            .invoke_command(context("alice").request(entity_command("revoke-first", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    let second_adapter = f.adapter();
    let second = tokio::spawn(async move {
        second_adapter
            .invoke_command(context("alice").request(entity_command("revoke-queued", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), async {
        while f
            .owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .queued
            != 1
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    policy::revoke(&f.policy);
    f.backend.imports.release.notify_one();
    let _first = tokio::time::timeout(Duration::from_secs(10), first)
        .await
        .unwrap()
        .unwrap();
    let second = tokio::time::timeout(Duration::from_secs(10), second)
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(second, Err(error) if error.code() == tonic::Code::PermissionDenied));
    assert_eq!(f.executions(), 1);
    assert_eq!(f.backend.real.resource_snapshot().stores_created, 1);
    assert_eq!(
        f.owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .keys,
        0
    );
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn duplicate_of_queued_entity_waits_for_its_original_claim() {
    let f = Fixture::with_concurrent_commands(true).await;
    authorize_entity(&f, "hot");
    let first_adapter = f.adapter();
    let first = tokio::spawn(async move {
        first_adapter
            .invoke_command(context("alice").request(entity_command("queue-owner", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    let second_adapter = f.adapter();
    let second = tokio::spawn(async move {
        second_adapter
            .invoke_command(context("alice").request(entity_command("queued-original", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), async {
        while f
            .owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .queued
            != 1
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let duplicate_adapter = f.adapter();
    let duplicate = tokio::spawn(async move {
        duplicate_adapter
            .invoke_command(context("alice").request(entity_command("queued-original", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), async {
        while f
            .owners
            .as_ref()
            .unwrap()
            .entity_duplicate_waiter_count()
            .unwrap()
            != 1
        {
            assert!(!duplicate.is_finished());
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(f.executions(), 1);
    f.backend.imports.release.notify_one();
    success(
        &tokio::time::timeout(Duration::from_secs(10), first)
            .await
            .unwrap()
            .unwrap()
            .unwrap()
            .into_inner(),
    );
    let replay = tokio::time::timeout(Duration::from_secs(10), duplicate)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    let _second = tokio::time::timeout(Duration::from_secs(10), second)
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert_eq!(f.executions(), 2);
    assert_eq!(f.rows(Family::Command).await, 2);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn trapped_entity_retains_its_lane_until_the_actual_abort_writer_finishes() {
    use latent_state::store_io::StoreIoKind;
    use std::sync::{Condvar, Mutex};

    let f = Fixture::with_concurrent_commands(true).await;
    authorize_entity(&f, "hot");
    f.backend
        .imports
        .fail_stage_once
        .store(true, Ordering::SeqCst);
    let first_adapter = f.adapter();
    let first = tokio::spawn(async move {
        first_adapter
            .invoke_command(context("alice").request(entity_command("trap-first", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    let second_adapter = f.adapter();
    let second = tokio::spawn(async move {
        second_adapter
            .invoke_command(context("alice").request(entity_command("trap-second", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), async {
        while f
            .owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .queued
            != 1
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();

    let gate = Arc::new((Mutex::new(false), Condvar::new()));
    let held = Arc::clone(&gate);
    let (entered, entered_rx) = tokio::sync::oneshot::channel();
    let worker = f
        .store
        .with_store(StoreIoKind::RecoveryWrite, 64, move |_| {
            entered.send(()).unwrap();
            let lock = held.0.lock().unwrap();
            let (lock, timeout) = held
                .1
                .wait_timeout_while(lock, Duration::from_secs(10), |released| !*released)
                .unwrap();
            assert!(*lock && !timeout.timed_out());
            Ok(())
        })
        .unwrap();
    tokio::time::timeout(Duration::from_secs(5), entered_rx)
        .await
        .unwrap()
        .unwrap();
    f.backend.imports.release.notify_one();
    tokio::time::timeout(Duration::from_secs(5), async {
        while !f.store.snapshot().is_ok_and(|snapshot| snapshot.queued > 0) {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let lanes = f.owners.as_ref().unwrap().entity_lanes_snapshot().unwrap();
    assert_eq!((lanes.active, lanes.queued), (1, 1));
    assert_eq!(f.executions(), 1);
    assert!(!second.is_finished());
    *gate.0.lock().unwrap() = true;
    gate.1.notify_all();
    worker.await.unwrap().unwrap();
    let first = tokio::time::timeout(Duration::from_secs(10), first)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    assert!(matches!(first.invocation.unwrap().result,
        Some(i::invoke_response::Result::PlatformFailure(ref failure)) if failure.code == "guest-trap"));
    let second = tokio::time::timeout(Duration::from_secs(10), second)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    success(&second);
    assert_eq!(f.executions(), 2);
    assert_eq!(
        f.owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .keys,
        0
    );
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn restart_rebuilds_empty_lanes_and_recovers_durable_entity_outcomes() {
    let mut f = Fixture::new(false).await;
    authorize_entity(&f, "hot");
    let original = f
        .adapter()
        .invoke_command(context("alice").request(entity_command("restart-original", 1)))
        .await
        .unwrap()
        .into_inner();
    let body = success(&original);
    let command_id = original.command.as_ref().unwrap().command_id.clone();
    drop(original);
    assert_eq!(
        f.owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .keys,
        0
    );
    assert_eq!(f.executions(), 1);

    f.restart().await;
    assert_eq!(
        f.owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .keys,
        0
    );
    let replay = f
        .adapter()
        .invoke_command(context("alice").request(entity_command("restart-original", 1)))
        .await
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    assert_eq!(replay.command.as_ref().unwrap().command_id, command_id);
    assert_eq!(success(&replay), body);
    assert_eq!(f.executions(), 1);
    drop(replay);
    let next = f
        .adapter()
        .invoke_command(context("alice").request(entity_command("restart-next", 1)))
        .await
        .unwrap()
        .into_inner();
    success(&next);
    drop(next);
    assert_eq!(f.executions(), 2);
    assert_eq!(
        f.owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .keys,
        0
    );
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn entity_admission_rejects_the_old_incarnation_after_namespace_recreation() {
    use latent_state::namespace::{NamespaceQuota, NamespaceTransition};

    let f = Fixture::new(false).await;
    authorize_entity(&f, "hot");
    f.namespace_transition(NamespaceTransition::Quiesce)
        .await
        .unwrap();
    f.namespace_transition(NamespaceTransition::Retire)
        .await
        .unwrap();
    let old = f
        .namespace_transition(NamespaceTransition::Destroy)
        .await
        .unwrap();
    let new = f
        .namespace_transition(NamespaceTransition::Recreate {
            state_schema: old.state_schema,
            quota: NamespaceQuota::default(),
        })
        .await
        .unwrap();
    assert_eq!(new.version.incarnation, 2);
    f.authorize_incarnation(2);
    let stale = f
        .adapter()
        .invoke_command(context("alice").request(entity_command("old-entity", 1)))
        .await;
    assert!(stale.is_err());
    assert_eq!(f.executions(), 0);
    assert_eq!(
        f.owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .keys,
        0
    );
    let mut current = entity_command("new-entity", 1);
    current
        .command
        .as_mut()
        .unwrap()
        .namespace
        .as_mut()
        .unwrap()
        .incarnation = "2".into();
    let result = f
        .adapter()
        .invoke_command(context("alice").request(current))
        .await
        .unwrap()
        .into_inner();
    success(&result);
    drop(result);
    assert_eq!(f.executions(), 1);
    assert_eq!(
        f.owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .keys,
        0
    );
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn distinct_entity_churn_reclaims_all_live_lane_metadata() {
    let f = Fixture::new(false).await;
    let entities = [
        "cold-0", "cold-1", "cold-2", "cold-3", "cold-4", "cold-5", "cold-6", "cold-7",
    ];
    authorize_entities(&f, &entities);
    for entity in entities {
        let request = command_for_entity(&format!("command-{entity}"), 1, entity);
        let result = f
            .adapter()
            .invoke_command(context("alice").request(request))
            .await
            .unwrap()
            .into_inner();
        success(&result);
        drop(result);
        let snapshot = f.owners.as_ref().unwrap().entity_lanes_snapshot().unwrap();
        assert_eq!((snapshot.keys, snapshot.queued, snapshot.active), (0, 0, 0));
        assert_eq!(snapshot.retained_bytes(), 0);
    }
    assert_eq!(f.executions(), entities.len() as u64);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn dropping_a_queued_entity_rpc_cancels_its_real_reservation() {
    let f = Fixture::with_concurrent_commands(true).await;
    authorize_entity(&f, "hot");
    let first_adapter = f.adapter();
    let first = tokio::spawn(async move {
        first_adapter
            .invoke_command(context("alice").request(entity_command("cancel-owner", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    let second_adapter = f.adapter();
    let second = tokio::spawn(async move {
        second_adapter
            .invoke_command(context("alice").request(entity_command("cancel-queued", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), async {
        while f
            .owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .queued
            != 1
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    second.abort();
    assert!(second.await.is_err_and(|error| error.is_cancelled()));
    tokio::time::timeout(Duration::from_secs(5), async {
        while f
            .owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .queued
            != 0
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let snapshot = f.owners.as_ref().unwrap().entity_lanes_snapshot().unwrap();
    assert_eq!((snapshot.active, snapshot.queued), (1, 0));
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Command).await, 1);
    f.backend.imports.release.notify_one();
    let first = tokio::time::timeout(Duration::from_secs(10), first)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    success(&first);
    drop(first);
    assert_eq!(
        f.owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .keys,
        0
    );
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn active_entity_cancellation_preserves_cleanup_before_the_next_command() {
    let f = Fixture::with_concurrent_commands(false).await;
    authorize_entity(&f, "hot");
    f.install_cancellation_management().await;
    f.backend
        .imports
        .pause_after_stage
        .store(true, Ordering::SeqCst);
    let first_adapter = f.adapter();
    let first = tokio::spawn(async move {
        first_adapter
            .invoke_command(context("alice").request(entity_command("active-cancel", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.staged.notified())
        .await
        .unwrap();
    let second_adapter = f.adapter();
    let second = tokio::spawn(async move {
        second_adapter
            .invoke_command(context("alice").request(entity_command("after-cancel", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), async {
        while f
            .owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .queued
            != 1
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let mut lookup = f.lookup_request("active-cancel");
    lookup.command.as_mut().unwrap().entity = Some("hot".into());
    lookup.attempt_id = Some("1".into());
    let request = t::CancelCommandRequest {
        command: Some(lookup),
        reason: "entity cancellation".into(),
    };
    let cancelled = f
        .adapter()
        .cancel_command(context("alice").request(request))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        cancelled.disposition,
        t::CommandCancelDisposition::Requested as i32
    );
    f.backend.imports.continue_after_stage.notify_one();
    let first = tokio::time::timeout(Duration::from_secs(10), first)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    assert!(matches!(first.invocation.unwrap().result,
        Some(i::invoke_response::Result::PlatformFailure(ref failure)) if failure.code == "cancelled"));
    let second = tokio::time::timeout(Duration::from_secs(10), second)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    success(&second);
    drop((cancelled, second));
    assert_eq!(f.executions(), 2);
    assert_eq!(
        f.owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .keys,
        0
    );
    f.shutdown().await;
}
