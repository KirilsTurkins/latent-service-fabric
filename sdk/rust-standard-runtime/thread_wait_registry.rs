// SPDX-License-Identifier: MIT OR Apache-2.0
//! Nonsuspending state for real selected std waiters. An engine host-await is
//! not an explicitly suspended canonical thread and must never be resumed by
//! thread.resume-later. Every returned action is performed after this borrow.
use super::Token;

pub(crate) const MAX_WAITS: usize = 32;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Error {
    Capacity,
    Stale,
    Identity,
    State,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Domain {
    CanonicalSuspend,
    EngineTimerAwait { timer: Token },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Phase {
    Prepared,
    Waiting,
    Notified,
    TimerElapsed,
}

#[derive(Clone, Copy)]
struct Record {
    wait: Token,
    canonical: u32,
    pointer: usize,
    domain: Domain,
    phase: Phase,
    await_live: bool,
    stop_claimed: bool,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Reservation {
    slot: usize,
    serial: u64,
    canonical: u32,
}

impl Reservation {
    pub(crate) fn slot(self) -> usize {
        self.slot
    }
}

/// A real typed host stop or canonical resumption, never a dispatch fallback.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Wake {
    BeforeSuspension,
    ResumeExplicitlySuspended { canonical: u32 },
    StopTimer { timer: Token },
    AlreadyReady,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Start {
    AlreadyNotified,
    SuspendCanonical,
    AwaitTimer { timer: Token },
}

pub(crate) struct Registry {
    records: [Option<Record>; MAX_WAITS],
    reservations: [Option<Reservation>; MAX_WAITS],
    serial: u64,
}

impl Registry {
    pub(crate) const fn new() -> Self {
        Self {
            records: [None; MAX_WAITS],
            reservations: [None; MAX_WAITS],
            serial: 0,
        }
    }

    /// Claim fixed registry capacity BEFORE broker admission or allocation.
    /// Other canonical threads may run during admission; this Copy ticket
    /// keeps their accepted waits from taking the same prepaid slot.
    pub(crate) fn reserve(&mut self, canonical: u32) -> Result<Reservation, Error> {
        if self
            .records
            .iter()
            .flatten()
            .any(|r| r.canonical == canonical)
            || self
                .reservations
                .iter()
                .flatten()
                .any(|r| r.canonical == canonical)
        {
            return Err(Error::Identity);
        }
        let slot = (0..MAX_WAITS)
            .find(|&slot| self.records[slot].is_none() && self.reservations[slot].is_none())
            .ok_or(Error::Capacity)?;
        self.serial = self.serial.checked_add(1).ok_or(Error::Capacity)?;
        let reservation = Reservation {
            slot,
            serial: self.serial,
            canonical,
        };
        self.reservations[slot] = Some(reservation);
        Ok(reservation)
    }
    pub(crate) fn cancel(&mut self, reservation: Reservation) -> Result<(), Error> {
        let slot = self
            .reservations
            .get_mut(reservation.slot)
            .ok_or(Error::Stale)?;
        if *slot != Some(reservation) {
            return Err(Error::Stale);
        }
        *slot = None;
        Ok(())
    }

    /// The original Wait/Timer owners and the reserved fixed node slot already
    /// exist. This table admits no owner and publishes no uncharged allocation.
    pub(crate) fn install(
        &mut self,
        reservation: Reservation,
        wait: Token,
        canonical: u32,
        pointer: usize,
        domain: Domain,
    ) -> Result<(), Error> {
        if reservation.canonical != canonical
            || self.reservations.get(reservation.slot) != Some(&Some(reservation))
            || self.records[reservation.slot].is_some()
            || !wait.valid()
            || pointer == 0
            || pointer % crate::mem::align_of::<Token>() != 0
            || matches!(domain, Domain::EngineTimerAwait { timer } if !timer.valid() || timer == wait)
            || self.records.iter().flatten().any(|row| {
                row.wait == wait
                    || row.pointer == pointer
                    || row.canonical == canonical
                    || matches!(domain, Domain::EngineTimerAwait { timer } if row.wait == timer)
                    || matches!(row.domain, Domain::EngineTimerAwait { timer } if timer == wait)
                    || matches!((row.domain, domain),
                        (Domain::EngineTimerAwait { timer: old }, Domain::EngineTimerAwait { timer: new })
                        if old == new)
            })
        {
            return Err(Error::Identity);
        }
        self.records[reservation.slot] = Some(Record {
            wait,
            canonical,
            pointer,
            domain,
            phase: Phase::Prepared,
            await_live: false,
            stop_claimed: false,
        });
        self.reservations[reservation.slot] = None;
        Ok(())
    }

    #[cfg(test)]
    pub(crate) fn insert(
        &mut self,
        wait: Token,
        canonical: u32,
        pointer: usize,
        domain: Domain,
    ) -> Result<(), Error> {
        let ticket = self.reserve(canonical)?;
        let result = self.install(ticket, wait, canonical, pointer, domain);
        if result.is_err() {
            self.cancel(ticket)?;
        }
        result
    }

    /// Publish Waiting only after the caller has parked its original Task.
    /// No yielding host call may intervene before the returned suspension.
    pub(crate) fn start(&mut self, wait: Token, canonical: u32) -> Result<Start, Error> {
        let row = self.find(wait)?;
        if row.canonical != canonical || row.await_live {
            return Err(Error::Identity);
        }
        match row.phase {
            Phase::Notified => Ok(Start::AlreadyNotified),
            Phase::Prepared => {
                row.phase = Phase::Waiting;
                row.await_live = true;
                Ok(match row.domain {
                    Domain::CanonicalSuspend => Start::SuspendCanonical,
                    Domain::EngineTimerAwait { timer } => Start::AwaitTimer { timer },
                })
            }
            _ => Err(Error::State),
        }
    }

    /// The intrusive queue has already unlinked its node, installed ownership
    /// handoff and set Notified. No node access follows the resulting host call.
    pub(crate) fn notify(&mut self, wait: Token, canonical: u32) -> Result<Wake, Error> {
        let row = self.find(wait)?;
        if row.canonical != canonical {
            return Err(Error::Identity);
        }
        let action = match row.phase {
            Phase::Prepared => Wake::BeforeSuspension,
            Phase::Waiting => match row.domain {
                Domain::CanonicalSuspend => Wake::ResumeExplicitlySuspended { canonical },
                Domain::EngineTimerAwait { timer } => Wake::StopTimer { timer },
            },
            Phase::Notified | Phase::TimerElapsed => return Ok(Wake::AlreadyReady),
        };
        row.phase = Phase::Notified;
        row.stop_claimed = matches!(action, Wake::StopTimer { .. });
        Ok(action)
    }

    /// The actual canonical suspend or typed timer future returned to THIS
    /// waiter. A notification cannot unregister/free a still-awaiting frame.
    pub(crate) fn returned(&mut self, wait: Token, canonical: u32) -> Result<(), Error> {
        let row = self.find(wait)?;
        if row.canonical != canonical || !row.await_live {
            return Err(Error::Identity);
        }
        if row.phase != Phase::Notified && row.phase != Phase::TimerElapsed {
            return Err(Error::State);
        }
        row.await_live = false;
        Ok(())
    }

    /// Call only for successful typed timer readiness, never for a cancelled,
    /// deadline, provider-error or generic engine result. Re-lookup after await.
    /// The bool selects whether the intrusive node should be marked elapsed;
    /// a prior real notification wins without fabricating timer completion.
    pub(crate) fn elapsed(
        &mut self,
        wait: Token,
        timer: Token,
        canonical: u32,
    ) -> Result<bool, Error> {
        let row = self.find(wait)?;
        if row.canonical != canonical
            || row.domain != (Domain::EngineTimerAwait { timer })
            || !row.await_live
        {
            return Err(Error::Identity);
        }
        match row.phase {
            Phase::Waiting => {
                row.phase = Phase::TimerElapsed;
                Ok(true)
            }
            Phase::Notified => Ok(false),
            _ => Err(Error::State),
        }
    }

    /// Return a copy only. The caller must drop its registry borrow before
    /// dereferencing the stable node and must not retain it through any await.
    pub(crate) fn pointer(&self, wait: Token, canonical: u32) -> Result<usize, Error> {
        self.records
            .iter()
            .flatten()
            .find(|row| row.wait == wait && row.canonical == canonical)
            .map(|row| row.pointer)
            .ok_or(Error::Stale)
    }

    pub(crate) fn remove(
        &mut self,
        wait: Token,
        canonical: u32,
        pointer: usize,
    ) -> Result<Option<Token>, Error> {
        let slot = self
            .records
            .iter_mut()
            .find(|slot| slot.is_some_and(|row| row.wait == wait))
            .ok_or(Error::Stale)?;
        let row = slot.unwrap();
        if row.canonical != canonical || row.pointer != pointer {
            return Err(Error::Identity);
        }
        if row.await_live || row.phase == Phase::Waiting {
            return Err(Error::State);
        }
        *slot = None;
        // A notifier claims the stop BEFORE its real host call. It does not
        // touch this row again: the resumed waiter may remove it during that
        // call. The host's pending call/TimerWait retains physical ownership.
        Ok(match row.domain {
            Domain::EngineTimerAwait { timer } if !row.stop_claimed => Some(timer),
            _ => None,
        })
    }

    pub(crate) fn notified(&self, wait: Token, canonical: u32) -> Result<bool, Error> {
        self.records
            .iter()
            .flatten()
            .find(|row| row.wait == wait && row.canonical == canonical)
            .map(|row| row.phase == Phase::Notified)
            .ok_or(Error::Stale)
    }

    pub(crate) fn is_empty(&self) -> bool {
        self.records.iter().all(Option::is_none) && self.reservations.iter().all(Option::is_none)
    }

    fn find(&mut self, wait: Token) -> Result<&mut Record, Error> {
        self.records
            .iter_mut()
            .flatten()
            .find(|row| row.wait == wait)
            .ok_or(Error::Stale)
    }
}
