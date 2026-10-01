use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
use latent_capabilities::broker::{
    io::{IoLimits, IoRuntime},
    pools::{ProviderPoolLimits, ProviderPools},
    secrets::TlsCredentialScope,
    ActivationCapabilityBroker, CapabilityBrokerLimits,
};
use latent_commit::atomic::{
    AdmissionDecision, AdmissionInput, AtomicError, CommandAccess, CommandTime, CompleteEnvelope,
    Outcome, PreparedAdmission, PreparedDisposition, ReplayPolicy, ResultPolicy, SourceIdentity,
    StagedIntent,
};
use latent_core::{
    transaction_contract::{CommandFingerprint, CommandKey, Value},
    StateNamespaceId, SystemActivationClock, TenantId,
};
use latent_effects::{
    authority::{
        DispatchCeiling, DurableEffectAuthority, EffectAuthorityOwner, EffectRule, EffectScope,
        EffectTime,
    },
    dispatch::{Disposition, EffectRecord},
    dispatch_store::{effect_row_key, DispatchCatalog},
    runtime::{DeferredEffectAdapter, DispatcherConfig, DispatcherOwner, EffectTimeSource},
};
use latent_nats::{
    deferred::{JetStreamEffectAdapter, JetStreamQualification},
    NatsConfig, NatsCredential, NatsEndpoint, NatsPublisher, TopicMapping,
};
use latent_policy::capability::{PolicyStore, PolicyStoreLimits};
use latent_secrets::{
    LocalSecretStore, SecretLimits, SecretPurpose, SecretSource, SecretSpec, SystemSecretClock,
};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, Family, ReadView, RowKey, RowMutation, StoreError},
    namespace::{
        catalog::NamespaceCatalog, namespace_record_key, NamespacePins, NamespaceQuota,
        NamespaceRecord, NamespaceStatus, NamespaceVersion,
    },
    protected_store::{ProtectedStoreConfig, ProtectedStoreOwner},
    session::{SessionLimits, StateAccess, StateMode, StateScope, StateSession},
    store_io::StoreIoKind,
};
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

pub const WATCHDOG: Duration = Duration::from_secs(20);

pub fn control(operation: &str) -> serde_json::Value {
    let output = std::process::Command::new("python3")
        .args([
            std::env::var("LSF_NATS_TEST_CONTROL").unwrap(),
            std::env::var("LSF_NATS_TEST_PORT").unwrap(),
            std::env::var("LSF_NATS_TEST_PEM").unwrap(),
            operation.into(),
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "owned fixture control failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stdout.len() < 65536);
    serde_json::from_slice(&output.stdout).unwrap()
}

pub fn config() -> NatsConfig {
    NatsConfig {
        format_version: 1,
        endpoint: NatsEndpoint {
            server_name: "127.0.0.1".into(),
            peer: (
                [127, 0, 0, 1],
                std::env::var("LSF_NATS_TEST_PORT")
                    .unwrap()
                    .parse::<u16>()
                    .unwrap(),
            )
                .into(),
            allow_non_public_peer: true,
        },
        public_roots: false,
        extra_roots: vec![fs::read(std::env::var("LSF_NATS_TEST_CA").unwrap()).unwrap()],
        topics: vec![TopicMapping {
            tenant: "tests".into(),
            topic: "updated".into(),
            subject: "lsf.deferred.allowed".into(),
            stream: "DURABLE".into(),
            duplicate_window_millis: 30_000,
        }],
        idempotency_namespace: "lsf-controlled-deferred".into(),
        maximum_payload_bytes: 8192,
        timeout_millis: 5000,
    }
}

pub struct Clock(pub AtomicU64);
impl EffectTimeSource for Clock {
    fn observe(&self) -> EffectTime {
        EffectTime {
            unix_millis: self.0.load(Ordering::Acquire),
            continuity_proven: true,
        }
    }
}

pub async fn call<T: Send + 'static>(
    store: &ProtectedStoreOwner,
    kind: StoreIoKind,
    action: impl FnOnce(&EmbeddedStore) -> T + Send + 'static,
) -> T {
    store
        .with_store(kind, 8 * 1024 * 1024, move |db| Ok(action(db)))
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}

pub fn validate(view: &ReadView) -> Result<(), StoreError> {
    latent_commit::atomic::validate_view(view, |view, key, bytes| {
        if key.family == Family::Namespace {
            return NamespaceCatalog::validate_row(key, bytes).map_err(|_| StoreError::Corrupt);
        }
        match latent_state::session::validate_row(view, key, bytes) {
            Err(StoreError::UnsupportedFormat) => {
                latent_effects::dispatch_store::validate_row(key, bytes)
            }
            answer => answer,
        }
    })?;
    DispatchCatalog::validate_view(view)
}

pub fn value(bytes: &[u8]) -> Value {
    Value {
        bytes: bytes.to_vec(),
        media_type: "text/plain".into(),
        metadata: vec![("event-kind".into(), "updated".into())],
    }
}

pub fn schema() -> String {
    format!("sha256:{}", "4".repeat(64))
}
pub fn scope() -> StateScope {
    StateScope {
        tenant: TenantId("tests".into()),
        namespace: StateNamespaceId("aggregate".into()),
        incarnation: 1,
        state_schema: schema(),
        entity: None,
        mode: StateMode::Command,
    }
}
pub fn state_permission(
    scope: &StateScope,
    _: StateAccess,
) -> Result<(), latent_state::session::StateError> {
    if scope.tenant.0 != "tests" || scope.namespace.0 != "aggregate" || scope.incarnation != 1 {
        Err(latent_state::session::StateError::PermissionDenied)
    } else {
        Ok(())
    }
}
pub fn input(key: &str, epoch: u64) -> AdmissionInput {
    AdmissionInput {
        key: CommandKey {
            tenant: "tests".into(),
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
            result_millis: 60_000,
            identity_millis: 120_000,
            maximum_attempts: 3,
        },
        inbox: None,
        owner_epoch: epoch,
    }
}
pub fn permission(
    _: CommandAccess,
    record: Option<&latent_commit::atomic::CommandRecord>,
) -> Result<(), AtomicError> {
    if record
        .is_some_and(|r| r.key().tenant != "tests" || r.key().recovery_scope != "subject:alice")
    {
        Err(AtomicError::PermissionDenied)
    } else {
        Ok(())
    }
}

fn install_shared_pools(
    root: &Path,
) -> (
    Arc<DirectoryArtifactRepository>,
    Arc<PolicyStore>,
    Arc<ProviderPools>,
) {
    let catalog = Arc::new(
        DirectoryArtifactRepository::open(
            root.join("catalog"),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap(),
    );
    let policies = Arc::new(
        PolicyStore::open(
            &root.join("policies"),
            PolicyStoreLimits::default(),
            catalog.lifecycle_authority(),
        )
        .unwrap(),
    );
    let broker = Arc::new(
        ActivationCapabilityBroker::new(
            catalog.lifecycle_authority(),
            policies.clone(),
            Arc::new(SystemActivationClock),
            CapabilityBrokerLimits::default(),
        )
        .unwrap(),
    );
    let io = Arc::new(IoRuntime::new(IoLimits::default()).unwrap());
    let pools = Arc::new(
        ProviderPools::new(
            broker,
            io,
            tokio::runtime::Handle::current(),
            ProviderPoolLimits::default(),
        )
        .unwrap(),
    );
    (catalog, policies, pools)
}

async fn install_protected_credentials(
    root: &Path,
    pools: Arc<ProviderPools>,
    config: &NatsConfig,
) -> LocalSecretStore {
    let secret_root = root.join("secrets");
    fs::create_dir(&secret_root).unwrap();
    fs::set_permissions(&secret_root, fs::Permissions::from_mode(0o700)).unwrap();
    fs::write(secret_root.join("password"), b"lsf-public-nats-password").unwrap();
    fs::set_permissions(
        secret_root.join("password"),
        fs::Permissions::from_mode(0o600),
    )
    .unwrap();
    let secrets = LocalSecretStore::open(
        pools,
        secret_root,
        SecretLimits::default(),
        vec![],
        Arc::new(SystemSecretClock),
    )
    .unwrap()
    .await
    .unwrap();
    secrets
        .reload(
            0,
            vec![SecretSpec {
                tenant: TenantId("tests".into()),
                reference: "nats-password".into(),
                source: SecretSource::File {
                    name: "password".into(),
                },
                purpose: SecretPurpose::TlsProviderCredential {
                    provider_id: "events".into(),
                    destination: config.endpoint.credential_destination(),
                },
                media_type: "application/octet-stream".into(),
                version: "1".into(),
                expires_at_unix_millis: None,
            }],
        )
        .unwrap()
        .await
        .unwrap();
    secrets
}

async fn initialized_store(root: &Path) -> (ProtectedStoreConfig, Arc<ProtectedStoreOwner>) {
    let store_root = root.join("state");
    fs::create_dir(&store_root).unwrap();
    fs::set_permissions(&store_root, fs::Permissions::from_mode(0o700)).unwrap();
    let mut store_config = ProtectedStoreConfig::bounded_linux(store_root);
    store_config.create_if_missing = true;
    let store = Arc::new(
        ProtectedStoreOwner::start_validated_view(store_config.clone(), 0, validate)
            .unwrap()
            .await
            .unwrap(),
    );
    call(&store, StoreIoKind::Write, |db| {
        let namespace = NamespaceRecord {
            tenant: TenantId("tests".into()),
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
        db.apply(AtomicBatch {
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
    })
    .await;
    (store_config, store)
}

pub struct Fixture {
    pub _root: tempfile::TempDir,
    pub store: Arc<ProtectedStoreOwner>,
    pub store_config: ProtectedStoreConfig,
    pub pools: Arc<ProviderPools>,
    pub secrets: LocalSecretStore,
    pub publisher: NatsPublisher,
    pub authority: EffectAuthorityOwner,
    pub adapter: Arc<JetStreamEffectAdapter>,
    pub clock: Arc<Clock>,
    pub rule: EffectRule,
    pub owner: Option<DispatcherOwner>,
    _catalog: Arc<DirectoryArtifactRepository>,
    _policies: Arc<PolicyStore>,
}

impl Fixture {
    pub async fn new(config: NatsConfig, qualification: JetStreamQualification) -> Self {
        let base = std::env::var_os("LATENT_STATE_TEST_ROOT")
            .map_or_else(std::env::temp_dir, PathBuf::from);
        let root = tempfile::tempdir_in(base).unwrap();
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
        let (catalog, policies, pools) = install_shared_pools(root.path());
        let secrets = install_protected_credentials(root.path(), pools.clone(), &config).await;
        let credential = secrets
            .bind_tls_credential(
                TlsCredentialScope {
                    tenant: TenantId("tests".into()),
                    provider_id: "events".into(),
                    destination: config.endpoint.credential_destination(),
                },
                "nats-password".into(),
            )
            .unwrap();
        let publisher = NatsPublisher::install(
            pools.clone(),
            "events",
            1,
            0,
            config,
            vec![NatsCredential {
                username: Some("publisher".into()),
                secret: credential,
            }],
        )
        .unwrap();
        let clock = Arc::new(Clock(AtomicU64::new(100)));
        let adapter = Arc::new(
            publisher
                .deferred_adapter("tests", "updated", qualification, clock.clone())
                .unwrap(),
        );
        let authority = EffectAuthorityOwner::new(16, 8, 100).unwrap();
        let rule = adapter
            .rule(
                EffectScope {
                    tenant: "tests".into(),
                    namespace: "aggregate".into(),
                    incarnation: 1,
                    publication: "publication".into(),
                    binding: "approved-event".into(),
                    operation: "event".into(),
                },
                1,
                1,
                DispatchCeiling {
                    maximum_payload_bytes: 8192,
                    maximum_response_bytes: 16384,
                    maximum_attempts: 3,
                    maximum_age_millis: 60_000,
                    attempt_timeout_millis: 5000,
                },
            )
            .unwrap();
        authority.publish(rule.clone()).unwrap();
        let (store_config, store) = initialized_store(root.path()).await;
        let mut fixture = Self {
            _root: root,
            store,
            store_config,
            pools,
            secrets,
            publisher,
            authority,
            adapter,
            clock,
            rule,
            owner: None,
            _catalog: catalog,
            _policies: policies,
        };
        fixture.start(true, None).await;
        fixture
    }
    pub async fn start(&mut self, paused: bool, checkpoint: Option<(u64, u64)>) {
        self.owner = Some(
            DispatcherOwner::start(
                DispatcherConfig {
                    start_paused: paused,
                    poll_interval: Duration::from_millis(2),
                    ..DispatcherConfig::default()
                },
                self.store.clone(),
                self.authority.clone(),
                vec![self.adapter.clone() as Arc<dyn DeferredEffectAdapter>],
                self.clock.clone(),
                checkpoint,
            )
            .await
            .unwrap(),
        );
    }
    pub async fn commit(&self, key: &str) -> DurableEffectAuthority {
        let role = self.owner.as_ref().unwrap().command_admission().unwrap();
        let epoch = role.owner_epoch();
        let effects = self.authority.clone();
        let clock = self.clock.clone();
        let key = key.to_owned();
        call(&self.store, StoreIoKind::Write, move |db| {
            let now = clock.observe(); let time = CommandTime { unix_millis: now.unix_millis, continuity_proven: now.continuity_proven };
            let view = db.snapshot().unwrap();
            let AdmissionDecision::New(prepared) = PreparedAdmission::prepare(&view, input(&key, epoch), time, permission).unwrap() else { panic!("new command") };
            let claim = prepared.publish(db, || role.with_current(|_, _| permission(CommandAccess::FinalClaim, None)).unwrap()).unwrap();
            drop(view);
            let view = db.snapshot().unwrap();
            let work = claim.physical_work().unwrap();
            let captured = claim.intent_capture_context().capture(0, StagedIntent { binding: "approved-event".into(), operation: "event".into(), payload: value(b"updated"), expires_at_millis: None }, &effects, time).unwrap();
            let mut session = StateSession::open(&view, scope(), SessionLimits::default(), state_permission).unwrap();
            session.put(&view, b"aggregate/count".to_vec(), value(&1u64.to_le_bytes()), state_permission).unwrap();
            let plan = session.seal(&view, state_permission).unwrap();
            let envelope = CompleteEnvelope::success_captured(&view, claim, Some(plan), vec![captured], value(b"committed"), &effects, time).unwrap();
            let authority = envelope.authorities()[0].clone();
            let disposition = envelope.publish(db, |authorities| role.with_current(|_, now| {
                let guard = effects.commit_fence(authorities, now)?; permission(CommandAccess::FinalDisposition, None)?; drop(guard); Ok(())
            }).unwrap());
            assert!(matches!(disposition, PreparedDisposition::Confirmed { ref command, .. } if command.outcome() == Outcome::Committed));
            drop(view); work.retire(); role.retire(); authority
        }).await
    }
    pub async fn record(&self, effect: &DurableEffectAuthority) -> EffectRecord {
        let key = effect_row_key(&effect.link().effect).unwrap();
        call(&self.store, StoreIoKind::Read, move |db| {
            EffectRecord::decode(&db.snapshot().unwrap().get(&key).unwrap().unwrap()).unwrap()
        })
        .await
    }
    pub async fn settled(
        &self,
        effect: &DurableEffectAuthority,
        wanted: Disposition,
    ) -> EffectRecord {
        tokio::time::timeout(WATCHDOG, async {
            loop {
                let record = self.record(effect).await;
                if record.disposition() == wanted {
                    return record;
                }
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("actual durable disposition did not arrive")
    }
    pub async fn stop_dispatcher(&mut self) {
        let mut owner = self.owner.take().unwrap();
        let report = owner.shutdown(Instant::now() + WATCHDOG).await.unwrap();
        assert!(report.clean, "{report:?}");
        assert!(report.physically_retired);
    }
    pub async fn stop_store(&self) {
        let deadline = Instant::now() + WATCHDOG;
        let report = self
            .store
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .unwrap()
            .await;
        assert!(report.clean, "{report:?}");
        self.store.reap_retired_threads().unwrap();
    }
    pub async fn finish(mut self) {
        self.stop_dispatcher().await;
        self.stop_store().await;
        self.secrets.close();
        assert!(self
            .pools
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .is_clean());
    }
}
