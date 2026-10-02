use super::*;
use latent_core::{
    transaction_contract::{CommandFingerprint, CommandKey, Value},
    StateNamespaceId, TenantId,
};
use latent_effects::authority::{
    DispatchCeiling, DispatchProfile, EffectAuthorityOwner, EffectRule, EffectScope, EffectTime,
};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, Family, RowKey, RowMutation, StoreLimits},
    namespace::{
        namespace_record_key, NamespacePins, NamespaceQuota, NamespaceRecord, NamespaceStatus,
        NamespaceVersion,
    },
    session::{SessionLimits, StateAccess, StateMode, StateScope, StateSession},
};
use std::fs::OpenOptions;
use writer::{inspect, RetryRequest, StagedIntent};
mod captured;
mod view_tokens;

mod retention_cases;

fn time(now: u64) -> CommandTime {
    CommandTime {
        unix_millis: now,
        continuity_proven: true,
    }
}
fn schema() -> String {
    format!("sha256:{}", "4".repeat(64))
}
fn value(bytes: &[u8]) -> Value {
    Value {
        bytes: bytes.to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: vec![],
    }
}
fn input(key: &str) -> AdmissionInput {
    AdmissionInput {
        key: CommandKey {
            tenant: "tenant".into(),
            namespace: "aggregate".into(),
            incarnation: "1".into(),
            recovery_scope: "subject:alice".into(),
            operation: "update".into(),
            entity: None,
            client_key: key.into(),
        },
        fingerprint: CommandFingerprint {
            input_format: "lsf-wit-values-v1".into(),
            input: value(b"delta=1"),
            expected_versions: vec![],
        },
        source: SourceIdentity {
            publication: "publication".into(),
            revision: "revision-1".into(),
            release_digest: format!("sha256:{}", "1".repeat(64)),
            component_digest: format!("sha256:{}", "2".repeat(64)),
            contract_digest: format!("sha256:{}", "3".repeat(64)),
            route_generation: 1,
            state_schema: schema(),
            input_format: "lsf-wit-values-v1".into(),
            result_format: "lsf-wit-values-v1".into(),
        },
        result_read_policy: "aggregate/read-v1".into(),
        result_policy: ResultPolicy {
            replay: ReplayPolicy::Full,
            maximum_result_bytes: 1024,
            result_millis: 1000,
            identity_millis: 2000,
            maximum_attempts: 3,
        },
        inbox: None,
        owner_epoch: 1,
    }
}
fn permission(_: CommandAccess, record: Option<&CommandRecord>) -> Result<(), AtomicError> {
    if record.is_some_and(|r| {
        r.key.tenant != "tenant"
            || r.key.recovery_scope != "subject:alice"
            || r.result_read_policy != "aggregate/read-v1"
    }) {
        Err(AtomicError::PermissionDenied)
    } else {
        Ok(())
    }
}
fn state_permission(
    scope: &StateScope,
    _: StateAccess,
) -> Result<(), latent_state::session::StateError> {
    if scope.tenant.0 == "tenant" && scope.namespace.0 == "aggregate" && scope.incarnation == 1 {
        Ok(())
    } else {
        Err(latent_state::session::StateError::PermissionDenied)
    }
}
fn namespace_key() -> RowKey {
    RowKey {
        family: Family::Namespace,
        key: namespace_record_key(
            &TenantId("tenant".into()),
            &StateNamespaceId("aggregate".into()),
        )
        .unwrap(),
    }
}
fn open(path: &std::path::Path) -> EmbeddedStore {
    open_limited(path, StoreLimits::default())
}
fn open_limited(path: &std::path::Path, limits: StoreLimits) -> EmbeddedStore {
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
        .unwrap();
    EmbeddedStore::open_file(
        file,
        StoreLimits {
            maximum_key_bytes: 4096,
            maximum_value_bytes: 2 * 1024 * 1024,
            maximum_batch_rows: 1024,
            ..limits
        },
    )
    .unwrap()
}
fn setup() -> (tempfile::TempDir, EmbeddedStore, EffectAuthorityOwner) {
    let dir = tempfile::tempdir().unwrap();
    let store = open(&dir.path().join("state.redb"));
    let namespace = NamespaceRecord {
        tenant: TenantId("tenant".into()),
        id: StateNamespaceId("aggregate".into()),
        version: NamespaceVersion {
            incarnation: 1,
            generation: 1,
        },
        state_schema: schema(),
        status: NamespaceStatus::Active,
        quota: NamespaceQuota::default(),
        pins: NamespacePins::default(),
    };
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: namespace_key(),
                value: Some(namespace.encode().unwrap()),
            }],
        })
        .unwrap();
    let effects = EffectAuthorityOwner::new(4, 4, 0).unwrap();
    effects
        .publish(EffectRule {
            scope: EffectScope {
                tenant: "tenant".into(),
                namespace: "aggregate".into(),
                incarnation: 1,
                publication: "publication".into(),
                binding: "approved-event".into(),
                operation: "event".into(),
            },
            profile: DispatchProfile {
                provider: "events".into(),
                destination: "events.subject".into(),
                adapter: "qualified-test-v1".into(),
                intent_format: 1,
                payload_format: "lsf-value-v1".into(),
                idempotency_profile: "qualified-test-idempotency-v1".into(),
            },
            policy_revision: 1,
            credential_epoch: 1,
            protected_credential_reference: "protected-events".into(),
            ceiling: DispatchCeiling {
                maximum_payload_bytes: 1024,
                maximum_response_bytes: 1024,
                maximum_attempts: 3,
                maximum_age_millis: 1000,
                attempt_timeout_millis: 100,
            },
            enabled: true,
        })
        .unwrap();
    (dir, store, effects)
}
fn claim(store: &EmbeddedStore, input: AdmissionInput) -> AdmittedCommand {
    let view = store.snapshot().unwrap();
    let AdmissionDecision::New(prepared) =
        PreparedAdmission::prepare(&view, input, time(100), permission).unwrap()
    else {
        panic!("expected a new host claim")
    };
    prepared
        .publish(store, || permission(CommandAccess::FinalClaim, None))
        .unwrap()
}
fn stage(view: &latent_state::embedded::ReadView) -> latent_state::session::StatePlan {
    let scope = StateScope {
        tenant: TenantId("tenant".into()),
        namespace: StateNamespaceId("aggregate".into()),
        incarnation: 1,
        state_schema: schema(),
        entity: None,
        mode: StateMode::Command,
    };
    let mut session =
        StateSession::open(view, scope, SessionLimits::default(), state_permission).unwrap();
    session
        .put(
            view,
            b"aggregate/count".to_vec(),
            value(&1u64.to_le_bytes()),
            state_permission,
        )
        .unwrap();
    session.seal(view, state_permission).unwrap()
}
fn intent() -> StagedIntent {
    StagedIntent {
        binding: "approved-event".into(),
        operation: "event".into(),
        payload: value(b"updated"),
        expires_at_millis: None,
    }
}
fn confirm(
    envelope: CompleteEnvelope,
    store: &EmbeddedStore,
    effects: &EffectAuthorityOwner,
) -> CommandRecord {
    match envelope.publish(store, |authorities| {
        let guard = effects.commit_fence(
            authorities,
            EffectTime {
                unix_millis: 101,
                continuity_proven: true,
            },
        )?;
        permission(CommandAccess::FinalDisposition, None)?;
        drop(guard);
        Ok(())
    }) {
        PreparedDisposition::Confirmed { command, .. } => *command,
        _ => panic!("expected durable disposition"),
    }
}

#[test]
fn actual_engine_success_reopens_with_state_result_inbox_and_exact_effect_linkage() {
    let (dir, store, effects) = setup();
    let mut request = input("one");
    request.inbox = Some(InboxIdentity {
        provider: "input".into(),
        binding: "source".into(),
        message: "message-1".into(),
        payload_digest: Identity::derive(b"input", &[b"message"]),
    });
    let inbox = request.inbox.clone().unwrap();
    let key = request.key.clone();
    let admitted = claim(&store, request);
    let view = store.snapshot().unwrap();
    let state = stage(&view);
    let envelope = CompleteEnvelope::success(
        &view,
        admitted,
        Some(state),
        vec![intent()],
        value(b"exact response"),
        &effects,
        time(101),
    )
    .unwrap();
    let command = confirm(envelope, &store, &effects);
    drop(view);
    drop(store);
    let store = open(&dir.path().join("state.redb"));
    let view = store.snapshot().unwrap();
    let (recovered, result) = inspect(&view, &key, time(102), permission).unwrap();
    assert_eq!(recovered, command);
    assert_eq!(result.unwrap().value(), Some(&value(b"exact response")));
    assert!(view.get(&inbox.row_key(&key).unwrap()).unwrap().is_some());
    let effect = command.effect_ids()[0].hex();
    let bytes = view
        .get(&latent_effects::dispatch_store::effect_row_key(&effect).unwrap())
        .unwrap()
        .unwrap();
    let outbox = latent_effects::dispatch::EffectRecord::decode(&bytes).unwrap();
    let authority = outbox.authority().unwrap();
    assert_eq!(authority.link().command, command.id.hex());
    assert_eq!(authority.link().attempt, 1);
    assert_eq!(authority.link().commit, command.disposition_id().hex());
    let payload = view
        .get(&latent_effects::dispatch_store::effect_payload_key(&effect).unwrap())
        .unwrap()
        .unwrap();
    let payload = latent_effects::payload::PayloadRecord::decode(&payload).unwrap();
    payload.verify(&authority).unwrap();
    assert_eq!(payload.value(), &value(b"updated"));
    let mut scope = StateScope {
        tenant: TenantId("tenant".into()),
        namespace: StateNamespaceId("aggregate".into()),
        incarnation: 1,
        state_schema: schema(),
        entity: None,
        mode: StateMode::Query,
    };
    let mut query = StateSession::open(
        &view,
        scope.clone(),
        SessionLimits::default(),
        state_permission,
    )
    .unwrap();
    assert_eq!(
        query
            .get(&view, b"aggregate/count", state_permission)
            .unwrap()
            .unwrap()
            .value
            .bytes,
        1u64.to_le_bytes()
    );
    scope.mode = StateMode::Command;
    assert_eq!(command.outcome(), Outcome::Committed);
}

#[test]
fn identical_concurrent_claims_have_one_writer_and_changed_fingerprints_conflict() {
    let (_dir, store, _effects) = setup();
    let view = store.snapshot().unwrap();
    let AdmissionDecision::New(one) =
        PreparedAdmission::prepare(&view, input("same"), time(100), permission).unwrap()
    else {
        panic!()
    };
    let AdmissionDecision::New(two) =
        PreparedAdmission::prepare(&view, input("same"), time(100), permission).unwrap()
    else {
        panic!()
    };
    let owner = one.publish(&store, || Ok(())).unwrap();
    assert!(matches!(
        two.publish(&store, || panic!(
            "stale claim must fail before authority acceptance"
        )),
        Err(AtomicError::Conflict)
    ));
    let view = store.snapshot().unwrap();
    assert!(matches!(
        PreparedAdmission::prepare(&view, input("same"), time(100), permission),
        Ok(AdmissionDecision::Existing(_))
    ));
    let mut changed = input("same");
    changed.fingerprint.input.bytes.push(1);
    assert!(matches!(
        PreparedAdmission::prepare(&view, changed, time(100), permission),
        Err(AtomicError::Conflict)
    ));
    assert_eq!(owner.record().attempt(), 1);
}

#[test]
fn lost_business_rejection_replays_after_restart_and_changed_business_state() {
    let (dir, store, effects) = setup();
    let request = input("reject");
    let key = request.key.clone();
    let admitted = claim(&store, request);
    let view = store.snapshot().unwrap();
    let discarded = stage(&view);
    drop(discarded);
    let rejection = CompleteEnvelope::rejection(
        &view,
        admitted,
        "inventory-unavailable".into(),
        value(b"original rejection"),
        time(101),
    )
    .unwrap();
    let record = confirm(rejection, &store, &effects);
    assert_eq!(record.outcome(), Outcome::Rejected);
    assert!(record.effect_ids().is_empty());
    drop(view);
    let admitted = claim(&store, input("other"));
    let view = store.snapshot().unwrap();
    let state = stage(&view);
    let success = CompleteEnvelope::success(
        &view,
        admitted,
        Some(state),
        vec![intent()],
        value(b"new stock"),
        &effects,
        time(101),
    )
    .unwrap();
    confirm(success, &store, &effects);
    drop(view);
    drop(store);
    let store = open(&dir.path().join("state.redb"));
    let view = store.snapshot().unwrap();
    let (replayed, result) = inspect(&view, &key, time(102), permission).unwrap();
    assert_eq!(replayed, record);
    let result = result.unwrap();
    assert_eq!(result.outcome(), Outcome::Rejected);
    assert_eq!(result.code(), Some("inventory-unavailable"));
    assert_eq!(result.value(), Some(&value(b"original rejection")));
}

#[test]
fn pre_fence_revocation_and_occ_failure_leave_all_business_families_untouched() {
    let (_dir, store, effects) = setup();
    let admitted = claim(&store, input("blocked"));
    let watch = admitted.retirement();
    let view = store.snapshot().unwrap();
    let envelope = CompleteEnvelope::success(
        &view,
        admitted,
        Some(stage(&view)),
        vec![intent()],
        value(b"response"),
        &effects,
        time(101),
    )
    .unwrap();
    let PreparedDisposition::KnownNotCommitted { command, reason } =
        envelope.publish(&store, |_| Err(AtomicError::PermissionDenied))
    else {
        panic!()
    };
    assert_eq!(reason, AtomicError::PermissionDenied);
    assert!(watch.proven_noncommit().is_err());
    assert!(!watch.physically_retired());
    drop(command);
    assert!(watch.physically_retired());
    let retired = watch.proven_noncommit().unwrap();
    drop(view);
    let view = store.snapshot().unwrap();
    assert!(view
        .scan_after(Family::State, b"", None, 128, 1024)
        .unwrap()
        .rows
        .is_empty());
    assert!(view
        .scan_after(Family::Outbox, b"", None, 128, 1024)
        .unwrap()
        .rows
        .is_empty());
    let abort =
        CompleteEnvelope::technical_abort(&view, retired, "permission-revoked".into(), time(101))
            .unwrap();
    assert_eq!(confirm(abort, &store, &effects).outcome(), Outcome::Aborted);
}

#[test]
fn physical_retirement_required_before_durable_abort_and_concurrent_explicit_retry() {
    let (_dir, store, effects) = setup();
    let admitted = claim(&store, input("retry"));
    let watch = admitted.retirement();
    let physical = admitted.physical_work().unwrap();
    drop(admitted);
    assert!(matches!(
        watch.proven_noncommit(),
        Err(AtomicError::RecoveryRequired)
    ));
    physical.retire();
    let retired = watch.proven_noncommit().unwrap();
    let view = store.snapshot().unwrap();
    let abort =
        CompleteEnvelope::technical_abort(&view, retired, "conflict".into(), time(101)).unwrap();
    let aborted = confirm(abort, &store, &effects);
    drop(view);
    let proof = aborted.abort_proof().unwrap();
    let view = store.snapshot().unwrap();
    let request = || RetryRequest {
        request_id: "retry-1".into(),
        expected_abort: proof,
    };
    let AdmissionDecision::New(one) =
        PreparedAdmission::retry(&view, &input("retry"), &request(), time(102), permission)
            .unwrap()
    else {
        panic!()
    };
    let AdmissionDecision::New(two) =
        PreparedAdmission::retry(&view, &input("retry"), &request(), time(102), permission)
            .unwrap()
    else {
        panic!()
    };
    let owner = one.publish(&store, || Ok(())).unwrap();
    assert_eq!(owner.record().attempt(), 2);
    assert!(matches!(
        two.publish(&store, || panic!(
            "duplicate retry must fail before acceptance"
        )),
        Err(AtomicError::Conflict)
    ));
    drop(view);
    let view = store.snapshot().unwrap();
    let AdmissionDecision::Existing(existing) =
        PreparedAdmission::retry(&view, &input("retry"), &request(), time(102), permission)
            .unwrap()
    else {
        panic!()
    };
    assert_eq!(existing.attempt(), 2);
    let old = view
        .get(&record::attempt_row_key(aborted.id, 1))
        .unwrap()
        .unwrap();
    assert_eq!(CommandRecord::decode(&old).unwrap(), aborted);
    let success = CompleteEnvelope::success(
        &view,
        owner,
        None,
        vec![],
        value(b"retry result"),
        &effects,
        time(102),
    )
    .unwrap();
    match success.publish(&store, |authorities| {
        let guard = effects.commit_fence(
            authorities,
            EffectTime {
                unix_millis: 102,
                continuity_proven: true,
            },
        )?;
        drop(guard);
        Ok(())
    }) {
        PreparedDisposition::Confirmed { command, .. } => {
            assert_eq!(command.outcome(), Outcome::Committed);
        }
        _ => panic!(),
    }
    assert!(matches!(
        PreparedAdmission::retry(
            &store.snapshot().unwrap(),
            &input("retry"),
            &RetryRequest {
                request_id: "another".into(),
                expected_abort: proof
            },
            time(103),
            permission
        ),
        Err(AtomicError::RecoveryRequired)
    ));
}

#[test]
fn dropped_physical_guard_and_unknown_clock_never_authorize_a_retry() {
    let (_dir, store, _effects) = setup();
    let owner = claim(&store, input("uncertain"));
    let watch = owner.retirement();
    let physical = owner.physical_work().unwrap();
    drop(owner);
    drop(physical);
    assert!(matches!(
        watch.proven_noncommit(),
        Err(AtomicError::RecoveryRequired)
    ));
    let view = store.snapshot().unwrap();
    assert!(matches!(
        PreparedAdmission::retry(
            &view,
            &input("uncertain"),
            &RetryRequest {
                request_id: "timeout".into(),
                expected_abort: Identity([0; 32])
            },
            time(101),
            permission
        ),
        Err(AtomicError::RecoveryRequired)
    ));
    assert!(matches!(
        inspect(
            &view,
            &input("uncertain").key,
            CommandTime {
                unix_millis: 200,
                continuity_proven: false
            },
            permission
        ),
        Err(AtomicError::RecoveryRequired)
    ));
}

#[test]
fn result_expiry_keeps_protected_identity_and_read_permission_is_current() {
    let (_dir, store, effects) = setup();
    let owner = claim(&store, input("expiry"));
    let view = store.snapshot().unwrap();
    let success = CompleteEnvelope::success(
        &view,
        owner,
        None,
        vec![intent()],
        value(b"response"),
        &effects,
        time(101),
    )
    .unwrap();
    let record = confirm(success, &store, &effects);
    drop(view);
    let view = store.snapshot().unwrap();
    let (expired, body) = inspect(&view, &input("expiry").key, time(1100), permission).unwrap();
    assert_eq!(expired, record);
    assert!(body.is_none());
    assert_eq!(expired.effect_ids().len(), 1);
    assert!(matches!(
        PreparedAdmission::prepare(&view, input("expiry"), time(2200), permission),
        Ok(AdmissionDecision::Existing(_))
    ));
    assert!(matches!(
        inspect(&view, &input("expiry").key, time(102), |_, _| Err(
            AtomicError::PermissionDenied
        )),
        Err(AtomicError::PermissionDenied)
    ));
    let mut foreign = input("expiry").key;
    foreign.recovery_scope = "subject:bob".into();
    assert!(matches!(
        inspect(&view, &foreign, time(102), permission),
        Err(AtomicError::NotFound)
    ));
}

#[test]
fn oversized_results_intents_and_capacity_fail_before_business_mutation() {
    let (_dir, store, effects) = setup();
    let owner = claim(&store, input("limit"));
    let watch = owner.retirement();
    let view = store.snapshot().unwrap();
    assert!(matches!(
        CompleteEnvelope::success(
            &view,
            owner,
            Some(stage(&view)),
            vec![intent()],
            value(&vec![0; 1025]),
            &effects,
            time(101)
        ),
        Err(AtomicError::Invalid)
    ));
    assert!(watch.proven_noncommit().is_ok());
    let owner = claim(&store, input("count-limit"));
    let intents = (0..129).map(|_| intent()).collect();
    assert!(matches!(
        CompleteEnvelope::success(
            &store.snapshot().unwrap(),
            owner,
            None,
            intents,
            value(b"response"),
            &effects,
            time(101)
        ),
        Err(AtomicError::Limit)
    ));
    let mut request = input("quota");
    request.result_policy.maximum_result_bytes = 1024 * 1024;
    let key = namespace_key();
    let original = store.snapshot().unwrap().get(&key).unwrap().unwrap();
    let mut ns = NamespaceRecord::decode(&original).unwrap();
    ns.quota.result_bytes = 1024;
    ns.quota.recovery_bytes = 1024;
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key,
                value: Some(ns.encode().unwrap()),
            }],
        })
        .unwrap();
    assert!(matches!(
        PreparedAdmission::prepare(&store.snapshot().unwrap(), request, time(100), permission),
        Err(AtomicError::Limit)
    ));
    assert!(store
        .snapshot()
        .unwrap()
        .scan_after(Family::State, b"", None, 128, 1024)
        .unwrap()
        .rows
        .is_empty());
}

#[test]
fn maximum_result_and_128_intents_commit_as_one_complete_envelope() {
    let (dir, store, effects) = setup();
    let mut request = input("maximum");
    request.result_policy.maximum_result_bytes = 1024 * 1024;
    let key = request.key.clone();
    let owner = claim(&store, request);
    let view = store.snapshot().unwrap();
    let body = value(&vec![42; 1024 * 1024]);
    let envelope = CompleteEnvelope::success(
        &view,
        owner,
        Some(stage(&view)),
        (0..128).map(|_| intent()).collect(),
        body.clone(),
        &effects,
        time(101),
    )
    .unwrap();
    let record = confirm(envelope, &store, &effects);
    assert_eq!(record.effect_ids().len(), 128);
    drop(view);
    drop(store);
    let store = open(&dir.path().join("state.redb"));
    let view = store.snapshot().unwrap();
    let (_, result) = inspect(&view, &key, time(102), permission).unwrap();
    assert_eq!(result.unwrap().value(), Some(&body));
    for (sequence, effect) in record.effect_ids().iter().enumerate() {
        let bytes = view
            .get(&latent_effects::dispatch_store::effect_row_key(&effect.hex()).unwrap())
            .unwrap()
            .unwrap();
        let outbox = latent_effects::dispatch::EffectRecord::decode(&bytes).unwrap();
        let authority = outbox.authority().unwrap();
        assert_eq!(authority.link().sequence as usize, sequence);
        assert_eq!(authority.link().effect, effect.hex());
        assert_eq!(authority.link().command, record.id.hex());
    }
}

#[test]
fn reserved_result_row_allows_terminal_rejection_and_inbox_at_full_row_capacity() {
    let (dir, store, effects) = setup();
    drop(store);
    let store = open_limited(
        &dir.path().join("state.redb"),
        StoreLimits {
            maximum_rows: 6,
            ..StoreLimits::default()
        },
    );
    let mut request = input("row-pressure");
    request.inbox = Some(InboxIdentity {
        provider: "input".into(),
        binding: "source".into(),
        message: "full-store".into(),
        payload_digest: Identity::derive(b"input", &[b"full"]),
    });
    let key = request.key.clone();
    let inbox = request.inbox.clone().unwrap();
    let owner = claim(&store, request);
    let view = store.snapshot().unwrap();
    let rejected = CompleteEnvelope::rejection(
        &view,
        owner,
        "inventory-unavailable".into(),
        value(b"immutable rejection"),
        time(101),
    )
    .unwrap();
    let record = confirm(rejected, &store, &effects);
    assert_eq!(record.outcome(), Outcome::Rejected);
    drop(view);
    let view = store.snapshot().unwrap();
    assert!(view.get(&inbox.row_key(&key).unwrap()).unwrap().is_some());
    let (_, result) = inspect(&view, &key, time(102), permission).unwrap();
    assert_eq!(
        result.unwrap().value(),
        Some(&value(b"immutable rejection"))
    );
    assert!(matches!(
        PreparedAdmission::prepare(&view, input("another"), time(102), permission).unwrap(),
        AdmissionDecision::New(_)
    ));
    let AdmissionDecision::New(next) =
        PreparedAdmission::prepare(&view, input("another"), time(102), permission).unwrap()
    else {
        panic!()
    };
    assert!(matches!(
        next.publish(&store, || panic!(
            "physical quota must fail before acceptance"
        )),
        Err(AtomicError::Limit)
    ));
}

#[test]
fn compatible_rollout_replays_original_source_and_clock_rollback_is_closed() {
    let (_dir, store, effects) = setup();
    let owner = claim(&store, input("rollout"));
    let view = store.snapshot().unwrap();
    let envelope = CompleteEnvelope::success(
        &view,
        owner,
        None,
        vec![intent()],
        value(b"original"),
        &effects,
        time(101),
    )
    .unwrap();
    let original = confirm(envelope, &store, &effects);
    drop(view);
    let mut next = input("rollout");
    next.source.revision = "revision-2".into();
    next.source.route_generation = 2;
    next.source.component_digest = format!("sha256:{}", "5".repeat(64));
    let view = store.snapshot().unwrap();
    let AdmissionDecision::Existing(replay) =
        PreparedAdmission::prepare(&view, next, time(102), permission).unwrap()
    else {
        panic!()
    };
    assert_eq!(replay, original);
    assert_eq!(replay.source().revision, "revision-1");
    assert!(matches!(
        inspect(&view, &input("rollout").key, time(100), permission),
        Err(AtomicError::RecoveryRequired)
    ));
    assert!(matches!(
        PreparedAdmission::prepare(&view, input("rollout"), time(100), permission),
        Err(AtomicError::RecoveryRequired)
    ));
    let (_, result) = inspect(&view, &input("rollout").key, time(102), permission).unwrap();
    let mut encoded = result.unwrap().encode().unwrap();
    let marker = encoded
        .windows(b"original".len())
        .position(|b| b == b"original")
        .unwrap();
    encoded[marker] ^= 1;
    assert_eq!(DurableResult::decode(&encoded), Err(AtomicError::Corrupt));
}

fn foreign_codec(
    view: &latent_state::embedded::ReadView,
    key: &RowKey,
    bytes: &[u8],
) -> Result<(), latent_state::embedded::StoreError> {
    use latent_state::{embedded::StoreError, namespace::NamespaceError};
    if key.family == Family::Namespace {
        return latent_state::namespace::catalog::NamespaceCatalog::validate_row(key, bytes)
            .map_err(|e| match e {
                NamespaceError::UnsupportedFormat => StoreError::UnsupportedFormat,
                _ => StoreError::Corrupt,
            });
    }
    match latent_state::session::validate_row(view, key, bytes) {
        Err(StoreError::UnsupportedFormat) => {
            latent_effects::dispatch_store::validate_row(key, bytes)
        }
        result => result,
    }
}

#[test]
fn coherent_startup_validates_pending_terminal_and_cross_family_links() {
    let (_dir, store, effects) = setup();
    let mut request = input("linked-startup");
    request.inbox = Some(InboxIdentity {
        provider: "input".into(),
        binding: "source".into(),
        message: "linked-input".into(),
        payload_digest: Identity::derive(b"input", &[b"linked"]),
    });
    let owner = claim(&store, request);
    let view = store.snapshot().unwrap();
    validate_view(&view, foreign_codec).unwrap();
    let envelope = CompleteEnvelope::success(
        &view,
        owner,
        Some(stage(&view)),
        vec![intent()],
        value(b"linked"),
        &effects,
        time(101),
    )
    .unwrap();
    let committed = confirm(envelope, &store, &effects);
    drop(view);
    let view = store.snapshot().unwrap();
    validate_view(&view, foreign_codec).unwrap();
    let payload_key =
        latent_effects::dispatch_store::effect_payload_key(&committed.effect_ids()[0].hex())
            .unwrap();
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: payload_key,
                value: None,
            }],
        })
        .unwrap();
    assert_eq!(
        validate_view(&store.snapshot().unwrap(), foreign_codec),
        Err(latent_state::embedded::StoreError::Corrupt)
    );
}

#[test]
fn startup_rejects_uninstalled_formats_key_aliases_and_orphan_results() {
    use latent_state::embedded::StoreError;
    let (_dir, store, effects) = setup();
    let owner = claim(&store, input("format"));
    let view = store.snapshot().unwrap();
    let mut key = record::command_row_key(owner.record().id());
    let record_bytes = owner.record().encode().unwrap();
    key.key[record::command_row_key(owner.record().id()).key.len() - 1] ^= 1;
    assert_eq!(validate_row(&key, &record_bytes), Err(StoreError::Corrupt));
    let unknown = RowKey {
        family: Family::Maintenance,
        key: b"uninstalled-format-v2".to_vec(),
    };
    assert_eq!(
        validate_row(&unknown, b"opaque"),
        Err(StoreError::UnsupportedFormat)
    );
    let state = stage(&view);
    let envelope = CompleteEnvelope::success(
        &view,
        owner,
        Some(state),
        vec![],
        value(b"format"),
        &effects,
        time(101),
    )
    .unwrap();
    let committed = confirm(envelope, &store, &effects);
    drop(view);
    let view = store.snapshot().unwrap();
    let state_row = view
        .scan_after(Family::State, b"", None, 1, 2 * 1024 * 1024)
        .unwrap()
        .rows
        .pop()
        .unwrap();
    let mut corrupt_state = state_row.1.clone();
    corrupt_state[4..12].copy_from_slice(&u64::MAX.to_le_bytes());
    assert_eq!(
        latent_state::session::validate_row(&view, &state_row.0, &corrupt_state),
        Err(StoreError::Corrupt)
    );
    let mut truncated_key = state_row.0.clone();
    truncated_key.key.truncate(b"state-v1\0".len() + 1);
    assert_eq!(
        latent_state::session::validate_row(&view, &truncated_key, &state_row.1),
        Err(StoreError::Corrupt)
    );
    let result_key = record::result_row_key(committed.id, committed.attempt);
    let result_bytes = view.get(&result_key).unwrap().unwrap();
    let mut wrong_format = result_bytes.clone();
    wrong_format[4] = 1;
    assert_eq!(
        validate_row(&result_key, &wrong_format),
        Err(StoreError::UnsupportedFormat)
    );
    drop(view);
    store
        .apply(AtomicBatch {
            expectations: vec![],
            mutations: vec![RowMutation {
                key: record::command_row_key(committed.id),
                value: None,
            }],
        })
        .unwrap();
    assert_eq!(
        validate_view(&store.snapshot().unwrap(), foreign_codec),
        Err(StoreError::Corrupt)
    );
}

#[test]
fn receipt_only_replay_and_malformed_record_lengths_remain_explicit() {
    let (_dir, store, effects) = setup();
    let mut request = input("receipt-only");
    request.result_policy.replay = ReplayPolicy::ReceiptOnly;
    let key = request.key.clone();
    let owner = claim(&store, request);
    let view = store.snapshot().unwrap();
    let success = CompleteEnvelope::success(
        &view,
        owner,
        None,
        vec![],
        value(b"not promised for replay"),
        &effects,
        time(101),
    )
    .unwrap();
    let record = confirm(success, &store, &effects);
    let (_record, result) =
        inspect(&store.snapshot().unwrap(), &key, time(102), permission).unwrap();
    assert!(result.unwrap().value().is_none());
    let encoded = record.encode().unwrap();
    for offset in [0, 4, 32, encoded.len() - 1] {
        assert!(CommandRecord::decode(&encoded[..offset]).is_err());
    }
    let mut malformed = encoded.clone();
    malformed[5..7].copy_from_slice(&u16::MAX.to_le_bytes());
    assert_eq!(CommandRecord::decode(&malformed), Err(AtomicError::Corrupt));
    let mut unsupported = encoded;
    unsupported[4] = 1;
    assert_eq!(
        CommandRecord::decode(&unsupported),
        Err(AtomicError::UnsupportedFormat)
    );
}

#[test]
fn original_terminal_namespace_version_survives_later_commit_and_reopen() {
    let (dir, store, effects) = setup();
    let first_key = input("original-version").key;
    let first = claim(&store, input("original-version"));
    assert_eq!(first.record().committed_version(), None);
    let view = store.snapshot().unwrap();
    let state = stage(&view);
    let original_version = state.version();
    let first = confirm(
        CompleteEnvelope::success(
            &view,
            first,
            Some(state),
            vec![],
            value(b"original"),
            &effects,
            time(101),
        )
        .unwrap(),
        &store,
        &effects,
    );
    assert_eq!(first.committed_version(), Some(original_version));
    drop(view);
    let second = claim(&store, input("later-version"));
    let view = store.snapshot().unwrap();
    let second = confirm(
        CompleteEnvelope::success(
            &view,
            second,
            None,
            vec![],
            value(b"later"),
            &effects,
            time(102),
        )
        .unwrap(),
        &store,
        &effects,
    );
    assert!(second.committed_version().unwrap().generation > original_version.generation);
    drop(view);
    drop(store);
    let store = open(&dir.path().join("state.redb"));
    let view = store.snapshot().unwrap();
    let (replayed, result) = inspect(&view, &first_key, time(103), permission).unwrap();
    let namespace = NamespaceRecord::decode(&view.get(&namespace_key()).unwrap().unwrap()).unwrap();
    assert_eq!(replayed, first);
    assert_eq!(replayed.committed_version(), Some(original_version));
    assert_eq!(
        result.as_ref().unwrap().committed_version(),
        original_version
    );
    assert_eq!(result.as_ref().unwrap().value(), Some(&value(b"original")));
    assert_eq!(namespace.version, second.committed_version().unwrap());
    assert_ne!(namespace.version, original_version);
}

#[test]
fn terminal_namespace_version_codec_rejects_forgery_absence_and_legacy_format() {
    let (_dir, store, effects) = setup();
    let key = input("version-codec").key;
    let claim = claim(&store, input("version-codec"));
    let mut pending = claim.record().clone();
    pending.committed_version = Some(NamespaceVersion {
        incarnation: 1,
        generation: 2,
    });
    assert_eq!(pending.encode(), Err(AtomicError::Invalid));
    let view = store.snapshot().unwrap();
    let original = confirm(
        CompleteEnvelope::rejection(
            &view,
            claim,
            "business-rejected".into(),
            value(b"rejected"),
            time(101),
        )
        .unwrap(),
        &store,
        &effects,
    );
    drop(view);
    let (replayed, result) =
        inspect(&store.snapshot().unwrap(), &key, time(102), permission).unwrap();
    let result = result.unwrap();
    assert_eq!(
        result.committed_version(),
        original.committed_version().unwrap()
    );
    for version in [
        None,
        Some(NamespaceVersion {
            incarnation: 1,
            generation: 0,
        }),
        Some(NamespaceVersion {
            incarnation: 2,
            generation: 3,
        }),
    ] {
        let mut wrong = replayed.clone();
        wrong.committed_version = version;
        assert_eq!(wrong.encode(), Err(AtomicError::Invalid));
    }
    let mut maximum = replayed.clone();
    maximum.committed_version = Some(NamespaceVersion {
        incarnation: 1,
        generation: u64::MAX,
    });
    let scope = super::record::record_scope(&maximum).unwrap();
    let mut identity = latent_state::session::version::ViewIdentity::from_token(
        &scope,
        &maximum.committed_view_token,
    )
    .unwrap();
    identity.namespace = maximum.committed_version.unwrap();
    maximum.committed_view_token = identity.token(&scope).unwrap();
    assert_eq!(
        CommandRecord::decode(&maximum.encode().unwrap()).unwrap(),
        maximum
    );
    assert_eq!(result.verify(&maximum), Err(AtomicError::Corrupt));
    let mut bytes = result.encode().unwrap();
    // Fixed bounded result header: magic, command, attempt, transaction, outcome.
    let generation = 5 + 32 + 8 + 32 + 1 + 8;
    bytes[generation..generation + 8].copy_from_slice(&0u64.to_le_bytes());
    assert_eq!(DurableResult::decode(&bytes), Err(AtomicError::Corrupt));
    bytes = result.encode().unwrap();
    bytes[generation..generation + 8].copy_from_slice(&u64::MAX.to_le_bytes());
    assert_eq!(DurableResult::decode(&bytes), Err(AtomicError::Corrupt));
    let mut historic = original.encode().unwrap();
    historic[4] = 1;
    assert_eq!(
        CommandRecord::decode(&historic),
        Err(AtomicError::UnsupportedFormat)
    );
    let mut historic = result.encode().unwrap();
    historic[4] = 1;
    assert_eq!(
        DurableResult::decode(&historic),
        Err(AtomicError::UnsupportedFormat)
    );
}
