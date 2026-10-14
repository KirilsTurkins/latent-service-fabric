use super::*;
use crate::transaction_runtime::tests::fixture::Fixture;
use crate::transaction_runtime::{factory::State, CommandCompletionDisposition};
use crate::TransactionActivationAdmission;
use latent_core::transaction_contract::{ExpectedVersion, Precondition};
use latent_executor::transaction::Mode;
use latent_state::embedded::Family;

fn value(bytes: &[u8]) -> latent_core::transaction_contract::Value {
    latent_core::transaction_contract::Value {
        bytes: bytes.to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: Vec::new(),
    }
}

async fn seed(fixture: &Fixture) {
    let (admission, envelope, budget) = fixture.invocation(false, "pre-host-seed");
    let host = admission.admit(&envelope, &budget).await.unwrap();
    host.acquire(Mode::Command).unwrap();
    host.put(b"counter".to_vec(), value(b"original value"))
        .await
        .unwrap();
    host.finish_guest_access();
    let consumed = budget.finalize_at(None, std::time::Instant::now());
    let outcome = ActivationOutcome::Succeeded(ActivationSuccess {
        output: b"seed".to_vec(),
        output_media_type: "application/octet-stream".into(),
        metadata: Metadata::new(),
        consumption: consumed.consumption().clone(),
        committed_state_version: None,
        effect_ids: Vec::new(),
    });
    let result = admission
        .complete(outcome, fixture.commit_control(&envelope, &budget))
        .await;
    assert!(matches!(result, ActivationOutcome::Succeeded(_)));
    let completion = admission.take_owned_completion().unwrap().unwrap();
    assert!(matches!(
        completion.result,
        TransactionCompletionResult::Command(CommandCompletionDisposition::Durable { .. })
    ));
    drop((completion, host, admission));
}

#[tokio::test]
async fn actual_pre_host_stale_condition_publishes_durable_original_abort() {
    let fixture = Fixture::new().await;
    seed(&fixture).await;
    let (admission, envelope, budget) = fixture.invocation(false, "pre-host-stale");
    {
        let mut state = admission.state.lock().unwrap();
        let State::Fresh(Some(selection)) = &mut *state else {
            panic!("fresh original admission absent");
        };
        selection.expected_versions.push(Precondition {
            key: b"counter".to_vec(),
            expected: ExpectedVersion::Absent,
        });
    }
    let error = admission.admit(&envelope, &budget).await.err().unwrap();
    assert_eq!(error.code, PlatformErrorCode::StateConflict);
    let original = {
        let state = admission.state.lock().unwrap();
        let State::Pending {
            claim: Some(claim), ..
        } = &*state
        else {
            panic!("actual flushed original claim absent");
        };
        claim.record().clone()
    };
    assert_eq!(fixture.rows(Family::State).await, 1);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    let consumed = budget.finalize_at(None, std::time::Instant::now());
    let expected = failure_for_platform_error(error, consumed.consumption().clone());
    let observed = admission
        .complete(expected.clone(), fixture.commit_control(&envelope, &budget))
        .await;
    assert_eq!(observed, expected);
    let completion = admission.take_owned_completion().unwrap().unwrap();
    let durable = match &completion.result {
        TransactionCompletionResult::Command(CommandCompletionDisposition::Durable {
            command,
            result,
            cleanup_failure,
            ..
        }) => {
            assert_eq!(command.id(), original.id());
            assert_eq!(command.attempt(), original.attempt());
            assert_eq!(command.transaction_id(), original.transaction_id());
            assert_eq!(command.source(), original.source());
            assert_eq!(command.fingerprint(), original.fingerprint());
            assert!(cleanup_failure.is_none());
            command.outcome() == Outcome::Aborted
                && command.abort_proof().is_some()
                && result.code() == Some("state-conflict")
        }
        TransactionCompletionResult::PendingRetired { proof, .. } => {
            assert!(proof.is_ok(), "the original physical retirement is real");
            false
        }
        _ => false,
    };
    let (record, result) = fixture.inspect(original.key().clone()).await;
    let retained = record.outcome() == Outcome::Aborted
        && record.abort_proof().is_some()
        && result.is_some_and(|result| result.code() == Some("state-conflict"));
    assert_eq!(fixture.rows(Family::State).await, 1);
    assert_eq!(fixture.rows(Family::Outbox).await, 0);
    drop((completion, admission));
    fixture.shutdown().await;
    assert!(
        durable && retained,
        "pre-host StateConflict lacks durable original abort"
    );
}
