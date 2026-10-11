//! A temporary rejection-only owner; it never opens a transaction database.

use std::any::Any;
use std::path::{Component, Path};
use std::sync::Arc;
use std::time::{Duration, Instant};

use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeCapacityLimits,
    NativeCapacityOwner, NativeCapacityPartition, NativeReservation, NativeReservationRequest,
    NATIVE_RESERVATION_METADATA_BYTES,
};
use latent_core::{ActivationClock, PlatformError, PlatformErrorCode};
use latent_state::store_io::{StoreIoJob, StoreIoKind, StoreIoLimits, StoreIoOwner};

#[cfg(unix)]
#[path = "stateless/unix.rs"]
mod native;
#[cfg(windows)]
#[path = "stateless/windows.rs"]
mod native;
#[cfg(not(any(unix, windows)))]
mod native {
    pub(super) fn observe(
        _: &std::path::Path,
        _: &latent_core::native_capacity::NativeReservation,
        _: impl FnOnce(),
    ) -> Result<bool, latent_core::PlatformError> {
        Err(super::unavailable())
    }
}

const MAXIMUM_PATH_BYTES: usize = 4096;
const MAXIMUM_COMPONENTS: usize = 64;
const WORK_BYTES: u64 = 2 * 1024 * 1024;
const JOB_BYTES: u64 = 640 * 1024;
const ORIGINAL_WINDOW: Duration = Duration::from_secs(30);
const STATE_DIRECTORY: &str = "state";

struct ProbeKeeper {
    // The original catalog's exclusive root lock also survives a detached
    // node-start waiter, until every anchored probe descriptor is destroyed.
    _catalog: Arc<dyn Any + Send + Sync>,
    _work: NativeBufferPermit,
    original: Arc<NativeReservation>,
}

struct PhysicalProbe {
    // Also held by the caller until the actual OS thread has been joined.
    keeper: Arc<ProbeKeeper>,
}

struct ProbeOwner {
    jobs: StoreIoOwner<PhysicalProbe>,
    native: NativeCapacityOwner,
    clock: Arc<dyn ActivationClock>,
    deadline: Instant,
    joined: usize,
    finished: bool,
    // Last: no native allocation is refunded before worker retirement.
    keeper: Option<Arc<ProbeKeeper>>,
}

/// Run after acquiring the real artifact repository's exclusive root ownership.
/// Every supported state configuration uses the fixed sibling `state` root;
/// any existing entry there requires its original state owner configuration.
/// A negative lookup is not permission to execute, restore or open an engine.
pub(in crate::standalone) async fn require_stateless_mode(
    data_directory: &Path,
    clock: Arc<dyn ActivationClock>,
    catalog: Arc<latent_artifacts::DirectoryArtifactRepository>,
) -> Result<(), PlatformError> {
    let (mut owner, job) = ProbeOwner::start(data_directory, clock, catalog, || {})?;
    let observed = tokio::time::timeout_at(owner.deadline.into(), job).await;
    // Refusal also retires the native owner. Timeout/detachment is never clean.
    owner.finish().await?;
    match observed {
        Ok(Ok(Ok(false))) => Ok(()),
        Ok(Ok(Ok(true))) => Err(configuration_required()),
        _ => Err(unavailable()),
    }
}

impl ProbeOwner {
    fn start(
        path: &Path,
        clock: Arc<dyn ActivationClock>,
        catalog: Arc<dyn Any + Send + Sync>,
        before_native_retirement: impl FnOnce() + Send + 'static,
    ) -> Result<(Self, StoreIoJob<Result<bool, PlatformError>>), PlatformError> {
        validate_path(path)?;
        let deadline = clock
            .monotonic_now()
            .checked_add(ORIGINAL_WINDOW)
            .ok_or_else(unavailable)?;
        let bytes = WORK_BYTES + NATIVE_RESERVATION_METADATA_BYTES;
        let native = NativeCapacityOwner::with_clock(
            NativeCapacityLimits {
                ordinary: NativeCapacityPartition {
                    slots: 1,
                    bytes: NATIVE_RESERVATION_METADATA_BYTES,
                    maximum_reservation_bytes: NATIVE_RESERVATION_METADATA_BYTES,
                },
                recovery: NativeCapacityPartition {
                    slots: 1,
                    bytes,
                    maximum_reservation_bytes: bytes,
                },
                maximum_lifetime: ORIGINAL_WINDOW,
            },
            Arc::clone(&clock),
        )
        .map_err(|_| unavailable())?;
        native.close_ordinary();
        let original = Arc::new(
            native
                .reserve(
                    NativeAdmissionClass::Recovery,
                    NativeReservationRequest {
                        work_bytes: WORK_BYTES,
                        ..NativeReservationRequest::default()
                    },
                    deadline,
                )
                .map_err(|_| unavailable())?,
        );
        let keeper = Arc::new(ProbeKeeper {
            _catalog: catalog,
            _work: original
                .reserve_buffer(NativeBufferClass::Work, WORK_BYTES)
                .map_err(|_| unavailable())?,
            original,
        });
        // Includes the fixed 1 MiB worker stack, bounded control metadata and
        // every retained Windows UTF-16 prefix plus its final lookup. No
        // probe file/native buffer exists before this original Work guard.
        let jobs = StoreIoOwner::with_clock(
            PhysicalProbe {
                keeper: Arc::clone(&keeper),
            },
            StoreIoLimits {
                recovery: None,
                workers: 1,
                queued_jobs: 1,
                accepted_jobs: 1,
                active_reads: 1,
                active_writes: 1,
                retained_bytes: WORK_BYTES,
                job_bytes: JOB_BYTES + 4096,
                resident_bytes: 1024 * 1024 + 64 * 1024,
            },
            |_| Ok(()),
            Arc::clone(&clock),
        )
        .map_err(|error| {
            if let Some(owner) = error.owner {
                owner.quarantine();
                owner.close();
            }
            native.quarantine();
            unavailable()
        })?;
        let owner = Self {
            jobs,
            native,
            clock,
            deadline,
            joined: 0,
            finished: false,
            keeper: Some(keeper),
        };
        let path = path.to_path_buf();
        let job = owner
            .jobs
            .submit(StoreIoKind::Read, JOB_BYTES, move |physical| {
                native::observe(&path, &physical.keeper.original, before_native_retirement)
            })
            .map_err(|_| unavailable())?;
        owner.check_live()?;
        Ok((owner, job))
    }

    fn check_live(&self) -> Result<(), PlatformError> {
        self.keeper
            .as_ref()
            .ok_or_else(unavailable)?
            .original
            .with_live(|| ())
            .map_err(|_| unavailable())
    }

    async fn finish(&mut self) -> Result<(), PlatformError> {
        self.jobs.close();
        let report = self
            .jobs
            .drain_async(
                self.deadline,
                tokio::time::sleep_until(self.deadline.into()),
            )
            .map_err(|_| unavailable())?
            .await;
        if !report.clean || !report.snapshot.physically_retired() {
            return Err(unavailable());
        }
        while self.joined != 1 {
            self.joined += self
                .jobs
                .reap_retired_threads()
                .map_err(|_| unavailable())?;
            if self.joined == 1 {
                break;
            }
            if self.clock.monotonic_now() >= self.deadline {
                return Err(unavailable());
            }
            tokio::task::yield_now().await;
        }
        self.check_live()?;
        self.native.close();
        drop(self.keeper.take());
        let report = self
            .native
            .drain_async(
                self.deadline,
                tokio::time::sleep_until(self.deadline.into()),
            )
            .map_err(|_| unavailable())?
            .await;
        if !report.clean || !report.snapshot.physically_retired() {
            return Err(unavailable());
        }
        self.finished = true;
        Ok(())
    }
}

impl Drop for ProbeOwner {
    fn drop(&mut self) {
        self.jobs.close();
        if !self.finished {
            self.jobs.quarantine();
            self.native.quarantine();
        }
        // The live worker independently retains the same keeper until all
        // accepted callbacks and their actual descriptors have been destroyed.
    }
}

fn validate_path(path: &Path) -> Result<(), PlatformError> {
    if !path.is_absolute()
        || path.as_os_str().len() > MAXIMUM_PATH_BYTES
        || path
            .components()
            .filter(|part| matches!(part, Component::Normal(_)))
            .count()
            > MAXIMUM_COMPONENTS
        || path.components().any(|part| {
            matches!(part, Component::ParentDir | Component::CurDir)
                || matches!(part, Component::Prefix(prefix)
                    if !matches!(prefix.kind(),
                        std::path::Prefix::Disk(_) | std::path::Prefix::VerbatimDisk(_)
                        | std::path::Prefix::UNC(_, _) | std::path::Prefix::VerbatimUNC(_, _)))
        })
    {
        return Err(unavailable());
    }
    Ok(())
}

fn unavailable() -> PlatformError {
    super::unavailable()
}

fn configuration_required() -> PlatformError {
    super::super::error(
        PlatformErrorCode::InvalidArgument,
        "state configuration is required for persisted state ownership",
    )
}

#[cfg(all(test, unix))]
#[path = "stateless/tests.rs"]
mod tests;
