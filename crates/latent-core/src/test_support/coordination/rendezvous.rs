use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::task::{Context, Poll, Waker};

use super::{with_watchdog, WATCHDOG};

// Opaque identities never repeat across fixture instances or recycled slots.
// Business/request identifiers remain supplied by DeterministicIds, separately.
static NEXT_REGISTRATION: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stage {
    Requested,
    Queued,
    Entered,
    CancellationObserved,
    Retired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CoordinationError {
    Capacity,
    StaleRegistration,
    MissingReadiness,
    WrongStage,
    InvalidTransition,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Registration {
    slot: usize,
    generation: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PauseTicket {
    registration: Registration,
    epoch: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Snapshot {
    pub stage: Stage,
    pub blocked: bool,
}

#[derive(Debug)]
struct Slot {
    generation: u64,
    stage: Stage,
    epoch: u64,
    blocked: bool,
    released: bool,
    waker: Option<Waker>,
}

/// Fixed-capacity metadata only: observers never retain work or buffers.
#[derive(Debug, Clone)]
pub struct Rendezvous(Arc<Mutex<Vec<Slot>>>);

impl Rendezvous {
    #[must_use]
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0, "rendezvous capacity must be nonzero");
        Self(Arc::new(Mutex::new(
            (0..capacity)
                .map(|_| Slot {
                    generation: 0,
                    stage: Stage::Retired,
                    epoch: 0,
                    blocked: false,
                    released: false,
                    waker: None,
                })
                .collect(),
        )))
    }

    fn lock(&self) -> MutexGuard<'_, Vec<Slot>> {
        self.0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub fn track<T>(&self, owner: T) -> Result<(Registration, Tracked<T>), CoordinationError> {
        let mut slots = self.lock();
        let (index, slot) = slots
            .iter_mut()
            .enumerate()
            .find(|(_, slot)| slot.stage == Stage::Retired)
            .ok_or(CoordinationError::Capacity)?;
        slot.generation = NEXT_REGISTRATION
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
                current.checked_add(1)
            })
            .map_err(|_| CoordinationError::Capacity)?;
        slot.stage = Stage::Requested;
        slot.epoch = 0;
        slot.blocked = false;
        slot.released = false;
        slot.waker = None;
        let registration = Registration {
            slot: index,
            generation: slot.generation,
        };
        Ok((
            registration,
            Tracked {
                rendezvous: self.clone(),
                registration,
                owner: Some(owner),
            },
        ))
    }

    fn slot(
        slots: &mut [Slot],
        registration: Registration,
    ) -> Result<&mut Slot, CoordinationError> {
        slots
            .get_mut(registration.slot)
            .filter(|slot| slot.generation == registration.generation)
            .ok_or(CoordinationError::StaleRegistration)
    }

    pub fn snapshot(&self, registration: Registration) -> Result<Snapshot, CoordinationError> {
        let mut slots = self.lock();
        let slot = Self::slot(&mut slots, registration)?;
        Ok(Snapshot {
            stage: slot.stage,
            blocked: slot.blocked,
        })
    }

    /// Checks current readiness and returns a ticket for this specific pause.
    pub fn blocked(
        &self,
        registration: Registration,
        stage: Stage,
    ) -> Result<PauseTicket, CoordinationError> {
        let mut slots = self.lock();
        let slot = Self::slot(&mut slots, registration)?;
        if slot.stage != stage {
            return Err(CoordinationError::WrongStage);
        }
        if !slot.blocked {
            return Err(CoordinationError::MissingReadiness);
        }
        Ok(PauseTicket {
            registration,
            epoch: slot.epoch,
        })
    }

    pub fn release(&self, ticket: PauseTicket) -> Result<(), CoordinationError> {
        let waker = {
            let mut slots = self.lock();
            let slot = Self::slot(&mut slots, ticket.registration)?;
            if slot.epoch != ticket.epoch {
                return Err(CoordinationError::StaleRegistration);
            }
            if !slot.blocked {
                return Err(CoordinationError::MissingReadiness);
            }
            slot.blocked = false;
            slot.released = true;
            slot.waker.take()
        };
        if let Some(waker) = waker {
            waker.wake();
        }
        Ok(())
    }

    pub fn require_retired(&self, registration: Registration) -> Result<(), CoordinationError> {
        if self.snapshot(registration)?.stage == Stage::Retired {
            Ok(())
        } else {
            Err(CoordinationError::WrongStage)
        }
    }

    #[must_use]
    pub fn live_owners(&self) -> usize {
        self.lock()
            .iter()
            .filter(|slot| slot.stage != Stage::Retired)
            .count()
    }
}

/// The owner is destroyed before retirement is committed, including unwinding.
/// There is deliberately no `take_owner` or manual `retire` shortcut.
#[derive(Debug)]
pub struct Tracked<T> {
    rendezvous: Rendezvous,
    registration: Registration,
    owner: Option<T>,
}

impl<T> Tracked<T> {
    #[must_use]
    pub fn owner(&self) -> &T {
        self.owner.as_ref().expect("live tracked owner")
    }

    /// Call only after observing the corresponding real subsystem transition.
    pub fn commit(&mut self, stage: Stage) -> Result<(), CoordinationError> {
        let mut slots = self.rendezvous.lock();
        let slot = Rendezvous::slot(&mut slots, self.registration)?;
        let legal = matches!(
            (slot.stage, stage),
            (
                Stage::Requested,
                Stage::Queued | Stage::Entered | Stage::CancellationObserved
            ) | (Stage::Queued, Stage::Entered | Stage::CancellationObserved)
                | (Stage::Entered, Stage::CancellationObserved)
        );
        if !legal || slot.blocked {
            return Err(CoordinationError::InvalidTransition);
        }
        slot.stage = stage;
        Ok(())
    }

    /// Parks until the controller releases this *live* pause; cancellation drops
    /// its registration. Each wait has an independent real-clock watchdog.
    pub async fn pause(&mut self) {
        with_watchdog(
            WATCHDOG,
            Gate {
                rendezvous: self.rendezvous.clone(),
                registration: self.registration,
                epoch: None,
            },
        )
        .await;
    }
}

struct Retirement<'a>(&'a Rendezvous, Registration);

impl Drop for Retirement<'_> {
    fn drop(&mut self) {
        let mut slots = self.0.lock();
        if let Ok(slot) = Rendezvous::slot(&mut slots, self.1) {
            slot.stage = Stage::Retired;
            slot.blocked = false;
            slot.waker = None;
        }
    }
}

impl<T> Drop for Tracked<T> {
    fn drop(&mut self) {
        let _retirement = Retirement(&self.rendezvous, self.registration);
        drop(self.owner.take());
    }
}

struct Gate {
    rendezvous: Rendezvous,
    registration: Registration,
    epoch: Option<u64>,
}

impl Future for Gate {
    type Output = ();

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
        let this = self.get_mut();
        let mut slots = this.rendezvous.lock();
        let slot = Rendezvous::slot(&mut slots, this.registration).expect("live work owner");
        if this.epoch.is_some() && slot.released {
            return Poll::Ready(());
        }
        if this.epoch.is_none() {
            slot.epoch = slot
                .epoch
                .checked_add(1)
                .expect("pause generation exhausted");
            this.epoch = Some(slot.epoch);
            slot.released = false;
            slot.blocked = true;
        }
        slot.waker = Some(cx.waker().clone());
        Poll::Pending
    }
}

impl Drop for Gate {
    fn drop(&mut self) {
        let mut slots = self.rendezvous.lock();
        if let Ok(slot) = Rendezvous::slot(&mut slots, self.registration) {
            if self.epoch == Some(slot.epoch) {
                slot.blocked = false;
                slot.waker = None;
            }
        }
    }
}
