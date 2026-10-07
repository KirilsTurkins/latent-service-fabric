//! Exclusive recovery custody, derived from the original physical owner.

use std::any::Any;
use std::sync::Arc;
use std::time::Instant;

use super::{
    StoreIoError, StoreIoJob, StoreIoKind, StoreIoOwner, StoreIoRetained, StoreIoRetirement,
    StoreIoRetirementWitness,
};

/// Private affine evidence: admission was reserved atomically while every
/// previously accepted callback, response, native view and operation pin had
/// physically retired. Neither a caller-provided clean flag nor an ID can
/// construct this owner. The original fixed workers perform its destruction.
pub(crate) struct StoreIoCustody<S: Send + 'static, T: Send + 'static> {
    retained: StoreIoRetained<S, T>,
}

pub(crate) type StoreIoCustodyJob<S, T, R> = StoreIoJob<(StoreIoCustody<S, T>, R)>;

impl<S: Send + Sync + 'static> StoreIoOwner<S> {
    pub(crate) fn reserve_custody<T: Send + 'static>(
        &self,
        bytes: u64,
        deadline: Instant,
        keeper: Arc<dyn Any + Send + Sync>,
    ) -> Result<StoreIoCustody<S, T>, StoreIoError> {
        let mut retained = self.reserve_custody_retained(bytes, deadline)?;
        retained
            .retain_owner(keeper)
            .map_err(|_| StoreIoError::CustodyMismatch)?;
        Ok(StoreIoCustody { retained })
    }

    /// Consuming the resource keeps custody in the queued/physical callback and
    /// unclaimed response. Waiter loss cannot reopen ordinary/recovery admission.
    pub(crate) fn submit_custody<T: Send + 'static, R: Send + 'static>(
        &self,
        mut custody: StoreIoCustody<S, T>,
        kind: StoreIoKind,
        bytes: u64,
        operation: impl FnOnce(&mut StoreIoCustody<S, T>, &S) -> R + Send + 'static,
    ) -> Result<StoreIoCustodyJob<S, T, R>, StoreIoError> {
        if !custody.retained.belongs_to(self) || !kind.is_recovery() {
            return Err(StoreIoError::CustodyMismatch);
        }
        let sequence = custody
            .retained
            .custody_sequence()
            .ok_or(StoreIoError::CustodyMismatch)?;
        self.submit_inner(kind, bytes, None, Some(sequence), move |store| {
            let result = operation(&mut custody, store);
            (custody, result)
        })
        .map_err(|error| error.reason)
    }
}

impl<S: Send + 'static, T: Send + 'static> StoreIoCustody<S, T> {
    pub(crate) fn attach(&mut self, value: T) -> Result<(), T> {
        self.retained.attach(value)
    }

    pub(crate) fn get(&self) -> Option<&T> {
        self.retained.get()
    }

    pub(crate) fn retirement_witness(&mut self) -> Option<StoreIoRetirementWitness> {
        self.retained.retirement_witness()
    }

    pub(crate) fn retire(self) -> StoreIoRetirement {
        self.retained.retire()
    }
}
