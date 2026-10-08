use super::*;
use latent_core::PlatformErrorCode;
use latent_state::{namespace::history::HistoryEpochs, session::StateScope};

async fn original_query(fixture: &Fixture) -> (Vec<u8>, StateScope) {
    let (admission, envelope, budget) = fixture.invocation(true, "original-view");
    let execution = execute(admission.admit(&envelope, &budget).await.unwrap());
    execution.host.acquire(Mode::Query).unwrap();
    let token = execution.host.view_identity().unwrap().version;
    let scope = state_scope(true);
    execution.host.finish_guest_access();
    let completion = execution.completion.complete(success(b"query")).await;
    assert!(matches!(
        completion.outcome(),
        ActivationOutcome::Succeeded(_)
    ));
    drop((completion, execution, admission));
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    (token, scope)
}

#[tokio::test]
async fn real_query_returns_original_history_token_and_enforces_future_minimum() {
    let fixture = Fixture::new().await;
    let (token, scope) = original_query(&fixture).await;
    let mut identity =
        latent_state::session::version::ViewIdentity::from_token(&scope, &token).unwrap();
    let (admission, envelope, budget) =
        fixture.invocation_with_minimum(true, "same-view", Some(token.clone()));
    let execution = execute(admission.admit(&envelope, &budget).await.unwrap());
    execution.host.acquire(Mode::Query).unwrap();
    assert_eq!(execution.host.view_identity().unwrap().version, token);
    execution.host.finish_guest_access();
    let completion = execution.completion.complete(success(b"query")).await;
    assert!(matches!(
        completion.outcome(),
        ActivationOutcome::Succeeded(_)
    ));
    drop((completion, execution, admission));

    identity.namespace.generation += 1;
    let (admission, envelope, budget) =
        fixture.invocation_with_minimum(true, "future-view", Some(identity.token(&scope).unwrap()));
    assert_eq!(
        admission
            .admit(&envelope, &budget)
            .await
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::StateConflict
    );
    assert_eq!(fixture.rows(Family::Command).await, 0);
    drop(admission);
    assert!(fixture.native.snapshot().unwrap().physically_retired());
    fixture.shutdown().await;
}

#[tokio::test]
async fn real_query_refuses_old_schema_or_recovery_history_without_business_changes() {
    for epochs in [
        HistoryEpochs {
            schema: 2,
            recovery: 1,
        },
        HistoryEpochs {
            schema: 1,
            recovery: 2,
        },
    ] {
        let fixture = Fixture::new().await;
        let (token, _) = original_query(&fixture).await;
        fixture.change_history(epochs).await;
        let (admission, envelope, budget) =
            fixture.invocation_with_minimum(true, "old-view", Some(token));
        assert_eq!(
            admission
                .admit(&envelope, &budget)
                .await
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::Unavailable
        );
        assert_eq!(fixture.rows(Family::State).await, 0);
        assert_eq!(fixture.rows(Family::Command).await, 0);
        drop(admission);
        assert!(fixture.native.snapshot().unwrap().physically_retired());
        fixture.shutdown().await;
    }
}

#[tokio::test]
async fn original_restored_store_refuses_queries_and_pending_before_review() {
    let fixture = Fixture::new().await;
    fixture.restore_paused().await;
    for query in [true, false] {
        let (admission, envelope, budget) = fixture.invocation(query, "restore-paused");
        assert_eq!(
            admission
                .admit(&envelope, &budget)
                .await
                .err()
                .unwrap()
                .code,
            PlatformErrorCode::Unavailable
        );
        drop(admission);
        assert!(fixture.native.snapshot().unwrap().physically_retired());
    }
    assert_eq!(fixture.rows(Family::Command).await, 0);
    assert_eq!(fixture.rows(Family::State).await, 0);
    fixture.shutdown().await;
}
