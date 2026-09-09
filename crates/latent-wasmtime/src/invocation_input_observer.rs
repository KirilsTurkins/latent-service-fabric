//! Opt-in, fixed-bound observations of the actual invocation input owner.
//!
//! No recorder handle retains a request, backend, Store, budget or runtime.
//! Disabled invocation hooks do no allocation, identity clone or lock acquisition.

mod guard;
mod model;
mod state;
#[cfg(test)]
mod tests;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Instant;

use latent_core::{ActivationId, PlatformError, PlatformErrorCode};

pub(crate) use guard::{InputTrace, InvocationObservation, RawGuard};
pub use model::{
    InvocationContextCharge, InvocationInputDropReason, InvocationInputIdentity,
    InvocationInputPhase, InvocationInputRecord, InvocationInputSnapshot,
};
use state::{Identity, State};

const MAXIMUM_IDENTITIES: usize = 8;
const MAXIMUM_IDENTITY_BYTES: usize = 512;
const MAXIMUM_RECORDS: usize = 64;

/// One independent diagnostic session; ordinary execution leaves it disabled.
#[derive(Clone)]
pub struct InvocationInputObserver {
    inner: Arc<Inner>,
}

struct Inner {
    enabled: AtomicBool,
    origin: Instant,
    state: Mutex<State>,
}

impl Inner {
    fn lock(&self) -> MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(|poisoned| {
            let mut state = poisoned.into_inner();
            state.overflowed = true;
            state
        })
    }
}

impl InvocationInputObserver {
    pub(crate) fn new() -> Self {
        Self {
            inner: Arc::new(Inner {
                enabled: AtomicBool::new(false),
                origin: Instant::now(),
                state: Mutex::new(State::default()),
            }),
        }
    }

    /// Enables one session before its invocations start. Unknown/reused IDs
    /// invalidate coverage; they never change an activation's result.
    pub fn enable(&self, activation_ids: &[ActivationId]) -> Result<(), PlatformError> {
        if activation_ids.is_empty()
            || activation_ids.len() > MAXIMUM_IDENTITIES
            || activation_ids.iter().enumerate().any(|(index, id)| {
                id.0.is_empty()
                    || id.0.len() > MAXIMUM_IDENTITY_BYTES
                    || activation_ids[..index].contains(id)
            })
        {
            return Err(invalid());
        }
        let identities = activation_ids
            .iter()
            .enumerate()
            .map(|(index, id)| Identity::new(u8::try_from(index).expect("eight identities"), id))
            .collect();
        let records = Vec::with_capacity(MAXIMUM_RECORDS);
        let mut state = self.inner.lock();
        if self.inner.enabled.load(Ordering::Acquire) {
            return Err(invalid());
        }
        state.identities = identities;
        state.records = records;
        self.inner.enabled.store(true, Ordering::Release);
        Ok(())
    }

    /// Process-monotonic diagnostic origin, independent of activation clocks.
    #[must_use]
    pub fn origin(&self) -> Instant {
        self.inner.origin
    }

    #[must_use]
    pub fn snapshot(&self) -> InvocationInputSnapshot {
        let mut state = self.inner.lock();
        let observed_nanos = state.now(self.inner.origin);
        state.snapshot(self.inner.enabled.load(Ordering::Acquire), observed_nanos)
    }

    pub(crate) fn begin(&self, activation_id: &ActivationId) -> Option<InvocationObservation> {
        if !self.inner.enabled.load(Ordering::Acquire) {
            return None;
        }
        let token = self.inner.lock().begin(activation_id)?;
        Some(InvocationObservation::new(InputTrace {
            inner: Arc::clone(&self.inner),
            token,
        }))
    }
}

fn invalid() -> PlatformError {
    crate::containment::platform_error(
        PlatformErrorCode::InvalidArgument,
        "invalid invocation input observation session",
        false,
    )
}
