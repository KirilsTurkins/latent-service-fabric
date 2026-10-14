use super::*;
use latent_commit::atomic::{
    AdmissionDecision, AdmissionInput, CommandTime, CompleteEnvelope, PreparedAdmission,
    PreparedDisposition, ReplayPolicy, ResultPolicy, SourceIdentity, StagedIntent,
};
use latent_core::{
    transaction_contract::{CommandFingerprint, CommandKey, Value},
    InvocationPrincipal, Metadata, PrincipalKind, TenantId,
};
use latent_effects::{
    authority::{
        DispatchCeiling, DispatchProfile, EffectAuthorityOwner, EffectRule, EffectScope, EffectTime,
    },
    runtime::{DispatcherConfig, DispatcherOwner},
};
use latent_state::store_io::StoreIoKind;
use std::sync::atomic::{AtomicU64, Ordering};

pub(super) struct FixtureEffect {
    pub fixture: Fixture,
    pub dispatcher: DispatcherOwner,
    pub time: Arc<AtomicU64>,
    pub command: latent_rpc::transaction::v1::CommandSelector,
    pub effect: String,
    pub version: Vec<u8>,
    pub policy_digest: String,
    pub provider: Option<Arc<super::provider::ControlledProvider>>,
}
pub(super) fn operator(subject: &str) -> AuthenticatedInvocationContext {
    AuthenticatedInvocationContext::new(InvocationPrincipal {
        subject: subject.into(),
        kind: PrincipalKind::Administrator,
        tenant: Some(TenantId("a".into())),
        service: None,
        claims: Metadata::from([("latent.node.operator".into(), "true".into())]),
    })
}
fn value(bytes: &[u8]) -> Value {
    Value {
        bytes: bytes.to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: vec![],
    }
}
pub(super) fn mutation(fixture: &Fixture, plan: c::EffectManagementPlan) -> c::MutateStateRequest {
    let original = plan.original.as_ref().unwrap();
    c::MutateStateRequest {
        namespace: Some(fixture.target()),
        operation_id: original.operation_id.clone(),
        mutation: original.mutation,
        record_id: Some(original.effect.as_ref().unwrap().effect_id.clone()),
        expected_version: original.expected_version.clone(),
        expected_policy_digest: original.expected_policy_digest.clone(),
        reason: original.reason.clone(),
        effect_plan: Some(plan),
    }
}
impl FixtureEffect {
    pub async fn related_command(&self) -> (latent_rpc::transaction::v1::CommandSelector, String) {
        let binding = &self.fixture.backend.0.bindings[0];
        let authority = EffectAuthorityOwner::new(16, 4, 100).unwrap();
        authority.publish(rule(binding)).unwrap();
        let mut input = admission(binding);
        input.key.client_key = "related-effect-command".into();
        let command = latent_rpc::transaction::v1::CommandSelector {
            namespace: self.fixture.target().namespace,
            operation: input.key.operation.clone(),
            entity: None,
            client_key: input.key.client_key.clone(),
            shared_recovery_scope: None,
        };
        let (effect, _) = publish(&self.fixture, input, authority).await;
        (command, effect)
    }

    pub async fn rows(&self) -> Vec<(latent_state::embedded::RowKey, Vec<u8>)> {
        self.fixture
            .store
            .with_store(StoreIoKind::RecoveryRead, 1024 * 1024, |engine| {
                let view = engine.snapshot()?;
                let mut rows = Vec::new();
                for family in [
                    latent_state::embedded::Family::Command,
                    latent_state::embedded::Family::Outbox,
                ] {
                    rows.extend(view.scan(family, &[], 128, 1024 * 1024)?);
                }
                Ok(rows)
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
    }

    pub fn request(&self, operation: &str) -> c::PlanEffectMutationRequest {
        c::PlanEffectMutationRequest {
            effect: Some(latent_rpc::transaction::v1::GetEffectRequest {
                profile: Some(contract::current_profile()),
                command: Some(self.command.clone()),
                effect_id: self.effect.clone(),
                authorization_publication: self.fixture.target().authorization_publication,
            }),
            operation_id: operation.into(),
            mutation: c::StateMutationKind::TerminateEffect as i32,
            expected_version: self.version.clone(),
            expected_policy_digest: self.policy_digest.clone(),
            reason: "stop future local dispatch".into(),
            retry_delay_millis: 0,
        }
    }
    pub async fn disposition(&self) -> latent_effects::dispatch::Disposition {
        let effect = self.effect.clone();
        self.fixture
            .store
            .with_store(StoreIoKind::RecoveryRead, 4096, move |engine| {
                let bytes = engine
                    .snapshot()?
                    .get(&latent_effects::dispatch_store::effect_row_key(&effect).unwrap())?
                    .unwrap();
                Ok(latent_effects::dispatch::EffectRecord::decode(&bytes)
                    .unwrap()
                    .disposition())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
    }
    pub async fn finish(&mut self) {
        let report = self.dispatcher.shutdown(deadline()).await.unwrap();
        assert!(report.clean);
        self.fixture.finish().await;
    }
    pub async fn settle_original(&mut self) {
        let expected = self.provider.as_ref().unwrap().original;
        self.dispatcher.resume().unwrap();
        let finished = tokio::time::timeout(Duration::from_secs(5), async {
            loop {
                let effect = self.effect.clone();
                let (disposition, version) = self
                    .fixture
                    .store
                    .with_store(StoreIoKind::RecoveryRead, 4096, move |engine| {
                        let bytes = engine
                            .snapshot()?
                            .get(&latent_effects::dispatch_store::effect_row_key(&effect).unwrap())?
                            .unwrap();
                        Ok((
                            latent_effects::dispatch::EffectRecord::decode(&bytes)
                                .unwrap()
                                .disposition(),
                            latent_effects::dispatch::effect_record_version(&bytes)
                                .unwrap()
                                .to_vec(),
                        ))
                    })
                    .unwrap()
                    .await
                    .unwrap()
                    .unwrap();
                let current = self.dispatcher.snapshot().unwrap();
                if disposition == expected
                    && current.active_jobs == 0
                    && current.physical_owners == 0
                {
                    self.version = version;
                    break;
                }
                tokio::task::yield_now().await;
            }
        })
        .await;
        assert!(
            finished.is_ok(),
            "provider control did not retire: disposition={:?}, sends={}, snapshot={:?}",
            self.disposition().await,
            self.provider.as_ref().unwrap().sends.load(Ordering::SeqCst),
            self.dispatcher.snapshot().unwrap()
        );
        self.dispatcher.pause();
        assert_eq!(
            self.provider.as_ref().unwrap().sends.load(Ordering::SeqCst),
            1
        );
    }
}
pub(super) async fn setup() -> FixtureEffect {
    setup_with_provider(None).await
}
pub(super) async fn setup_with_provider(
    original: Option<latent_effects::dispatch::Disposition>,
) -> FixtureEffect {
    let fixture = Fixture::new(true).await;
    let authority = EffectAuthorityOwner::new(16, 4, 100).unwrap();
    setup_fixture(fixture, authority, original, false, false).await
}
pub(super) fn reader(subject: &str) -> AuthenticatedInvocationContext {
    AuthenticatedInvocationContext::new(InvocationPrincipal {
        subject: subject.into(),
        kind: PrincipalKind::User,
        tenant: Some(TenantId("a".into())),
        service: None,
        claims: Metadata::new(),
    })
}
pub(super) async fn setup_with_recovery() -> FixtureEffect {
    setup_recovery(false, None).await
}
pub(super) async fn setup_with_maximum_recovery() -> FixtureEffect {
    setup_recovery(true, None).await
}
pub(super) async fn setup_with_recovery_provider(
    original: latent_effects::dispatch::Disposition,
) -> FixtureEffect {
    setup_recovery(false, Some(original)).await
}
async fn setup_recovery(
    maximum: bool,
    original: Option<latent_effects::dispatch::Disposition>,
) -> FixtureEffect {
    let authority = EffectAuthorityOwner::new(16, 4, 100).unwrap();
    let fixture = Fixture::with_effect_authority(&authority).await;
    setup_fixture(fixture, authority, original, true, maximum).await
}
async fn setup_fixture(
    mut fixture: Fixture,
    authority: EffectAuthorityOwner,
    original: Option<latent_effects::dispatch::Disposition>,
    recovery: bool,
    maximum: bool,
) -> FixtureEffect {
    drop(fixture.create().await);
    if recovery {
        install_reader_policy(&mut fixture);
    }
    let binding = &fixture.backend.0.bindings[0];
    let mut rule = rule(binding);
    if maximum {
        rule.ceiling.maximum_payload_bytes = latent_core::transaction_contract::VALUE_BYTES as u64;
        rule.ceiling.maximum_attempts = 128;
    }
    let time = Arc::new(AtomicU64::new(if maximum { 1000 } else { 102 }));
    let provider = original.map(|original| {
        Arc::new(super::provider::ControlledProvider::new(
            rule.profile.clone(),
            Arc::clone(&time),
            original,
        ))
    });
    authority.publish(rule).unwrap();
    let mut input = admission(binding);
    if recovery {
        input.key.recovery_scope = latent_capabilities::namespace::CallerScope::derive(
            reader("alice").principal(),
            &latent_capabilities::namespace::RecoverySelection::OriginalCaller,
        )
        .unwrap()
        .scope;
    }
    let command = latent_rpc::transaction::v1::CommandSelector {
        namespace: fixture.target().namespace,
        operation: input.key.operation.clone(),
        entity: None,
        client_key: input.key.client_key.clone(),
        shared_recovery_scope: None,
    };
    let (effect, version) = publish_profile(&fixture, input, authority.clone(), maximum).await;
    let checkpoint = if maximum {
        assert_eq!(fixture.store.snapshot().unwrap().physical_owners, 0);
        fixture
            .store
            .with_store(StoreIoKind::RecoveryRead, 8192, |engine| {
                latent_effects::dispatch_store::DispatchCatalog::owner_checkpoint(
                    &engine.snapshot()?,
                )
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
    } else {
        None
    };
    let clock = Arc::clone(&time);
    let dispatcher = DispatcherOwner::start(
        DispatcherConfig {
            start_paused: true,
            ..DispatcherConfig::default()
        },
        Arc::clone(&fixture.store),
        authority,
        provider
            .iter()
            .map(|provider| {
                Arc::new(super::provider::Adapter(Arc::clone(provider)))
                    as Arc<dyn latent_effects::runtime::DeferredEffectAdapter>
            })
            .collect(),
        Arc::new(move || EffectTime {
            unix_millis: clock.load(Ordering::SeqCst),
            continuity_proven: true,
        }),
        checkpoint,
    )
    .await
    .unwrap();
    dispatcher
        .bind_native_capacity(&fixture.admission.native)
        .unwrap();
    Arc::get_mut(&mut fixture.backend.0).unwrap().dispatcher = Some(dispatcher.management_port());
    if recovery {
        fixture.backend = fixture
            .backend
            .with_command_recovery(dispatcher.command_admission_source())
            .unwrap();
    }
    let policy_digest = namespace_policy_digest(&fixture).await;
    FixtureEffect {
        fixture,
        dispatcher,
        time,
        command,
        effect,
        version,
        policy_digest,
        provider,
    }
}

fn install_reader_policy(fixture: &mut Fixture) {
    let mut document = fixture.document.clone();
    for subject in ["alice", "bob"] {
        let mut rule = document["rules"][0].clone();
        rule["id"] = format!("{subject}-effect-reader").into();
        rule["principals"] = serde_json::json!([{"kind":"user","subject":subject}]);
        rule["operations"] = serde_json::json!(["inspect-effect"]);
        rule["resources"]["scopes"][0]["recoveryScope"] =
            latent_capabilities::namespace::CallerScope::derive(
                reader(subject).principal(),
                &latent_capabilities::namespace::RecoverySelection::OriginalCaller,
            )
            .unwrap()
            .scope
            .into();
        document["rules"].as_array_mut().unwrap().push(rule);
    }
    fixture.update(Some(&document), "effect-reader-policy");
    fixture.document = document;
}

async fn namespace_policy_digest(fixture: &Fixture) -> String {
    let inspection = fixture
        .backend
        .execute_state(context("alice"), fixture.target().into())
        .await
        .unwrap();
    let contract::Response::InspectNamespace(namespace) = &inspection.response else {
        panic!("namespace");
    };
    let policy_digest = namespace
        .namespace
        .as_ref()
        .unwrap()
        .namespace_policy_digest
        .clone();
    drop(inspection);
    policy_digest
}

fn rule(binding: &StateManagementBinding) -> EffectRule {
    EffectRule {
        scope: EffectScope {
            tenant: "a".into(),
            namespace: "orders".into(),
            incarnation: 1,
            publication: binding.publication.id.as_str().into(),
            binding: "events".into(),
            operation: "event".into(),
        },
        profile: DispatchProfile {
            provider: "events".into(),
            destination: "orders".into(),
            adapter: "qualified-test-v1".into(),
            intent_format: 1,
            payload_format: "value.v1".into(),
            idempotency_profile: "dedup.v1".into(),
        },
        policy_revision: 1,
        credential_epoch: 1,
        protected_credential_reference: "events-secret".into(),
        ceiling: DispatchCeiling {
            maximum_payload_bytes: 1024,
            maximum_response_bytes: 1024,
            maximum_attempts: 3,
            maximum_age_millis: 60_000,
            attempt_timeout_millis: 30_000,
        },
        enabled: true,
    }
}

fn admission(binding: &StateManagementBinding) -> AdmissionInput {
    let caller = latent_capabilities::namespace::CallerScope::derive(
        operator("alice").principal(),
        &latent_capabilities::namespace::RecoverySelection::OriginalCaller,
    )
    .unwrap();
    AdmissionInput {
        key: CommandKey {
            tenant: "a".into(),
            namespace: "orders".into(),
            incarnation: "1".into(),
            recovery_scope: caller.scope,
            operation: "create-order".into(),
            entity: None,
            client_key: "effect-command".into(),
        },
        fingerprint: CommandFingerprint {
            input_format: "value.v1".into(),
            input: value(b"original"),
            expected_versions: vec![],
        },
        source: SourceIdentity {
            publication: binding.publication.id.as_str().into(),
            revision: "revision-original".into(),
            release_digest: binding.component.0.clone(),
            component_digest: binding.component.0.clone(),
            contract_digest: format!("sha256:{}", "3".repeat(64)),
            route_generation: 1,
            state_schema: binding.state_schema.clone(),
            input_format: "value.v1".into(),
            result_format: "value.v1".into(),
        },
        result_read_policy: binding.result_policy.clone(),
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

async fn publish(
    fixture: &Fixture,
    input: AdmissionInput,
    effects: EffectAuthorityOwner,
) -> (String, Vec<u8>) {
    publish_profile(fixture, input, effects, false).await
}
async fn publish_profile(
    fixture: &Fixture,
    input: AdmissionInput,
    effects: EffectAuthorityOwner,
    maximum: bool,
) -> (String, Vec<u8>) {
    fixture
        .store
        .with_store(
            StoreIoKind::RecoveryWrite,
            if maximum {
                WORK_BYTES as u64
            } else {
                1024 * 1024
            },
            move |engine| {
                let time = CommandTime {
                    unix_millis: 100,
                    continuity_proven: true,
                };
                let AdmissionDecision::New(prepared) =
                    PreparedAdmission::prepare(&engine.snapshot()?, input, time, |_, _| Ok(()))
                        .unwrap()
                else {
                    panic!("new command required");
                };
                let claim = prepared.publish(engine, || Ok(())).unwrap();
                let envelope = CompleteEnvelope::success(
                    &engine.snapshot()?,
                    claim,
                    None,
                    vec![StagedIntent {
                        binding: "events".into(),
                        operation: "event".into(),
                        payload: if maximum {
                            Value {
                                bytes: vec![7; latent_core::transaction_contract::VALUE_BYTES],
                                media_type: "a"
                                    .repeat(latent_core::transaction_contract::MEDIA_TYPE_BYTES),
                                metadata: (0..32)
                                    .map(|index| (format!("key{index:05}"), "v".repeat(248)))
                                    .collect(),
                            }
                        } else {
                            value(b"original intent")
                        },
                        expires_at_millis: None,
                    }],
                    value(b"committed result"),
                    &effects,
                    CommandTime {
                        unix_millis: 101,
                        continuity_proven: true,
                    },
                )
                .unwrap();
                let PreparedDisposition::Confirmed { command, .. } =
                    envelope.publish(engine, |authorities| {
                        let _fence = effects.commit_fence(
                            authorities,
                            EffectTime {
                                unix_millis: 101,
                                continuity_proven: true,
                            },
                        )?;
                        Ok(())
                    })
                else {
                    panic!("actual commit required");
                };
                let effect = command.effect_ids()[0].hex();
                if maximum {
                    maximum_history(engine, &effect);
                }
                let bytes = engine
                    .snapshot()?
                    .get(&latent_effects::dispatch_store::effect_row_key(&effect).unwrap())?
                    .unwrap();
                let version = latent_effects::dispatch::effect_record_version(&bytes)
                    .unwrap()
                    .to_vec();
                Ok((effect, version))
            },
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}

fn maximum_history(engine: &latent_state::embedded::EmbeddedStore, effect: &str) {
    use latent_effects::{
        dispatch::{AttemptReceipt, Disposition, RetryProof},
        dispatch_store::DispatchCatalog,
    };
    let time = |unix_millis| EffectTime {
        unix_millis,
        continuity_proven: true,
    };
    let epoch = DispatchCatalog::begin_exclusive_epoch(engine, time(102), None).unwrap();
    for attempt in 1..=128 {
        let now = 102 + attempt * 2;
        let due = DispatchCatalog::due_page(&engine.snapshot().unwrap(), now, None, 1, 4096)
            .unwrap()
            .rows
            .remove(0);
        assert_eq!(due.effect, effect);
        let claim = DispatchCatalog::claim(engine, epoch, &due, time(now)).unwrap();
        // No provider is invoked. These are real durable before-send known
        // nonexecution receipts, not inferred physical retirement or delivery.
        DispatchCatalog::complete(
            engine,
            epoch,
            &claim.attempt,
            AttemptReceipt {
                disposition: Disposition::KnownFailed,
                reason: "f".repeat(128),
                provider_receipt: None,
                observed_at_millis: now + 1,
            },
            (attempt < 128).then_some((RetryProof::KnownNonexecution, 1)),
            time(now + 1),
        )
        .unwrap();
    }
}
