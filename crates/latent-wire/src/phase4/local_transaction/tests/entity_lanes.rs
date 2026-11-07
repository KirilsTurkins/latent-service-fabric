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
async fn queued_entity_keeps_its_original_revision_after_compatible_route_change() {
    let mut f = Fixture::with_concurrent_commands(true).await;
    authorize_entity(&f, "hot");
    let first_adapter = f.adapter();
    let first = tokio::spawn(async move {
        first_adapter
            .invoke_command(context("alice").request(entity_command("pin-owner", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    let queued_adapter = f.adapter();
    let queued = tokio::spawn(async move {
        queued_adapter
            .invoke_command(context("alice").request(entity_command("pin-queued", 1)))
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
    let current = f.apply_compatible_revision().await;
    f.backend.imports.release.notify_one();
    let first = tokio::time::timeout(Duration::from_secs(10), first)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    success(&first);
    let queued = tokio::time::timeout(Duration::from_secs(10), queued)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    success(&queued);
    let original = &first
        .command
        .as_ref()
        .unwrap()
        .source
        .as_ref()
        .unwrap()
        .revision_id;
    let pinned = &queued
        .command
        .as_ref()
        .unwrap()
        .source
        .as_ref()
        .unwrap()
        .revision_id;
    assert_eq!(pinned, original);
    assert_ne!(pinned, &current.revision.0);
    assert_eq!(f.executions(), 2);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
#[expect(
    clippy::too_many_lines,
    reason = "Exercise conflict and waiter cancellation against one physical original owner"
)]
async fn conflicting_or_cancelled_queued_duplicate_does_not_change_its_original() {
    let f = Fixture::with_concurrent_commands(true).await;
    authorize_entity(&f, "hot");
    let first_adapter = f.adapter();
    let first = tokio::spawn(async move {
        first_adapter
            .invoke_command(context("alice").request(entity_command("duplicate-holder", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    let original_adapter = f.adapter();
    let original = tokio::spawn(async move {
        original_adapter
            .invoke_command(context("alice").request(entity_command("duplicate-original", 1)))
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
    let conflict = tokio::time::timeout(
        Duration::from_secs(5),
        f.adapter()
            .invoke_command(context("alice").request(entity_command("duplicate-original", 2))),
    )
    .await
    .unwrap();
    assert!(matches!(conflict, Err(error) if error.code() == tonic::Code::Aborted));
    let duplicate_adapter = f.adapter();
    let duplicate = tokio::spawn(async move {
        duplicate_adapter
            .invoke_command(context("alice").request(entity_command("duplicate-original", 1)))
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
    duplicate.abort();
    assert!(duplicate.await.is_err_and(|error| error.is_cancelled()));
    tokio::time::timeout(Duration::from_secs(5), async {
        while f
            .owners
            .as_ref()
            .unwrap()
            .entity_duplicate_waiter_count()
            .unwrap()
            != 0
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(
        f.owners
            .as_ref()
            .unwrap()
            .entity_lanes_snapshot()
            .unwrap()
            .queued,
        1
    );
    assert_eq!(f.executions(), 1);
    f.backend.imports.release.notify_one();
    let first = tokio::time::timeout(Duration::from_secs(10), first)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    success(&first);
    let original = tokio::time::timeout(Duration::from_secs(10), original)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    success(&original);
    assert_eq!(f.executions(), 2);
    assert_eq!(f.rows(Family::Command).await, 2);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn cold_entity_progresses_while_hot_owner_reports_conservative_conflict() {
    let f = Fixture::with_concurrent_commands(true).await;
    authorize_entities(&f, &["hot", "cold"]);
    let hot_adapter = f.adapter();
    let hot = tokio::spawn(async move {
        hot_adapter
            .invoke_command(context("alice").request(command_for_entity("parallel-hot", 1, "hot")))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    let cold = tokio::time::timeout(
        Duration::from_secs(10),
        f.adapter()
            .invoke_command(context("alice").request(command_for_entity(
                "parallel-cold",
                1,
                "cold",
            ))),
    )
    .await
    .unwrap()
    .unwrap()
    .into_inner();
    success(&cold);
    assert!(!hot.is_finished());
    f.backend.imports.release.notify_one();
    let hot = tokio::time::timeout(Duration::from_secs(10), hot)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    let Some(i::invoke_response::Result::PlatformFailure(failure)) =
        hot.invocation.as_ref().unwrap().result.as_ref()
    else {
        panic!("expected a visible conflict from the original hot command");
    };
    assert_eq!(failure.code, "state-conflict");
    let hot_command = hot.command.as_ref().unwrap();
    assert_eq!(hot_command.outcome, t::CommandOutcome::Aborted as i32);
    assert!(!hot_command.application_state_committed);
    assert_eq!(f.executions(), 2);
    assert_eq!(f.rows(Family::Command).await, 2);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn departed_duplicate_does_not_keep_disconnected_owner_alive() {
    let f = Fixture::with_concurrent_commands(true).await;
    authorize_entity(&f, "hot");
    let adapter = f.adapter();
    let holder = tokio::spawn(async move {
        adapter
            .invoke_command(context("alice").request(entity_command("depart-holder", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    let adapter = f.adapter();
    let original = tokio::spawn(async move {
        adapter
            .invoke_command(context("alice").request(entity_command("depart-shared", 1)))
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
    let adapter = f.adapter();
    let duplicate = tokio::spawn(async move {
        adapter
            .invoke_command(context("alice").request(entity_command("depart-shared", 1)))
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
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    duplicate.abort();
    assert!(duplicate.await.is_err_and(|error| error.is_cancelled()));
    tokio::time::timeout(Duration::from_secs(5), async {
        while f
            .owners
            .as_ref()
            .unwrap()
            .entity_duplicate_waiter_count()
            .unwrap()
            != 0
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    original.abort();
    assert!(original.await.is_err_and(|error| error.is_cancelled()));
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
    f.backend.imports.release.notify_one();
    let holder = tokio::time::timeout(Duration::from_secs(10), holder)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    success(&holder);
    assert_eq!(f.rows(Family::Command).await, 1);
    assert_eq!(f.executions(), 1);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn cancelled_queued_owner_is_not_replaced_by_its_duplicate() {
    let f = Fixture::with_concurrent_commands(true).await;
    authorize_entity(&f, "hot");
    let holder_adapter = f.adapter();
    let holder = tokio::spawn(async move {
        holder_adapter
            .invoke_command(context("alice").request(entity_command("cancel-holder", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    let original_adapter = f.adapter();
    let mut request = entity_command("cancel-shared", 1);
    request.invocation.as_mut().unwrap().activation_id = Some("cancel-shared-owner".into());
    let original = tokio::spawn(async move {
        original_adapter
            .invoke_command(context("alice").request(request))
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
            .invoke_command(context("alice").request(entity_command("cancel-shared", 1)))
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
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(
        f.manager
            .cancel_for(
                &latent_core::TenantId(publication::TENANT.into()),
                &latent_core::ActivationId("cancel-shared-owner".into()),
                "explicit cancellation"
            )
            .unwrap(),
        latent_core::CancelDisposition::Accepted
    );
    let original = tokio::time::timeout(Duration::from_secs(10), original)
        .await
        .unwrap()
        .unwrap();
    assert!(original.is_err());
    let duplicate = tokio::time::timeout(Duration::from_secs(10), duplicate)
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(duplicate, Err(error) if error.code() == tonic::Code::Unavailable));
    assert_eq!(f.executions(), 1);
    f.backend.imports.release.notify_one();
    let holder = tokio::time::timeout(Duration::from_secs(10), holder)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    success(&holder);
    assert_eq!(f.rows(Family::Command).await, 1);
    assert_eq!(f.executions(), 1);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn queued_duplicate_keeps_first_owner_after_original_waiter_disconnects() {
    let mut f = Fixture::with_concurrent_commands(true).await;
    authorize_entity(&f, "hot");
    let holder_adapter = f.adapter();
    let holder = tokio::spawn(async move {
        holder_adapter
            .invoke_command(context("alice").request(entity_command("pin-holder", 1)))
            .await
    });
    tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
        .await
        .unwrap();
    let original_adapter = f.adapter();
    let original = tokio::spawn(async move {
        original_adapter
            .invoke_command(context("alice").request(entity_command("pin-surviving", 1)))
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
    let current = f.apply_compatible_revision().await;
    let duplicate_adapter = f.adapter();
    let duplicate = tokio::spawn(async move {
        duplicate_adapter
            .invoke_command(context("alice").request(entity_command("pin-surviving", 1)))
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
    original.abort();
    assert!(original.await.is_err_and(|error| error.is_cancelled()));
    assert_eq!(f.executions(), 1);
    f.backend.imports.release.notify_one();
    let holder = tokio::time::timeout(Duration::from_secs(10), holder)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    success(&holder);
    let duplicate = tokio::time::timeout(Duration::from_secs(10), duplicate)
        .await
        .unwrap()
        .unwrap()
        .unwrap()
        .into_inner();
    assert!(duplicate.replayed);
    tokio::time::timeout(Duration::from_secs(10), async {
        while f.rows(Family::Outbox).await != 2 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let retry = tokio::time::timeout(
        Duration::from_secs(10),
        f.adapter()
            .invoke_command(context("alice").request(entity_command("pin-surviving", 1))),
    )
    .await
    .unwrap()
    .unwrap()
    .into_inner();
    success(&retry);
    let first = &holder
        .command
        .as_ref()
        .unwrap()
        .source
        .as_ref()
        .unwrap()
        .revision_id;
    let observed = &retry
        .command
        .as_ref()
        .unwrap()
        .source
        .as_ref()
        .unwrap()
        .revision_id;
    assert_ne!(first, &current.revision.0);
    assert_eq!(observed, first);
    assert_eq!(f.executions(), 2);
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
