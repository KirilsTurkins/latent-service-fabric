mod history;
mod invocation;
mod policy;
mod publication;

use super::*;
use latent_artifacts::{DirectoryArtifactRepository, ReleaseUseEligibility};
use latent_core::transaction_contract::{CommandKey, Value};
use latent_effects::{
    authority::EffectTime,
    runtime::{DispatcherConfig, DispatcherOwner, EffectTimeSource},
};
use latent_policy::capability::{MutationRequest, PolicyStore, RecordKind};
use latent_state::{
    namespace::catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
    protected_store::{ProtectedStoreConfig, ProtectedStoreOwner},
    store_io::StoreIoKind,
};
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::PathBuf,
    sync::Arc,
    time::{Duration, Instant},
};

pub(super) fn value(bytes: &[u8]) -> Value {
    Value {
        bytes: bytes.to_vec(),
        media_type: "application/octet-stream".into(),
        metadata: Vec::new(),
    }
}
fn schema() -> String {
    format!("sha256:{}", "1".repeat(64))
}
struct Clock {
    millis: std::sync::atomic::AtomicU64,
    continuity: std::sync::atomic::AtomicBool,
}
impl EffectTimeSource for Clock {
    fn observe(&self) -> EffectTime {
        // This fixture positively owns one uninterrupted process. Production
        // startup uses the admitted continuity/checkpoint owner.
        EffectTime {
            unix_millis: self.millis.load(std::sync::atomic::Ordering::SeqCst),
            continuity_proven: self.continuity.load(std::sync::atomic::Ordering::SeqCst),
        }
    }
}

pub(super) struct Fixture {
    _root: tempfile::TempDir,
    _catalog: DirectoryArtifactRepository,
    pub effects: EffectAuthorityOwner,
    pub time: Arc<dyn CommandTimeSource>,
    store: Arc<ProtectedStoreOwner>,
    pub(super) owners: Arc<TransactionAdmissionOwners>,
    pub(super) installation: Arc<TransactionInstallation>,
    publication: ReleaseUseEligibility,
    dispatcher: DispatcherOwner,
    policy: Arc<PolicyStore>,
    namespaces: Arc<NamespaceCatalog>,
    cancellations: crate::ActivationCancellationRegistry,
    registrations: std::sync::Mutex<Vec<crate::CancellationRegistration>>,
    pub native: latent_core::native_capacity::NativeCapacityOwner,
    clock: Arc<Clock>,
}
impl Fixture {
    pub async fn new() -> Self {
        Self::with_native_limits(latent_core::native_capacity::NativeCapacityLimits::default())
            .await
    }

    pub async fn with_native_limits(
        limits: latent_core::native_capacity::NativeCapacityLimits,
    ) -> Self {
        let base = std::env::var_os("LATENT_STATE_TEST_ROOT")
            .map_or_else(std::env::temp_dir, PathBuf::from);
        let root = tempfile::tempdir_in(base).unwrap();
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
        let (catalog, metadata, publication, deployment, declaration) =
            publication::publish(root.path()).await;
        let (policy, binding) = policy::create(root.path(), &catalog, &publication);
        let policy = Arc::new(policy);
        let state_root = root.path().join("state");
        fs::create_dir(&state_root).unwrap();
        fs::set_permissions(&state_root, fs::Permissions::from_mode(0o700)).unwrap();
        let mut config = ProtectedStoreConfig::bounded_linux(state_root);
        config.create_if_missing = true;
        let store = Arc::new(ProtectedStoreOwner::start(config).unwrap().await.unwrap());
        let native = latent_core::native_capacity::NativeCapacityOwner::new(limits).unwrap();
        store.bind_native_capacity(&native).unwrap();
        let namespaces = Arc::new(NamespaceCatalog::new());
        Self::create_namespace(&store, &namespaces).await;
        let effects = EffectAuthorityOwner::new(128, 16, 100).unwrap();
        let clock = Arc::new(Clock {
            millis: std::sync::atomic::AtomicU64::new(1000),
            continuity: std::sync::atomic::AtomicBool::new(true),
        });
        let dispatcher = DispatcherOwner::start(
            DispatcherConfig::default(),
            Arc::clone(&store),
            effects.clone(),
            Vec::new(),
            clock.clone(),
            None,
        )
        .await
        .unwrap();
        dispatcher.bind_native_capacity(&native).unwrap();
        let command = dispatcher.command_admission_source();
        let time: Arc<dyn CommandTimeSource> =
            Arc::new(command_role::CommandClock(command.clone()));
        let owners = Arc::new(
            TransactionAdmissionOwners::new(
                Arc::clone(&store),
                Arc::clone(&namespaces),
                Arc::clone(&policy),
                command,
            )
            .unwrap(),
        );
        let installation = Arc::new(
            TransactionInstallation::new(
                metadata,
                declaration,
                &deployment,
                publication.clone(),
                Arc::new(binding),
                None,
                latent_capabilities::namespace::RecoverySelection::OriginalCaller,
                "visibility-v1".into(),
                latent_commit::atomic::ResultPolicy {
                    replay: latent_commit::atomic::ReplayPolicy::Full,
                    maximum_result_bytes: 4096,
                    result_millis: 10_000,
                    identity_millis: 20_000,
                    maximum_attempts: 3,
                },
            )
            .unwrap(),
        );
        Self {
            _root: root,
            _catalog: catalog,
            effects,
            time,
            store,
            owners,
            installation,
            publication,
            dispatcher,
            policy,
            namespaces,
            cancellations: crate::ActivationCancellationRegistry::default(),
            registrations: std::sync::Mutex::new(Vec::new()),
            native,
            clock,
        }
    }

    pub fn set_result_time(&self, millis: u64, continuity: bool) {
        self.clock
            .millis
            .store(millis, std::sync::atomic::Ordering::SeqCst);
        self.clock
            .continuity
            .store(continuity, std::sync::atomic::Ordering::SeqCst);
    }
    async fn create_namespace(store: &ProtectedStoreOwner, namespaces: &Arc<NamespaceCatalog>) {
        let namespaces = Arc::clone(namespaces);
        store
            .with_store(StoreIoKind::Write, 8192, move |store| {
                // Trusted fixture bootstrap, followed by real caller authorization.
                let plan = namespaces
                    .prepare(
                        store,
                        NamespaceOperationContext {
                            tenant: latent_core::TenantId("a".into()),
                            actor: "operator".into(),
                            operation_id: "namespace-create".into(),
                        },
                        &NamespaceMutation::Create {
                            id: latent_core::StateNamespaceId("orders".into()),
                            state_schema: schema(),
                            quota: latent_state::namespace::NamespaceQuota::default(),
                        },
                        0,
                    )
                    .unwrap();
                store.apply(plan.batch)
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
    }
    pub async fn rows(&self, family: Family) -> usize {
        self.store
            .with_store(StoreIoKind::Read, 128 * 1024, move |store| {
                Ok(store.snapshot()?.scan(family, b"", 256, 128 * 1024)?.len())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
    }
    pub async fn inspect(
        &self,
        key: CommandKey,
    ) -> (
        latent_commit::atomic::CommandRecord,
        Option<latent_commit::atomic::DurableResult>,
    ) {
        let namespace = self
            .store
            .with_store(StoreIoKind::Read, 8192, |store| {
                Ok(NamespaceCatalog::read_in(
                    &store.snapshot()?,
                    &latent_core::TenantId("a".into()),
                    &latent_core::StateNamespaceId("orders".into()),
                )
                .unwrap()
                .unwrap())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        let (_, envelope, budget) = self.invocation(true, "inspect-policy");
        let auth = policy::inspection(self, namespace, &envelope, &budget);
        let time = self.time.sample();
        let result = self
            .store
            .with_store(StoreIoKind::Read, 128 * 1024, move |store| {
                Ok(latent_commit::atomic::inspect(
                    &store.snapshot()?,
                    &key,
                    time,
                    |_, record| {
                        if record
                            .is_some_and(|record| record.result_read_policy() != "visibility-v1")
                        {
                            return Err(latent_commit::atomic::AtomicError::PermissionDenied);
                        }
                        auth.authorize("read-result", 0, 0, || Ok(()))
                            .map_err(|_| latent_commit::atomic::AtomicError::PermissionDenied)
                    },
                ))
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        result
    }
    pub fn revoke(&self) {
        let deadline = Instant::now() + Duration::from_secs(10);
        let current = self
            .policy
            .get("a", RecordKind::Policy, "state", 64 * 1024, deadline)
            .unwrap();
        let expected_revision = current.value().as_ref().unwrap().revision;
        drop(current);
        self.policy
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    kind: RecordKind::Policy,
                    id: "state",
                    operation_id: "revoke",
                    expected_revision,
                    document: None,
                },
                deadline,
                |_| Ok(()),
            )
            .unwrap();
    }
    pub async fn shutdown(mut self) {
        let deadline = Instant::now() + Duration::from_secs(10);
        let report = self.dispatcher.shutdown(deadline).await.unwrap();
        assert!(report.clean, "{report:?}");
        let report = self
            .store
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .unwrap()
            .await;
        assert!(report.clean, "{report:?}");
        assert!(report.snapshot.physically_retired());
        self.store.reap_retired_threads().unwrap();
    }
}
