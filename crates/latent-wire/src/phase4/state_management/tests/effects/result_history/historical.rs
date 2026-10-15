use super::*;
use latent_commit::atomic::{
    AdmissionDecision, AdmissionInput, CommandRecord, CommandTime, CompleteEnvelope,
    PreparedAdmission, PreparedDisposition, ReplayPolicy, ResultPolicy, RetryRequest,
};
use latent_core::transaction_contract::{CommandFingerprint, Value};
use latent_state::store_io::StoreIoKind;

fn value(bytes: &[u8]) -> Value {
    Value {
        bytes: bytes.to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: vec![],
    }
}

fn time(unix_millis: u64) -> CommandTime {
    CommandTime {
        unix_millis,
        continuity_proven: true,
    }
}

fn input(original: &CommandRecord) -> AdmissionInput {
    let mut key = original.key().clone();
    key.client_key = "historical-original-result".into();
    AdmissionInput {
        key,
        fingerprint: CommandFingerprint {
            input_format: "value.v1".into(),
            input: value(b"original historical input"),
            expected_versions: vec![],
        },
        source: original.source().clone(),
        result_read_policy: original.result_read_policy().into(),
        result_policy: ResultPolicy {
            replay: ReplayPolicy::Full,
            maximum_result_bytes: 1024,
            result_millis: 60_000,
            identity_millis: 120_000,
            maximum_attempts: 3,
        },
        inbox: None,
        owner_epoch: 1,
    }
}

fn confirmed(
    envelope: CompleteEnvelope,
    engine: &latent_state::embedded::EmbeddedStore,
) -> CommandRecord {
    let PreparedDisposition::Confirmed { command, .. } = envelope.publish(engine, |effects| {
        assert!(effects.is_empty());
        Ok(())
    }) else {
        panic!("original durable disposition required")
    };
    command
}

pub(super) async fn seed(fixture: &HistoryFixture) -> t::CommandSelector {
    let original = rows(&fixture.effect)
        .await
        .into_iter()
        .find_map(|(_, bytes)| CommandRecord::decode(&bytes).ok())
        .unwrap();
    let selected = input(&original).key;
    fixture
        .effect
        .fixture
        .store
        .with_store(
            StoreIoKind::RecoveryWrite,
            WORK_BYTES as u64,
            move |engine| {
                let AdmissionDecision::New(prepared) = PreparedAdmission::prepare(
                    &engine.snapshot()?,
                    input(&original),
                    time(100),
                    |_, _| Ok(()),
                )
                .unwrap() else {
                    panic!("new historical command required")
                };
                let claim = prepared.publish(engine, || Ok(())).unwrap();
                let retirement = claim.retirement();
                drop(claim);
                assert!(retirement.physically_retired());
                let retired = retirement.proven_noncommit().unwrap();
                let aborted = confirmed(
                    CompleteEnvelope::technical_abort(
                        &engine.snapshot()?,
                        retired,
                        "state-conflict".into(),
                        time(101),
                    )
                    .unwrap(),
                    engine,
                );
                let retry = RetryRequest {
                    request_id: "explicit-history-retry".into(),
                    expected_abort: aborted.abort_proof().unwrap(),
                };
                let AdmissionDecision::New(prepared) = PreparedAdmission::retry(
                    &engine.snapshot()?,
                    &input(&original),
                    &retry,
                    time(102),
                    |_, _| Ok(()),
                )
                .unwrap() else {
                    panic!("one explicit second attempt required")
                };
                let claim = prepared.publish(engine, || Ok(())).unwrap();
                let rejected = confirmed(
                    CompleteEnvelope::rejection(
                        &engine.snapshot()?,
                        claim,
                        "original-business-rejection".into(),
                        value(b"second original decision"),
                        time(103),
                    )
                    .unwrap(),
                    engine,
                );
                assert_eq!(rejected.attempt(), 2);
                assert_eq!(rejected.source(), aborted.source());
                Ok(())
            },
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    fixture.effect.time.store(104, Ordering::SeqCst);
    let mut command = fixture.effect.command.clone();
    command.client_key = selected.client_key;
    command
}
