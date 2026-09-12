//! One bounded blocking job, suitable for the existing fixed compiler workers.

mod process;

use super::ownership::{AotResourceLimits, AotResourceSnapshot, Budget, OutputPermit, WorkPermit};
use super::sandbox::SandboxLimits;
use super::{
    error, exhausted, invalid, mismatch, AotCompatibilityKey, AotCompilerLimits,
    TrustedAotCompilerAuthority, TrustedAotOutput, ValidatedAotProfile,
};
use latent_artifacts::{
    preparation_metadata_fingerprint, ArtifactPreparationReadLimits, CapsuleArtifact,
    LifecycleScope, OwnedArtifactPreparationSource, ReleaseUseEligibility,
};
use latent_core::{PackageDigest, PlatformError, PlatformErrorCode, ReleaseDigest};
use sha2::{Digest, Sha256};
use std::{
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AotProcessLimits {
    pub resources: AotResourceLimits,
    pub compiler: AotCompilerLimits,
    pub sandbox: SandboxLimits,
    pub maximum_component_bytes: usize,
    pub maximum_metadata_bytes: usize,
    pub maximum_document_bytes: usize,
    /// Includes time held by an unstarted reservation, independently of a caller.
    pub job_timeout: Duration,
}
impl Default for AotProcessLimits {
    fn default() -> Self {
        Self {
            resources: AotResourceLimits::default(),
            compiler: AotCompilerLimits::default(),
            sandbox: SandboxLimits::default(),
            maximum_component_bytes: 64 * 1024 * 1024,
            maximum_metadata_bytes: 16 * 1024 * 1024,
            maximum_document_bytes: 32 * 1024 * 1024,
            job_timeout: Duration::from_secs(30),
        }
    }
}
impl AotProcessLimits {
    pub fn validate(self) -> Result<Self, PlatformError> {
        self.resources.validate()?;
        self.compiler.validate()?;
        self.sandbox.validate()?;
        if !(1..=64 * 1024 * 1024).contains(&self.maximum_component_bytes)
            || !(1..=64 * 1024 * 1024).contains(&self.maximum_metadata_bytes)
            || !(1..=64 * 1024 * 1024).contains(&self.maximum_document_bytes)
            || self.job_timeout.is_zero()
            || self.job_timeout > Duration::from_mins(5)
            || self.compiler.maximum_output_bytes > self.resources.maximum_native_bytes
        {
            return Err(invalid());
        }
        Ok(self)
    }
}

struct State {
    executable: PathBuf,
    compiler_digest: [u8; 32],
    sandbox_digest: [u8; 32],
    bootstrap: Box<[u8]>,
    profile: ValidatedAotProfile,
    authority: TrustedAotCompilerAuthority,
    limits: AotProcessLimits,
    budget: Arc<Budget>,
    closed: AtomicBool,
}
struct Owner {
    state: Arc<State>,
}
impl Drop for Owner {
    fn drop(&mut self) {
        self.state.closed.store(true, Ordering::Release);
    }
}

/// Host-configured producer. No queue, threads or dormant service processes.
/// The approved executable digest and authentication key come from trusted node
/// configuration, never an artifact or a replaceable cache receipt.
#[derive(Clone)]
pub struct IsolatedAotCompiler {
    owner: Arc<Owner>,
}
impl IsolatedAotCompiler {
    pub fn new(
        executable: &Path,
        approved_digest: [u8; 32],
        profile: ValidatedAotProfile,
        authority: TrustedAotCompilerAuthority,
        limits: AotProcessLimits,
    ) -> Result<Self, PlatformError> {
        process::supported()?;
        let limits = limits.validate()?;
        if executable.as_os_str().len() > 4096 || !executable.is_absolute() {
            return Err(invalid());
        }
        let executable = executable.canonicalize().map_err(|_| process::failed())?;
        if executable.as_os_str().len() > 4096 {
            return Err(invalid());
        }
        if process::hash_executable(&executable, || Ok(()))? != approved_digest {
            return Err(mismatch());
        }
        let bootstrap = profile.bootstrap()?.into_boxed_slice();
        let mut sandbox = Sha256::new();
        sandbox.update(super::sandbox::PROFILE_ID.as_bytes());
        for value in [
            limits.sandbox.address_space_bytes,
            limits.sandbox.cpu_seconds,
            limits.sandbox.stack_bytes,
            limits.sandbox.maximum_fds,
        ] {
            sandbox.update(value.to_le_bytes());
        }
        let state = Arc::new(State {
            executable,
            compiler_digest: approved_digest,
            sandbox_digest: sandbox.finalize().into(),
            bootstrap,
            profile,
            authority,
            limits,
            budget: Budget::new(limits.resources)?,
            closed: AtomicBool::new(false),
        });
        Ok(Self {
            owner: Arc::new(Owner { state }),
        })
    }
    #[must_use]
    pub fn snapshot(&self) -> AotResourceSnapshot {
        self.owner.state.budget.snapshot()
    }
    /// Close admission and signal every actual job. A timeout never refunds its
    /// resources or detaches its child: the blocking owner still kills and reaps.
    pub fn shutdown(&self, timeout: Duration) -> Result<(), PlatformError> {
        let state = &self.owner.state;
        state.closed.store(true, Ordering::Release);
        let deadline = Instant::now()
            .checked_add(timeout.min(Duration::from_mins(5)))
            .ok_or_else(invalid)?;
        while state.budget.snapshot().jobs != 0 {
            if Instant::now() >= deadline {
                return Err(timed_out());
            }
            std::thread::sleep(Duration::from_millis(1));
        }
        Ok(())
    }
    pub fn reserve(
        &self,
        source: OwnedArtifactPreparationSource,
        release: &ReleaseDigest,
    ) -> Result<AotCompilationJob, PlatformError> {
        let state = &self.owner.state;
        if state.closed.load(Ordering::Acquire) {
            return Err(cancelled());
        }
        let deadline = Instant::now()
            .checked_add(state.limits.job_timeout)
            .ok_or_else(invalid)?;
        // ReleaseDigest is an older public String wrapper. Never retain excess
        // caller capacity or let a malformed identity reach filesystem access.
        let _: latent_core::ArtifactBlobDigest = release.0.parse().map_err(|_| invalid())?;
        let bounds = source.read_bounds(release)?;
        let component = usize::try_from(bounds.component_bytes).map_err(|_| exhausted())?;
        if component == 0 || component > state.limits.maximum_component_bytes {
            return Err(exhausted());
        }
        if let Some(identity) = source.identity(release)? {
            if identity.metadata().charged_bytes() > state.limits.maximum_metadata_bytes
                || identity.metadata().required_type_depth() > 32
            {
                return Err(exhausted());
            }
        }
        let metadata = bounds
            .maximum_metadata_document_bytes
            .min(state.limits.maximum_document_bytes);
        let manifest = bounds
            .maximum_manifest_document_bytes
            .min(state.limits.maximum_document_bytes);
        // Reserve encoded documents, an accepted-metadata allowance, and fixed
        // catalog validation scratch. The fingerprint limit is not a predecode
        // heap ceiling: the repository's bounded decoder also owns transient
        // allocations. These counters deliberately do not claim process RSS.
        let documents = metadata
            .checked_add(manifest)
            .and_then(|value| value.checked_add(state.limits.maximum_metadata_bytes))
            .and_then(|value| value.checked_add(1024 * 1024))
            .ok_or_else(exhausted)?;
        let (work, output) = state.budget.reserve(
            component,
            documents,
            state.limits.compiler.maximum_output_bytes,
        )?;
        let eligibility = source
            .execution_eligibility(release)?
            .ok_or_else(mismatch)?;
        eligibility.check_current()?;
        if eligibility.release() != release || eligibility.retained_bytes() > 64 * 1024 {
            return Err(mismatch());
        }
        let job = AotCompilationJob {
            source,
            release: ReleaseDigest(release.0.as_str().into()),
            eligibility,
            limits: ArtifactPreparationReadLimits {
                maximum_component_bytes: component,
                maximum_metadata_document_bytes: metadata,
                maximum_manifest_document_bytes: manifest,
            },
            state: Arc::clone(state),
            control: AotJobControl {
                cancelled: Arc::new(AtomicBool::new(false)),
            },
            deadline,
            output: Some(output),
            _work: work,
        };
        job.check()?;
        Ok(job)
    }
}

/// Cancellation signals an owner; it does not claim that the process stopped.
#[derive(Clone)]
pub struct AotJobControl {
    cancelled: Arc<AtomicBool>,
}
impl AotJobControl {
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }
}

/// Affine reservation: run on a shared bounded blocking worker. Dropping an
/// unstarted job starts nothing. During run, the stack owns its child through reap.
pub struct AotCompilationJob {
    source: OwnedArtifactPreparationSource,
    release: ReleaseDigest,
    eligibility: ReleaseUseEligibility,
    limits: ArtifactPreparationReadLimits,
    state: Arc<State>,
    control: AotJobControl,
    deadline: Instant,
    output: Option<OutputPermit>,
    _work: WorkPermit,
}
impl AotCompilationJob {
    #[must_use]
    pub fn control(&self) -> AotJobControl {
        self.control.clone()
    }
    pub fn run(mut self) -> Result<TrustedAotOutput, PlatformError> {
        self.check()?;
        let artifact = self.source.fetch_blocking(&self.release, self.limits)?;
        self.check()?;
        let source = self.checked_source(&artifact)?;
        let key = AotCompatibilityKey::from_source(
            &source,
            &self.state.profile,
            self.state.compiler_digest,
            self.state.sandbox_digest,
        )?;
        let output = process::compile(&self, &artifact.component_bytes)?;
        // Recheck the exact retained capability; re-verification into a new
        // generation cannot silently upgrade a job queued under an older proof.
        self.check()?;
        let completed = CompletedAotJob {
            key,
            output,
            permit: self.output.take().ok_or_else(invalid)?,
        };
        let output = self.state.authority.seal_completed(completed)?;
        self.check()?;
        Ok(output)
    }
    fn check(&self) -> Result<(), PlatformError> {
        self.check_control()?;
        self.eligibility.check_current()
    }
    fn check_control(&self) -> Result<(), PlatformError> {
        if self.state.closed.load(Ordering::Acquire)
            || self.control.cancelled.load(Ordering::Acquire)
        {
            return Err(cancelled());
        }
        if Instant::now() >= self.deadline {
            return Err(timed_out());
        }
        Ok(())
    }
    fn checked_source(
        &self,
        artifact: &CapsuleArtifact,
    ) -> Result<CheckedAotSource, PlatformError> {
        let component_digest: [u8; 32] = Sha256::digest(&artifact.component_bytes).into();
        if super::blob(component_digest).as_str() != self.release.0
            || artifact.descriptor.release_digest != self.release
            || artifact.manifest.component_digest != self.release
            || artifact.descriptor.size_bytes != artifact.component_bytes.len() as u64
            || artifact.component_bytes.len() != self.limits.maximum_component_bytes
        {
            return Err(mismatch());
        }
        let metadata = preparation_metadata_fingerprint(
            &artifact.descriptor,
            &artifact.manifest,
            &artifact.contracts,
            self.state.limits.maximum_metadata_bytes,
            32,
        )?;
        if let Some(identity) = self.source.identity(&self.release)? {
            identity.verify_metadata(artifact, self.state.limits.maximum_metadata_bytes, 32)?;
        }
        Ok(CheckedAotSource {
            eligibility: self.eligibility.clone(),
            component_digest,
            component_bytes: artifact.component_bytes.len() as u64,
            metadata_digest: *metadata.digest(),
        })
    }
}

/// Only a current catalog-owned, freshly verified fetch can construct this.
pub(crate) struct CheckedAotSource {
    eligibility: ReleaseUseEligibility,
    component_digest: [u8; 32],
    component_bytes: u64,
    metadata_digest: [u8; 32],
}
impl CheckedAotSource {
    pub(crate) fn scope(&self) -> &LifecycleScope {
        self.eligibility.scope()
    }
    pub(crate) fn package(&self) -> Option<&PackageDigest> {
        self.eligibility.package()
    }
    pub(crate) fn component_digest(&self) -> &[u8; 32] {
        &self.component_digest
    }
    pub(crate) fn component_bytes(&self) -> u64 {
        self.component_bytes
    }
    pub(crate) fn metadata_digest(&self) -> &[u8; 32] {
        &self.metadata_digest
    }
}
pub(crate) struct CompletedAotJob {
    key: AotCompatibilityKey,
    output: Vec<u8>,
    permit: OutputPermit,
}
impl CompletedAotJob {
    #[cfg(test)]
    pub(super) fn fixture(key: AotCompatibilityKey, output: Vec<u8>, permit: OutputPermit) -> Self {
        Self {
            key,
            output,
            permit,
        }
    }

    pub(super) fn into_parts(self) -> (AotCompatibilityKey, Vec<u8>, OutputPermit) {
        (self.key, self.output, self.permit)
    }
}
fn cancelled() -> PlatformError {
    error(PlatformErrorCode::Cancelled, "aot-job-cancelled")
}
fn timed_out() -> PlatformError {
    error(PlatformErrorCode::DeadlineExceeded, "aot-job-deadline")
}
