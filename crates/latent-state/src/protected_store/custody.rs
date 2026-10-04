//! Same-engine exclusive recovery custody; no replacement owner or worker.

use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, OnceLock};
use std::task::{Context, Poll};

use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeReservation,
};

use super::physical::PhysicalStore;
use super::{ProtectedStoreError, ProtectedStoreOwner};
use crate::embedded::{EmbeddedStore, StoreError};
use crate::store_io::{
    StoreIoCustody, StoreIoJob, StoreIoKind, StoreIoRetirement, StoreIoRetirementWitness,
};

struct CustodyKeeper {
    _buffers: NativeBufferPermit,
    _original: Arc<NativeReservation>,
}

/// Private producer port. Closed snapshot/migration wrappers expose bounded
/// metadata only; File/ProtectedRoot and this generic native value never escape
/// into a transport DTO. Its admission gate survives dropped job waiters.
pub(super) struct ProtectedStoreCustody<T: Send + 'static> {
    io: StoreIoCustody<OnceLock<PhysicalStore>, T>,
    maximum_job_bytes: u64,
    original: Arc<NativeReservation>,
}

impl<T: Send + 'static> ProtectedStoreCustody<T> {
    pub(super) fn retirement_witness(&mut self) -> Option<StoreIoRetirementWitness> {
        self.io.retirement_witness()
    }

    pub(super) fn retire(self) -> StoreIoRetirement {
        self.io.retire()
    }
}

type CustodyCompletion<T, R> = (
    StoreIoCustody<OnceLock<PhysicalStore>, T>,
    (Result<R, ProtectedStoreError>, u64, Arc<NativeReservation>),
);

pub(super) struct ProtectedCustodyJob<T: Send + 'static, R> {
    inner: StoreIoJob<CustodyCompletion<T, R>>,
}

impl<T: Send + 'static, R> Future for ProtectedCustodyJob<T, R> {
    type Output = Result<
        (ProtectedStoreCustody<T>, Result<R, ProtectedStoreError>),
        crate::store_io::StoreIoError,
    >;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        match Pin::new(&mut self.get_mut().inner).poll(cx) {
            Poll::Ready(Ok((io, (result, maximum_job_bytes, original)))) => Poll::Ready(Ok((
                ProtectedStoreCustody {
                    io,
                    maximum_job_bytes,
                    original,
                },
                result,
            ))),
            Poll::Ready(Err(error)) => Poll::Ready(Err(error)),
            Poll::Pending => Poll::Pending,
        }
    }
}

impl ProtectedStoreOwner {
    /// Atomically reserve physical custody only when the original owner has no
    /// accepted callbacks/responses, native views, operation pins or retirement
    /// backlog. Busy/pressure is a healthy refusal, never a clean/abort claim.
    pub(super) fn reserve_custody<T: Send + 'static>(
        &self,
        resource_bytes: u64,
        maximum_job_bytes: u64,
        original: Arc<NativeReservation>,
    ) -> Result<ProtectedStoreCustody<T>, ProtectedStoreError> {
        self.available()?;
        if original.class() != NativeAdmissionClass::Recovery
            || !original.is_from_owner(&self.native_capacity()?)
            || resource_bytes == 0
            || maximum_job_bytes == 0
        {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        let work_bytes = resource_bytes
            .checked_add(maximum_job_bytes)
            .ok_or(ProtectedStoreError::InvalidConfiguration)?;
        let buffers = original
            .reserve_buffer(NativeBufferClass::Work, work_bytes)
            .map_err(|_| ProtectedStoreError::InvalidConfiguration)?;
        let keeper = Arc::new(CustodyKeeper {
            _buffers: buffers,
            _original: Arc::clone(&original),
        });
        let io = original
            .with_live(|| {
                self.ready
                    .reserve_custody(resource_bytes, original.original_deadline(), keeper)
            })
            .map_err(|_| ProtectedStoreError::InvalidConfiguration)?
            .map_err(ProtectedStoreError::Io)?;
        Ok(ProtectedStoreCustody {
            io,
            maximum_job_bytes,
            original,
        })
    }

    pub(super) fn initialize_custody_with<T: Send + 'static, R: Send + 'static>(
        &self,
        custody: ProtectedStoreCustody<T>,
        bytes: u64,
        initializer: impl FnOnce(&PhysicalStore) -> Result<(T, R), StoreError> + Send + 'static,
    ) -> Result<ProtectedCustodyJob<T, R>, ProtectedStoreError> {
        if custody.io.get().is_some() || bytes > custody.maximum_job_bytes {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        self.with_custody_io(
            custody,
            StoreIoKind::RecoveryWrite,
            bytes,
            move |io, store| {
                let (native, result) = initializer(store)?;
                if let Err(native) = io.attach(native) {
                    drop(native); // Native destruction remains on this fixed worker.
                    return Err(StoreError::Invalid);
                }
                Ok(result)
            },
        )
    }

    pub(super) fn with_custody<T: Send + 'static, R: Send + 'static>(
        &self,
        custody: ProtectedStoreCustody<T>,
        kind: StoreIoKind,
        bytes: u64,
        operation: impl FnOnce(&T, &EmbeddedStore) -> Result<R, StoreError> + Send + 'static,
    ) -> Result<ProtectedCustodyJob<T, R>, ProtectedStoreError> {
        if custody.io.get().is_none() {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        self.with_custody_io(custody, kind, bytes, move |io, store| {
            operation(
                io.get().expect("initialized custody resource"),
                store.engine(),
            )
        })
    }

    /// Closed restore producer needs original physical source fences as well
    /// as the engine. This remains private to these typed storage wrappers.
    pub(super) fn with_physical_custody<T: Send + 'static, R: Send + 'static>(
        &self,
        custody: ProtectedStoreCustody<T>,
        bytes: u64,
        operation: impl FnOnce(&T, &PhysicalStore) -> Result<R, StoreError> + Send + 'static,
    ) -> Result<ProtectedCustodyJob<T, R>, ProtectedStoreError> {
        if custody.io.get().is_none() || bytes > custody.maximum_job_bytes {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        self.with_custody_io(
            custody,
            StoreIoKind::RecoveryWrite,
            bytes,
            move |io, store| operation(io.get().expect("initialized custody resource"), store),
        )
    }

    fn with_custody_io<T: Send + 'static, R: Send + 'static>(
        &self,
        custody: ProtectedStoreCustody<T>,
        kind: StoreIoKind,
        bytes: u64,
        operation: impl FnOnce(
                &mut StoreIoCustody<OnceLock<PhysicalStore>, T>,
                &PhysicalStore,
            ) -> Result<R, StoreError>
            + Send
            + 'static,
    ) -> Result<ProtectedCustodyJob<T, R>, ProtectedStoreError> {
        if !kind.is_recovery() || bytes > custody.maximum_job_bytes {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        self.available()?;
        let ProtectedStoreCustody {
            io,
            maximum_job_bytes,
            original,
        } = custody;
        let callback_original = Arc::clone(&original);
        let job = self
            .ready
            .submit_custody(io, kind, bytes, move |io, store| {
                let result = if callback_original.with_live(|| ()).is_ok() {
                    store.with_store(kind, |_| operation(io, store))
                } else {
                    // Expiry is healthy domain refusal. Never map it through
                    // StoreError::Unavailable and quarantine a healthy engine.
                    Err(ProtectedStoreError::Io(
                        crate::store_io::StoreIoError::CustodyExpired,
                    ))
                };
                (result, maximum_job_bytes, original)
            })
            .map_err(ProtectedStoreError::Io)?;
        Ok(ProtectedCustodyJob { inner: job })
    }
}
