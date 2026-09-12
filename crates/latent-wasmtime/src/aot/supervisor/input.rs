//! A single sealed fetch retained through cache lookup, compilation and loading.

use super::{process, AotCompilationJob, CompletedAotJob};
use crate::aot::seal::{AuthenticatedAotReceipt, AuthenticatedNative};
use crate::aot::{invalid, mismatch, AotCompatibilityKey, TrustedAotOutput};
use latent_artifacts::{ArtifactPreparationIdentity, CapsuleArtifact, ReleaseUseEligibility};
use latent_core::PlatformError;
use wasmtime::Engine;

/// No public constructor can pair caller metadata with a real catalog token.
/// The job's source/work allowances drop after the actual retained artifact.
pub(crate) struct AotPreparedInput {
    artifact: CapsuleArtifact,
    key: AotCompatibilityKey,
    authentication: Option<ArtifactPreparationIdentity>,
    job: AotCompilationJob,
}

#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
pub(super) mod tests {
    use super::*;
    use crate::aot::ownership::Budget;
    use crate::aot::supervisor::{AotProcessLimits, IsolatedAotCompiler, Owner, State};
    use crate::aot::{TrustedAotCompilerAuthority, ValidatedAotProfile};
    use latent_artifacts::{
        content_digest, ArtifactDescriptor, ArtifactRepository, DirectoryArtifactRepository,
        DirectoryArtifactRepositoryConfig, LifecycleScope, ReleaseActor, ReleaseActorKind,
        ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
        ReleaseOperationPrecondition,
    };
    use latent_core::{ArtifactReference, ContractId, Metadata, ReleaseDigest, TenantId};
    use latent_manifest::{
        ContractExport, JsonManifestCodec, ManifestCodec, ManifestValidator,
        Phase1ManifestValidator,
    };
    use std::{
        future::Future,
        path::PathBuf,
        pin::Pin,
        sync::{
            atomic::{AtomicBool, AtomicU64, Ordering},
            Arc,
        },
        task::{Context, Poll, Waker},
    };
    use zeroize::Zeroizing;

    struct Directory(PathBuf);
    impl Drop for Directory {
        fn drop(&mut self) {
            std::fs::remove_dir_all(&self.0).unwrap();
        }
    }

    /// A real sealed catalog input. Only tests substitute the process stage:
    /// native bytes below come from the pinned Wasmtime precompiler itself.
    pub(crate) struct Fixture {
        compiler: IsolatedAotCompiler,
        repository: Arc<DirectoryArtifactRepository>,
        release: ReleaseDigest,
        directory: Directory,
    }
    impl Fixture {
        pub(crate) fn new() -> Self {
            static NEXT: AtomicU64 = AtomicU64::new(0);
            let directory = Directory(std::env::temp_dir().join(format!(
                    "lsf-native-input-test-{}-{}-{}",
                    std::process::id(),
                    std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .unwrap()
                        .as_nanos(),
                    NEXT.fetch_add(1, Ordering::Relaxed),
                )));
            std::fs::create_dir(&directory.0).unwrap();
            let repository = Arc::new(
                DirectoryArtifactRepository::open(
                    &directory.0,
                    DirectoryArtifactRepositoryConfig::default(),
                )
                .unwrap(),
            );
            let bytes = b"\0asm\x0d\0\x01\0".to_vec();
            let release = content_digest(&bytes);
            let mut manifest = JsonManifestCodec::default()
                .decode_capsule(include_bytes!(
                    "../../../../../examples/echo-contract/capsule.json"
                ))
                .unwrap();
            manifest.component_digest = release.clone();
            manifest.metadata.name = "tests/native-input".into();
            manifest.metadata.tenant = Some(TenantId("tests".into()));
            manifest.world = ContractId("tests:native-input/service@0.1.0".into());
            manifest.minimum_fabric_version = "0.1.0-alpha.0".into();
            manifest.imports.clear();
            // The catalog requires a declared export. These lower-level loader
            // tests intentionally do not run runtime surface validation.
            manifest.exports = vec![ContractExport {
                contract: ContractId("tests:native-input/api@0.1.0".into()),
            }];
            Phase1ManifestValidator::new()
                .validate_capsule(&manifest)
                .expect("the native-input fixture must satisfy catalog manifest validation");
            let artifact = CapsuleArtifact {
                descriptor: ArtifactDescriptor {
                    reference: ArtifactReference("local://native-input".into()),
                    release_digest: release.clone(),
                    media_type: "application/vnd.wasm.component.v1+wasm".into(),
                    size_bytes: bytes.len() as u64,
                    publisher: None,
                    layers: Vec::new(),
                    annotations: Metadata::new(),
                },
                manifest,
                contracts: Vec::new(),
                component_bytes: bytes,
            };
            ready(repository.publish(artifact)).unwrap();
            let mut limits = AotProcessLimits::default();
            limits.compiler.maximum_output_bytes = 1024 * 1024;
            limits.resources.maximum_jobs = 2;
            limits.maximum_metadata_bytes = 64 * 1024;
            limits.maximum_document_bytes = 64 * 1024;
            let profile = ValidatedAotProfile::from_config(
                &crate::WasmtimeConfig::default(),
                limits.compiler,
            )
            .unwrap();
            let state = Arc::new(State {
                executable: PathBuf::from("/bin/false"),
                compiler_digest: [4; 32],
                sandbox_digest: [5; 32],
                bootstrap: profile.bootstrap().unwrap().into_boxed_slice(),
                profile,
                authority: TrustedAotCompilerAuthority::new(
                    "compiler",
                    Zeroizing::new([7; 32]),
                    limits.compiler,
                )
                .unwrap(),
                limits,
                budget: Budget::new(limits.resources).unwrap(),
                closed: AtomicBool::new(false),
            });
            Self {
                compiler: IsolatedAotCompiler {
                    owner: Arc::new(Owner { state }),
                },
                repository,
                release,
                directory,
            }
        }
        pub(crate) fn read(&self) -> AotPreparedInput {
            self.compiler
                .reserve(
                    self.repository.clone().owned_preparation_source().unwrap(),
                    &self.release,
                )
                .unwrap()
                .read()
                .unwrap()
        }
        pub(crate) fn engine(&self) -> Engine {
            let state = &self.compiler.owner.state;
            crate::aot::profile::engine_from_bootstrap(&state.bootstrap, state.limits.compiler)
                .unwrap()
                .0
        }
        pub(crate) fn output(&self, input: &AotPreparedInput, engine: &Engine) -> TrustedAotOutput {
            let bytes = engine
                .precompile_component(&input.artifact.component_bytes)
                .unwrap();
            let budget = Budget::new(self.compiler.owner.state.limits.resources).unwrap();
            let (work, permit) = budget.reserve(1, 1, bytes.capacity()).unwrap();
            drop(work);
            self.compiler
                .owner
                .state
                .authority
                .seal_completed(CompletedAotJob::fixture(input.key.clone(), bytes, permit))
                .unwrap()
        }
        pub(crate) fn revoke(&self) {
            ready(self.repository.change_release_lifecycle(
                ReleaseMutationContext {
                    scope: LifecycleScope::Tenant(TenantId("tests".into())),
                    actor: ReleaseActor {
                        subject: "native-test".into(),
                        kind: ReleaseActorKind::Host,
                    },
                    operation: Some(ReleaseOperationPrecondition {
                        operation_id: "revoke".into(),
                        expected_generation: 1,
                    }),
                },
                &self.release,
                ReleaseLifecycleAction::Revoke,
                ReleaseLifecycleReason::OperatorRevocation,
                &mut |_| Ok(()),
            ))
            .unwrap();
        }
        pub(crate) fn raw_bytes(&self, bytes: &[u8]) -> latent_artifacts::RawArtifactBytes {
            use latent_artifacts::{RawArtifactCache, RawArtifactCacheLimits, RawArtifactKey};
            use sha2::{Digest, Sha256};
            let cache = RawArtifactCache::open(
                self.directory.0.join("raw-cache"),
                RawArtifactCacheLimits::default(),
            )
            .unwrap();
            let key = RawArtifactKey::Blob(crate::aot::blob(Sha256::digest(bytes).into()));
            cache
                .reserve_write(key.clone(), bytes.len() as u64)
                .unwrap()
                .publish(bytes)
                .unwrap();
            cache
                .try_pin(&key)
                .unwrap()
                .unwrap()
                .reserve_read(bytes.len() as u64)
                .unwrap()
                .read_verified()
                .unwrap()
        }
        fn remove_component_after_fetch(&self) {
            std::fs::remove_file(
                self.directory
                    .0
                    .join("releases")
                    .join(self.release.0.strip_prefix("sha256:").unwrap())
                    .join("component.wasm"),
            )
            .unwrap();
        }
    }
    fn ready<T>(mut future: Pin<Box<dyn Future<Output = T> + Send + '_>>) -> T {
        match future
            .as_mut()
            .poll(&mut Context::from_waker(Waker::noop()))
        {
            Poll::Ready(value) => value,
            Poll::Pending => panic!("directory operation must be synchronous"),
        }
    }

    #[test]
    fn checked_input_is_retained_after_one_fetch_without_a_second_disk_read() {
        let fixture = Fixture::new();
        let input = fixture.read();
        fixture.remove_component_after_fetch();
        let engine = fixture.engine();
        let output = fixture.output(&input, &engine);
        let proof = input.authenticate_output(&output).unwrap();
        assert_eq!(proof.bytes(), output.output());
        let receipt = output.receipt().to_vec();
        let restored = input.authenticate_receipt(&receipt).unwrap();
        drop(receipt);
        assert_eq!(restored.output_size(), output.output().len());
    }

    #[test]
    fn failed_compile_is_one_shot_and_refunds_native_allowance_without_dropping_input() {
        let fixture = Fixture::new();
        let mut input = fixture.read();
        input.job.control.cancel();
        assert_eq!(
            input.compile().unwrap_err().code,
            latent_core::PlatformErrorCode::Cancelled
        );
        assert!(input.job.output.is_none());
        assert_eq!(fixture.compiler.snapshot().jobs, 1);
        assert_eq!(fixture.compiler.snapshot().native_bytes, 0);
        assert_eq!(
            input.compile().unwrap_err().code,
            latent_core::PlatformErrorCode::InvalidArgument
        );
        drop(input);
        assert_eq!(fixture.compiler.snapshot().jobs, 0);
    }

    #[test]
    fn retained_input_does_not_keep_a_retired_producer_authorizing() {
        let fixture = Fixture::new();
        let input = fixture.read();
        assert_eq!(
            fixture
                .compiler
                .shutdown(std::time::Duration::ZERO)
                .unwrap_err()
                .code,
            latent_core::PlatformErrorCode::DeadlineExceeded
        );
        assert_eq!(
            input.check().unwrap_err().code,
            latent_core::PlatformErrorCode::Cancelled
        );
    }
}

impl AotPreparedInput {
    pub(super) fn new(
        artifact: CapsuleArtifact,
        key: AotCompatibilityKey,
        authentication: Option<ArtifactPreparationIdentity>,
        job: AotCompilationJob,
    ) -> Self {
        Self {
            artifact,
            key,
            authentication,
            job,
        }
    }

    pub(crate) fn artifact(&self) -> &CapsuleArtifact {
        &self.artifact
    }
    pub(crate) fn key(&self) -> &AotCompatibilityKey {
        &self.key
    }
    pub(crate) fn eligibility(&self) -> &ReleaseUseEligibility {
        &self.job.eligibility
    }
    pub(crate) fn preparation_identity(&self) -> Option<&ArtifactPreparationIdentity> {
        self.authentication.as_ref()
    }
    pub(crate) fn check(&self) -> Result<(), PlatformError> {
        self.job.check()
    }

    #[cfg(test)]
    pub(crate) fn control(&self) -> super::AotJobControl {
        self.job.control()
    }

    pub(crate) fn check_engine(&self, engine: &Engine) -> Result<(), PlatformError> {
        self.check()?;
        self.job.state.profile.check_engine(engine)?;
        if self.key.engine_compatibility() != self.job.state.profile.engine_compatibility()
            || self.key.engine_profile_digest().as_str()
                != crate::aot::blob(*self.job.state.profile.digest()).as_str()
        {
            return Err(mismatch());
        }
        Ok(())
    }

    /// One process attempt, including failure. The taken allowance remains on
    /// this stack until compile has killed/reaped its real child on every exit.
    pub(crate) fn compile(&mut self) -> Result<TrustedAotOutput, PlatformError> {
        let permit = self.job.output.take().ok_or_else(invalid)?;
        self.check()?;
        let output = process::compile(&self.job, &self.artifact.component_bytes)?;
        self.check()?;
        let completed = CompletedAotJob {
            key: self.key.clone(),
            output,
            permit,
        };
        let output = self.job.state.authority.seal_completed(completed)?;
        self.check()?;
        Ok(output)
    }

    pub(crate) fn authenticate_receipt<'a>(
        &'a self,
        receipt: &[u8],
    ) -> Result<AuthenticatedAotReceipt<'a>, PlatformError> {
        self.job.state.authority.authenticate_receipt(self, receipt)
    }

    pub(crate) fn authenticate_output<'a>(
        &'a self,
        output: &'a TrustedAotOutput,
    ) -> Result<AuthenticatedNative<'a>, PlatformError> {
        self.job.state.authority.authenticate_output(self, output)
    }

    pub(crate) fn maximum_output_bytes(&self) -> usize {
        self.job.state.limits.compiler.maximum_output_bytes
    }
}
