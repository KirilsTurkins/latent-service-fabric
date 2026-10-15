pub(super) use super::super::super::{
    authority::{Authority, NativeProfile},
    catalog::Catalog,
    codecs::Codecs,
    request::{Action, File},
    selection,
};
pub(super) use crate::config::state::{OperationSettings, StateSettings};
use crate::standalone::effects::ProtectedEffectClock;
pub(super) use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBuffer, NativeBufferClass, NativeCapacityLimits,
        NativeCapacityOwner, NativeReservationRequest,
    },
    InvocationPrincipal, Metadata, PrincipalKind, SystemActivationClock, TenantId,
};
use latent_core::{ActivationClock, ClockSample, PlatformError};
pub(super) use latent_policy::capability::PolicyStore;
pub(super) use latent_state::{
    protected_store::{ProtectedStoreConfig, ProtectedStoreOwner, ProtectedStoreStartupMemory},
    store_identity::{ExternalCheckpoint, StoreIdentity},
    store_io::StoreIoKind,
};
pub(super) use serde_json::json;
use std::os::unix::fs::PermissionsExt;
pub(super) use std::{
    sync::Arc,
    time::{Duration, Instant},
};

struct Clock(Instant);
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(1_100_000, self.0)
    }
    fn monotonic_now(&self) -> Instant {
        self.0
    }
}

pub(super) struct Fixture {
    pub codecs: Arc<Codecs>,
    pub store: Arc<ProtectedStoreOwner>,
    pub policy: Arc<PolicyStore>,
    pub native: NativeCapacityOwner,
    pub settings: StateSettings,
    pub principal: InvocationPrincipal,
    pub(super) root: tempfile::TempDir,
}

impl Fixture {
    pub async fn new(count: usize) -> Self {
        let root = tempfile::tempdir().unwrap();
        let packages = super::configuration::packages(root.path(), count).await;
        let policy = super::configuration::policy(root.path(), &packages);
        let mut config = ProtectedStoreConfig::bounded_linux(root.path().join("state"));
        config.create_if_missing = true;
        config.engine.cache_bytes = 1024 * 1024;
        config.io.resident_bytes = config.engine.cache_bytes as u64 + 64 * 1024;
        private_directory(&config.root);
        private_directory(&root.path().join("snapshots"));
        let settings = super::configuration::settings(root.path(), config.clone());
        let work_bytes = super::configuration::work_bytes(&config, root.path());
        let native = NativeCapacityOwner::with_clock(
            NativeCapacityLimits::default(),
            Arc::new(SystemActivationClock),
        )
        .unwrap();
        let cutoff = Instant::now() + settings.startup_timeout;
        let original = Arc::new(
            native
                .reserve(
                    NativeAdmissionClass::Recovery,
                    NativeReservationRequest {
                        request_bytes: 32 * 1024,
                        work_bytes,
                        response_bytes: 14 * 1024 * 1024,
                    },
                    cutoff,
                )
                .unwrap(),
        );
        assert_eq!(original.original_deadline(), cutoff);
        assert!(original.reserved_bytes() <= settings.native.recovery.maximum_reservation_bytes);
        eprintln!(
            "migration-package-admission: {}",
            json!({
                "requestBytes":original.request_bytes(),"workBytes":original.work_bytes(),
                "responseBytes":original.response_bytes(),"reservedBytes":original.reserved_bytes(),
                "maximumReservationBytes":settings.native.recovery.maximum_reservation_bytes,
                "originalCutoffMillis":settings.startup_timeout.as_millis(),
            })
        );
        let store = Arc::new(
            ProtectedStoreOwner::start_bound_retained_validated_view_with_clock(
                config,
                settings.store_identity.clone(),
                ProtectedStoreStartupMemory::new(&native, original.clone()).unwrap(),
                0,
                |_| Ok(()),
                Arc::new(SystemActivationClock),
            )
            .unwrap()
            .await
            .unwrap(),
        );
        let quotas = crate::standalone::state::validation::quotas(&settings);
        let quota = quotas[0].clone();
        let seed_memory = original
            .reserve_buffer(NativeBufferClass::Work, 8 * 1024 * 1024)
            .unwrap();
        store
            .with_store_retaining(
                StoreIoKind::RecoveryWrite,
                8 * 1024 * 1024,
                original.clone(),
                move |engine| {
                    let _memory = seed_memory;
                    super::seed::populate(engine, quota)
                },
            )
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        let input = super::configuration::operation(
            &packages.publications[0].0,
            &packages.publications[0].1,
        );
        let deployment = super::configuration::deployment(&input);
        let metadata = original
            .reserve_buffer(NativeBufferClass::Work, 1024 * 1024)
            .unwrap();
        let current = selection::capture_current(
            &packages.artifacts,
            &settings,
            input,
            &deployment,
            native.clone(),
            original.clone(),
        )
        .unwrap();
        let mut sources = vec![current.clone()];
        for (publication, component) in packages.publications.iter().skip(1) {
            sources.push(
                selection::capture_decoder(
                    &packages.artifacts,
                    &current,
                    &super::super::super::request::DecoderSource {
                        component_digest: component.0.clone(),
                        publication: publication.id.as_str().into(),
                    },
                )
                .unwrap(),
            );
        }
        let catalog = Catalog::capture(
            &packages.artifacts,
            &sources,
            Vec::new(),
            current.publication().publication().as_str(),
        )
        .unwrap();
        let principal = InvocationPrincipal {
            subject: "operator".into(),
            kind: PrincipalKind::Administrator,
            tenant: Some(TenantId("examples".into())),
            service: None,
            claims: Metadata::new(),
        };
        let (profile, hash) = store.inspection_profile();
        let digest = format!("sha256:{:x}", latent_core::digest::HexDigest(hash));
        super::policy::install(
            &policy,
            &principal,
            current.publication().publication().as_str(),
            profile,
            &digest,
            original.original_deadline(),
        );
        let clock =
            ProtectedEffectClock::admit(Arc::new(Clock(Instant::now())), packages.authority, None)
                .unwrap();
        let action = Action::Snapshot {
            operation_id: "installed-snapshot".into(),
            file: File {
                root: root.path().join("snapshots"),
                name: "installed.snapshot".into(),
            },
        };
        let authority = Authority::retain(
            policy.clone(),
            catalog.primary(),
            &principal,
            &action,
            clock,
            original.original_deadline(),
            &NativeProfile {
                profile,
                digest: &digest,
                epoch: 1,
            },
        )
        .unwrap();
        let selected = current.clone();
        let namespace = store
            .with_store_retaining(
                StoreIoKind::RecoveryRead,
                1024 * 1024,
                original.clone(),
                move |engine| {
                    latent_state::recovery::namespace_resume::NamespaceRecoveryView::capture(
                        &engine.snapshot()?,
                        &selected.target().tenant,
                        &latent_core::StateNamespaceId(selected.namespace().into()),
                    )
                    .map(|observed| observed.namespace)
                },
            )
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        let (runtime, review) = Codecs::identities(&catalog, &authority.actor).unwrap();
        let checkpoint =
            ExternalCheckpoint::initial(settings.store_identity.clone(), 1, 1, 1_100_000).unwrap();
        let codecs = Arc::new(Codecs {
            catalog,
            authority,
            action,
            runtime,
            review,
            namespace,
            identity: settings.store_identity.clone(),
            quotas,
            checkpoint,
            original,
            _metadata: metadata,
        });
        Self {
            codecs,
            store,
            policy,
            native,
            settings,
            principal,
            root,
        }
    }

    pub fn cutoff(&self) -> Instant {
        self.codecs.original.original_deadline()
    }

    pub fn file(&self, name: &str) -> File {
        File {
            root: self.root.path().join("snapshots"),
            name: name.into(),
        }
    }

    pub fn reseal(&mut self, action: Action) {
        let (profile, hash) = self.store.inspection_profile();
        let digest = format!("sha256:{:x}", latent_core::digest::HexDigest(hash));
        let authority = Authority::retain(
            self.policy.clone(),
            self.codecs.catalog.primary(),
            &self.principal,
            &action,
            self.codecs.authority.clock.clone(),
            self.cutoff(),
            &NativeProfile {
                profile,
                digest: &digest,
                epoch: 1,
            },
        )
        .unwrap();
        let codecs = Arc::get_mut(&mut self.codecs).unwrap();
        codecs.authority = authority;
        codecs.action = action;
    }

    pub async fn idle(&self) {
        loop {
            let physical = self.store.snapshot().unwrap();
            if physical.accepted == 0
                && physical.retained_operation_bytes == 0
                && !physical.custody_active
            {
                return;
            }
            assert!(
                Instant::now() < self.cutoff(),
                "same-store physical metadata/custody retirement cutoff"
            );
            tokio::task::yield_now().await;
        }
    }

    pub async fn snapshot(&self) -> NativeBuffer<serde_json::Value> {
        self.idle().await;
        let response = self
            .codecs
            .original
            .reserve_buffer(NativeBufferClass::Response, 2 * 1024 * 1024)
            .unwrap();
        let Action::Snapshot { operation_id, file } = &self.codecs.action else {
            panic!("snapshot purpose required")
        };
        let result = super::super::snapshot(&self.store, self.codecs.clone(), operation_id, file)
            .await
            .unwrap();
        assert_eq!(result["resourcePhysicallyRetired"], true);
        response.attach(result)
    }

    pub async fn stage(
        &mut self,
        snapshot: &serde_json::Value,
        name: &str,
    ) -> NativeBuffer<Result<serde_json::Value, PlatformError>> {
        let selected = self.codecs.clone();
        let expected = self
            .store
            .with_store_retaining(
                StoreIoKind::RecoveryRead,
                1024 * 1024,
                self.codecs.original.clone(),
                move |engine| selected.selected_view(&engine.snapshot()?)?.view_token(),
            )
            .unwrap()
            .await
            .unwrap()
            .unwrap();
        self.idle().await;
        self.reseal(Action::StageMigration {
            operation_id: "installed-migration".into(),
            file: self.file(name),
            expected_view: expected,
            checkpoint_digest: snapshot["snapshotDigest"].as_str().unwrap().into(),
            checkpoint_manifest_digest: snapshot["manifestDigest"].as_str().unwrap().into(),
        });
        let response = self
            .codecs
            .original
            .reserve_buffer(NativeBufferClass::Response, 2 * 1024 * 1024)
            .unwrap();
        response.attach(Box::pin(super::super::migration(&self.store, self.codecs.clone())).await)
    }

    pub async fn finish(self) -> bool {
        self.idle().await;
        self.store.close();
        let retired = self
            .store
            .drain_async(
                self.cutoff(),
                tokio::time::sleep_until(self.cutoff().into()),
            )
            .unwrap()
            .await;
        assert!(retired.clean && retired.snapshot.physically_retired());
        assert_eq!(retired.snapshot.accepted, 0);
        assert!(self.store.reap_retired_threads().unwrap() > 0);
        let policy = self.policy.clone();
        let native = self.native.clone();
        drop(self);
        assert_eq!(policy.retained_read_owners(), 0);
        let snapshot = native.snapshot().unwrap();
        assert_eq!(snapshot.recovery.slots, 0);
        assert_eq!(snapshot.recovery.bytes, 0);
        true
    }
}

pub(super) fn private_directory(path: &std::path::Path) {
    std::fs::create_dir(path).unwrap();
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
}
