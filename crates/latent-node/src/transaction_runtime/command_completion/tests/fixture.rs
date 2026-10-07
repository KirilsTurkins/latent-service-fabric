mod factory;
mod invocation;
mod publication;
mod time;

use super::*;
use latent_artifacts::{DirectoryArtifactRepository, ReleaseUseEligibility};
use latent_core::{ActivationClock, Metadata, SystemActivationClock};
use latent_effects::{
    authority::{EffectAuthorityOwner, EffectTime},
    runtime::{CommandAdmissionSource, DispatcherConfig, DispatcherOwner, EffectTimeSource},
};
use latent_policy::capability::{MutationRequest, PolicyStore, PolicyStoreLimits, RecordKind};
use latent_state::{
    namespace::catalog::{NamespaceCatalog, NamespaceMutation, NamespaceOperationContext},
    protected_store::{ProtectedStoreConfig, ProtectedStoreOwner},
    store_io::StoreIoKind,
};
use std::{fs, os::unix::fs::PermissionsExt, path::PathBuf, sync::Arc, time::Instant};

pub(super) fn schema() -> String {
    format!("sha256:{}", "1".repeat(64))
}

struct ProcessClock;
impl EffectTimeSource for ProcessClock {
    fn observe(&self) -> EffectTime {
        // The fixture owns one uninterrupted real process, original dispatcher
        // epoch and protected root. No restart/time advance is certified here.
        EffectTime {
            unix_millis: SystemActivationClock.sample().unix_millis(),
            continuity_proven: true,
        }
    }
}

pub(in crate::transaction_runtime) struct Owners {
    pub store: Arc<ProtectedStoreOwner>,
    pub policy: Arc<PolicyStore>,
    pub namespaces: Arc<NamespaceCatalog>,
    pub publication: ReleaseUseEligibility,
    pub source: CommandAdmissionSource,
}

pub(in crate::transaction_runtime) struct Fixture {
    _root: tempfile::TempDir,
    _catalog: DirectoryArtifactRepository,
    pub owners: Arc<Owners>,
    pub lanes: Arc<crate::transaction_runtime::EntityCommandLanes>,
    pub waiters: crate::command_waiters::CommandWaiterRegistry,
    pub native: latent_core::native_capacity::NativeCapacityOwner,
    pub cancellations: crate::ActivationCancellationRegistry,
    dispatcher: DispatcherOwner,
}

impl Fixture {
    pub(in crate::transaction_runtime) fn broker(
        &self,
    ) -> latent_capabilities::broker::ActivationCapabilityBroker {
        latent_capabilities::broker::ActivationCapabilityBroker::new(
            self._catalog.lifecycle_authority(),
            Arc::clone(&self.owners.policy),
            Arc::new(SystemActivationClock),
            Default::default(),
        )
        .unwrap()
    }

    pub async fn new() -> Self {
        let base = std::env::var_os("LATENT_STATE_TEST_ROOT")
            .map_or_else(std::env::temp_dir, PathBuf::from);
        let root = tempfile::tempdir_in(base).unwrap();
        fs::set_permissions(root.path(), fs::Permissions::from_mode(0o700)).unwrap();
        let (catalog, _, publication, _, _) = publication::publish(root.path()).await;
        let policy = Arc::new(
            PolicyStore::open(
                &root.path().join("policies"),
                PolicyStoreLimits::default(),
                catalog.lifecycle_authority(),
            )
            .unwrap(),
        );
        factory::install_policy(&policy, &publication);
        let directory = root.path().join("state");
        fs::create_dir(&directory).unwrap();
        fs::set_permissions(&directory, fs::Permissions::from_mode(0o700)).unwrap();
        let mut config = ProtectedStoreConfig::bounded_linux(directory);
        config.create_if_missing = true;
        let store = Arc::new(ProtectedStoreOwner::start(config).unwrap().await.unwrap());
        let native =
            latent_core::native_capacity::NativeCapacityOwner::new(Default::default()).unwrap();
        store.bind_native_capacity(&native).unwrap();
        let namespaces = Arc::new(NamespaceCatalog::new());
        let catalog_owner = Arc::clone(&namespaces);
        store
            .with_store(StoreIoKind::Write, 8192, move |engine| {
                let prepared = catalog_owner
                    .prepare(
                        engine,
                        NamespaceOperationContext {
                            tenant: latent_core::TenantId("a".into()),
                            actor: "operator".into(),
                            operation_id: "installed-entity-namespace".into(),
                        },
                        &NamespaceMutation::Create {
                            id: latent_core::StateNamespaceId("orders".into()),
                            state_schema: schema(),
                            quota: Default::default(),
                        },
                        0,
                    )
                    .unwrap();
                engine.apply(prepared.batch)
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        let effects = EffectAuthorityOwner::new(128, 16, 100).unwrap();
        let dispatcher = DispatcherOwner::start(
            DispatcherConfig::default(),
            Arc::clone(&store),
            effects,
            Vec::new(),
            Arc::new(ProcessClock),
            None,
        )
        .await
        .unwrap();
        dispatcher.bind_native_capacity(&native).unwrap();
        let source = dispatcher.command_admission_source();
        assert!(source.uses_store(&store) && source.uses_native_capacity(&native));
        let lanes = Arc::new(
            crate::transaction_runtime::EntityCommandLanes::new(
                &store,
                crate::transaction_runtime::default_entity_limits(),
            )
            .unwrap(),
        );
        Self {
            _root: root,
            _catalog: catalog,
            owners: Arc::new(Owners {
                store,
                policy,
                namespaces,
                publication,
                source,
            }),
            lanes,
            waiters: crate::command_waiters::CommandWaiterRegistry::new(Default::default())
                .unwrap(),
            native,
            cancellations: Default::default(),
            dispatcher,
        }
    }

    pub fn revoke_policy(&self) {
        let deadline = Instant::now() + WATCHDOG;
        let current = self
            .owners
            .policy
            .get("a", RecordKind::Policy, "state", 65_536, deadline)
            .unwrap();
        let revision = current.value().as_ref().unwrap().revision;
        drop(current);
        self.owners
            .policy
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    kind: RecordKind::Policy,
                    id: "state",
                    operation_id: "installed-entity-revoke",
                    expected_revision: revision,
                    document: None,
                },
                deadline,
                |_| Ok(()),
            )
            .unwrap();
    }

    pub async fn change_namespace_control(&self, return_active: bool) {
        let catalog = Arc::clone(&self.owners.namespaces);
        self.owners
            .store
            .with_store(StoreIoKind::Write, 8192, move |store| {
                for step in 0..=usize::from(return_active) {
                    let view = store.snapshot()?;
                    let before = NamespaceCatalog::read_in(
                        &view,
                        &latent_core::TenantId("a".into()),
                        &latent_core::StateNamespaceId("orders".into()),
                    )
                    .unwrap()
                    .unwrap();
                    let after = if step == 0 {
                        before
                            .record()
                            .transition(
                                before.record().version,
                                &latent_state::namespace::NamespaceTransition::Quiesce,
                                0,
                            )
                            .unwrap()
                    } else {
                        // Exercise an actual control/write returning the same valid
                        // Active metadata. This fixture adds no production Resume
                        // operation; its original captured lifecycle epoch must stay
                        // revoked even when every descriptive field matches again.
                        let mut after = before.record().clone();
                        after.status = latent_state::namespace::NamespaceStatus::Active;
                        after.version.generation = after.version.generation.checked_add(1).unwrap();
                        after.validate().unwrap();
                        after
                    };
                    let expected = before.expectation();
                    let batch = latent_state::embedded::AtomicBatch {
                        expectations: vec![expected.clone()],
                        mutations: vec![latent_state::embedded::RowMutation {
                            key: expected.key,
                            value: Some(after.encode().unwrap()),
                        }],
                    };
                    drop(view);
                    let mut completion = None;
                    store
                        .apply_fenced(batch, || {
                            catalog
                                .lifecycle()
                                .begin_transition(&before, &after, false)
                                .map(|owned| completion = Some(owned))
                        })
                        .unwrap();
                    let view = store.snapshot()?;
                    let committed = NamespaceCatalog::read_in(
                        &view,
                        &latent_core::TenantId("a".into()),
                        &latent_core::StateNamespaceId("orders".into()),
                    )
                    .unwrap()
                    .unwrap();
                    completion.unwrap().resolve(&committed).unwrap();
                }
                Ok(())
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
    }

    pub async fn queued(&self, count: usize) {
        tokio::time::timeout(WATCHDOG, async {
            while self.lanes.snapshot().unwrap().queued != count {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
    }

    pub async fn assert_no_claim(&self) {
        let empty = self
            .owners
            .store
            .with_store(StoreIoKind::Read, 8192, |store| {
                let view = store.snapshot()?;
                Ok(
                    !view.contains_prefix(latent_state::embedded::Family::Command, b"")?
                        && !view.contains_prefix(latent_state::embedded::Family::Attempt, b"")?,
                )
            })
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        assert!(
            empty,
            "refusal must precede durable command and attempt publication"
        );
    }

    pub async fn shutdown(mut self) {
        let deadline = Instant::now() + Duration::from_secs(10);
        let report = self.dispatcher.shutdown(deadline).await.unwrap();
        assert!(report.clean, "{report:?}");
        self.owners.store.close();
        let report = self
            .owners
            .store
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .unwrap()
            .await;
        assert!(
            report.clean && report.snapshot.physically_retired(),
            "{report:?}"
        );
        self.owners.store.reap_retired_threads().unwrap();
        assert!(self.native.snapshot().unwrap().physically_retired());
    }
}
