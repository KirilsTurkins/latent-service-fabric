use super::*;
use crate::authority::{
    CommitLink, DispatchCeiling, DispatchProfile, EffectAuthorityOwner, EffectRule, EffectScope,
};

fn time(value: u64) -> EffectTime {
    EffectTime {
        unix_millis: value,
        continuity_proven: true,
    }
}

fn record() -> EffectRecord {
    let owner = EffectAuthorityOwner::new(1, 1, 100).unwrap();
    let scope = EffectScope {
        tenant: "a".into(),
        namespace: "orders".into(),
        incarnation: 1,
        publication: "pub-a".into(),
        binding: "events".into(),
        operation: "publish".into(),
    };
    owner
        .publish(EffectRule {
            scope: scope.clone(),
            profile: DispatchProfile {
                provider: "broker".into(),
                destination: "orders".into(),
                adapter: "jetstream.v1".into(),
                intent_format: 1,
                payload_format: "bytes.v1".into(),
                idempotency_profile: "bounded.v1".into(),
            },
            policy_revision: 1,
            credential_epoch: 1,
            protected_credential_reference: "protected-ref".into(),
            enabled: true,
            ceiling: DispatchCeiling {
                maximum_payload_bytes: 1024,
                maximum_response_bytes: 1024,
                maximum_attempts: 3,
                maximum_age_millis: 10_000,
                attempt_timeout_millis: 100,
            },
        })
        .unwrap();
    let authority = owner
        .capture(
            &scope,
            CommitLink {
                command: "cmd-a".into(),
                caller_scope: "caller-a".into(),
                attempt: 1,
                commit: "commit-a".into(),
                effect: "effect-a".into(),
                sequence: 0,
            },
            100,
            "a".repeat(64),
            time(100),
        )
        .unwrap();
    EffectRecord::committed(&authority).unwrap()
}

fn receipt(disposition: Disposition, now: u64) -> AttemptReceipt {
    AttemptReceipt {
        disposition,
        reason: "controlled-peer".into(),
        provider_receipt: (disposition == Disposition::ProviderAcknowledged)
            .then(|| "receipt-a".into()),
        observed_at_millis: now,
    }
}

#[test]
fn only_one_claim_can_send_and_duplicate_completion_cannot_rewrite_terminal_work() {
    let mut record = record();
    let claim = record.claim(1, time(101)).unwrap();
    assert_eq!(record.claim(2, time(102)), Err(AuthorityError::Stale));
    record.begin_send(&claim).unwrap();
    assert_eq!(record.begin_send(&claim), Err(AuthorityError::Stale));
    record
        .complete(&claim, receipt(Disposition::ProviderAcknowledged, 103))
        .unwrap();
    assert_eq!(
        record.complete(&claim, receipt(Disposition::Uncertain, 104)),
        Err(AuthorityError::Stale)
    );
    assert_eq!(record.disposition(), Disposition::ProviderAcknowledged);
    assert_eq!(record.history_sequence(), 1);
}

#[test]
fn lease_expiry_never_retires_a_live_physical_owner_or_resends_after_expiry() {
    let mut record = record();
    let claim = record.claim(1, time(101)).unwrap();
    record.begin_send(&claim).unwrap();
    assert_eq!(
        record.recover_interrupted(2, false, time(102)),
        Err(AuthorityError::Unavailable)
    );
    assert_eq!(
        record.claim(2, time(20_000)),
        Err(AuthorityError::Unavailable)
    );
    assert_eq!(record.disposition(), Disposition::Dispatching);
    record
        .complete(&claim, receipt(Disposition::ProviderAcknowledged, 20_001))
        .unwrap();
    assert_eq!(record.disposition(), Disposition::ProviderAcknowledged);
}

#[test]
fn process_restart_after_send_is_uncertain_and_stale_old_completion_is_fenced() {
    let mut record = record();
    let claim = record.claim(1, time(101)).unwrap();
    record.begin_send(&claim).unwrap();
    record.recover_interrupted(2, true, time(102)).unwrap();
    assert_eq!(record.disposition(), Disposition::Uncertain);
    assert_eq!(
        record.complete(&claim, receipt(Disposition::ProviderAcknowledged, 103)),
        Err(AuthorityError::Stale)
    );
    assert_eq!(
        record.schedule_retry(RetryProof::KnownNonexecution, time(104), 1),
        Err(AuthorityError::PolicyBlocked)
    );
    assert_eq!(record.claim(2, time(105)), Err(AuthorityError::Stale));
}

#[test]
fn process_restart_before_persisted_send_marker_is_known_nondispatch() {
    let mut record = record();
    let claim = record.claim(1, time(101)).unwrap();
    record.recover_interrupted(2, true, time(102)).unwrap();
    assert_eq!(record.disposition(), Disposition::KnownFailed);
    record
        .schedule_retry(RetryProof::KnownNonexecution, time(103), 1)
        .unwrap();
    let replacement = record.claim(2, time(104)).unwrap();
    assert_eq!(record.begin_send(&claim), Err(AuthorityError::Stale));
    record.begin_send(&replacement).unwrap();
    assert_eq!(replacement.attempt(), 2);
}

#[test]
fn qualified_retry_preserves_payload_provider_incarnation_and_dedup_horizon() {
    let mut record = record();
    let claim = record.claim(1, time(101)).unwrap();
    record.begin_send(&claim).unwrap();
    record
        .complete(&claim, receipt(Disposition::Uncertain, 102))
        .unwrap();
    for proof in [
        RetryProof::QualifiedDeduplication {
            valid_until_millis: 200,
            same_payload: false,
            same_provider_incarnation: true,
        },
        RetryProof::QualifiedDeduplication {
            valid_until_millis: 200,
            same_payload: true,
            same_provider_incarnation: false,
        },
        RetryProof::QualifiedDeduplication {
            valid_until_millis: 104,
            same_payload: true,
            same_provider_incarnation: true,
        },
    ] {
        assert_eq!(
            record.schedule_retry(proof, time(103), 1),
            Err(AuthorityError::PolicyBlocked)
        );
    }
    record
        .schedule_retry(
            RetryProof::QualifiedDeduplication {
                valid_until_millis: 200,
                same_payload: true,
                same_provider_incarnation: true,
            },
            time(104),
            1,
        )
        .unwrap();
    let replacement = record.claim(2, time(105)).unwrap();
    assert_eq!(replacement.retry_horizon_millis(), Some(200));
}

#[test]
fn delayed_retry_beyond_provider_horizon_blocks_without_network_send() {
    let mut record = record();
    let claim = record.claim(1, time(101)).unwrap();
    record.begin_send(&claim).unwrap();
    record
        .complete(&claim, receipt(Disposition::Uncertain, 102))
        .unwrap();
    record
        .schedule_retry(
            RetryProof::QualifiedDeduplication {
                valid_until_millis: 200,
                same_payload: true,
                same_provider_incarnation: true,
            },
            time(103),
            1,
        )
        .unwrap();
    assert_eq!(
        record.claim(2, time(200)),
        Err(AuthorityError::PolicyBlocked)
    );
    assert_eq!(record.disposition(), Disposition::PolicyBlocked);
    assert_eq!(record.attempts(), 1);
}

#[test]
fn finite_attempt_ceiling_stops_even_proven_nondispatched_retries() {
    let mut record = record();
    for attempt in 1_u32..=3 {
        let now = 100 + u64::from(attempt) * 10;
        let claim = record.claim(1, time(now)).unwrap();
        record
            .complete(&claim, receipt(Disposition::KnownFailed, now + 1))
            .unwrap();
        record
            .schedule_retry(RetryProof::KnownNonexecution, time(now + 2), 1)
            .unwrap();
    }
    assert_eq!(record.claim(2, time(150)), Err(AuthorityError::Capacity));
    assert_eq!(record.disposition(), Disposition::DeadLettered);
    assert_eq!(record.attempts(), 3);
}

#[test]
fn receipt_and_record_limits_reject_corruption_without_false_acknowledgement() {
    let mut record = record();
    let claim = record.claim(1, time(101)).unwrap();
    assert_eq!(
        record.complete(&claim, receipt(Disposition::ProviderAcknowledged, 102)),
        Err(AuthorityError::Invalid)
    );
    let mut malformed = receipt(Disposition::KnownFailed, 102);
    malformed.reason = "a".repeat(129);
    assert_eq!(
        record.complete(&claim, malformed),
        Err(AuthorityError::Invalid)
    );
    let bytes = record.encode().unwrap();
    assert_eq!(EffectRecord::decode(&bytes).unwrap(), record);
    let mut corrupt = bytes;
    corrupt[4] = 2;
    assert_eq!(
        EffectRecord::decode(&corrupt),
        Err(AuthorityError::UnsupportedFormat)
    );
    assert_eq!(
        EffectRecord::decode(&vec![0; 65_542]),
        Err(AuthorityError::Capacity)
    );
    assert_eq!(record.disposition(), Disposition::Dispatching);
}

#[test]
fn retained_old_envelope_and_command_link_survive_state_schema_and_result_expiry() {
    let mut record = record();
    let claim = record.claim(1, time(101)).unwrap();
    record.begin_send(&claim).unwrap();
    record
        .complete(&claim, receipt(Disposition::Uncertain, 102))
        .unwrap();
    let reopened = EffectRecord::decode(&record.encode().unwrap()).unwrap();
    let envelope = reopened.authority().unwrap();
    assert_eq!(envelope.link().command, "cmd-a");
    assert_eq!(envelope.link().commit, "commit-a");
    assert_eq!(envelope.link().effect, "effect-a");
    assert_eq!(envelope.profile().intent_format, 1);
    assert_eq!(reopened.disposition(), Disposition::Uncertain);
}

#[test]
fn forged_terminal_record_without_physical_send_and_receipt_is_corrupt() {
    let record = record();
    let mut forged: serde_json::Value =
        serde_json::from_slice(&record.encode().unwrap()[5..]).unwrap();
    forged["disposition"] = serde_json::json!("ProviderAcknowledged");
    let mut bytes = b"LER\0\x01".to_vec();
    bytes.extend(serde_json::to_vec(&forged).unwrap());
    assert_eq!(EffectRecord::decode(&bytes), Err(AuthorityError::Invalid));
    forged["disposition"] = serde_json::json!("Pending");
    forged["attempt"] = serde_json::json!(4);
    bytes.truncate(5);
    bytes.extend(serde_json::to_vec(&forged).unwrap());
    assert_eq!(EffectRecord::decode(&bytes), Err(AuthorityError::Invalid));
}
