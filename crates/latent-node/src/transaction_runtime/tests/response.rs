use super::*;

#[tokio::test]
async fn original_response_permission_survives_commit_and_freeze_but_not_policy_revocation() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(false, "retained-permission");
    assert!(admission.take_owned_completion().unwrap().is_none());
    let guest = admission.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Command).unwrap();
    guest
        .put(b"counter".to_vec(), value(b"committed"))
        .await
        .unwrap();
    guest.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    assert!(matches!(
        admission
            .complete(
                success(b"result"),
                fixture.commit_control(&envelope, &budget)
            )
            .await,
        ActivationOutcome::Succeeded(_)
    ));
    let response = admission.take_owned_completion().unwrap().unwrap();
    assert!(admission.take_owned_completion().unwrap().is_none());
    assert!(matches!(
        response.result,
        TransactionCompletionResult::Command(CommandCompletionDisposition::Durable { .. })
    ));
    drop((guest, admission));
    let owner = Arc::clone(&response.authority);
    assert_eq!(owner.reserved_response_bytes(), 8 * 1024 * 1024 + 16384);
    let mut delivered = 0;
    owner.with_current(&mut || delivered += 1).unwrap();
    assert_eq!(delivered, 1);
    assert_eq!(fixture.rows(Family::State).await, 1);
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);
    fixture.revoke();
    assert!(owner.with_current(&mut || delivered += 1).is_err());
    assert_eq!(delivered, 1);
    drop(response);
    // Extracted frame owners remain charged even after delivery is forbidden.
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);
    drop(owner);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test]
async fn query_response_keeps_original_read_permission_and_global_frame_charge() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(true, "retained-query");
    let guest = admission.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Query).unwrap();
    guest.finish_guest_access();
    let _ = budget.finalize_at(None, std::time::Instant::now());
    let outcome = admission
        .complete(
            success(b"query"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    assert!(matches!(outcome, ActivationOutcome::Succeeded(_)));
    let response = admission.take_owned_completion().unwrap().unwrap();
    assert!(matches!(
        response.result,
        TransactionCompletionResult::Query { .. }
    ));
    drop((guest, admission));
    let mut delivered = false;
    response
        .authority
        .with_current(&mut || delivered = true)
        .unwrap();
    assert!(delivered);
    assert_eq!(fixture.rows(Family::Command).await, 0);
    assert_eq!(fixture.rows(Family::Result).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    fixture.native.close_ordinary();
    assert!(response
        .authority
        .with_current(&mut || panic!("closed original native owner"))
        .is_err());
    assert_eq!(fixture.native.snapshot().unwrap().ordinary.slots, 1);
    drop(response);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test]
async fn existing_command_response_rechecks_fresh_data_permission_without_another_guest() {
    let fixture = Fixture::new().await;
    let (first, envelope, budget) = fixture.invocation(false, "same-key");
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
    drop((guest, first.take_owned_completion().unwrap(), first));
    assert!(fixture.native.snapshot().unwrap().physically_retired());

    let (replay, envelope, budget) = fixture.invocation(false, "same-key");
    assert_eq!(
        replay.admit(&envelope, &budget).await.err().unwrap().code,
        latent_core::PlatformErrorCode::AlreadyExists
    );
    let _ = budget.finalize_at(None, std::time::Instant::now());
    replay
        .complete(
            success(b"must not replace"),
            fixture.commit_control(&envelope, &budget),
        )
        .await;
    let response = replay.take_owned_completion().unwrap().unwrap();
    assert!(matches!(
        response.result,
        TransactionCompletionResult::Existing { .. }
    ));
    drop(replay);
    response.authority.with_current(&mut || {}).unwrap();
    assert_eq!(fixture.rows(Family::Command).await, 1);
    assert_eq!(fixture.rows(Family::Result).await, 1);
    fixture.revoke();
    assert!(response
        .authority
        .with_current(&mut || panic!("revoked replay data"))
        .is_err());
    drop(response);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}
