use std::any::Any;
use std::sync::Arc;

use super::job::Reservation;
use super::retirement::{RetirementSignal, StoreIoRetirement, StoreIoRetirementWitness};
use super::state::{Control, Retirement};
use super::{StoreIoError, StoreIoOwner};

struct PhysicalReservation<S>(Reservation<S>);

impl<S> Drop for PhysicalReservation<S> {
    fn drop(&mut self) {
        {
            let mut state = self
                .0
                .control
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.physical_owners -= 1;
        }
        self.0.control.notify();
    }
}

struct Retained<S, T> {
    value: Option<T>,
    owner: Option<Arc<dyn Any + Send + Sync>>,
    reservation: PhysicalReservation<S>,
    retired: Arc<RetirementSignal>,
    witness_issued: bool,
    custody: Option<u64>,
}

impl<S: Send + 'static, T: Send + 'static> Retirement for Retained<S, T> {
    fn retire(self: Box<Self>) {
        let Self {
            value,
            owner,
            reservation,
            retired,
            witness_issued: _,
            custody,
        } = *self;
        let control = Arc::clone(&reservation.0.control);
        // Native handle destruction precedes physical ownership/byte refund.
        if custody.is_some() {
            if std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(value))).is_err() {
                // Native retirement was not positively observed. Keep the
                // bounded original keeper/pin charged until process loss;
                // unwinding must not reopen custody or refund its capacity.
                control.fail(StoreIoError::RecoveryRequired);
                std::mem::forget(owner);
                std::mem::forget(reservation);
                return;
            }
        } else {
            drop(value);
        }
        drop(owner);
        drop(reservation);
        if let Some(sequence) = custody {
            {
                let mut state = control
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                if let Some(custody) = &mut state.custody {
                    if custody.sequence == sequence {
                        custody.physically_retired = true;
                    }
                }
                state.release_retired_custody();
            }
            control.notify();
        }
        retired.complete();
    }
}

/// An affine native resource with a pre-reserved worker retirement slot.
/// Drop queues actual destruction on the fixed workers, including after close
/// or quarantine. A live resource prevents engine finalization.
pub struct StoreIoRetained<S: Send + 'static, T: Send + 'static> {
    control: Arc<Control<S>>,
    retained: Option<Box<Retained<S, T>>>,
}

impl<S: Send + Sync + 'static> StoreIoOwner<S> {
    /// Reserve before opening a native view or allocating its owned metadata.
    pub fn reserve_retained<T: Send + 'static>(
        &self,
        retained_bytes: u64,
    ) -> Result<StoreIoRetained<S, T>, StoreIoError> {
        self.reserve_in(false, retained_bytes, None)
    }

    /// The same affine physical owner, admitted and retired exclusively in the
    /// existing recovery partition. Ordinary native cleanup cannot consume its
    /// reserved fixed worker or preallocated retirement slots.
    pub fn reserve_recovery_retained<T: Send + 'static>(
        &self,
        retained_bytes: u64,
    ) -> Result<StoreIoRetained<S, T>, StoreIoError> {
        self.reserve_in(true, retained_bytes, None)
    }

    pub(crate) fn reserve_custody_retained<T: Send + 'static>(
        &self,
        retained_bytes: u64,
        deadline: std::time::Instant,
    ) -> Result<StoreIoRetained<S, T>, StoreIoError> {
        self.reserve_in(true, retained_bytes, Some(deadline))
    }

    fn reserve_in<T: Send + 'static>(
        &self,
        recovery: bool,
        retained_bytes: u64,
        custody_deadline: Option<std::time::Instant>,
    ) -> Result<StoreIoRetained<S, T>, StoreIoError> {
        let control = &self.inner.control;
        let mut state = control.state.lock().map_err(|_| StoreIoError::Poisoned)?;
        let metadata = std::mem::size_of::<Retained<S, T>>()
            // Box/Arc headers, preallocated retirement receipt and queue slot.
            .checked_add(192)
            .ok_or(StoreIoError::Exhausted)?;
        let metadata = u64::try_from(metadata).map_err(|_| StoreIoError::Exhausted)?;
        let bytes = retained_bytes
            .checked_add(metadata)
            .ok_or(StoreIoError::Exhausted)?;
        if custody_deadline.is_some() {
            state.require_idle_custody()?;
        }
        state.admit(recovery, bytes)?;
        let custody = if let Some(deadline) = custody_deadline {
            if control.clock.monotonic_now() >= deadline {
                return Err(StoreIoError::CustodyExpired);
            }
            let sequence = state
                .next_custody
                .checked_add(1)
                .ok_or(StoreIoError::Exhausted)?;
            state.next_custody = sequence;
            state.custody = Some(super::state::CustodyState {
                sequence,
                deadline,
                physically_retired: false,
            });
            Some(sequence)
        } else {
            None
        };
        state.reserve(recovery, bytes);
        state.physical_owners += 1;
        let retained = Box::new(Retained {
            value: None,
            owner: None,
            reservation: PhysicalReservation(Reservation {
                control: Arc::clone(control),
                bytes,
                recovery,
                keeper: None,
            }),
            retired: Arc::new(RetirementSignal::default()),
            witness_issued: false,
            custody,
        });
        Ok(StoreIoRetained {
            control: Arc::clone(control),
            retained: Some(retained),
        })
    }
}

impl<S: Send + 'static, T: Send + 'static> StoreIoRetained<S, T> {
    /// Bind one original capacity/authority keeper before native allocation and
    /// submission. The caller pre-reserves its own keeper metadata. Retirement
    /// destroys the actual native value before dropping this owner, then releases
    /// the storage reservation and completes the existing retirement signal.
    /// A rejected keeper is returned unchanged and cannot replace an earlier one.
    pub fn retain_owner(
        &mut self,
        owner: Arc<dyn Any + Send + Sync>,
    ) -> Result<(), Arc<dyn Any + Send + Sync>> {
        let retained = self.retained.as_mut().expect("affine resource owner");
        if retained.value.is_some() || retained.owner.is_some() {
            return Err(owner);
        }
        retained.owner = Some(owner);
        Ok(())
    }

    /// Issue at most one non-clone observer across all moves of this resource.
    /// It shares pre-reserved metadata and leaves the single receipt waiter free.
    pub fn retirement_witness(&mut self) -> Option<StoreIoRetirementWitness> {
        let retained = self.retained.as_mut().expect("affine resource owner");
        if retained.witness_issued {
            return None;
        }
        retained.witness_issued = true;
        Some(StoreIoRetirementWitness::new(Arc::clone(&retained.retired)))
    }

    /// Enqueue the pre-reserved cleanup and observe actual worker retirement.
    /// A receipt that is dropped never refunds or cancels accepted destruction.
    pub fn retire(mut self) -> StoreIoRetirement {
        let retired = Arc::clone(
            &self
                .retained
                .as_ref()
                .expect("affine resource owner")
                .retired,
        );
        self.enqueue_retirement();
        StoreIoRetirement::new(retired)
    }

    fn enqueue_retirement(&mut self) {
        if let Some(retained) = self.retained.take() {
            {
                let mut state = self
                    .control
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                if retained.reservation.0.recovery {
                    state.recovery_retirements.push_back(retained);
                } else {
                    state.retirements.push_back(retained);
                }
            }
            self.control.notify();
        }
    }

    /// Attach only on a physical worker after the resource has been opened.
    pub fn attach(&mut self, value: T) -> Result<(), T> {
        let retained = self.retained.as_mut().expect("affine resource owner");
        if retained.value.is_some() {
            return Err(value);
        }
        retained.value = Some(value);
        Ok(())
    }

    pub(crate) fn get(&self) -> Option<&T> {
        self.retained.as_ref()?.value.as_ref()
    }

    pub(crate) fn custody_sequence(&self) -> Option<u64> {
        self.retained.as_ref()?.custody
    }

    pub(crate) fn belongs_to(&self, owner: &StoreIoOwner<S>) -> bool {
        Arc::ptr_eq(&self.control, &owner.inner.control)
    }
}

impl<S: Send + 'static, T: Send + 'static> Drop for StoreIoRetained<S, T> {
    fn drop(&mut self) {
        self.enqueue_retirement();
    }
}
