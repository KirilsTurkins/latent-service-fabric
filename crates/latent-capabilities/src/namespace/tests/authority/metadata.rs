//! Joint current decisions restrict metadata without creating a new grant.
use super::*;

fn original(f: &Fixture) -> NamespaceAuthority {
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = f.snapshot();
    let initial = f.decision(&snapshot, &actor, &scope, "acquire-command");
    let read = f.read();
    NamespaceAuthority::seal(
        &f.policy,
        &initial,
        &read,
        NamespaceAdmission {
            activation: ActivationId("original-metadata".into()),
            deadline: deadline(),
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema(),
        },
        f.namespaces.lifecycle().pin(&read).unwrap(),
    )
    .unwrap()
}
fn retained(f: &Fixture, subject: &str, operation: &str) -> OwnedPolicyDecision {
    let actor = principal(subject);
    let scope = scope(
        &actor,
        Some(if subject == "alice" {
            "alice-order"
        } else {
            "bob-order"
        }),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = f.snapshot();
    let decision = f.decision(&snapshot, &actor, &scope, operation);
    f.policy.retain_decision(&decision).unwrap()
}

#[test]
fn joint_cancel_metadata_requires_current_original_and_retained_purpose() {
    let f = Fixture::new();
    let authority = original(&f);
    let dependency = retained(&f, "alice", "cancel-command");
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = f.snapshot();
    let commit = f.decision(&snapshot, &actor, &scope, "commit");
    let read = f.read();
    let mut called = false;
    authority
        .with_operation_metadata_dependency(
            &f.policy,
            &commit,
            &read,
            ("commit", &dependency),
            || {
                called = true;
                Ok(())
            },
        )
        .unwrap();
    assert!(called);
    f.update(None, "revoke-joint-metadata");
    called = false;
    assert!(authority
        .with_operation_metadata_dependency(
            &f.policy,
            &commit,
            &read,
            ("commit", &dependency),
            || {
                called = true;
                Ok(())
            }
        )
        .is_err());
    assert!(!called);
    absent(&f, "joint-metadata");
}

#[test]
fn joint_cancel_metadata_refuses_foreign_principal_store_and_non_cancel_purpose() {
    let f = Fixture::new();
    let foreign = Fixture::new();
    let authority = original(&f);
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = f.snapshot();
    let commit = f.decision(&snapshot, &actor, &scope, "commit");
    let read = f.read();
    for dependency in [
        retained(&f, "bob", "cancel-command"),
        retained(&f, "alice", "read-result"),
        retained(&foreign, "alice", "cancel-command"),
    ] {
        let mut called = false;
        assert!(authority
            .with_operation_metadata_dependency(
                &f.policy,
                &commit,
                &read,
                ("commit", &dependency),
                || {
                    called = true;
                    Ok(())
                }
            )
            .is_err());
        assert!(!called);
    }
    let dependency = retained(&f, "alice", "cancel-command");
    let mut called = false;
    assert!(authority
        .with_operation_metadata_dependency(&f.policy, &commit, &read, ("put", &dependency), || {
            called = true;
            Ok(())
        })
        .is_err());
    assert!(!called);
    absent(&f, "joint-foreign-metadata");
}

#[test]
fn joint_metadata_callback_refusal_and_panic_preserve_existing_policy_owner() {
    let f = Fixture::new();
    let authority = original(&f);
    let dependency = retained(&f, "alice", "cancel-command");
    let actor = principal("alice");
    let scope = scope(
        &actor,
        Some("alice-order"),
        &RecoverySelection::OriginalCaller,
    );
    let snapshot = f.snapshot();
    let commit = f.decision(&snapshot, &actor, &scope, "commit");
    let read = f.read();
    assert!(authority
        .with_operation_metadata_dependency(
            &f.policy,
            &commit,
            &read,
            ("commit", &dependency),
            || Err(denied())
        )
        .is_err());
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _ = authority.with_operation_metadata_dependency(
            &f.policy,
            &commit,
            &read,
            ("commit", &dependency),
            || panic!("joint callback refused"),
        );
    }))
    .is_err());
    // Existing policy and namespace locks recover a callback panic. Neither
    // callback writes storage or changes the original current decision.
    authority
        .with_operation_metadata_dependency(
            &f.policy,
            &commit,
            &read,
            ("commit", &dependency),
            || Ok(()),
        )
        .unwrap();
    absent(&f, "joint-panic-metadata");
}
