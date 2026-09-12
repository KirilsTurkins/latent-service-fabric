//! Affine decoded/encoding allowance, retained through the final transport frame.

use crate::{busy, capacity, CoordinatorLimits, Result};
use std::sync::{Arc, Mutex};

pub(crate) struct PageBudget {
    state: Mutex<(usize, usize)>,
    owners: usize,
    bytes: usize,
    page: usize,
}

impl PageBudget {
    pub(crate) fn new(limits: CoordinatorLimits) -> Arc<Self> {
        Arc::new(Self {
            state: Mutex::new((0, 0)),
            owners: limits.maximum_query_owners,
            bytes: limits.maximum_total_page_bytes,
            page: limits.maximum_page_bytes,
        })
    }

    pub(crate) fn reserve(self: &Arc<Self>, encoded_bytes: usize) -> Result<ResponseLease> {
        if encoded_bytes < 4096 || encoded_bytes > self.page {
            return Err(capacity("rollout-response-size"));
        }
        let bytes = encoded_bytes
            .checked_mul(4)
            .ok_or_else(|| capacity("rollout-response-size"))?;
        let mut state = self.state.try_lock().map_err(|_| busy())?;
        if state.0 >= self.owners || bytes > self.bytes - state.1 {
            return Err(capacity("rollout-response-capacity"));
        }
        state.0 += 1;
        state.1 += bytes;
        Ok(ResponseLease(Arc::new(Charge {
            budget: Arc::clone(self),
            bytes,
        })))
    }

    pub(crate) fn snapshot(&self) -> (usize, usize) {
        *self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

struct Charge {
    budget: Arc<PageBudget>,
    bytes: usize,
}

impl Drop for Charge {
    fn drop(&mut self) {
        let mut state = self
            .budget
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.0 -= 1;
        state.1 -= self.bytes;
    }
}

/// Keep this opaque allowance alive while response data or encoded frames live.
#[derive(Clone)]
pub struct ResponseLease(Arc<Charge>);

impl ResponseLease {
    #[must_use]
    pub fn reserved_bytes(&self) -> usize {
        self.0.bytes
    }
}

/// Payload drops before its allowance. Extraction transfers both obligations.
pub struct OwnedResponse<T> {
    pub(crate) value: T,
    pub(crate) lease: ResponseLease,
}

impl<T> OwnedResponse<T> {
    #[must_use]
    pub fn value(&self) -> &T {
        &self.value
    }

    #[must_use]
    pub fn into_parts(self) -> (T, ResponseLease) {
        (self.value, self.lease)
    }
}
