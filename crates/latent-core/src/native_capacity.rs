//! One node's physical request, work and response admission capacity.
//!
//! Reserve before native allocation or guest admission. Ordinary transactions
//! and queries share one finite partition; recovery uses a separate partition.
//! The original reservation, accepted worker and owned response/frame guards
//! retain capacity through actual destruction, including after ledger freeze,
//! deadline expiry or waiter loss. There are no per-request timers or workers.

mod buffer;
mod drain;
mod reservation;
mod types;

pub use buffer::{NativeBuffer, NativeBufferPermit};
pub use drain::NativeCapacityDrain;
pub use reservation::NativeReservation;
pub use types::{
    NativeAdmissionClass, NativeBufferClass, NativeCapacityError, NativeCapacityLimits,
    NativeCapacityPartition, NativeCapacityShutdown, NativeCapacitySnapshot,
    NativePartitionSnapshot, NativeReservationRequest,
};

use std::sync::{Arc, Mutex, MutexGuard};
use std::task::Waker;
use std::time::Instant;

use crate::{ActivationClock, SystemActivationClock};

/// Fixed state plus at most sixteen affine buffer-owner shells per admission.
/// Payload capacities are charged separately by their exact reservation fields.
pub const NATIVE_RESERVATION_METADATA_BYTES: u64 = 2_048;
pub const MAXIMUM_NATIVE_BUFFER_GUARDS: usize = 16;

struct State {
    usage: [NativePartitionSnapshot; 2],
    ordinary_closed: bool,
    closed: bool,
    quarantined: bool,
    retired_at: Option<Instant>,
    shutdown_deadline: Option<Instant>,
    next_waiter: u64,
    waiter: Option<(u64, Option<Waker>)>,
}

struct Owner {
    limits: NativeCapacityLimits,
    clock: Arc<dyn ActivationClock>,
    state: Mutex<State>,
}

/// Clones share the same counters and original physical reservations.
#[derive(Clone)]
pub struct NativeCapacityOwner(Arc<Owner>);

impl NativeCapacityOwner {
    pub fn new(limits: NativeCapacityLimits) -> Result<Self, NativeCapacityError> {
        Self::with_clock(limits, Arc::new(SystemActivationClock))
    }

    pub fn with_clock(
        limits: NativeCapacityLimits,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Self, NativeCapacityError> {
        limits.validate()?;
        Ok(Self(Arc::new(Owner {
            limits,
            clock,
            state: Mutex::new(State {
                usage: [NativePartitionSnapshot::default(); 2],
                ordinary_closed: false,
                closed: false,
                quarantined: false,
                retired_at: None,
                shutdown_deadline: None,
                next_waiter: 0,
                waiter: None,
            }),
        })))
    }

    #[must_use]
    pub fn is_same_owner(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.0, &other.0)
    }

    pub fn reserve(
        &self,
        class: NativeAdmissionClass,
        request: NativeReservationRequest,
        original_deadline: Instant,
    ) -> Result<NativeReservation, NativeCapacityError> {
        let bytes = request
            .payload_bytes()?
            .checked_add(NATIVE_RESERVATION_METADATA_BYTES)
            .ok_or(NativeCapacityError::InvalidRequest)?;
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| NativeCapacityError::Poisoned)?;
        self.0.check(&state, class, original_deadline)?;
        let remaining = original_deadline
            .checked_duration_since(self.0.clock.monotonic_now())
            .ok_or(NativeCapacityError::DeadlineExceeded)?;
        if remaining > self.0.limits.maximum_lifetime {
            return Err(NativeCapacityError::DeadlineTooLong);
        }
        let limits = self.0.limits.partition(class);
        if bytes > limits.maximum_reservation_bytes {
            return Err(NativeCapacityError::ReservationTooLarge);
        }
        let usage = &mut state.usage[class.index()];
        if usage.slots >= limits.slots {
            return Err(NativeCapacityError::SlotsFull);
        }
        if usage
            .bytes
            .checked_add(bytes)
            .is_none_or(|sum| sum > limits.bytes)
        {
            return Err(NativeCapacityError::BytesFull);
        }
        usage.slots += 1;
        usage.bytes += bytes;
        state.retired_at = None;
        Ok(NativeReservation::new(
            Arc::clone(&self.0),
            class,
            request,
            bytes,
            original_deadline,
        ))
    }

    /// Stop ordinary admission while retaining the bounded recovery partition.
    pub fn close_ordinary(&self) {
        self.0.lock_physical().ordinary_closed = true;
        self.0.wake();
    }

    pub fn close(&self) {
        self.0.lock_physical().closed = true;
        self.0.wake();
    }

    pub fn quarantine(&self) {
        let mut state = self.0.lock_physical();
        state.closed = true;
        state.quarantined = true;
        drop(state);
        self.0.wake();
    }

    pub fn snapshot(&self) -> Result<NativeCapacitySnapshot, NativeCapacityError> {
        self.0
            .state
            .lock()
            .map(|state| state.snapshot())
            .map_err(|_| NativeCapacityError::Poisoned)
    }

    /// One bounded node drain waiter, using its existing original-deadline timer.
    pub fn drain_async<F: std::future::Future<Output = ()>>(
        &self,
        original_deadline: Instant,
        deadline_wait: F,
    ) -> Result<NativeCapacityDrain<F>, NativeCapacityError> {
        NativeCapacityDrain::new(Arc::clone(&self.0), original_deadline, deadline_wait)
    }
}

impl Owner {
    fn lock_physical(&self) -> MutexGuard<'_, State> {
        match self.state.lock() {
            Ok(state) => state,
            Err(poisoned) => {
                let mut state = poisoned.into_inner();
                state.closed = true;
                state.quarantined = true;
                state
            }
        }
    }

    fn check(
        &self,
        state: &State,
        class: NativeAdmissionClass,
        deadline: Instant,
    ) -> Result<(), NativeCapacityError> {
        if state.quarantined {
            return Err(NativeCapacityError::Quarantined);
        }
        if state.closed || (class == NativeAdmissionClass::Ordinary && state.ordinary_closed) {
            return Err(NativeCapacityError::AdmissionClosed);
        }
        if self.clock.monotonic_now() >= deadline {
            return Err(NativeCapacityError::DeadlineExceeded);
        }
        Ok(())
    }

    fn wake(&self) {
        let waker = self
            .lock_physical()
            .waiter
            .as_ref()
            .and_then(|(_, waiter)| waiter.clone());
        if let Some(waker) = waker {
            waker.wake();
        }
    }
}

impl State {
    fn snapshot(&self) -> NativeCapacitySnapshot {
        NativeCapacitySnapshot {
            ordinary: self.usage[0],
            recovery: self.usage[1],
            ordinary_admission_closed: self.ordinary_closed || self.closed,
            admission_closed: self.closed,
            quarantined: self.quarantined,
        }
    }

    fn report(&mut self, timeout: bool) -> NativeCapacityShutdown {
        let retired = self.snapshot().physically_retired();
        if (timeout && !retired)
            || self
                .shutdown_deadline
                .is_some_and(|deadline| self.retired_at.is_some_and(|actual| actual > deadline))
        {
            self.quarantined = true;
        }
        let snapshot = self.snapshot();
        NativeCapacityShutdown {
            clean: retired && !self.quarantined,
            snapshot,
        }
    }
}

#[cfg(all(test, feature = "test-support"))]
mod tests;
