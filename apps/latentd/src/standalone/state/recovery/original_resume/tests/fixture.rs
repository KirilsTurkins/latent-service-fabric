//! Real protected worker, atomic command/effect rows and affine native owners.
use super::{deadline, policy::Gate};
use latent_commit::atomic::{
    AdmissionDecision, AdmissionInput, CommandRecord, CommandTime, CompleteEnvelope, Outcome,
    PreparedAdmission, PreparedDisposition, ReplayPolicy, ResultPolicy, SourceIdentity,
    StagedIntent,
};
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeCapacityOwner, NativeReservation, NativeReservationRequest,
    },
    transaction_contract::{CommandFingerprint, CommandKey, Value},
    InvocationPrincipal, Metadata, PrincipalKind, StateNamespaceId, SystemActivationClock,
    TenantId,
};
use latent_effects::{
    authority::{
        DispatchCeiling, DispatchProfile, EffectAuthorityOwner, EffectRule, EffectScope, EffectTime,
    },
    dispatch::EffectRecord,
    dispatch_store::DispatchCatalog,
};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, Family, RowKey, RowMutation, StoreError},
    namespace::{
        compatibility::{RetainedCount, RetainedFormat, RetainedInventory, RetainedKind, SchemaId},
        history::{history_key, NamespaceHistory},
        namespace_record_key, NamespaceQuota, NamespaceRecord, NamespaceTransition,
    },
    protected_store::{ProtectedStoreConfig, ProtectedStoreOwner, ProtectedStoreStartupMemory},
    recovery::namespace_resume::{NamespaceRecoveryView, NamespaceResumeRequest},
    store_identity::StoreIdentity,
    store_io::StoreIoKind,
    tenant::{TenantQuota, TenantUsage},
};
use sha2::{Digest, Sha256};
use std::{os::unix::fs::PermissionsExt, sync::Arc};

pub(super) struct Fixture {
    pub store: Arc<ProtectedStoreOwner>,
    pub original: Arc<NativeReservation>,
    pub gate: Arc<Gate>,
    pub request: NamespaceResumeRequest,
    pub effect: String,
    pub effects: EffectAuthorityOwner,
    native: NativeCapacityOwner,
    root: tempfile::TempDir,
}

impl Fixture {
    pub async fn new(payload_bytes: usize) -> Self {
        Self::configured(payload_bytes, false, false).await
    }

    pub async fn with_uncertain_command() -> Self {
        Self::configured(27, true, false).await
    }

    pub async fn with_attempted_effect() -> Self {
        Self::configured(27, false, true).await
    }

    async fn configured(payload_bytes: usize, uncertain_command: bool, attempted: bool) -> Self {
        let root = tempfile::tempdir().unwrap();
        let mut config = ProtectedStoreConfig::bounded_linux(root.path().join("state"));
        std::fs::create_dir(&config.root).unwrap();
        std::fs::set_permissions(&config.root, std::fs::Permissions::from_mode(0o700)).unwrap();
        config.create_if_missing = true;
        config.engine.cache_bytes = 1024 * 1024;
        let native = NativeCapacityOwner::with_clock(
            latent_core::native_capacity::NativeCapacityLimits::default(),
            Arc::new(SystemActivationClock),
        )
        .unwrap();
        let original = Arc::new(
            native
                .reserve(
                    NativeAdmissionClass::Recovery,
                    NativeReservationRequest {
                        work_bytes: config.startup_memory_bytes(0).unwrap() + 8 * 1024 * 1024,
                        response_bytes: 2 * 1024 * 1024,
                        ..NativeReservationRequest::default()
                    },
                    deadline(),
                )
                .unwrap(),
        );
        let store = Arc::new(
            ProtectedStoreOwner::start_bound_retained_validated_view_with_clock(
                config,
                StoreIdentity::new("original-pending-resume".into()).unwrap(),
                ProtectedStoreStartupMemory::new(&native, original.clone()).unwrap(),
                0,
                |_| Ok(()),
                Arc::new(SystemActivationClock),
            )
            .unwrap()
            .await
            .unwrap(),
        );
        assert!(store.uses_native_capacity(&native));
        let (profile, digest) = store.inspection_profile();
        let digest = format!("sha256:{:x}", latent_core::digest::HexDigest(digest));
        let gate = Arc::new(Gate::new(root.path(), profile, &digest).await);
        let effects = EffectAuthorityOwner::new(16, 4, 100).unwrap();
        effects.publish(rule(&gate, "tests", "business")).unwrap();
        let source = gate.clone();
        let publisher = effects.clone();
        let (effect, request) = store
            .with_store(StoreIoKind::RecoveryWrite, 8 * 1024 * 1024, move |engine| {
                initialize(engine)?;
                let effect = publish(engine, &source, &publisher, payload_bytes, false)?;
                if uncertain_command {
                    publish(engine, &source, &publisher, 0, true)?;
                }
                if attempted {
                    let time = EffectTime {
                        unix_millis: 102,
                        continuity_proven: true,
                    };
                    let epoch = DispatchCatalog::begin_exclusive_epoch(engine, time, None).unwrap();
                    let due = DispatchCatalog::due_page(&engine.snapshot()?, 102, None, 1, 4096)
                        .unwrap()
                        .rows
                        .remove(0);
                    // Actual durable before-send claim; no provider, receipt or retirement proof is invented.
                    let claim = DispatchCatalog::claim(engine, epoch, &due, time).unwrap();
                    assert_eq!(claim.attempt.attempt(), 1);
                    drop(claim);
                }
                let request = quiesce(engine)?;
                Ok((effect, request))
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        Self {
            store,
            original,
            gate,
            request,
            effect,
            effects,
            native,
            root,
        }
    }

    pub async fn rows_digest(&self) -> [u8; 32] {
        self.store
            .with_store(StoreIoKind::RecoveryRead, 8 * 1024 * 1024, |engine| {
                Ok(latent_state::recovery::snapshot::visit_view(
                    &engine.snapshot()?,
                    deadline(),
                    |_, _, _| Ok(()),
                )?
                .digest)
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
    }

    pub async fn effect_payload_digest(&self) -> ([u8; 32], Vec<u8>) {
        let effect = self.effect.clone();
        self.store
            .with_store(StoreIoKind::RecoveryRead, 8 * 1024 * 1024, move |engine| {
                let view = engine.snapshot()?;
                let record = view
                    .get(&latent_effects::dispatch_store::effect_row_key(&effect)?)?
                    .unwrap();
                let mut digest = Sha256::new();
                latent_state::recovery::snapshot::visit_view(
                    &view,
                    deadline(),
                    |header, key, bytes| {
                        if matches!(
                            key.family,
                            Family::Outbox | Family::PayloadReference | Family::Attempt
                        ) || key
                            .key
                            .starts_with(latent_effects::dispatch_store::DUE_PREFIX)
                        {
                            digest.update(header);
                            digest.update(&key.key);
                            digest.update(bytes);
                        }
                        Ok(())
                    },
                )?;
                Ok((digest.finalize().into(), record))
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
    }

    pub async fn resume(
        &self,
        request: NamespaceResumeRequest,
    ) -> Result<(bool, Vec<u8>), StoreError> {
        let original = self.original.clone();
        let gate = self.gate.clone();
        self.store
            .with_store_retaining(
                StoreIoKind::RecoveryWrite,
                8 * 1024 * 1024,
                original.clone() as Arc<dyn std::any::Any + Send + Sync>,
                move |engine| {
                    // Match the real native adapter: domain refusal is an owned result,
                    // never a physical-store health failure or an invented retirement.
                    let outcome = (|| {
                        let view = engine.snapshot()?;
                        let inventory = census(&view)?;
                        let plan =
                            super::super::prepare(&view, &request, &inventory, deadline(), || {
                                gate.check()?;
                                original
                                    .with_live(|| ())
                                    .map_err(|_| StoreError::Unavailable)
                            })?;
                        let result = (plan.replayed(), plan.receipt().encode()?);
                        drop(view);
                        engine
                            .apply_fenced(plan.into_batch(), || {
                                gate.check()?;
                                original
                                    .with_live(|| ())
                                    .map_err(|_| StoreError::Unavailable)
                            })
                            .map_err(|error| match error {
                                latent_state::embedded::FencedStoreError::Store(e)
                                | latent_state::embedded::FencedStoreError::Fence(e) => e,
                            })?;
                        Ok(result)
                    })();
                    Ok(outcome)
                },
            )
            .unwrap()
            .await
            .unwrap()
            .map_err(|error| match error {
                latent_state::protected_store::ProtectedStoreError::Store(e) => e,
                _ => StoreError::Unavailable,
            })?
    }

    pub async fn finish(self) {
        let Self {
            store,
            original,
            gate,
            effects,
            native,
            root,
            ..
        } = self;
        store.close();
        let until = deadline();
        let retired = store
            .drain_async(until, tokio::time::sleep_until(until.into()))
            .unwrap()
            .await;
        assert!(retired.clean && retired.snapshot.physically_retired());
        assert!(store.reap_retired_threads().unwrap() > 0);
        drop(store);
        drop(original);
        drop(gate);
        drop(effects);
        assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
        assert_eq!(native.snapshot().unwrap().recovery.bytes, 0);
        drop(root);
    }
}

fn quiesce(engine: &EmbeddedStore) -> Result<NamespaceResumeRequest, StoreError> {
    let view = engine.snapshot()?;
    let mut namespace = NamespaceRecoveryView::capture(
        &view,
        &TenantId("tests".into()),
        &StateNamespaceId("business".into()),
    )?
    .namespace;
    namespace = namespace
        .transition(namespace.version, &NamespaceTransition::Quiesce, 0)
        .map_err(|_| StoreError::Invalid)?;
    let key = RowKey {
        family: Family::Namespace,
        key: namespace_record_key(&namespace.tenant, &namespace.id).unwrap(),
    };
    let batch = AtomicBatch {
        expectations: vec![],
        mutations: vec![RowMutation {
            key,
            value: Some(namespace.encode().unwrap()),
        }],
    };
    drop(view);
    apply_accounted(engine, batch)?;
    let observed = NamespaceRecoveryView::capture(
        &engine.snapshot()?,
        &TenantId("tests".into()),
        &StateNamespaceId("business".into()),
    )?;
    Ok(NamespaceResumeRequest {
        scope: observed.scope(),
        operation_id: "original-resume".into(),
        operator_id: "operator".into(),
        expected_view: observed.view_token()?,
        review_digest: [7; 32],
    })
}

fn initialize(engine: &EmbeddedStore) -> Result<(), StoreError> {
    let quota = TenantQuota {
        tenant: TenantId("tests".into()),
        limits: TenantUsage {
            state_keys: 32,
            state_bytes: 2 * 1024 * 1024,
            tombstone_keys: 32,
            tombstone_bytes: 2 * 1024 * 1024,
            result_rows: 32,
            result_bytes: 2 * 1024 * 1024,
            effect_rows: 32,
            effect_bytes: 2 * 1024 * 1024,
            payload_bytes: 2 * 1024 * 1024,
            recovery_bytes: 2 * 1024 * 1024,
            metadata_rows: 128,
            metadata_bytes: 2 * 1024 * 1024,
        },
    };
    let view = engine.snapshot()?;
    let installed = latent_state::tenant::prepare_install(&view, &[quota])?;
    drop(view);
    installed.publish(engine, || Ok::<_, ()>(())).unwrap();
    let schema = SchemaId::from_definition(super::super::super::profile::V1).unwrap();
    let namespace = NamespaceRecord::create(
        TenantId("tests".into()),
        StateNamespaceId("business".into()),
        schema.as_str().into(),
        NamespaceQuota::default(),
    )
    .unwrap();
    let history = NamespaceHistory::initial(&namespace);
    apply_accounted(
        engine,
        AtomicBatch {
            expectations: vec![],
            mutations: vec![
                RowMutation {
                    key: RowKey {
                        family: Family::Namespace,
                        key: namespace_record_key(&namespace.tenant, &namespace.id).unwrap(),
                    },
                    value: Some(namespace.encode().unwrap()),
                },
                RowMutation {
                    key: history_key(&history.tenant, &history.namespace, history.incarnation)
                        .unwrap(),
                    value: Some(history.encode().unwrap()),
                },
            ],
        },
    )
}

pub(super) fn apply_accounted(
    engine: &EmbeddedStore,
    mut batch: AtomicBatch,
) -> Result<(), StoreError> {
    let view = engine.snapshot()?;
    let mut delta = latent_state::tenant::TenantDelta::default();
    for row in &batch.mutations {
        if let Some(bytes) = view.get(&row.key)? {
            delta.removed.metadata_rows += 1;
            delta.removed.metadata_bytes += latent_state::tenant::row_charge(&row.key, &bytes)?;
        }
        if let Some(bytes) = &row.value {
            delta.added.metadata_rows += 1;
            delta.added.metadata_bytes += latent_state::tenant::row_charge(&row.key, bytes)?;
        }
    }
    latent_state::tenant::prepare_update(&view, &TenantId("tests".into()), delta)?
        .append_to(&mut batch)?;
    drop(view);
    engine.apply(batch)
}

pub(super) fn rule(gate: &Gate, tenant: &str, namespace: &str) -> EffectRule {
    EffectRule {
        scope: EffectScope {
            tenant: tenant.into(),
            namespace: namespace.into(),
            incarnation: 1,
            publication: gate.publication.clone(),
            binding: "events".into(),
            operation: "event".into(),
        },
        profile: DispatchProfile {
            provider: "events".into(),
            destination: "business".into(),
            adapter: "native-resume-test-v1".into(),
            intent_format: 1,
            payload_format: "value.v1".into(),
            idempotency_profile: "dedup.v1".into(),
        },
        policy_revision: 1,
        credential_epoch: 1,
        protected_credential_reference: "native-test-reference".into(),
        ceiling: DispatchCeiling {
            maximum_payload_bytes: 1024 * 1024,
            maximum_response_bytes: 1024,
            maximum_attempts: 3,
            maximum_age_millis: 60_000,
            attempt_timeout_millis: 30_000,
        },
        enabled: true,
    }
}

pub(super) fn publish(
    engine: &EmbeddedStore,
    gate: &Gate,
    effects: &EffectAuthorityOwner,
    payload_bytes: usize,
    unresolved: bool,
) -> Result<String, StoreError> {
    publish_named(engine, gate, effects, payload_bytes, unresolved, "business")
}

pub(super) fn publish_named(
    engine: &EmbeddedStore,
    gate: &Gate,
    effects: &EffectAuthorityOwner,
    payload_bytes: usize,
    unresolved: bool,
    namespace: &str,
) -> Result<String, StoreError> {
    let observed = NamespaceRecoveryView::capture(
        &engine.snapshot()?,
        &TenantId("tests".into()),
        &StateNamespaceId(namespace.into()),
    )?;
    let caller = latent_capabilities::namespace::CallerScope::derive(
        &InvocationPrincipal {
            subject: "operator".into(),
            kind: PrincipalKind::Administrator,
            tenant: Some(TenantId("tests".into())),
            service: None,
            claims: Metadata::new(),
        },
        &latent_capabilities::namespace::RecoverySelection::OriginalCaller,
    )
    .unwrap();
    let input = AdmissionInput {
        key: CommandKey {
            tenant: "tests".into(),
            namespace: namespace.into(),
            incarnation: "1".into(),
            recovery_scope: caller.scope,
            operation: "commit".into(),
            entity: None,
            client_key: if unresolved {
                "uncertain".into()
            } else {
                "original".into()
            },
        },
        fingerprint: CommandFingerprint {
            input_format: "value.v1".into(),
            input: value(b"original".to_vec()),
            expected_versions: vec![],
        },
        source: source(gate, observed.namespace.state_schema),
        result_read_policy: "visibility-v1".into(),
        result_policy: ResultPolicy {
            replay: ReplayPolicy::Full,
            maximum_result_bytes: 1024,
            result_millis: 60_000,
            identity_millis: 120_000,
            maximum_attempts: 3,
        },
        inbox: None,
        owner_epoch: 1,
    };
    let AdmissionDecision::New(prepared) = PreparedAdmission::prepare(
        &engine.snapshot()?,
        input,
        CommandTime {
            unix_millis: 100,
            continuity_proven: true,
        },
        |_, _| Ok(()),
    )
    .unwrap() else {
        return Err(StoreError::Conflict);
    };
    let claim = prepared.publish(engine, || Ok(())).unwrap();
    if unresolved {
        drop(claim);
        return Ok(String::new());
    }
    let complete = CompleteEnvelope::success(
        &engine.snapshot()?,
        claim,
        None,
        vec![StagedIntent {
            binding: "events".into(),
            operation: "event".into(),
            payload: value(vec![7; payload_bytes]),
            expires_at_millis: None,
        }],
        value(b"committed".to_vec()),
        effects,
        CommandTime {
            unix_millis: 101,
            continuity_proven: true,
        },
    )
    .unwrap();
    let PreparedDisposition::Confirmed { command, .. } = complete.publish(engine, |authorities| {
        let _fence = effects.commit_fence(
            authorities,
            EffectTime {
                unix_millis: 101,
                continuity_proven: true,
            },
        )?;
        Ok(())
    }) else {
        return Err(StoreError::Unavailable);
    };
    Ok(command.effect_ids()[0].hex())
}

fn source(gate: &Gate, state_schema: String) -> SourceIdentity {
    SourceIdentity {
        publication: gate.publication.clone(),
        revision: "original".into(),
        release_digest: gate.component.clone(),
        component_digest: gate.component.clone(),
        contract_digest: format!("sha256:{}", "3".repeat(64)),
        route_generation: 1,
        state_schema,
        input_format: "value.v1".into(),
        result_format: "value.v1".into(),
    }
}

fn value(bytes: Vec<u8>) -> Value {
    Value {
        bytes,
        media_type: "application/octet-stream".into(),
        metadata: vec![],
    }
}

pub(super) fn census(
    view: &latent_state::embedded::ReadView,
) -> Result<RetainedInventory, StoreError> {
    latent_commit::atomic::validate_view(view, |_, _, _| Ok(()))
        .map_err(|_| StoreError::Corrupt)?;
    DispatchCatalog::validate_view(view)?;
    let mut inventory = RetainedInventory::default();
    latent_state::recovery::snapshot::visit_view(view, deadline(), |_, key, bytes| {
        let count = RetainedCount {
            rows: 1,
            bytes: (key.key.len() + bytes.len() + 1) as u64,
            unresolved: 0,
        };
        let entry = if key.family == Family::Outbox {
            let effect = EffectRecord::decode(bytes).map_err(|_| StoreError::Corrupt)?;
            let (identity, version) = effect.durable_format();
            Some((
                RetainedKind::EffectEnvelope,
                format!("{identity}:{version}"),
                u64::from(!effect.disposition().terminal()),
            ))
        } else if matches!(key.family, Family::Command | Family::Attempt)
            && bytes.starts_with(b"LCM\0")
        {
            Some((
                RetainedKind::CommandAttempt,
                "latent.command.v1:1".into(),
                u64::from(
                    CommandRecord::decode(bytes)
                        .map_err(|_| StoreError::Corrupt)?
                        .outcome()
                        == Outcome::Pending,
                ),
            ))
        } else if key.family == Family::Result && bytes.starts_with(b"LCP\0") {
            Some((RetainedKind::SuccessResult, "value.v1".into(), 1))
        } else {
            None
        };
        if let Some((kind, identity, unresolved)) = entry {
            inventory
                .observe(
                    RetainedFormat { kind, identity },
                    RetainedCount {
                        unresolved,
                        ..count
                    },
                )
                .map_err(|_| StoreError::Corrupt)?;
        }
        Ok(())
    })?;
    Ok(inventory)
}
