use super::*;
use crate::transaction_runtime::tests::fixture::Fixture;
use crate::transaction_runtime::CommandCompletion;
use crate::TransactionActivationAdmission;
use latent_activation::ActivationOutcome;
use latent_core::{ActivationTerminalState, PlatformError, PlatformErrorCode};
use latent_executor::transaction::{Mode, TransactionHost};

struct Original {
    admission: Arc<NativeTransactionAdmission>,
    host: Arc<StateTransactionHost>,
    guest: Arc<dyn TransactionHost>,
    disposition: CommandCompletionDisposition,
}

async fn retired_original(fixture: &Fixture) -> Original {
    let (admission, envelope, budget) = fixture.invocation(false, "uncertain-original-writer");
    let guest = admission.admit(&envelope, &budget).await.unwrap();
    guest.acquire(Mode::Command).unwrap();
    guest
        .put(
            b"counter".to_vec(),
            latent_core::transaction_contract::Value {
                bytes: b"must not commit".to_vec(),
                media_type: "application/octet-stream".into(),
                metadata: Vec::new(),
            },
        )
        .await
        .unwrap();
    let super::super::TransactionAdmissionResult::Command { claim, host } =
        admission.take_result().unwrap().unwrap()
    else {
        panic!("original command host absent");
    };
    host.finish_guest_access();
    let finalized = budget.finalize_at(None, std::time::Instant::now());
    let failure = ActivationOutcome::Failed {
        terminal_state: ActivationTerminalState::GuestTrap,
        error: PlatformError {
            code: PlatformErrorCode::GuestTrap,
            message: "original guest trap".into(),
            retryable: false,
            details: Vec::new(),
        },
        consumption: finalized.consumption().clone(),
    };
    let disposition = CommandCompletion::new(
        claim,
        host.clone(),
        fixture.effects.clone(),
        fixture.time.clone(),
        fixture.commit_control(&envelope, &budget),
    )
    .unwrap()
    .finish(failure)
    .await;
    Original {
        admission,
        host,
        guest,
        disposition,
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn uncertain_protected_abort_writer_cannot_certify_an_original_fault() {
    let fixture = Fixture::new().await;
    let Original {
        admission,
        host,
        guest,
        disposition,
    } = Box::pin(retired_original(&fixture)).await;
    let CommandCompletionDisposition::Retired {
        command,
        proof,
        retained,
        retained_native,
        ..
    } = disposition
    else {
        panic!("real original physical noncommit proof absent");
    };
    let original = command.clone();
    let writer = AbortWriter::new(&admission, &host, &command).unwrap();
    let physical_writer = Arc::clone(&writer);
    let keeper: Arc<dyn std::any::Any + Send + Sync> = writer.clone();
    let (entered, entering) = tokio::sync::oneshot::channel();
    let (release, released) = std::sync::mpsc::sync_channel(1);
    let job = admission
        .owners
        .store
        .with_store_retaining(
            StoreIoKind::RecoveryWrite,
            WORK_BYTES,
            keeper,
            move |_| -> Result<Publication, StoreError> {
                entered.send(()).unwrap();
                released
                    .recv_timeout(std::time::Duration::from_secs(10))
                    .unwrap();
                Err(StoreError::CommitUncertain)
            },
        )
        .unwrap();
    tokio::time::timeout(std::time::Duration::from_secs(10), entering)
        .await
        .unwrap()
        .unwrap();
    let result = AbortCompletion {
        command,
        retained,
        retained_native,
        writer,
    }
    .finish(&admission, None);
    let CommandCompletionDisposition::RecoveryRequired { command, .. } = &result else {
        panic!("uncertain protected writer manufactured a durable abort");
    };
    assert_eq!(command, &original);
    assert!(command.abort_proof().is_none());
    assert_eq!(fixture.native.snapshot().unwrap().recovery.slots, 1);
    release.send(()).unwrap();
    let observed = tokio::time::timeout(std::time::Duration::from_secs(10), job)
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(
        observed,
        Err(latent_state::protected_store::ProtectedStoreError::Store(
            StoreError::CommitUncertain
        ))
    ));
    // The surviving physical owner cleans up only after the real job ACK.
    // This controlled store fault remains uncertainty, never durable-abort proof.
    physical_writer.role.retire().unwrap();
    drop((physical_writer, proof, result, guest, host, admission));
    fixture.shutdown_uncertain_writer().await;
}
