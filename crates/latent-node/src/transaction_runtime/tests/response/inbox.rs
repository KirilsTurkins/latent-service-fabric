//! Recheck the real source after duplicate admission, before a positive reply.
use super::*;
use latent_commit::atomic::{CommandRecord, Identity, InboxIdentity};
use latent_state::{
    embedded::{AtomicBatch, RowMutation, StoreError},
    inbox_scope::{InboxScope, PreparedInboxScope},
    protected_store::ProtectedStoreError,
    store_io::StoreIoKind,
};
use sha2::{Digest, Sha256};

mod entity;
mod retry;

fn attach(
    admission: Arc<NativeTransactionAdmission>,
    identity: &InboxIdentity,
    scope: &InboxScope,
) -> Arc<NativeTransactionAdmission> {
    Arc::new(
        Arc::try_unwrap(admission)
            .ok()
            .unwrap()
            .with_trusted_inbox(identity.clone())
            .unwrap()
            .with_trusted_inbox_scope(scope.clone())
            .unwrap(),
    )
}

fn source() -> (InboxScope, InboxIdentity) {
    let scope = InboxScope {
        tenant: "a".into(),
        namespace: "orders".into(),
        incarnation: 1,
        processing_scope: "primary".into(),
        provider: "input".into(),
        stream: "orders".into(),
        stream_created: "2026-01-01T00:00:00Z".into(),
    };
    let identity = InboxIdentity {
        provider: scope.provider.clone(),
        binding: scope.input_binding().unwrap(),
        message: "42".into(),
        payload_digest: Identity::parse_hex(&format!(
            "{:x}",
            latent_core::digest::HexDigest(Sha256::digest(b"same"))
        ))
        .unwrap(),
    };
    (scope, identity)
}

async fn install_source(fixture: &Fixture, scope: &InboxScope) {
    let approved = scope.clone();
    fixture
        .protected_store()
        .with_store(StoreIoKind::Write, 8192, move |store| {
            let view = store.snapshot()?;
            let plan = PreparedInboxScope::prepare(&view, &approved)?;
            drop(view);
            store.apply(plan.into_batch())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}

fn invocation(
    fixture: &Fixture,
    scope: &InboxScope,
    identity: &InboxIdentity,
    entity: Option<&str>,
) -> (
    Arc<NativeTransactionAdmission>,
    latent_activation::ActivationEnvelope,
    latent_core::ActivationBudget,
) {
    let key = identity.command_key().unwrap();
    let (admission, mut envelope, budget) = match entity {
        Some(entity) => fixture.entity_invocation(&key, entity),
        None => fixture.invocation(false, &key),
    };
    envelope.principal.kind = latent_core::PrincipalKind::Trigger;
    (attach(admission, identity, scope), envelope, budget)
}

async fn committed_input(
    entity: Option<&str>,
) -> (Fixture, InboxScope, InboxIdentity, CommandRecord) {
    let fixture = Box::pin(Fixture::with_scoped_trigger()).await;
    let (scope, identity) = source();
    install_source(&fixture, &scope).await;
    let (first, envelope, budget) = invocation(&fixture, &scope, &identity, entity);
    let guest = first.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Command).unwrap();
    guest.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    first
        .complete(
            success(b"original"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    let original = first.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
        command, ..
    }) = &original.result
    else {
        panic!("original inbox command did not commit");
    };
    let command = command.clone();
    assert_eq!(command.inbox_identity(), Some(&identity));
    drop((guest, original, first, envelope, budget));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    assert_eq!(fixture.owners.lanes.snapshot().keys, 0);
    (fixture, scope, identity, command)
}

async fn replace_source(fixture: &Fixture, scope: InboxScope, bytes: Option<Vec<u8>>) {
    fixture
        .protected_store()
        .with_store(StoreIoKind::RecoveryWrite, 8192, move |store| {
            let view = store.snapshot()?;
            let expected = latent_state::inbox_scope::require_existing(&view, &scope)?;
            drop(view);
            store.apply(AtomicBatch {
                mutations: vec![RowMutation {
                    key: expected.key.clone(),
                    value: bytes,
                }],
                expectations: vec![expected],
            })
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn source_loss_after_admission_refuses_full_and_expired_inbox_replay() {
    for entity in [None, Some("hot")] {
        for expired_body in [false, true] {
            Box::pin(source_loss_after_admission(entity, expired_body)).await;
        }
    }
}

async fn source_loss_after_admission(entity: Option<&str>, expired_body: bool) {
    let (fixture, scope, identity, original) = Box::pin(committed_input(entity)).await;
    if expired_body {
        fixture.set_result_time(original.result_expires(), true);
    }
    let (replay, envelope, budget) = invocation(&fixture, &scope, &identity, entity);
    assert_eq!(
        replay.admit(&envelope, &budget).await.err().unwrap().code,
        latent_core::PlatformErrorCode::AlreadyExists
    );
    replace_source(&fixture, scope, None).await;
    let _ = budget.finalize_at(None, std::time::Instant::now());
    replay
        .complete(
            success(b"must not execute or acknowledge"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    let response = replay.take_owned_completion().unwrap().unwrap();
    let TransactionCompletionResult::Existing {
        command,
        result: Err(error),
        ..
    } = &response.result
    else {
        panic!("missing source must not publish a successful duplicate result");
    };
    assert_eq!(error.code, latent_core::PlatformErrorCode::StateConflict);
    assert_eq!(command.id(), original.id());
    assert_eq!(command.attempt(), original.attempt());
    assert_eq!(command.source(), original.source());
    assert_eq!(command.inbox_identity(), Some(&identity));
    assert_eq!(command.outcome(), Outcome::Committed);
    for family in [Family::Command, Family::Result, Family::Inbox] {
        assert_eq!(fixture.rows(family).await, 1);
    }
    for family in [Family::State, Family::Outbox] {
        assert_eq!(fixture.rows(family).await, 0);
    }
    assert!(fixture.protected_store().failure().is_none());
    drop((response, replay, envelope, budget));
    assert_eq!(fixture.owners.lanes.snapshot().keys, 0);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn corrupt_source_after_admission_quarantines_inbox_replay() {
    for entity in [None, Some("hot")] {
        Box::pin(corrupt_source_after_admission(entity)).await;
    }
}

async fn corrupt_source_after_admission(entity: Option<&str>) {
    let (fixture, scope, identity, _original) = Box::pin(committed_input(entity)).await;
    let (replay, envelope, budget) = invocation(&fixture, &scope, &identity, entity);
    assert_eq!(
        replay.admit(&envelope, &budget).await.err().unwrap().code,
        latent_core::PlatformErrorCode::AlreadyExists
    );
    replace_source(&fixture, scope, Some(b"damaged".to_vec())).await;
    let _ = budget.finalize_at(None, std::time::Instant::now());
    replay
        .complete(
            success(b"must not acknowledge"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    assert_eq!(
        fixture.protected_store().failure(),
        Some(ProtectedStoreError::Store(StoreError::Corrupt))
    );
    let response = replay.take_owned_completion().unwrap();
    if let Some(response) = &response {
        assert!(matches!(
            &response.result,
            TransactionCompletionResult::Existing { result: Err(_), .. }
        ));
    }
    drop((response, replay, envelope, budget));
    assert_eq!(fixture.owners.lanes.snapshot().keys, 0);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown_uncertain_writer().await;
}
