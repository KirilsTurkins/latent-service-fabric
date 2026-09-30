use std::sync::Arc;

use super::job::Reservation;
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
    reservation: PhysicalReservation<S>,
}

impl<S: Send + 'static, T: Send + 'static> Retirement for Retained<S, T> {
    fn retire(self: Box<Self>) {
        let Self { value, reservation } = *self;
        // Native handle destruction precedes physical ownership/byte refund.
        drop(value);
        drop(reservation);
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
        let control = &self.inner.control;
        let mut state = control.state.lock().map_err(|_| StoreIoError::Poisoned)?;
        let metadata = std::mem::size_of::<Retained<S, T>>()
            .checked_add(64)
            .ok_or(StoreIoError::Exhausted)?;
        let metadata = u64::try_from(metadata).map_err(|_| StoreIoError::Exhausted)?;
        let bytes = retained_bytes
            .checked_add(metadata)
            .ok_or(StoreIoError::Exhausted)?;
        state.admit(bytes)?;
        state.accepted += 1;
        state.physical_owners += 1;
        state.retained_bytes += bytes;
        let retained = Box::new(Retained {
            value: None,
            reservation: PhysicalReservation(Reservation {
                control: Arc::clone(control),
                bytes,
            }),
        });
        Ok(StoreIoRetained {
            control: Arc::clone(control),
            retained: Some(retained),
        })
    }
}

impl<S: Send + 'static, T: Send + 'static> StoreIoRetained<S, T> {
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

    pub(crate) fn belongs_to(&self, owner: &StoreIoOwner<S>) -> bool {
        Arc::ptr_eq(&self.control, &owner.inner.control)
    }
}

impl<S: Send + 'static, T: Send + 'static> Drop for StoreIoRetained<S, T> {
    fn drop(&mut self) {
        if let Some(retained) = self.retained.take() {
            {
                let mut state = self
                    .control
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                // Capacity was reserved before native-resource creation.
                state.retirements.push_back(retained);
            }
            self.control.notify();
        }
    }
}
