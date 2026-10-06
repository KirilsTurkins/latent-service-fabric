//! Sealed external checkpoint ownership on the same fixed recovery workers.
//! Native files and roots are private; every public result is bounded metadata.

use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};

use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeReservation,
};

use super::physical::FailureLatch;
use super::{
    ProtectedResourceJob, ProtectedStoreError, ProtectedStoreOwner, ProtectedStoreResource,
};
use crate::embedded::{ReadView, StoreError};
use crate::store_identity::{ExternalCheckpoint, StoreIdentity};
use crate::store_io::{
    StoreIoError, StoreIoJob, StoreIoKind, StoreIoRetirement, StoreIoRetirementWitness,
};

mod native;
pub(super) use native::CheckpointFile;

const RESOURCE_BYTES: u64 = 32 * 1024;
const METADATA_JOB_BYTES: u64 = 4096;

struct CheckpointKeeper {
    // Actual native footprint retires only after the private resource's native
    // destructors. These parts use the existing original reservation ledger.
    _buffer: NativeBufferPermit,
    _reservation: Arc<NativeReservation>,
}

/// A once-only witness of the actual fresh identity transaction applied by the
/// exclusive initializer. It cannot be constructed from a path, matching
/// persisted identity or caller-provided fresh flag.
pub struct StoreInitializationWitness {
    owner: Arc<FailureLatch>,
    identity: StoreIdentity,
    fresh_root: Option<(u64, u64)>,
}

impl StoreInitializationWitness {
    #[must_use]
    pub fn identity(&self) -> &StoreIdentity {
        &self.identity
    }

    /// Only a private destination with real empty-root/exclusive-leaf evidence
    /// can produce this once. Ordinary logical initialization never suffices.
    pub(super) fn take_restore(store: &super::physical::PhysicalStore) -> Result<Self, StoreError> {
        store.check().map_err(|_| StoreError::Unavailable)?;
        if store.fresh_root.is_none() {
            return Err(StoreError::Conflict);
        }
        let identity = store
            .fresh_identity
            .lock()
            .map_err(|_| StoreError::Unavailable)?
            .take()
            .ok_or(StoreError::Conflict)?;
        Ok(Self {
            owner: Arc::clone(&store.failure),
            identity,
            fresh_root: store.fresh_root,
        })
    }
}

#[derive(Clone, Debug)]
pub struct ProtectedCheckpointConfig {
    pub root: PathBuf,
}

impl ProtectedCheckpointConfig {
    pub(super) fn validate(&self) -> Result<u64, ProtectedStoreError> {
        let path_bytes = self.root.as_os_str().len();
        if !self.root.is_absolute()
            || path_bytes == 0
            || path_bytes > 4096
            || self.root.capacity() > 4096
        {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        u64::try_from(self.root.capacity())
            .ok()
            .and_then(|bytes| bytes.checked_add(RESOURCE_BYTES))
            .ok_or(ProtectedStoreError::InvalidConfiguration)
    }
}

/// The actual external file remains confined to its pre-reserved recovery
/// resource. Unexpected waiter drop retires it on the same workers; observing
/// an external floor alone never permits execution or generic restore resume.
#[must_use = "retain until checkpoint jobs and actual physical retirement complete"]
pub struct ProtectedCheckpoint {
    resource: ProtectedStoreResource<CheckpointFile>,
}

impl ProtectedCheckpoint {
    pub fn retirement_witness(&mut self) -> Option<StoreIoRetirementWitness> {
        self.resource.retirement_witness()
    }

    pub fn retire(self) -> StoreIoRetirement {
        self.resource.retire()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CheckpointInspection {
    pub checkpoint: Option<ExternalCheckpoint>,
    pub dispatch_owner: Option<(u64, u64)>,
}

/// A single bounded waiter for a closed checkpoint operation. No generic
/// production result can transfer File, ProtectedRoot or the private resource.
#[must_use = "dropping observation detaches accepted work and reserved destruction"]
pub struct ProtectedCheckpointJob<R> {
    inner: ProtectedResourceJob<CheckpointFile, R>,
}

impl<R> Future for ProtectedCheckpointJob<R> {
    type Output = Result<(ProtectedCheckpoint, Result<R, ProtectedStoreError>), StoreIoError>;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match Pin::new(&mut self.get_mut().inner).poll(cx) {
            Poll::Ready(Ok((resource, result))) => {
                Poll::Ready(Ok((ProtectedCheckpoint { resource }, result)))
            }
            Poll::Ready(Err(error)) => Poll::Ready(Err(error)),
            Poll::Pending => Poll::Pending,
        }
    }
}

impl ProtectedStoreOwner {
    /// Consume the initializer's Fresh evidence once on a fixed worker. A
    /// detached response loses this witness conservatively; no later matching
    /// identity or restart can recreate it.
    pub fn take_initialization_witness(
        &self,
    ) -> Result<
        StoreIoJob<Result<Option<StoreInitializationWitness>, ProtectedStoreError>>,
        ProtectedStoreError,
    > {
        self.available()?;
        let owner = Arc::clone(&self.failure);
        self.ready
            .submit(
                StoreIoKind::RecoveryRead,
                METADATA_JOB_BYTES,
                move |store| {
                    store.with_store(StoreIoKind::RecoveryRead, |_| {
                        let identity = store
                            .fresh_identity
                            .lock()
                            .map_err(|_| StoreError::Unavailable)?
                            .take();
                        Ok(identity.map(|identity| StoreInitializationWitness {
                            owner,
                            identity,
                            fresh_root: store.fresh_root,
                        }))
                    })
                },
            )
            .map_err(ProtectedStoreError::Io)
    }

    /// Pre-reserve the external native owner and original keeper before opening
    /// files. Existing files are always opened without truncation; only the
    /// same-owner Fresh witness permits exclusive creation of a missing leaf.
    /// `observe_dispatch` is a trusted bounded metadata projection from one
    /// coherent native view, normally DispatchCatalog::checkpoint.
    pub fn open_checkpoint(
        &self,
        config: ProtectedCheckpointConfig,
        identity: StoreIdentity,
        fresh: Option<StoreInitializationWitness>,
        keeper: Arc<NativeReservation>,
        observe_dispatch: impl FnOnce(&ReadView) -> Result<Option<(u64, u64)>, StoreError>
            + Send
            + 'static,
    ) -> Result<ProtectedCheckpointJob<()>, ProtectedStoreError> {
        let bytes = config.validate()?;
        if keeper.class() != NativeAdmissionClass::Recovery
            || !keeper.is_from_owner(&self.native_capacity()?)
        {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        if fresh.as_ref().is_some_and(|witness| {
            !Arc::ptr_eq(&witness.owner, &self.failure) || witness.identity != identity
        }) {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        let buffer = keeper
            .reserve_buffer(NativeBufferClass::Work, bytes + METADATA_JOB_BYTES)
            .map_err(|_| ProtectedStoreError::InvalidConfiguration)?;
        let original = Arc::clone(&keeper);
        let resource = self.reserve_recovery_resource(
            bytes,
            Arc::new(CheckpointKeeper {
                _buffer: buffer,
                _reservation: keeper,
            }),
        )?;
        let failure = Arc::clone(&self.failure);
        let inner =
            self.initialize_native_resource(resource, METADATA_JOB_BYTES, move |store| {
                let view = store.engine().snapshot()?;
                if StoreIdentity::inspect(&view)?.as_ref() != Some(&identity) {
                    return Err(StoreError::Corrupt);
                }
                let dispatch = observe_dispatch(&view)?;
                if fresh.is_some() && dispatch.is_some() {
                    return Err(StoreError::Conflict);
                }
                if fresh.is_some() {
                    check_fresh_view(&view, &identity)?;
                }
                CheckpointFile::open(store, config, identity, fresh, dispatch, failure, original)
            })?;
        Ok(ProtectedCheckpointJob { inner })
    }

    /// Read the exact protected external file and compare it with current
    /// durable identity/owner floors on the existing recovery reader.
    pub fn inspect_checkpoint(
        &self,
        checkpoint: ProtectedCheckpoint,
        observe_dispatch: impl FnOnce(&ReadView) -> Result<Option<(u64, u64)>, StoreError>
            + Send
            + 'static,
    ) -> Result<ProtectedCheckpointJob<CheckpointInspection>, ProtectedStoreError> {
        let inner = self.with_resource(
            checkpoint.resource,
            StoreIoKind::RecoveryRead,
            METADATA_JOB_BYTES,
            move |file, engine| {
                let view = engine.snapshot()?;
                file.inspect(&view, observe_dispatch(&view)?)
            },
        )?;
        Ok(ProtectedCheckpointJob { inner })
    }

    /// Persist an exact original-record comparison plus monotonic checkpoint
    /// advance before readiness. The protected clock epoch is trusted covered
    /// metadata supplied by the SAME clock authority, not a continuity flag.
    /// Actual dispatch owner/floor values come only from the worker's coherent
    /// durable view. Partial/uncertain external writes quarantine this owner.
    pub fn advance_checkpoint(
        &self,
        checkpoint: ProtectedCheckpoint,
        expected: Option<ExternalCheckpoint>,
        protected_clock_epoch: u64,
        observe_dispatch: impl FnOnce(&ReadView) -> Result<Option<(u64, u64)>, StoreError>
            + Send
            + 'static,
    ) -> Result<ProtectedCheckpointJob<ExternalCheckpoint>, ProtectedStoreError> {
        if protected_clock_epoch == 0 {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        let inner = self.with_resource(
            checkpoint.resource,
            StoreIoKind::RecoveryWrite,
            METADATA_JOB_BYTES,
            move |file, engine| {
                let view = engine.snapshot()?;
                file.advance(
                    &view,
                    expected.as_ref(),
                    protected_clock_epoch,
                    observe_dispatch(&view)?,
                )
            },
        )?;
        Ok(ProtectedCheckpointJob { inner })
    }

    #[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
    pub(in crate::protected_store) fn advance_checkpoint_for_test(
        &self,
        checkpoint: ProtectedCheckpoint,
        expected: Option<ExternalCheckpoint>,
        protected_clock_epoch: u64,
        observe_dispatch: impl FnOnce(&ReadView) -> Result<Option<(u64, u64)>, StoreError>
            + Send
            + 'static,
        after_write: impl FnOnce() + Send + 'static,
    ) -> Result<ProtectedCheckpointJob<ExternalCheckpoint>, ProtectedStoreError> {
        let inner = self.with_resource(
            checkpoint.resource,
            StoreIoKind::RecoveryWrite,
            METADATA_JOB_BYTES,
            move |file, engine| {
                let view = engine.snapshot()?;
                file.advance_for_test(
                    &view,
                    expected.as_ref(),
                    protected_clock_epoch,
                    observe_dispatch(&view)?,
                    after_write,
                )
            },
        )?;
        Ok(ProtectedCheckpointJob { inner })
    }
}

fn check_fresh_view(view: &ReadView, identity: &StoreIdentity) -> Result<(), StoreError> {
    use crate::embedded::Family;
    let identity_key = StoreIdentity::row_key();
    let identity_value = identity.encode();
    for family in [
        Family::Namespace,
        Family::State,
        Family::Tombstone,
        Family::Command,
        Family::Result,
        Family::Outbox,
        Family::Attempt,
        Family::Inbox,
        Family::PayloadReference,
        Family::Maintenance,
    ] {
        let page = view.scan_after(family, b"", None, 2, 256)?;
        if page.resume.is_some()
            || page
                .rows
                .iter()
                .any(|(key, value)| key != &identity_key || value != &identity_value)
        {
            return Err(StoreError::Conflict);
        }
    }
    Ok(())
}
