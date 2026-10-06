//! Real common envelope: aggregate, original command/result, inbox and one
//! captured pending effect/payload. The synthetic source does not execute Java.
use super::*;
use latent_commit::atomic::{
    AdmissionDecision, AdmissionInput, CompleteEnvelope, InboxIdentity, PreparedAdmission,
    PreparedDisposition, ReplayPolicy, ResultPolicy, SourceIdentity, StagedIntent,
};
use latent_core::transaction_contract::{CommandFingerprint, CommandKey};
use latent_state::{
    embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowKey, RowMutation},
    namespace::{namespace_record_key, NamespaceQuota, NamespaceRecord, NamespaceTransition},
    session::{SessionLimits, StateMode, StatePlan, StateScope, StateSession},
};

pub(super) struct Workload {
    pub key: CommandKey,
    pub authority: DurableEffectAuthority,
    pub command: Vec<u8>,
    pub result: Vec<u8>,
    pub original_view: Vec<u8>,
}

pub(super) fn scope() -> StateScope {
    StateScope {
        tenant: TenantId("a".into()),
        namespace: latent_core::StateNamespaceId("orders".into()),
        incarnation: 7,
        state_schema: codecs::schema_artifact().identity,
        entity: None,
        mode: StateMode::Command,
    }
}

pub(super) fn input(fixture: &Fixture) -> AdmissionInput {
    let fingerprint = CommandFingerprint {
        input_format: "latent.http-restore.input.v1".into(),
        input: value(b"synthetic update delta=7"),
        expected_versions: vec![],
    };
    AdmissionInput {
        key: CommandKey {
            tenant: "a".into(),
            namespace: "orders".into(),
            incarnation: "7".into(),
            recovery_scope: "subject:alice".into(),
            operation: "update".into(),
            entity: None,
            client_key: "restore-pending-effect".into(),
        },
        inbox: Some(InboxIdentity {
            provider: "synthetic-event".into(),
            binding: "orders-input".into(),
            message: "event-1".into(),
            payload_digest: latent_commit::atomic::fingerprint(&fingerprint, None).unwrap(),
        }),
        fingerprint,
        source: SourceIdentity {
            publication: fixture.rule.scope.publication.clone(),
            revision: fixture.http.revision.revision.0.clone(),
            release_digest: fixture.http.publication.release().0.clone(),
            component_digest: codecs::component_artifact().identity,
            contract_digest: codecs::contract_artifact().identity,
            route_generation: fixture.http.revision.route_generation.0,
            state_schema: scope().state_schema,
            input_format: "latent.http-restore.input.v1".into(),
            result_format: "latent.http-restore.result.v1".into(),
        },
        result_read_policy: "orders/read-v1".into(),
        result_policy: ResultPolicy {
            replay: ReplayPolicy::Full,
            maximum_result_bytes: 1024,
            result_millis: 1000,
            identity_millis: 20_000,
            maximum_attempts: 3,
        },
        owner_epoch: 1,
    }
}

pub(super) async fn commit(store: &Store, fixture: &Fixture) -> Workload {
    let input = input(fixture);
    let effects = fixture.authority.clone();
    store
        .owner
        .with_store(StoreIoKind::Write, 8 * 1024 * 1024, move |store| {
            create_namespace(store)?;
            let view = store.snapshot()?;
            let key = input.key.clone();
            let AdmissionDecision::New(prepared) =
                PreparedAdmission::prepare(&view, input, time(), |_, _| Ok(())).unwrap()
            else {
                panic!("new actual command expected");
            };
            drop(view);
            let admitted = prepared.publish(store, || Ok(())).unwrap();
            let captured = admitted
                .intent_capture_context()
                .capture(
                    0,
                    StagedIntent {
                        binding: "qualified-http".into(),
                        operation: HTTP_EFFECT_OPERATION.into(),
                        payload: value(BODY),
                        expires_at_millis: Some(10_100),
                    },
                    &effects,
                    time(),
                )
                .unwrap();
            let view = store.snapshot()?;
            let envelope = CompleteEnvelope::success_captured(
                &view,
                admitted,
                Some(stage(&view)),
                vec![captured],
                value(b"count=7"),
                &effects,
                time(),
            )
            .unwrap();
            let authority = envelope.authorities()[0].clone();
            drop(view);
            let PreparedDisposition::Confirmed { command, result } =
                envelope.publish(store, |authorities| {
                    // Final currentness runs at the real store acceptance fence.
                    // No metadata lock is retained across the physical flush.
                    drop(effects.commit_fence(
                        authorities,
                        EffectTime {
                            unix_millis: 100,
                            continuity_proven: true,
                        },
                    )?);
                    Ok(())
                })
            else {
                panic!("actual common envelope must commit");
            };
            assert_eq!(command.effect_ids(), &[command.effect_id(0)]);
            assert_eq!(command.effect_id(0).hex(), authority.link().effect);
            Ok(Workload {
                key,
                authority,
                original_view: result.committed_view_token().to_vec(),
                command: command.encode().unwrap(),
                result: result.encode().unwrap(),
            })
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}

fn create_namespace(store: &latent_state::embedded::EmbeddedStore) -> Result<(), StoreError> {
    let scope = scope();
    let mut namespace = NamespaceRecord::create(
        scope.tenant,
        scope.namespace,
        scope.state_schema,
        NamespaceQuota::default(),
    )
    .unwrap();
    namespace.version.incarnation = 7;
    store.apply(AtomicBatch {
        expectations: vec![],
        mutations: vec![RowMutation {
            key: namespace_key(),
            value: Some(namespace.encode().unwrap()),
        }],
    })
}

fn stage(view: &ReadView) -> StatePlan {
    let mut session =
        StateSession::open(view, scope(), SessionLimits::default(), |_, _| Ok(())).unwrap();
    let mut value = value(&7_u64.to_le_bytes());
    value.media_type = "application/vnd.lsf.aggregate-v1".into();
    session
        .put(view, b"aggregate/count".to_vec(), value, |_, _| Ok(()))
        .unwrap();
    session.seal(view, |_, _| Ok(())).unwrap()
}

pub(super) fn namespace_key() -> RowKey {
    let scope = scope();
    RowKey {
        family: Family::Namespace,
        key: namespace_record_key(&scope.tenant, &scope.namespace).unwrap(),
    }
}

pub(super) async fn quiesce(store: &Store) {
    store
        .owner
        .with_store(StoreIoKind::Write, 1024 * 1024, |store| {
            let view = store.snapshot()?;
            let key = namespace_key();
            let original = view.get(&key)?.unwrap();
            let namespace = NamespaceRecord::decode(&original).unwrap();
            let next = namespace
                .transition(namespace.version, &NamespaceTransition::Quiesce, 0)
                .unwrap();
            drop(view);
            store.apply(AtomicBatch {
                expectations: vec![ExpectedRow {
                    key: key.clone(),
                    value: Some(original),
                }],
                mutations: vec![RowMutation {
                    key,
                    value: Some(next.encode().unwrap()),
                }],
            })
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}

pub(super) fn value(bytes: &[u8]) -> Value {
    Value {
        bytes: bytes.to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: vec![],
    }
}

pub(super) fn time() -> latent_commit::atomic::CommandTime {
    latent_commit::atomic::CommandTime {
        unix_millis: 100,
        continuity_proven: true,
    }
}
