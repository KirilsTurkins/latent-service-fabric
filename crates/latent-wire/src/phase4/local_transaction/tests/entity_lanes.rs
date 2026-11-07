//! Real guest and authenticated RPC evidence for entity ownership.
use super::*;
use latent_policy::capability::{MutationRequest, RecordKind};

fn authorize_entity(f: &Fixture, entity: &str) {
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
            let mut selected = scopes[0].clone();
            selected["entity"] = entity.into();
            scopes.push(selected);
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
    let mut request = command(key, delta, false);
    request.command.as_mut().unwrap().entity = Some("hot".into());
    request
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_entity_guest_serializes_before_cell_and_replays_in_progress_duplicate() {
    let f = Fixture::with_concurrent_commands(true).await;
    authorize_entity(&f, "hot");
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
