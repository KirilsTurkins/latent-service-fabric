use super::{compiler, component, runtime};
use latent_artifacts::{
    ArtifactRepository, CapsuleArtifact, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, RawArtifactCacheLimits, ReleaseActor,
    ReleaseActorKind, ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationPrecondition,
};
use latent_core::{PlatformError, ReleaseDigest, TenantId};
use latent_executor::{ExecutionBackend, PreparedActivation, PreparedReadiness};
use latent_wasmtime::{
    AotReceiptCacheLimits, AotResourceSnapshot, NativeAotCacheConfig, NativeAotSettings,
    NativeAotSnapshot, NativeImageLimits, TrustedAotCompilerAuthority, WasmtimeBackend,
    WasmtimeComponentEngineFactory, WasmtimeHostServices,
};
use std::{path::PathBuf, sync::Arc, time::Duration};
use zeroize::Zeroizing;

pub const KEY: [u8; 32] = [73; 32];
pub const OUTPUT: usize = compiler::OUTPUT_BYTES;

pub struct Fixture {
    directory: compiler::Directory,
}

impl Fixture {
    pub fn new() -> Self {
        Self {
            directory: compiler::Directory::new(),
        }
    }
    pub fn catalog(&self) -> Arc<DirectoryArtifactRepository> {
        Arc::new(
            DirectoryArtifactRepository::open(
                self.directory.path().join("catalog"),
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        )
    }
    pub fn blobs(&self) -> PathBuf {
        self.directory.path().join("native-blobs")
    }
    pub fn receipts(&self) -> PathBuf {
        self.directory.path().join("native-receipts")
    }
    pub fn session(&self, repository: Arc<DirectoryArtifactRepository>, key: [u8; 32]) -> Session {
        self.session_with_audit(repository, key, None)
    }
    pub fn audit(&self) -> (latent_audit::AuditHandle, latent_audit::AuditWorker) {
        latent_audit::DirectoryPhase2AuditJournal::open(
            self.directory.path().join("audit"),
            latent_audit::AuditLimits::default(),
        )
        .unwrap()
    }
    pub fn session_with_audit(
        &self,
        repository: Arc<DirectoryArtifactRepository>,
        key: [u8; 32],
        audit: Option<latent_audit::AuditHandle>,
    ) -> Session {
        let process = compiler::limits();
        let authority = TrustedAotCompilerAuthority::new(
            compiler::COMPILER_NAME,
            Zeroizing::new(key),
            process.compiler,
        )
        .unwrap();
        let settings = NativeAotSettings {
            audit,
            executable: compiler::executable().to_path_buf(),
            approved_digest: compiler::executable_digest(),
            authority,
            process,
            cache: NativeAotCacheConfig {
                blob_root: self.blobs(),
                receipt_root: self.receipts(),
                raw: RawArtifactCacheLimits {
                    maximum_entries: 4,
                    maximum_disk_bytes: (4 * OUTPUT) as u64,
                    maximum_metadata_bytes: 64 * 1024,
                    maximum_staging_entries: 1,
                    maximum_staging_bytes: OUTPUT as u64,
                    maximum_read_bytes: OUTPUT as u64,
                    maximum_reads: 1,
                    maximum_pins: 2,
                    maximum_work: 2,
                    maximum_object_bytes: OUTPUT as u64,
                    maximum_recovery_entries: 8,
                },
                receipts: AotReceiptCacheLimits {
                    maximum_entries: 4,
                    maximum_disk_bytes: 32 * 1024,
                    maximum_metadata_bytes: 64 * 1024,
                    maximum_receipt_bytes: 8192,
                    maximum_retained_read_bytes: 8192,
                    maximum_read_owners: 1,
                    maximum_recovery_entries: 8,
                },
            },
            images: NativeImageLimits {
                maximum_images: 2,
                maximum_image_bytes: OUTPUT,
                maximum_total_bytes: 2 * OUTPUT,
            },
        };
        let config = latent_wasmtime::WasmtimeConfig {
            prepared_cache_maximum_entries: 1,
            ..runtime::config()
        };
        let factory = WasmtimeComponentEngineFactory::with_catalog_and_aot(
            config,
            WasmtimeHostServices::default(),
            repository,
            settings,
        )
        .unwrap();
        Session {
            backend: factory.create_backend_instance(),
            factory,
        }
    }
}

pub struct Session {
    pub backend: WasmtimeBackend,
    factory: WasmtimeComponentEngineFactory,
}

impl Session {
    pub async fn prepare(
        &self,
        repository: Arc<DirectoryArtifactRepository>,
        release: &ReleaseDigest,
    ) -> Result<PreparedReadiness, PlatformError> {
        // The real child has its own finite deadline; this bounds the test's
        // control operation as well without retrying failed compilation.
        tokio::time::timeout(
            Duration::from_secs(45),
            self.backend.prepare_ready_from_repository(
                repository,
                self.factory.preparation_key(release.clone()),
            ),
        )
        .await
        .expect("bounded native preparation completed")
    }
    pub fn snapshot(&self) -> NativeAotSnapshot {
        self.backend.native_aot_snapshot().unwrap().unwrap()
    }
    pub async fn prepare_borrowed(
        &self,
        repository: &DirectoryArtifactRepository,
        release: &ReleaseDigest,
    ) -> Result<PreparedActivation, PlatformError> {
        let key = self.factory.preparation_key(release.clone());
        tokio::time::timeout(
            Duration::from_secs(45),
            self.backend.prepare_from_repository(repository, &key),
        )
        .await
        .expect("bounded borrowed native preparation completed")
    }
    pub async fn answer(&self, ready: PreparedReadiness) {
        let active = self.backend.materialize_ready(ready).unwrap();
        self.answer_active(active).await;
    }
    pub async fn answer_active(&self, active: PreparedActivation) {
        let cancellation = runtime::Cancellation::new("native-cache-answer");
        let request = runtime::request(
            active.prepared.descriptor().clone(),
            &cancellation.id,
            component::CONTRACT,
            "answer",
            b"[]",
            runtime::budget(),
        );
        let report = tokio::time::timeout(
            Duration::from_secs(5),
            self.backend
                .invoke_prepared_contained(request, active.prepared, &cancellation),
        )
        .await
        .expect("tiny native invocation completed");
        assert_eq!(
            runtime::returned(report.outcome.unwrap()),
            serde_json::json!([7])
        );
        assert_eq!(self.backend.active_instance_reservations(), 0);
    }
    pub fn idle(&self) {
        let snapshot = self.snapshot();
        assert_eq!(snapshot.producer, AotResourceSnapshot::default());
        assert_eq!(snapshot.images.loading_images, 0);
        assert_eq!(snapshot.images.loading_bytes, 0);
        assert_eq!(snapshot.receipts.read_owners, 0);
        assert_eq!(snapshot.receipts.active_work, 0);
        assert_eq!(snapshot.persistence_failures, 0);
        assert_eq!(self.backend.compiler_snapshot().ready_preparations, 0);
        assert_eq!(self.backend.active_instance_reservations(), 0);
    }
}

pub fn artifact(second: bool) -> CapsuleArtifact {
    let mut bytes = component::bytes();
    if second {
        // A valid custom section changes exact source identity without changing
        // the exported scalar function or requiring another compiler fixture.
        bytes.extend_from_slice(&[0, 3, 1, b'x', 1]);
    }
    let mut artifact = runtime::artifact_bytes(bytes, &[component::CONTRACT]);
    artifact.descriptor.reference.0 = if second {
        "local://native-two"
    } else {
        "local://native-one"
    }
    .into();
    artifact
}

pub async fn publish(repository: &DirectoryArtifactRepository, second: bool) -> ReleaseDigest {
    let artifact = artifact(second);
    let release = artifact.descriptor.release_digest.clone();
    repository.publish(artifact).await.unwrap();
    release
}

pub async fn revoke(repository: &DirectoryArtifactRepository, release: &ReleaseDigest) {
    repository
        .change_release_lifecycle(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId("tests".into())),
                actor: ReleaseActor {
                    subject: "native-cache-test".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: "revoke-native-cache".into(),
                    expected_generation: 1,
                }),
            },
            release,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .await
        .unwrap();
}
