//! Explicit gate input: freshly exported signed bytes and a real compiler binary.
//! This composes existing authorities; it generates no keys or fake admission proof.

#[path = "../../../../../../crates/latent-wasmtime/tests/generic_backend/support.rs"]
#[allow(
    dead_code,
    reason = "reuse the existing real invocation request and cancellation fixture"
)]
mod runtime;

use latent_artifacts::{
    package::{inspect_package, PackageLimits},
    AdmissionEvidence, AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, PackageAdmissionUpload,
    ReleaseLiveEligibility,
};
use latent_core::{CapabilityId, PlatformError, PlatformErrorCode, ReleaseDigest, TenantId};
use latent_executor::{BoundImport, ExecutionBackend, PreparedActivation, PreparedReadiness};
use latent_policy::supply_chain::{SupplyChainAuthority, SupplyChainClock, SupplyChainPolicy};
use latent_wasmtime::{
    AotProcessLimits, AotReceiptCacheLimits, NativeAotCacheConfig, NativeAotSettings,
    NativeAotSnapshot, NativeImageLimits, TrustedAotCompilerAuthority, WasmtimeBackend,
    WasmtimeComponentEngineFactory, WasmtimeConfig, WasmtimeHostServices,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File},
    io::Read,
    path::{Component, Path, PathBuf},
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc,
    },
    time::Duration,
};
use tempfile::TempDir;
use zeroize::Zeroizing;

const OUTPUT_BYTES: usize = 2 * 1024 * 1024;
const DOCUMENT_BYTES: usize = 256 * 1024;
const COMPONENT_BYTES: usize = 64 * 1024;
const CONTRACT: &str = "tests:packaging/api@1.0.0";
const CLOCK: &str = "latent:clock/monotonic@0.1.0";

struct Clock(AtomicU64);
impl SupplyChainClock for Clock {
    fn now(&self) -> Result<u64, PlatformError> {
        Ok(self.0.load(Ordering::Acquire))
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Cause {
    ProofAge,
    PolicyExpiry,
    PublisherRevocation,
}
impl Cause {
    fn expected(self) -> (PlatformErrorCode, &'static str) {
        match self {
            Self::ProofAge => (PlatformErrorCode::StateConflict, "signature-stale-proof"),
            Self::PolicyExpiry => (
                PlatformErrorCode::PermissionDenied,
                "admission-policy-expired",
            ),
            Self::PublisherRevocation => {
                (PlatformErrorCode::PermissionDenied, "admission-grant-stale")
            }
        }
    }
}

struct Fixture {
    directory: TempDir,
    input: PathBuf,
    policy: Value,
    now: u64,
    compiler: PathBuf,
    compiler_digest: [u8; 32],
}
impl Fixture {
    fn new(cause: Cause) -> Self {
        let input = PathBuf::from(
            std::env::var_os("LSF_OPERATOR_FIXTURE_ROOT")
                .expect("explicit fresh operator fixture directory"),
        );
        let compiler = PathBuf::from(
            std::env::var_os("LSF_AOT_COMPILER")
                .expect("explicit current latent-aot-compiler executable"),
        );
        assert!(input.is_absolute() && compiler.is_absolute());
        let metadata: Value =
            serde_json::from_slice(&read(&input, "fixture.json", DOCUMENT_BYTES)).unwrap();
        assert_eq!(metadata["formatVersion"], 1);
        assert_eq!(metadata["tenant"], "tests");
        assert_eq!(metadata["contract"], CONTRACT);
        let now = metadata["verifiedAtUnixSeconds"]
            .as_str()
            .unwrap()
            .parse::<u64>()
            .unwrap();
        let mut policy: Value =
            serde_json::from_slice(&read(&input, "policy.json", DOCUMENT_BYTES)).unwrap();
        assert_eq!(policy["publisher"]["maxProofAgeSeconds"], 600);
        assert_eq!(policy["builder"]["maxProofAgeSeconds"], 600);
        if cause == Cause::PolicyExpiry {
            // Only the outer trusted policy expires. Signatures, child trust,
            // and the 600-second proof age remain current at now+61.
            policy["validUntil"] = json!(now + 60);
        }
        let file = fs::symlink_metadata(&compiler).unwrap();
        assert!(file.is_file() && file.len() <= 256 * 1024 * 1024);
        let mut executable = File::open(&compiler).unwrap();
        let mut hash = Sha256::new();
        let mut chunk = [0_u8; 16 * 1024];
        loop {
            let count = executable.read(&mut chunk).unwrap();
            if count == 0 {
                break;
            }
            hash.update(&chunk[..count]);
        }
        Self {
            directory: tempfile::tempdir().unwrap(),
            input,
            policy,
            now,
            compiler,
            compiler_digest: hash.finalize().into(),
        }
    }

    fn authority(&self, clock: Arc<Clock>) -> Arc<SupplyChainAuthority> {
        Arc::new(
            SupplyChainAuthority::open_with_runtime(
                &self.directory.path().join("trust"),
                SupplyChainPolicy::from_json(&serde_json::to_vec(&self.policy).unwrap()).unwrap(),
                clock,
                5,
                Arc::new(config().detected_runtime_profile().unwrap()),
            )
            .unwrap(),
        )
    }

    fn repository(&self, authority: Arc<SupplyChainAuthority>) -> Arc<DirectoryArtifactRepository> {
        Arc::new(
            DirectoryArtifactRepository::open_enforced(
                self.directory.path().join("catalog"),
                DirectoryArtifactRepositoryConfig {
                    max_index_entries: 4,
                    max_page_size: 4,
                    max_recovery_directories: 4,
                    max_component_bytes: COMPONENT_BYTES,
                    ..DirectoryArtifactRepositoryConfig::default()
                },
                AdmissionStorageLimits::default(),
                authority,
            )
            .unwrap(),
        )
    }

    fn upload(&self) -> PackageAdmissionUpload {
        let root = self.input.join("blue/package");
        let manifest = read(&root, "manifest.json", DOCUMENT_BYTES);
        let configuration = read(&root, "config.json", DOCUMENT_BYTES);
        let layout = inspect_package(&manifest, &configuration, PackageLimits::default()).unwrap();
        assert!(layout.config().layers.len() <= 16);
        let mut remaining = 2 * 1024 * 1024;
        let layers = layout
            .config()
            .layers
            .iter()
            .map(|layer| {
                let bytes = read(
                    &root.join("layers"),
                    &layer.path,
                    remaining.min(DOCUMENT_BYTES),
                );
                remaining = remaining.checked_sub(bytes.len()).unwrap();
                (layer.path.clone(), bytes)
            })
            .collect();
        let root = self.input.join("blue/evidence");
        let index: Value = serde_json::from_slice(&read(&root, "index.json", 16 * 1024)).unwrap();
        assert_eq!(index["formatVersion"], 1);
        assert_eq!(index["packageDigest"], layout.digest().to_string());
        PackageAdmissionUpload {
            manifest,
            configuration,
            layers,
            signatures: evidence(&root, &index["signatures"]),
            provenance: evidence(&root, &index["provenance"]),
            sboms: evidence(&root, &index["sboms"]),
        }
    }

    fn invalidate(&mut self, cause: Cause, clock: &Clock, authority: &SupplyChainAuthority) {
        match cause {
            Cause::ProofAge => clock.0.store(self.now + 601, Ordering::Release),
            Cause::PolicyExpiry => clock.0.store(self.now + 61, Ordering::Release),
            Cause::PublisherRevocation => {
                self.policy["generation"] = json!(self.policy["generation"].as_u64().unwrap() + 1);
                self.policy["publisherRevocations"]["generation"] = json!(
                    self.policy["publisherRevocations"]["generation"]
                        .as_u64()
                        .unwrap()
                        + 1
                );
                self.policy["publisherRevocations"]["revokedPublishers"] = json!(["publisher-a"]);
                authority
                    .replace_policy(
                        SupplyChainPolicy::from_json(&serde_json::to_vec(&self.policy).unwrap())
                            .unwrap(),
                    )
                    .unwrap();
            }
        }
        // A successfully renewed clock lease is an independent prerequisite;
        // none of the following failures may be lease-uncovered/unavailable.
        authority.renew_clock_lease().unwrap();
    }
}

fn read(root: &Path, relative: &str, maximum: usize) -> Vec<u8> {
    assert!(relative.len() <= 240);
    let mut path = root.to_path_buf();
    let components: Vec<_> = Path::new(relative).components().collect();
    assert!(!components.is_empty() && components.len() <= 8);
    assert!(fs::symlink_metadata(root).unwrap().is_dir());
    for part in components {
        let Component::Normal(part) = part else {
            panic!("fixture path must be a descendant")
        };
        path.push(part);
        assert!(!fs::symlink_metadata(&path)
            .unwrap()
            .file_type()
            .is_symlink());
    }
    let metadata = fs::symlink_metadata(&path).unwrap();
    assert!(metadata.is_file() && metadata.len() <= maximum as u64);
    let mut bytes = Vec::new();
    File::open(path)
        .unwrap()
        .take(maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .unwrap();
    assert!(bytes.len() <= maximum);
    bytes
}

fn evidence(root: &Path, entries: &Value) -> Vec<AdmissionEvidence> {
    let entries = entries.as_array().unwrap();
    assert!(entries.len() <= 1);
    entries
        .iter()
        .map(|entry| AdmissionEvidence {
            manifest: read(root, entry["manifest"].as_str().unwrap(), 4096),
            configuration: read(root, entry["configuration"].as_str().unwrap(), 2),
            payload: read(root, entry["payload"].as_str().unwrap(), DOCUMENT_BYTES),
        })
        .collect()
}

fn config() -> WasmtimeConfig {
    WasmtimeConfig {
        maximum_component_bytes: COMPONENT_BYTES,
        maximum_memory_bytes: 4 * 1024 * 1024,
        maximum_fuel: 1_000_000,
        prepared_cache_maximum_entries: 1,
        maximum_concurrent_preparations: 1,
        compiler_workers: Some(1),
        maximum_ready_preparations: 4,
        ..WasmtimeConfig::default()
    }
}

struct Session {
    backend: WasmtimeBackend,
    factory: WasmtimeComponentEngineFactory,
}
impl Session {
    fn new(fixture: &Fixture, repository: Arc<DirectoryArtifactRepository>) -> Self {
        let mut process = AotProcessLimits::default();
        process.compiler.maximum_output_bytes = OUTPUT_BYTES;
        process.resources.maximum_jobs = 1;
        process.resources.maximum_outputs = 1;
        process.resources.maximum_native_bytes = OUTPUT_BYTES;
        process.resources.maximum_input_bytes = COMPONENT_BYTES;
        process.resources.maximum_document_bytes = 2 * 1024 * 1024;
        process.maximum_component_bytes = COMPONENT_BYTES;
        process.maximum_metadata_bytes = DOCUMENT_BYTES;
        process.maximum_document_bytes = DOCUMENT_BYTES;
        let settings = NativeAotSettings {
            audit: None,
            executable: fixture.compiler.clone(),
            approved_digest: fixture.compiler_digest,
            authority: TrustedAotCompilerAuthority::new(
                "lsf-isolated-aot-v1",
                Zeroizing::new([83; 32]),
                process.compiler,
            )
            .unwrap(),
            process,
            cache: NativeAotCacheConfig {
                blob_root: fixture.directory.path().join("native-blobs"),
                receipt_root: fixture.directory.path().join("native-receipts"),
                raw: latent_artifacts::RawArtifactCacheLimits {
                    maximum_entries: 2,
                    maximum_disk_bytes: (2 * OUTPUT_BYTES) as u64,
                    maximum_metadata_bytes: 64 * 1024,
                    maximum_staging_entries: 1,
                    maximum_staging_bytes: OUTPUT_BYTES as u64,
                    maximum_read_bytes: OUTPUT_BYTES as u64,
                    maximum_reads: 1,
                    maximum_pins: 2,
                    maximum_work: 2,
                    maximum_object_bytes: OUTPUT_BYTES as u64,
                    maximum_recovery_entries: 4,
                },
                receipts: AotReceiptCacheLimits {
                    maximum_entries: 2,
                    maximum_disk_bytes: 16 * 1024,
                    maximum_metadata_bytes: 64 * 1024,
                    maximum_receipt_bytes: 8192,
                    maximum_retained_read_bytes: 8192,
                    maximum_read_owners: 1,
                    maximum_recovery_entries: 5,
                },
            },
            images: NativeImageLimits {
                maximum_images: 2,
                maximum_image_bytes: OUTPUT_BYTES,
                maximum_total_bytes: 2 * OUTPUT_BYTES,
            },
        };
        let factory = WasmtimeComponentEngineFactory::with_catalog_and_aot(
            config(),
            WasmtimeHostServices::default(),
            repository,
            settings,
        )
        .unwrap();
        Self {
            backend: factory.create_backend_instance(),
            factory,
        }
    }

    async fn prepare(
        &self,
        repository: Arc<DirectoryArtifactRepository>,
        release: &ReleaseDigest,
    ) -> Result<PreparedReadiness, PlatformError> {
        tokio::time::timeout(
            Duration::from_secs(45),
            self.backend.prepare_ready_from_repository(
                repository,
                self.factory.preparation_key(release.clone()),
            ),
        )
        .await
        .unwrap()
    }

    fn snapshot(&self) -> NativeAotSnapshot {
        self.backend.native_aot_snapshot().unwrap().unwrap()
    }

    async fn invoke(&self, active: PreparedActivation) {
        let cancellation = runtime::Cancellation::new("current-trust-warm-call");
        let request = invocation(&active, &cancellation);
        let result = tokio::time::timeout(
            Duration::from_secs(5),
            self.backend
                .invoke_prepared_contained(request, active.prepared, &cancellation),
        )
        .await
        .unwrap();
        assert_eq!(runtime::returned(result.outcome.unwrap()), json!([7]));
        assert_eq!(self.backend.active_instance_reservations(), 0);
    }

    fn close(self) {
        drop(self.backend);
        self.factory.shutdown().unwrap();
    }
}

fn invocation(
    active: &PreparedActivation,
    cancellation: &runtime::Cancellation,
) -> latent_executor::ExecutionRequest {
    let mut budget = runtime::budget();
    budget.cpu_fuel = 1_000_000;
    budget.memory_bytes = 4 * 1024 * 1024;
    budget.wall_time_limit_millis = Some(5000);
    let mut request = runtime::request(
        active.prepared.descriptor().clone(),
        &cancellation.id,
        CONTRACT,
        "inspect",
        br#"[{"count":7,"outcome":{"ok":{"case":"empty"}}}]"#,
        budget,
    );
    request.imports = vec![BoundImport {
        capability: CapabilityId("clock".into()),
        contract: CLOCK.into(),
        opaque_handle: "gate-clock-binding".into(),
    }];
    request
}

fn denied(error: &PlatformError, cause: Cause) {
    let (code, message) = cause.expected();
    assert_eq!(error.code, code, "{error:?}");
    assert_eq!(error.message, message);
    assert!(!error.retryable);
}

async fn no_new_preparation(
    session: &Session,
    repository: &Arc<DirectoryArtifactRepository>,
    release: &ReleaseDigest,
    cause: Cause,
) {
    denied(
        &session
            .prepare(repository.clone(), release)
            .await
            .err()
            .unwrap(),
        cause,
    );
    denied(
        &session
            .backend
            .prepare_from_repository(
                repository.as_ref(),
                &session.factory.preparation_key(release.clone()),
            )
            .await
            .err()
            .unwrap(),
        cause,
    );
}

#[allow(
    clippy::too_many_lines,
    reason = "one deterministic warm, cutover, and retained-capability schedule"
)]
async fn schedule(cause: Cause) {
    let mut fixture = Fixture::new(cause);
    let clock = Arc::new(Clock(AtomicU64::new(fixture.now)));
    let authority = fixture.authority(clock.clone());
    let repository = fixture.repository(authority.clone());
    let admitted = repository
        .admit_package(&TenantId("tests".into()), fixture.upload(), &mut |_| Ok(()))
        .await
        .unwrap();
    let release = admitted.descriptor.release_digest;
    let session = Session::new(&fixture, repository.clone());
    let ready = session.prepare(repository.clone(), &release).await.unwrap();
    session
        .invoke(session.backend.materialize_ready(ready).unwrap())
        .await;
    let retained = session.prepare(repository.clone(), &release).await.unwrap();
    let active = session
        .backend
        .materialize_ready(session.prepare(repository.clone(), &release).await.unwrap())
        .unwrap();
    let before = session.snapshot();
    assert_eq!(before.isolated_compilations, 1);
    assert_eq!(before.images.loader_attempts, 1);
    assert_eq!(before.persistence_failures, 0);
    let stores = session.backend.resource_snapshot().stores_created;
    let cancellation = runtime::Cancellation::new("held-before-trust-cutover");
    // Construct before cutover, poll only afterwards: a queued/ready activation
    // is not an already accepted in-flight invocation.
    let pending = session.backend.invoke_prepared_contained(
        invocation(&active, &cancellation),
        active.prepared,
        &cancellation,
    );
    fixture.invalidate(cause, &clock, &authority);
    denied(
        &session.backend.materialize_ready(retained).err().unwrap(),
        cause,
    );
    denied(&pending.await.outcome.unwrap_err(), cause);
    no_new_preparation(&session, &repository, &release, cause).await;
    let after = session.snapshot();
    assert_eq!(after.isolated_compilations, before.isolated_compilations);
    assert_eq!(after.images.loader_attempts, before.images.loader_attempts);
    assert_eq!(session.backend.resource_snapshot().stores_created, stores);
    assert_eq!(session.backend.active_instance_reservations(), 0);
    assert_eq!(session.backend.compiler_snapshot().ready_preparations, 0);
    session.close();

    // The same persisted native receipt/key cannot revive this catalog's old
    // proof. Opening the cache performs no native loading or source refresh.
    let reopened = Session::new(&fixture, repository.clone());
    no_new_preparation(&reopened, &repository, &release, cause).await;
    assert_eq!(reopened.snapshot().isolated_compilations, 0);
    assert_eq!(reopened.snapshot().images.loader_attempts, 0);
    reopened.close();

    if cause != Cause::ProofAge {
        // Fresh catalog recovery may legitimately renew proof-age-only grants;
        // expired policy and revoked publishers must instead retain denied history.
        let scope = LifecycleScope::Tenant(TenantId("tests".into()));
        let previous = repository
            .get_release_lifecycle(&scope, &release)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(previous.eligibility, ReleaseLiveEligibility::Denied);
        drop(repository);
        authority.retire();
        drop(authority);
        clock.0.fetch_add(6, Ordering::AcqRel); // beyond the durable restart lease floor
        let authority = fixture.authority(clock.clone());
        let repository = fixture.repository(authority.clone());
        let recovered = repository
            .get_release_lifecycle(&scope, &release)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(recovered.record, previous.record);
        assert_eq!(recovered.eligibility, ReleaseLiveEligibility::Denied);
        assert!(repository
            .historical_execution_snapshot(&release)
            .await
            .is_ok());
        let native = Session::new(&fixture, repository.clone());
        let failure = native.prepare(repository, &release).await.err().unwrap();
        assert_eq!(failure.code, PlatformErrorCode::PermissionDenied);
        assert_eq!(native.snapshot().isolated_compilations, 0);
        assert_eq!(native.snapshot().images.loader_attempts, 0);
        native.close();
    }
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires fresh LSF_OPERATOR_FIXTURE_ROOT and real LSF_AOT_COMPILER"]
async fn real_proof_age_expiry_denies_retained_native_work_with_a_current_clock_lease() {
    Box::pin(schedule(Cause::ProofAge)).await;
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires fresh LSF_OPERATOR_FIXTURE_ROOT and real LSF_AOT_COMPILER"]
async fn real_policy_expiry_denies_native_work_and_recovers_readable_negative_history() {
    Box::pin(schedule(Cause::PolicyExpiry)).await;
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires fresh LSF_OPERATOR_FIXTURE_ROOT and real LSF_AOT_COMPILER"]
async fn real_publisher_revocation_denies_native_work_without_any_registry_event() {
    Box::pin(schedule(Cause::PublisherRevocation)).await;
}
