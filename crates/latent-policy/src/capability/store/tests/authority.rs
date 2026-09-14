use super::*;
use crate::capability::{EvaluationInput, Explanation, ResourceTarget};
mod publication;

fn configure(store: &PolicyStore) {
    let bytes = serde_json::to_vec(&policy()).unwrap();
    mutate(store, "p", "policy", 0, Some(&bytes)).unwrap();
    let bytes = serde_json::to_vec(&binding()).unwrap();
    store
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                kind: RecordKind::ProviderBinding,
                id: "binding",
                operation_id: "binding",
                expected_revision: 0,
                document: Some(&bytes),
            },
            deadline(),
            |_| Ok(()),
        )
        .unwrap();
}
#[test]
fn held_policy_snapshots_reject_later_calls_after_revocation_and_owner_retirement() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits {
        maximum_read_owners: 1,
        ..PolicyStoreLimits::default()
    });
    configure(&store);
    let snapshot = store
        .snapshot(&TenantId("a".into()), &["p".into()], "binding", deadline())
        .unwrap();
    let actor = principal();
    let publication = publication_id();
    let input = EvaluationInput {
        principal: &actor,
        service: "echo",
        publication: &publication,
        capability: "latent:secrets/reader@0.1.0",
        operation: "read",
        resource: ResourceTarget::Secrets {
            reference: "test-key",
        },
    };
    assert_eq!(snapshot.explain(&input), Explanation::Allow);
    mutate(&store, "p", "revoke", 2, None).unwrap();
    assert_eq!(snapshot.explain(&input), Explanation::Indeterminate);
    drop(snapshot);
    assert!(store
        .snapshot(&TenantId("a".into()), &["p".into()], "binding", deadline())
        .is_err());
    let bytes = serde_json::to_vec(&policy()).unwrap();
    mutate(&store, "p", "replace", 4, Some(&bytes)).unwrap();
    let held = store
        .snapshot(&TenantId("a".into()), &["p".into()], "binding", deadline())
        .unwrap();
    assert_eq!(held.explain(&input), Explanation::Allow);
    drop(store);
    let reopened = fixture.store(PolicyStoreLimits::default());
    assert_eq!(held.explain(&input), Explanation::Indeterminate);
    assert_eq!(
        reopened
            .snapshot(&TenantId("a".into()), &["p".into()], "binding", deadline())
            .unwrap()
            .explain(&input),
        Explanation::Allow
    );
}
#[test]
fn principal_policy_and_binding_revisions_narrow_and_invalidate_independently() {
    let fixture = Fixture::new();
    let store = fixture.store(PolicyStoreLimits::default());
    configure(&store);
    let mut other = policy();
    other["rules"][0]["principals"][0]["subject"] = "bob".into();
    let bytes = serde_json::to_vec(&other).unwrap();
    mutate(&store, "principal", "principal", 0, Some(&bytes)).unwrap();
    let actor = principal();
    let publication = publication_id();
    let input = EvaluationInput {
        principal: &actor,
        service: "echo",
        publication: &publication,
        capability: "latent:secrets/reader@0.1.0",
        operation: "read",
        resource: ResourceTarget::Secrets {
            reference: "test-key",
        },
    };
    let snapshot = store
        .snapshot(
            &TenantId("a".into()),
            &["p".into(), "principal".into()],
            "binding",
            deadline(),
        )
        .unwrap();
    assert_eq!(snapshot.explain(&input), Explanation::Deny);
    let accepted = store
        .snapshot(&TenantId("a".into()), &["p".into()], "binding", deadline())
        .unwrap();
    assert_eq!(accepted.explain(&input), Explanation::Allow);
    store
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                kind: RecordKind::ProviderBinding,
                id: "binding",
                operation_id: "revoke-binding",
                expected_revision: 3,
                document: None,
            },
            deadline(),
            |_| Ok(()),
        )
        .unwrap();
    assert_eq!(accepted.explain(&input), Explanation::Indeterminate);
    assert!(store
        .snapshot(&TenantId("b".into()), &["p".into()], "binding", deadline())
        .is_err());
}
