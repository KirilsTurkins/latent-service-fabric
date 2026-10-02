//! Final policy intersections use original sealed staging decisions and redb.
use super::*;
use latent_policy::capability::{CallRestrictions, GrantRestriction, MutationRequest, RecordKind};
use serde_json::json;

fn mutation(
    fixture: &Fixture,
    kind: RecordKind,
    operation: &str,
    expected: u64,
    document: Option<&serde_json::Value>,
) -> u64 {
    let bytes = document.map(|value| serde_json::to_vec(value).unwrap());
    let receipt = fixture
        .policy
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                kind,
                id: "intents",
                operation_id: operation,
                expected_revision: expected,
                document: bytes.as_deref(),
            },
            deadline(),
            |_| Ok(()),
        )
        .unwrap();
    receipt.value().revision
}

fn stage(fixture: &Fixture) -> (OwnedPolicyDecision, u64) {
    let mut rule = fixture.document["rules"][0].clone();
    rule["capability"] = INTENT_CONTRACT.into();
    rule["operations"] = json!(["stage"]);
    let revision = mutation(
        fixture,
        RecordKind::Policy,
        "stage-policy",
        0,
        Some(&json!({"formatVersion":1,"tenant":"a","rules":[rule]})),
    );
    mutation(
        fixture,
        RecordKind::ProviderBinding,
        "stage-binding",
        0,
        Some(
            &json!({"formatVersion":1,"tenant":"a","capability":INTENT_CONTRACT,
            "providerProfile":"qualified-http-put-once-v1",
            "configurationDigest":format!("sha256:{}","3".repeat(64)),
            "configurationEpoch":1,"restriction":{"operations":["stage"]}}),
        ),
    );
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = fixture
        .policy
        .snapshot(
            &TenantId("a".into()),
            &["intents".into()],
            "intents",
            deadline(),
        )
        .unwrap();
    let grant = GrantRestriction::parse(br#"{"operations":[]}"#, INTENT_CONTRACT).unwrap();
    let decision = snapshot
        .authorize(
            EvaluationInput {
                principal: &actor,
                service: "echo",
                publication: fixture.publication.publication().as_str(),
                capability: INTENT_CONTRACT,
                operation: "stage",
                resource: ResourceTarget::State {
                    namespace: &scope.namespace,
                    incarnation: scope.incarnation,
                    entity: scope.entity.as_deref(),
                    recovery_kind: scope.recovery_kind,
                    recovery_scope: &scope.recovery_scope,
                    result_policy: &scope.result_policy,
                },
            },
            &CallRestrictions {
                imported_operations: &["stage".into()],
                deployment: &grant,
                provider_configuration: &grant,
                provider_profile: "qualified-http-put-once-v1",
                configuration_digest: &format!("sha256:{}", "3".repeat(64)),
                configuration_epoch: 1,
                remaining: CapabilityCeiling {
                    operations: 16,
                    input_bytes: 1_048_576,
                    output_bytes: 1_048_576,
                    wall_time_millis: 10_000,
                },
                input_bytes: 0,
                output_bytes: 0,
            },
            &fixture.publication,
        )
        .unwrap();
    (fixture.policy.retain_decision(&decision).unwrap(), revision)
}

#[test]
fn retained_staging_revocation_blocks_actual_commit_without_revoking_state_or_running_effect_fence()
{
    let fixture = Fixture::new();
    let (stage, revision) = stage(&fixture);
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = fixture.snapshot();
    let initial = fixture.decision(&snapshot, &actor, &scope, "acquire-command");
    let commit = fixture.decision(&snapshot, &actor, &scope, "commit");
    let read = fixture.read();
    for revoked in [false, true] {
        let authority = NamespaceAuthority::seal(
            &fixture.policy,
            &initial,
            &read,
            NamespaceAdmission {
                activation: ActivationId(format!("stage-{revoked}")),
                deadline: deadline(),
                recovery: &RecoverySelection::OriginalCaller,
                state_schema: &schema(),
            },
            fixture.namespaces.lifecycle().pin(&read).unwrap(),
        )
        .unwrap();
        let name = if revoked {
            "stage-revoked"
        } else {
            "stage-current"
        };
        let pending = batch(&read, name);
        let acceptance = authority
            .prepare_commit_io(&fixture.policy, &commit, &read, &pending)
            .unwrap()
            .retain_policy(&stage)
            .unwrap();
        if revoked {
            mutation(
                &fixture,
                RecordKind::Policy,
                "revoke-staging-only",
                revision,
                None,
            );
        }
        // The state acquisition and current commit grant remain valid independently.
        fixture
            .policy
            .with_current(&commit, &mut |_, _| Ok(()))
            .unwrap();
        let mut effect_fence_ran = false;
        let result = fixture.database.apply_fenced(pending, || {
            acceptance.accept_with(|| {
                effect_fence_ran = true;
                Ok(())
            })
        });
        assert_eq!(effect_fence_ran, !revoked);
        if revoked {
            assert!(matches!(result, Err(FencedStoreError::Fence(_))));
            absent(&fixture, name);
            assert!(authority.cancellation().request());
        } else {
            result.unwrap();
            assert!(!authority.cancellation().request());
            for family in [Family::State, Family::Outbox, Family::Command] {
                assert_eq!(
                    fixture
                        .database
                        .snapshot()
                        .unwrap()
                        .get(&RowKey {
                            family,
                            key: name.as_bytes().to_vec()
                        })
                        .unwrap(),
                    Some(b"retained".to_vec())
                );
            }
        }
    }
}
