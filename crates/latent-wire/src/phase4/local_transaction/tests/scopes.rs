use super::*;
use latent_capabilities::namespace::RecoverySelection;

fn scoped(f: &Fixture, subject: &str, key: &str) -> tonic::Request<t::InvokeCommandRequest> {
    let mut request = command(key, 1, false);
    request.command.as_mut().unwrap().shared_recovery_scope = Some(f.recovery_scope(subject));
    context(subject).request(request)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_same_tenant_authorized_users_keep_independent_default_command_identity() {
    let f = Fixture::with_recovery(
        false,
        Default::default(),
        RecoverySelection::OriginalCaller,
        &["alice", "bob"],
    )
    .await;
    let alice = f
        .adapter()
        .invoke_command(context("alice").request(command("original", 1, false)))
        .await
        .unwrap()
        .into_inner();
    let alice_identity = alice.command.as_ref().unwrap().command_id.clone();
    assert_eq!(aggregate(&success(&alice).payload), 1);
    drop(alice);
    let bob = f
        .adapter()
        .invoke_command(context("bob").request(command("original", 1, false)))
        .await
        .unwrap()
        .into_inner();
    assert!(!bob.replayed);
    assert_ne!(bob.command.as_ref().unwrap().command_id, alice_identity);
    assert_eq!(aggregate(&success(&bob).payload), 2);
    drop(bob);
    let replay = f
        .adapter()
        .invoke_command(context("alice").request(command("original", 1, false)))
        .await
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    assert_eq!(aggregate(&success(&replay).payload), 1);
    drop(replay);
    assert_eq!(f.executions(), 2);
    assert_eq!(f.rows(Family::Command).await, 2);
    assert_eq!(f.rows(Family::Outbox).await, 2);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_explicit_shared_scope_coalesces_authorized_users_and_revocation_denies_replay(
) {
    let f = Fixture::with_recovery(
        false,
        Default::default(),
        RecoverySelection::Shared {
            name: "approved-order-team".into(),
        },
        &["alice", "bob"],
    )
    .await;
    let original = f
        .adapter()
        .invoke_command(scoped(&f, "alice", "shared"))
        .await
        .unwrap()
        .into_inner();
    let body = success(&original);
    let identity = original.command.as_ref().unwrap().command_id.clone();
    drop(original);
    assert_eq!(f.recovery_scope("alice"), f.recovery_scope("bob"));
    let replay = f
        .adapter()
        .invoke_command(scoped(&f, "bob", "shared"))
        .await
        .unwrap()
        .into_inner();
    assert!(replay.replayed);
    assert_eq!(replay.command.as_ref().unwrap().command_id, identity);
    assert_eq!(success(&replay), body);
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Outbox).await, 1);
    drop(replay);
    revoke_subject(&f, "bob");
    assert_eq!(
        f.adapter()
            .invoke_command(scoped(&f, "bob", "shared"))
            .await
            .unwrap_err()
            .code(),
        tonic::Code::PermissionDenied
    );
    let alice = f
        .adapter()
        .invoke_command(scoped(&f, "alice", "shared"))
        .await
        .unwrap()
        .into_inner();
    assert!(alice.replayed);
    assert_eq!(success(&alice), body);
    drop(alice);
    assert_eq!(f.executions(), 1);
    assert_eq!(f.rows(Family::Command).await, 1);
    f.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "Requires the maintained compiled Rust transaction guest"]
async fn actual_guest_delegation_preserves_owner_subject_and_rejects_a_forged_other_users_scope() {
    let f = Fixture::with_recovery(
        false,
        Default::default(),
        RecoverySelection::Delegated {
            delegation: "approved-order-review".into(),
            service: "orders-api".into(),
        },
        &["alice", "bob"],
    )
    .await;
    let original = f
        .adapter()
        .invoke_command(scoped(&f, "alice", "delegated"))
        .await
        .unwrap()
        .into_inner();
    let alice_identity = original.command.as_ref().unwrap().command_id.clone();
    drop(original);
    assert_ne!(f.recovery_scope("alice"), f.recovery_scope("bob"));
    let mut forged = command("delegated", 1, false);
    forged.command.as_mut().unwrap().shared_recovery_scope = Some(f.recovery_scope("alice"));
    let mut bob = principal("bob");
    bob.claims
        .insert("delegation".into(), "approved-order-review".into());
    assert_eq!(
        f.adapter()
            .invoke_command(context_for(bob).request(forged))
            .await
            .unwrap_err()
            .code(),
        tonic::Code::PermissionDenied
    );
    assert_eq!(f.executions(), 1);
    let independent = f
        .adapter()
        .invoke_command(scoped(&f, "bob", "delegated"))
        .await
        .unwrap()
        .into_inner();
    assert!(!independent.replayed);
    assert_ne!(
        independent.command.as_ref().unwrap().command_id,
        alice_identity
    );
    assert_eq!(aggregate(&success(&independent).payload), 2);
    drop(independent);
    let alice = f
        .adapter()
        .invoke_command(scoped(&f, "alice", "delegated"))
        .await
        .unwrap()
        .into_inner();
    assert!(alice.replayed);
    assert_eq!(aggregate(&success(&alice).payload), 1);
    drop(alice);
    assert_eq!(f.executions(), 2);
    assert_eq!(f.rows(Family::Command).await, 2);
    assert_eq!(f.rows(Family::Outbox).await, 2);
    f.shutdown().await;
}

fn revoke_subject(f: &Fixture, subject: &str) {
    use latent_policy::capability::{MutationRequest, RecordKind};
    let deadline = Instant::now() + Duration::from_secs(10);
    let current = f
        .policy
        .get(
            publication::TENANT,
            RecordKind::Policy,
            "state",
            64 * 1024,
            deadline,
        )
        .unwrap();
    let revision = current.value().as_ref().unwrap().revision;
    let mut document: serde_json::Value =
        serde_json::from_str(current.value().as_ref().unwrap().document.as_ref().unwrap()).unwrap();
    drop(current);
    document["rules"]
        .as_array_mut()
        .unwrap()
        .retain(|rule| rule["id"].as_str() != Some(subject));
    f.policy
        .mutate(
            MutationRequest {
                tenant: publication::TENANT,
                actor: "compiled-guest-test-operator",
                kind: RecordKind::Policy,
                id: "state",
                operation_id: "revoke-shared-user",
                expected_revision: revision,
                document: Some(&serde_json::to_vec(&document).unwrap()),
            },
            deadline,
            |_| Ok(()),
        )
        .unwrap();
}
