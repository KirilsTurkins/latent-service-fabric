use std::sync::{
    atomic::{AtomicU64, Ordering},
    mpsc, Arc,
};
use std::time::{Duration, Instant};

use latent_artifacts::{ArtifactRepository, DirectoryArtifactRepository, ReleaseUseEligibility};
use latent_core::{BoxFuture, PlatformError, TenantId};
use latent_executor::{ExecutionBackend, PreparationKey, PreparationReadWait, PreparedReadiness};
use latent_policy::supply_chain::{
    SupplyChainAuthority, SupplyChainClock, SupplyChainPolicy, SystemSupplyChainClock,
};

use crate::{
    WasmtimeBackend, WasmtimeComponentEngineFactory, WasmtimeConfig, WasmtimeHostServices,
};

#[path = "../../../../tests/guest_sdk/package.rs"]
mod package;
#[path = "../../../../../latent-packaging/tests/fixtures/mod.rs"]
mod packaging;
#[path = "../../../../../latent-signing/tests/build_provenance/support.rs"]
#[allow(dead_code)]
mod provenance;
#[path = "../../../../../latent-packaging/tests/sbom_association/support.rs"]
#[allow(dead_code)]
mod sbom;

// The shared signing helper's unused catalog constructor requires this config.
mod support {
    pub fn config() -> crate::WasmtimeConfig {
        crate::WasmtimeConfig::default()
    }
}

pub struct Timer;
impl PreparationReadWait for Timer {
    fn now(&self) -> Instant {
        tokio::time::Instant::now().into_std()
    }
    fn wait_until(&self, deadline: Instant) -> BoxFuture<'_, ()> {
        Box::pin(tokio::time::sleep_until(deadline.into()))
    }
}

pub struct Clock(pub AtomicU64);
impl SupplyChainClock for Clock {
    fn now(&self) -> Result<u64, PlatformError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

pub struct Fixture {
    pub backend: WasmtimeBackend,
    pub factory: WasmtimeComponentEngineFactory,
    pub repository: Arc<DirectoryArtifactRepository>,
    pub authority: Arc<SupplyChainAuthority>,
    pub clock: Arc<Clock>,
    pub key: PreparationKey,
    pub eligibility: ReleaseUseEligibility,
    pub policy: serde_json::Value,
    _root: tempfile::TempDir,
}

impl Fixture {
    pub async fn new() -> Self {
        Self::with_services(WasmtimeHostServices::default()).await
    }

    pub async fn with_services(services: WasmtimeHostServices) -> Self {
        let root = tempfile::tempdir().unwrap();
        let input = packaging::capsule(packaging::component::Options::default());
        let inventory = sbom::inventory(&input);
        let bundle =
            latent_packaging::build_package_with_sbom(input, inventory, Default::default())
                .unwrap();
        let release = bundle.layout().component_release().unwrap();
        let signers = package::Signers::new(latent_signing::PROVENANCE_BUILD_TYPE);
        let mut observation = provenance::observation();
        observation.source.repository =
            "https://github.com/KirilsTurkins/latent-service-fabric".into();
        observation.component_digest = release.0.clone();
        observation.component_size = bundle
            .layers()
            .iter()
            .find(|layer| layer.path() == "component.wasm")
            .unwrap()
            .bytes()
            .len() as u64;
        let upload = signers.upload(&bundle, &observation);
        let policy = serde_json::from_slice(&signers.policy_document).unwrap();
        let clock = Arc::new(Clock(AtomicU64::new(SystemSupplyChainClock.now().unwrap())));
        let config = WasmtimeConfig {
            compiler_workers: Some(1),
            maximum_concurrent_preparations: 3,
            ..Default::default()
        };
        let authority = Arc::new(
            SupplyChainAuthority::open_with_runtime(
                &root.path().join("trust"),
                signers.policy,
                clock.clone(),
                5,
                Arc::new(config.detected_runtime_profile().unwrap()),
            )
            .unwrap(),
        );
        let repository = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                root.path().join("catalog"),
                Default::default(),
                Default::default(),
                authority.clone(),
            )
            .unwrap(),
        );
        repository
            .admit_package(&TenantId("tests".into()), upload, &mut |_| Ok(()))
            .await
            .unwrap();
        let eligibility = repository
            .execution_eligibility_selected(&release, None)
            .unwrap()
            .unwrap();
        let factory = WasmtimeComponentEngineFactory::with_catalog(
            config,
            services,
            repository.lifecycle_authority(),
        )
        .unwrap();
        let backend = factory.create_backend_instance();
        let mut key = factory.preparation_key(release);
        key.publication = Some(eligibility.publication().clone());
        Self {
            backend,
            factory,
            repository,
            authority,
            clock,
            key,
            eligibility,
            policy,
            _root: root,
        }
    }

    pub async fn ready(&self) -> PreparedReadiness {
        self.backend
            .prepare_ready_from_repository_with_wait(
                self.repository.clone(),
                self.key.clone(),
                &Timer,
            )
            .await
            .unwrap()
    }

    pub fn idle(&self) {
        assert_eq!(self.backend.active_instance_reservations(), 0);
        assert_eq!(self.backend.resource_snapshot().stores_created, 0);
        let compiler = self.backend.compiler_snapshot();
        assert_eq!(compiler.ready_preparations, 0);
        assert_eq!(compiler.ready_metadata_bytes, 0);
        assert_eq!(compiler.ready_compiled_image_bytes, 0);
        assert_eq!(compiler.waiting_callers, 0);
        assert_eq!(compiler.reserved_document_bytes, 0);
        let cache = self.backend.cache_snapshot();
        assert_eq!(cache.preparing, 0);
        assert_eq!(cache.preparing_source_bytes, 0);
        assert_eq!(cache.preparing_metadata_bytes, 0);
    }

    pub fn replace_policy(&mut self) {
        self.policy["generation"] = serde_json::json!(2);
        let next =
            SupplyChainPolicy::from_json(&serde_json::to_vec(&self.policy).unwrap()).unwrap();
        self.authority.replace_policy(next).unwrap();
    }
}

/// Holds the real production currentness mutex in its existing public fence.
/// Drop always releases before joining, including a failing RED assertion.
pub struct Fence {
    release: Option<mpsc::SyncSender<()>>,
    worker: Option<std::thread::JoinHandle<Result<(), PlatformError>>>,
}
impl Fence {
    pub fn release(mut self) {
        self.release.take().unwrap().send(()).unwrap();
        self.worker.take().unwrap().join().unwrap().unwrap();
    }

    pub fn hold(eligibility: &ReleaseUseEligibility) -> Self {
        let grant = eligibility.admission().unwrap().clone();
        let (entered_send, entered) = mpsc::sync_channel(1);
        let (release, released) = mpsc::sync_channel(1);
        let worker = std::thread::spawn(move || {
            grant.with_current(&mut |_| {
                entered_send.send(()).unwrap();
                released.recv_timeout(Duration::from_secs(10)).unwrap();
                Ok(())
            })
        });
        let owner = Self {
            release: Some(release),
            worker: Some(worker),
        };
        entered.recv_timeout(Duration::from_secs(5)).unwrap();
        owner
    }
}
impl Drop for Fence {
    fn drop(&mut self) {
        if let Some(release) = self.release.take() {
            let _ = release.send(());
        }
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}
