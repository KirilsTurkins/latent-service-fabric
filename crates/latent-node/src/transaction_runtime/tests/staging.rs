use super::*;
use latent_executor::transaction::{
    Intent, IntentFailure, TransactionStagingObserver, TransactionStagingProgress,
};
use std::sync::Mutex;
use std::time::Instant;

#[derive(Default)]
struct Observed(Mutex<Vec<TransactionStagingProgress>>);
impl TransactionStagingObserver for Observed {
    fn observe(&self, progress: TransactionStagingProgress) {
        self.0.lock().unwrap().push(progress);
    }
}

fn intent(binding: &str) -> Intent {
    Intent {
        binding: binding.into(),
        operation: "event".into(),
        payload: value(b"original intent"),
        expires_at_unix_millis: None,
    }
}

#[tokio::test]
async fn native_staging_observer_reports_only_post_insertion_on_original_host() {
    let fixture = Fixture::with_staging().await;
    let (admission, envelope, budget) = fixture.invocation(false, "original-observer");
    admission.admit(&envelope, &budget).await.unwrap();
    let TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("command host absent");
    };
    let identity = host.staging_identity().unwrap();
    assert_eq!(identity.command_id, claim.record().id().hex());
    assert_eq!(identity.attempt_id, claim.record().attempt().to_string());
    assert_eq!(
        identity.transaction_id,
        claim.record().transaction_id().hex()
    );
    assert_eq!(identity.publication_id, claim.record().source().publication);
    let observed = Arc::new(Observed::default());
    host.bind_staging_observer(observed.clone()).unwrap();
    assert_eq!(
        host.bind_staging_observer(observed.clone()),
        Err(StateFailure::HandleClosed)
    );
    assert_eq!(
        host.stage(intent("approved-event")).await,
        Err(IntentFailure::HandleClosed)
    );
    host.acquire(Mode::Command).unwrap();
    host.put(b"counter".to_vec(), value(b"staged only"))
        .await
        .unwrap();
    assert!(observed.0.lock().unwrap().is_empty());
    assert!(host.stage(intent("")).await.is_err());
    assert!(observed.0.lock().unwrap().is_empty());
    let mut expired = intent("approved-event");
    expired.expires_at_unix_millis = Some(1);
    assert_eq!(host.stage(expired).await, Err(IntentFailure::InvalidExpiry));
    assert!(observed.0.lock().unwrap().is_empty());
    assert_eq!(host.stage(intent("approved-event")).await.unwrap(), 0);
    let progress = observed.0.lock().unwrap().clone();
    assert_eq!(progress.len(), 1);
    assert_eq!(progress[0].staged_mutations, 1);
    assert_eq!(progress[0].captured_intents, 1);
    assert_eq!(
        progress[0].state_write_bytes,
        budget.snapshot_at(Instant::now()).state_write_bytes
    );
    fixture.revoke();
    assert_eq!(
        host.stage(intent("approved-event")).await,
        Err(IntentFailure::PermissionDenied)
    );
    assert_eq!(observed.0.lock().unwrap().len(), 1);
    host.finish_guest_access();
    assert_eq!(
        host.stage(intent("approved-event")).await,
        Err(IntentFailure::HandleClosed)
    );
    assert_eq!(observed.0.lock().unwrap().len(), 1);
    host.retire().await.unwrap();
    drop(claim);
    host.retire_command_role().unwrap();
    drop((host, admission));
    assert_eq!(fixture.rows(Family::State).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    fixture.shutdown().await;
}

#[tokio::test]
async fn native_query_host_has_no_staging_identity_or_observer() {
    let fixture = Fixture::new().await;
    let (admission, envelope, budget) = fixture.invocation(true, "query-observer");
    admission.admit(&envelope, &budget).await.unwrap();
    let TransactionAdmissionResult::Query { host } = admission.take_result().unwrap().unwrap()
    else {
        panic!("query host absent");
    };
    assert!(host.staging_identity().is_none());
    assert_eq!(
        host.bind_staging_observer(Arc::new(Observed::default())),
        Err(StateFailure::WrongMode)
    );
    host.acquire(Mode::Query).unwrap();
    host.finish_guest_access();
    host.retire().await.unwrap();
    drop((host, admission));
    assert_eq!(fixture.rows(Family::Command).await, 0);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    fixture.shutdown().await;
}
