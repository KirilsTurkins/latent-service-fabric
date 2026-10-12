use latent_commit::atomic::{
    inspect, AdmissionDecision, AdmissionInput, AdmittedCommand, AtomicError, CommandAccess,
    CommandRecord, CommandTime, CompleteEnvelope, DurableResult, PreparedAdmission,
    PreparedDisposition, ReplayPolicy, ResultPolicy, SourceIdentity, StagedIntent,
};
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
};

pub(super) fn time(unix_millis: u64) -> CommandTime {
    CommandTime {
        unix_millis,
        continuity_proven: true,
    }
}
pub(super) fn value(bytes: &[u8]) -> Value {
    Value {
        bytes: bytes.to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: vec![],
    }
}
pub(super) fn input(client_key: &str) -> AdmissionInput {
    AdmissionInput {
        key: CommandKey {
            tenant: "tenant".into(),
            namespace: "namespace".into(),
            incarnation: "1".into(),
            recovery_scope: "caller-alice".into(),
            operation: "update".into(),
            entity: None,
            client_key: client_key.into(),
        },
        fingerprint: CommandFingerprint {
            input_format: "lsf-wit-values-v1".into(),
            input: value(b"original-input"),
            expected_versions: vec![],
        },
        source: SourceIdentity {
            publication: "publication".into(),
            revision: "revision-1".into(),
            release_digest: format!("sha256:{}", "1".repeat(64)),
            component_digest: format!("sha256:{}", "2".repeat(64)),
            contract_digest: format!("sha256:{}", "3".repeat(64)),
            route_generation: 1,
            state_schema: format!("sha256:{}", "4".repeat(64)),
            input_format: "lsf-wit-values-v1".into(),
            result_format: "lsf-wit-values-v1".into(),
        },
        result_read_policy: "application/read-v1".into(),
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
pub(super) fn authorize(record: &CommandRecord) -> Result<(), AtomicError> {
    permission(CommandAccess::Replay, Some(record))
}
pub(super) fn permission(
    _: CommandAccess,
    record: Option<&CommandRecord>,
) -> Result<(), AtomicError> {
    if record.is_some_and(|record| {
        record.key().tenant != "tenant"
            || record.key().recovery_scope != "caller-alice"
            || record.result_read_policy() != "application/read-v1"
    }) {
        return Err(AtomicError::PermissionDenied);
    }
    Ok(())
}

pub(super) struct Fixture {
    pub dir: tempfile::TempDir,
    pub store: EmbeddedStore,
    pub effects: EffectAuthorityOwner,
}
pub(super) fn open(path: &std::path::Path) -> EmbeddedStore {
    let file = std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path)
        .unwrap();
    EmbeddedStore::open_file(
        file,
        StoreLimits {
            maximum_value_bytes: 2 * 1024 * 1024,
            maximum_batch_rows: 1024,
            ..StoreLimits::default()
        },
    )
    .unwrap()
}
impl Fixture {
    pub fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let store = open(&dir.path().join("state.redb"));
        let namespace = NamespaceRecord {
            tenant: TenantId("tenant".into()),
            id: StateNamespaceId("namespace".into()),
            version: NamespaceVersion {
                incarnation: 1,
                generation: 1,
            },
            state_schema: input("schema").source.state_schema,
            status: NamespaceStatus::Active,
            quota: NamespaceQuota::default(),
            pins: NamespacePins::default(),
        };
        store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: RowKey {
                        family: Family::Namespace,
                        key: namespace_record_key(&namespace.tenant, &namespace.id).unwrap(),
                    },
                    value: Some(namespace.encode().unwrap()),
                }],
            })
            .unwrap();
        let effects = EffectAuthorityOwner::new(4, 4, 0).unwrap();
        effects
            .publish(EffectRule {
                scope: EffectScope {
                    tenant: "tenant".into(),
                    namespace: "namespace".into(),
                    incarnation: 1,
                    publication: "publication".into(),
                    binding: "event".into(),
                    operation: "publish".into(),
                },
                profile: DispatchProfile {
                    provider: "events".into(),
                    destination: "approved-subject".into(),
                    adapter: "qualified-test-v1".into(),
                    intent_format: 1,
                    payload_format: "lsf-value-v1".into(),
                    idempotency_profile: "qualified-test-idempotency-v1".into(),
                },
                policy_revision: 1,
                credential_epoch: 1,
                protected_credential_reference: "protected-reference".into(),
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
        Self {
            dir,
            store,
            effects,
        }
    }
    pub fn claim(&self, key: &str) -> AdmittedCommand {
        self.claim_input(input(key))
    }
    pub fn claim_input(&self, input: AdmissionInput) -> AdmittedCommand {
        let AdmissionDecision::New(prepared) = PreparedAdmission::prepare(
            &self.store.snapshot().unwrap(),
            input,
            time(100),
            permission,
        )
        .unwrap() else {
            panic!("expected new durable claim")
        };
        prepared.publish(&self.store, || Ok(())).unwrap()
    }
    pub fn lookup(&self, key: &str) -> (CommandRecord, Option<DurableResult>) {
        inspect(
            &self.store.snapshot().unwrap(),
            &input(key).key,
            time(102),
            permission,
        )
        .unwrap()
    }
    pub fn commit(&self, claim: AdmittedCommand, with_effect: bool) -> CommandRecord {
        let intents = if with_effect {
            vec![StagedIntent {
                binding: "event".into(),
                operation: "publish".into(),
                payload: value(b"one-effect"),
                expires_at_millis: None,
            }]
        } else {
            vec![]
        };
        let envelope = CompleteEnvelope::success(
            &self.store.snapshot().unwrap(),
            claim,
            None,
            intents,
            value(b"original-result"),
            &self.effects,
            time(101),
        )
        .unwrap();
        self.publish(envelope)
    }
    pub fn publish(&self, envelope: CompleteEnvelope) -> CommandRecord {
        let now = envelope.command().clock_floor();
        match envelope.publish(&self.store, |authorities| {
            let fence = self.effects.commit_fence(
                authorities,
                EffectTime {
                    unix_millis: now,
                    continuity_proven: true,
                },
            )?;
            drop(fence);
            Ok(())
        }) {
            PreparedDisposition::Confirmed { command, .. } => *command,
            _ => panic!("expected confirmed original atomic disposition"),
        }
    }
}
