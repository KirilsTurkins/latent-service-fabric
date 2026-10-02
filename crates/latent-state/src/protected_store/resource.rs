//! Affine node resources confined to the existing recovery storage workers.

use std::any::Any;
use std::sync::{Arc, OnceLock};

use super::physical::PhysicalStore;
use super::{ProtectedStoreError, ProtectedStoreOwner};
use crate::embedded::{EmbeddedStore, StoreError};
use crate::store_io::{
    StoreIoJob, StoreIoKind, StoreIoRetained, StoreIoRetirement, StoreIoRetirementWitness,
};

/// One host-owned native resource. Its value has no public accessor and is
/// initialized, borrowed and destroyed only on the same fixed recovery workers.
/// Reserve its entire native footprint before initialization. Logical close or
/// a dropped waiter never refunds its pre-reserved physical retirement slot.
pub struct ProtectedStoreResource<T: Send + 'static> {
    retained: StoreIoRetained<OnceLock<PhysicalStore>, T>,
}

impl<T: Send + 'static> ProtectedStoreResource<T> {
    /// One bounded observer, captured before transferring into a native job.
    /// It becomes positive only after native destruction, keeper destruction
    /// and physical reservation release have all actually completed.
    pub fn retirement_witness(&mut self) -> Option<StoreIoRetirementWitness> {
        self.retained.retirement_witness()
    }

    /// Retire through the independently reserved recovery cleanup path, even
    /// after logical close or quarantine. Dropping the receipt detaches only
    /// observation; the same physical owner still drives actual destruction.
    pub fn retire(self) -> StoreIoRetirement {
        self.retained.retire()
    }
}

pub type ProtectedResourceResult<T, R> =
    (ProtectedStoreResource<T>, Result<R, ProtectedStoreError>);
pub type ProtectedResourceJob<T, R> = StoreIoJob<ProtectedResourceResult<T, R>>;

impl ProtectedStoreOwner {
    /// Bind the original global/request keeper before any native allocation.
    /// Ordinary jobs and cleanup cannot consume this reserved recovery slot.
    pub fn reserve_recovery_resource<T: Send + 'static>(
        &self,
        retained_bytes: u64,
        keeper: Arc<dyn Any + Send + Sync>,
    ) -> Result<ProtectedStoreResource<T>, ProtectedStoreError> {
        self.available()?;
        let mut retained = self
            .ready
            .reserve_recovery_retained(retained_bytes)
            .map_err(ProtectedStoreError::Io)?;
        retained
            .retain_owner(keeper)
            .map_err(|_| ProtectedStoreError::InvalidConfiguration)?;
        Ok(ProtectedStoreResource { retained })
    }

    /// Initialize once on the existing recovery writer. The borrowed native
    /// engine and the resource value remain confined to the worker; only the
    /// affine resource identity is returned to its lifecycle owner.
    /// Rejected submission and detached responses enqueue reserved destruction.
    pub fn initialize_resource<T: Send + 'static>(
        &self,
        resource: ProtectedStoreResource<T>,
        retained_payload_bytes: u64,
        initializer: impl FnOnce(&EmbeddedStore) -> Result<T, StoreError> + Send + 'static,
    ) -> Result<ProtectedResourceJob<T, ()>, ProtectedStoreError> {
        self.initialize_native_resource(resource, retained_payload_bytes, move |store| {
            initializer(store.engine())
        })
    }

    /// Crate-private wrappers can inspect sealed physical-root metadata. The
    /// public generic resource initializer still borrows only the engine.
    pub(super) fn initialize_native_resource<T: Send + 'static>(
        &self,
        mut resource: ProtectedStoreResource<T>,
        retained_payload_bytes: u64,
        initializer: impl FnOnce(&PhysicalStore) -> Result<T, StoreError> + Send + 'static,
    ) -> Result<ProtectedResourceJob<T, ()>, ProtectedStoreError> {
        if !self.ready.owns_retained(&resource.retained) || resource.retained.get().is_some() {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        self.available()?;
        self.ready
            .submit(
                StoreIoKind::RecoveryWrite,
                retained_payload_bytes,
                move |store| {
                    let result = store.with_store(StoreIoKind::RecoveryWrite, |_| {
                        let value = initializer(store)?;
                        if let Err(value) = resource.retained.attach(value) {
                            drop(value); // The native value is already on its worker.
                            return Err(StoreError::Invalid);
                        }
                        Ok(())
                    });
                    (resource, result)
                },
            )
            .map_err(ProtectedStoreError::Io)
    }

    /// Borrow an initialized resource for one bounded trusted native operation.
    /// The caller declares every retained input/result byte and cannot substitute
    /// an ordinary queue, different protected owner or uninitialized resource.
    pub fn with_resource<T: Send + 'static, R: Send + 'static>(
        &self,
        resource: ProtectedStoreResource<T>,
        kind: StoreIoKind,
        retained_payload_bytes: u64,
        operation: impl FnOnce(&T, &EmbeddedStore) -> Result<R, StoreError> + Send + 'static,
    ) -> Result<ProtectedResourceJob<T, R>, ProtectedStoreError> {
        if !kind.is_recovery()
            || !self.ready.owns_retained(&resource.retained)
            || resource.retained.get().is_none()
        {
            return Err(ProtectedStoreError::InvalidConfiguration);
        }
        self.available()?;
        self.ready
            .submit(kind, retained_payload_bytes, move |store| {
                let result = store.with_store(kind, |engine| {
                    let native = resource
                        .retained
                        .get()
                        .expect("worker-owned initialized native resource");
                    operation(native, engine)
                });
                (resource, result)
            })
            .map_err(ProtectedStoreError::Io)
    }
}
