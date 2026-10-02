//! Real selected-engine and complete-envelope fixtures. These controlled
//! immutable evidence callbacks are not production policy/audit qualification.
use super::*;
use crate::atomic::{
    AdmissionDecision, AdmissionInput, CommandAccess, CommandTime, CompleteEnvelope, InboxIdentity,
    PreparedAdmission, PreparedDisposition, ReplayPolicy, ResultPolicy, StagedIntent,
};
use latent_core::{
    transaction_contract::{CommandFingerprint, CommandKey, Value},
    StateNamespaceId, TenantId,
};
use latent_effects::{
    authority::{DispatchCeiling, EffectAuthorityOwner, EffectRule, EffectTime},
    dispatch::{AttemptReceipt, Disposition},
};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, Family, RowMutation, StoreLimits},
    namespace::{
        catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
        compatibility::SchemaId,
        namespace_record_key, NamespaceQuota, NamespaceRecord, NamespaceTransition,
    },
    session::{SessionLimits, StateError, StateMode, StateScope, StateSession},
    tenant::{self, TenantUsage, INSTALLED_GLOBAL_ALLOWANCE},
};
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, fs::OpenOptions, path::Path, time::Duration};

const DEFINITION: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../contracts/state/application-aggregate-v1.schema.json"
));
pub(super) const RUNTIME: [u8; 32] = [90; 32];
pub(super) const PUBLICATION: [u8; 32] = [91; 32];
pub(super) const ADAPTER: [u8; 32] = [92; 32];
pub(super) const PROFILE: [u8; 32] = [93; 32];
pub(super) const INBOX: [u8; 32] = [94; 32];

pub(super) fn quota(tenant: &str) -> TenantQuota {
    TenantQuota {
        tenant: TenantId(tenant.into()),
        limits: TenantUsage {
            state_keys: 8,
            state_bytes: 1024 * 1024,
            tombstone_keys: 8,
            tombstone_bytes: 1024 * 1024,
            result_rows: 128,
            result_bytes: 16 * 1024 * 1024,
            effect_rows: 16,
            effect_bytes: 16 * 1024 * 1024,
            payload_bytes: 16 * 1024 * 1024,
            recovery_bytes: 8 * 1024 * 1024,
            metadata_rows: 128,
            metadata_bytes: 1024 * 1024,
        },
    }
}
pub(super) fn value(bytes: &[u8]) -> Value {
    Value {
        bytes: bytes.into(),
        media_type: "application/octet-stream".into(),
        metadata: vec![],
    }
}
pub(super) fn time(now: u64) -> CommandTime {
    CommandTime {
        unix_millis: now,
        continuity_proven: true,
    }
}
pub(super) fn effect_time(now: u64) -> EffectTime {
    EffectTime {
        unix_millis: now,
        continuity_proven: true,
    }
}
pub(super) fn schema() -> String {
    SchemaId::from_definition(DEFINITION)
        .unwrap()
        .as_str()
        .into()
}
pub(super) fn source_identity() -> SourceIdentity {
    SourceIdentity {
        publication: "original-publication".into(),
        revision: "original-revision".into(),
        release_digest: format!("sha256:{}", "1".repeat(64)),
        component_digest: format!("sha256:{}", "2".repeat(64)),
        contract_digest: format!("sha256:{}", "3".repeat(64)),
        route_generation: 1,
        state_schema: schema(),
        input_format: "lsf-wit-values-v1".into(),
        result_format: "lsf-wit-values-v1".into(),
    }
}
pub(super) fn input(key: &str, entity: Option<String>) -> AdmissionInput {
    AdmissionInput {
        key: CommandKey {
            tenant: "tenant".into(),
            namespace: "aggregate".into(),
            incarnation: "1".into(),
            recovery_scope: "subject:alice".into(),
            operation: "update".into(),
            entity,
            client_key: key.into(),
        },
        fingerprint: CommandFingerprint {
            input_format: "lsf-wit-values-v1".into(),
            input: value(b"delta=1"),
            expected_versions: vec![],
        },
        source: source_identity(),
        result_read_policy: "aggregate/read-v1".into(),
        result_policy: ResultPolicy {
            replay: ReplayPolicy::Full,
            maximum_result_bytes: 1024,
            result_millis: 1000,
            identity_millis: 2000,
            maximum_attempts: 3,
        },
        inbox: Some(InboxIdentity {
            provider: "source-provider".into(),
            binding: "original-consumer".into(),
            message: format!("message-{key}"),
            payload_digest: atomic::Identity::parse_hex(&"a".repeat(64)).unwrap(),
        }),
        owner_epoch: 1,
    }
}
pub(super) fn profile() -> DispatchProfile {
    DispatchProfile {
        provider: "events".into(),
        destination: "events.original-subject".into(),
        adapter: "qualified-test-v1".into(),
        intent_format: 1,
        payload_format: "lsf-value-v1".into(),
        idempotency_profile: "original-finite-dedup-v1".into(),
    }
}
fn effects() -> EffectAuthorityOwner {
    let owner = EffectAuthorityOwner::new(4, 4, 0).unwrap();
    owner
        .publish(EffectRule {
            scope: EffectScope {
                tenant: "tenant".into(),
                namespace: "aggregate".into(),
                incarnation: 1,
                publication: "original-publication".into(),
                binding: "approved-event".into(),
                operation: "event".into(),
            },
            profile: profile(),
            ceiling: DispatchCeiling {
                maximum_payload_bytes: 1024,
                maximum_response_bytes: 1024,
                maximum_attempts: 3,
                maximum_age_millis: 1000,
                attempt_timeout_millis: 100,
            },
            policy_revision: 1,
            credential_epoch: 1,
            protected_credential_reference: "protected-events".into(),
            enabled: true,
        })
        .unwrap();
    owner
}
pub(super) fn open(path: &Path) -> EmbeddedStore {
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
            ..StoreLimits::default()
        },
    )
    .unwrap()
}
pub(super) struct Fixture {
    pub directory: tempfile::TempDir,
    pub store: EmbeddedStore,
    pub effects: EffectAuthorityOwner,
    pub quotas: Vec<TenantQuota>,
}
impl Fixture {
    pub fn new(two_tenants: bool) -> Self {
        let directory = tempfile::tempdir().unwrap();
        let store = open(&directory.path().join("state.redb"));
        let mut quotas = vec![quota("tenant")];
        if two_tenants {
            quotas.push(quota("other-tenant"));
        }
        let view = store.snapshot().unwrap();
        let installation = tenant::prepare_install(&view, &quotas).unwrap();
        drop(view);
        installation.publish(&store, || Ok::<_, ()>(())).unwrap();
        store
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: StoreIdentity::row_key(),
                    value: Some(
                        StoreIdentity::new("original-whole-unit".into())
                            .unwrap()
                            .encode(),
                    ),
                }],
            })
            .unwrap();
        for quota in &quotas {
            let prepared = NamespaceCatalog::new()
                .prepare(
                    &store,
                    NamespaceOperationContext {
                        tenant: quota.tenant.clone(),
                        actor: "original-operator".into(),
                        operation_id: "create".into(),
                    },
                    &NamespaceMutation::Create {
                        id: StateNamespaceId("aggregate".into()),
                        state_schema: schema(),
                        quota: NamespaceQuota::default(),
                    },
                    0,
                )
                .unwrap();
            store.apply(prepared.batch).unwrap();
        }
        Self {
            directory,
            store,
            effects: effects(),
            quotas,
        }
    }
    pub fn command(
        &self,
        key: &str,
        entity: Option<String>,
        state_key: Vec<u8>,
        reject: bool,
    ) -> atomic::CommandRecord {
        let view = self.store.snapshot().unwrap();
        let AdmissionDecision::New(prepared) =
            PreparedAdmission::prepare(&view, input(key, entity.clone()), time(100), permission)
                .unwrap()
        else {
            panic!("expected original new claim")
        };
        drop(view);
        let admitted = prepared
            .publish(&self.store, || permission(CommandAccess::FinalClaim, None))
            .unwrap();
        let view = self.store.snapshot().unwrap();
        let envelope = if reject {
            CompleteEnvelope::rejection(
                &view,
                admitted,
                "BUSINESS_DECLINED".into(),
                value(b"original rejection"),
                time(101),
            )
            .unwrap()
        } else {
            let mut session = StateSession::open(
                &view,
                StateScope {
                    tenant: TenantId("tenant".into()),
                    namespace: StateNamespaceId("aggregate".into()),
                    incarnation: 1,
                    state_schema: schema(),
                    entity,
                    mode: StateMode::Command,
                },
                SessionLimits::default(),
                state_permission,
            )
            .unwrap();
            session
                .put(
                    &view,
                    state_key,
                    value(&1u64.to_le_bytes()),
                    state_permission,
                )
                .unwrap();
            let plan = session.seal(&view, state_permission).unwrap();
            CompleteEnvelope::success(
                &view,
                admitted,
                Some(plan),
                vec![StagedIntent {
                    binding: "approved-event".into(),
                    operation: "event".into(),
                    payload: value(b"original effect payload"),
                    expires_at_millis: None,
                }],
                value(b"original result"),
                &self.effects,
                time(101),
            )
            .unwrap()
        };
        let result = envelope.publish(&self.store, |authorities| {
            let original = self.effects.commit_fence(authorities, effect_time(101))?;
            permission(CommandAccess::FinalDisposition, None)?;
            drop(original);
            Ok(())
        });
        match result {
            PreparedDisposition::Confirmed { command, .. } => *command,
            _ => panic!("expected actual durable disposition"),
        }
    }
    pub fn uncertain(&self) {
        let epoch =
            DispatchCatalog::begin_exclusive_epoch(&self.store, effect_time(102), None).unwrap();
        let candidate =
            DispatchCatalog::due_page(&self.store.snapshot().unwrap(), 102, None, 1, 4096)
                .unwrap()
                .rows
                .pop()
                .unwrap();
        let claim =
            DispatchCatalog::claim(&self.store, epoch, &candidate, effect_time(102)).unwrap();
        DispatchCatalog::begin_send(&self.store, epoch, &claim.attempt, effect_time(103)).unwrap();
        DispatchCatalog::complete(
            &self.store,
            epoch,
            &claim.attempt,
            AttemptReceipt {
                disposition: Disposition::Uncertain,
                reason: "lost-original-response".into(),
                provider_receipt: None,
                observed_at_millis: 104,
            },
            None,
            effect_time(104),
        )
        .unwrap();
    }
    pub fn quiesce(&self) {
        for quota in &self.quotas {
            let key = RowKey {
                family: Family::Namespace,
                key: namespace_record_key(&quota.tenant, &StateNamespaceId("aggregate".into()))
                    .unwrap(),
            };
            let record = NamespaceRecord::decode(
                &self.store.snapshot().unwrap().get(&key).unwrap().unwrap(),
            )
            .unwrap();
            let prepared = NamespaceCatalog::new()
                .prepare(
                    &self.store,
                    NamespaceOperationContext {
                        tenant: quota.tenant.clone(),
                        actor: "original-operator".into(),
                        operation_id: "quiesce".into(),
                    },
                    &NamespaceMutation::Transition {
                        id: record.id,
                        expected: record.version,
                        action: NamespaceTransition::Quiesce,
                    },
                    0,
                )
                .unwrap();
            self.store.apply(prepared.batch).unwrap();
        }
    }
    pub fn metadata(&self) -> SnapshotMetadata {
        let source = source_identity();
        let key = input("fixture", None).key;
        let inbox = input("fixture", None).inbox.unwrap();
        let inbox_profile = original_inbox_profile_identity(&key, &source, &inbox).unwrap();
        let provider_profile = original_profile_identity(&profile()).unwrap();
        let formats = approved_formats(&inbox_profile);
        let mut required_artifacts = vec![
            RequiredArtifact {
                identity: source.publication,
                digest: PUBLICATION,
            },
            RequiredArtifact {
                identity: source.release_digest,
                digest: [0x11; 32],
            },
            RequiredArtifact {
                identity: source.component_digest,
                digest: [0x22; 32],
            },
            RequiredArtifact {
                identity: source.contract_digest,
                digest: [0x33; 32],
            },
            RequiredArtifact {
                identity: source.state_schema,
                digest: Sha256::digest(DEFINITION).into(),
            },
            RequiredArtifact {
                identity: profile().adapter,
                digest: ADAPTER,
            },
            RequiredArtifact {
                identity: provider_profile,
                digest: PROFILE,
            },
            RequiredArtifact {
                identity: inbox_profile,
                digest: INBOX,
            },
        ];
        required_artifacts.sort_by(|one, two| one.identity.cmp(&two.identity));
        SnapshotMetadata {
            tenant: "tenant".into(),
            operation_id: "backup-original".into(),
            operator_id: "original-operator".into(),
            runtime_digest: RUNTIME,
            decoder_formats: formats.into_iter().collect(),
            required_artifacts,
        }
    }
    pub fn review(
        &self,
        metadata: &SnapshotMetadata,
        owners: &mut Owners,
    ) -> Result<RecoveryReview, RecoveryReviewError> {
        review_snapshot(
            &self.store.snapshot().unwrap(),
            RecoveryReviewRequest {
                quotas: &self.quotas,
                global_allowance: INSTALLED_GLOBAL_ALLOWANCE,
                metadata,
                deadline: Instant::now() + Duration::from_secs(20),
            },
            owners,
            || Ok(()),
        )
    }
}

fn permission(_: CommandAccess, record: Option<&atomic::CommandRecord>) -> Result<(), AtomicError> {
    if record.is_some_and(|record| {
        record.key().tenant != "tenant"
            || record.key().recovery_scope != "subject:alice"
            || record.result_read_policy() != "aggregate/read-v1"
    }) {
        Err(AtomicError::PermissionDenied)
    } else {
        Ok(())
    }
}
fn state_permission(
    scope: &StateScope,
    _: latent_state::session::StateAccess,
) -> Result<(), StateError> {
    if scope.tenant.0 == "tenant"
        && scope.namespace.0 == "aggregate"
        && scope.incarnation == 1
        && scope.state_schema == schema()
    {
        Ok(())
    } else {
        Err(StateError::PermissionDenied)
    }
}

pub(super) fn approved_formats(inbox: &str) -> BTreeSet<RetainedFormat> {
    use RetainedKind as K;
    [
        (K::CommandFingerprint, "latent.command.v1/4"),
        (K::CommandFingerprint, "lsf-wit-values-v1"),
        (K::CommandFingerprint, "latent.result-expired.v1/1"),
        (K::CommandFingerprint, "latent.command-retired.v1/1"),
        (K::CommandAttempt, "latent.command.v1/4"),
        (K::CommandAttempt, "latent.effect-attempt.v1/1"),
        (K::CommandAttempt, "latent.effect-attempt-pending.v1/1"),
        (K::CommandAttempt, "latent.result-pending.v1/1"),
        (K::CommandAttempt, "latent.result.v1/3"),
        (K::CommandAttempt, "lsf-wit-values-v1"),
        (K::SuccessResult, "lsf-wit-values-v1"),
        (K::SuccessResult, "latent.result.v1/3"),
        (K::RejectionResult, "lsf-wit-values-v1"),
        (K::RejectionResult, "latent.result.v1/3"),
        (K::EffectEnvelope, "latent.effect-record.v1/1"),
        (K::EffectEnvelope, "latent.effect-record.v1/2"),
        (K::EffectEnvelope, "latent.intent.v1"),
        (K::EffectPayload, "latent.effect-payload.v1/1"),
        (K::EffectPayload, "lsf-value-v1"),
        (K::AdapterProfile, "qualified-test-v1"),
        (K::AdapterProfile, "original-finite-dedup-v1"),
        (K::InboxIdentity, "latent.inbox.v1/1"),
        (K::InboxIdentity, inbox),
    ]
    .into_iter()
    .map(|(kind, identity)| RetainedFormat {
        kind,
        identity: identity.into(),
    })
    .collect()
}
pub(super) struct Owners {
    pub source: SourceIdentity,
    pub profile: DispatchProfile,
    pub inbox_binding: String,
    pub formats: BTreeSet<RetainedFormat>,
    pub calls: usize,
}
impl Owners {
    pub fn new() -> Self {
        let request = input("fixture", None);
        let inbox = request.inbox.unwrap();
        let identity =
            original_inbox_profile_identity(&request.key, &request.source, &inbox).unwrap();
        Self {
            source: source_identity(),
            profile: profile(),
            inbox_binding: inbox.binding,
            formats: approved_formats(&identity),
            calls: 0,
        }
    }
}
impl RecoveryReviewOwners for Owners {
    fn require_runtime(&mut self, actual: [u8; 32]) -> Result<(), StoreError> {
        self.calls += 1;
        if actual == RUNTIME {
            Ok(())
        } else {
            Err(StoreError::UnsupportedFormat)
        }
    }
    fn require_decoder(&mut self, actual: &RetainedFormat) -> Result<(), StoreError> {
        self.calls += 1;
        if self.formats.contains(actual) {
            Ok(())
        } else {
            Err(StoreError::UnsupportedFormat)
        }
    }
    fn publication(&mut self, original: &SourceIdentity) -> Result<[u8; 32], StoreError> {
        self.calls += 1;
        if *original == self.source {
            Ok(PUBLICATION)
        } else {
            Err(StoreError::UnsupportedFormat)
        }
    }
    fn dispatch_profile(
        &mut self,
        scope: &EffectScope,
        original: &DispatchProfile,
    ) -> Result<OriginalProfileArtifacts, StoreError> {
        self.calls += 1;
        if *original == self.profile
            && scope.tenant == "tenant"
            && scope.namespace == "aggregate"
            && scope.incarnation == 1
            && scope.publication == "original-publication"
            && scope.binding == "approved-event"
            && scope.operation == "event"
        {
            Ok(OriginalProfileArtifacts {
                adapter_digest: ADAPTER,
                definition_digest: PROFILE,
            })
        } else {
            Err(StoreError::UnsupportedFormat)
        }
    }
    fn inbox_profile(
        &mut self,
        key: &CommandKey,
        source: &SourceIdentity,
        original: &InboxIdentity,
    ) -> Result<[u8; 32], StoreError> {
        self.calls += 1;
        if key.tenant == "tenant"
            && key.namespace == "aggregate"
            && key.incarnation == "1"
            && key.recovery_scope == "subject:alice"
            && *source == self.source
            && original.provider == "source-provider"
            && original.binding == self.inbox_binding
        {
            Ok(INBOX)
        } else {
            Err(StoreError::UnsupportedFormat)
        }
    }
}
