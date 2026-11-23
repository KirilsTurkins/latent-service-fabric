//! One opt-in, fixed-size first-owner observation. It never admits, retains,
//! cancels or settles work and its absence cannot change a host result.
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
};

pub const ACTIVATION: &str = "go-lazy-first-owner";

#[derive(Clone, Copy, Debug, Default)]
pub struct Owner {
    pub before: usize,
    pub after: usize,
    pub capacity: usize,
    pub tasks: u32,
    pub other_owners: u32,
    pub live_token: bool,
    pub same_original_budget: bool,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct Snapshot {
    pub calls: u32,
    pub table_preexisting: bool,
    pub granted_bytes: u64,
    pub owner: Owner,
}

static ARMED: AtomicBool = AtomicBool::new(false);
static LOST: AtomicBool = AtomicBool::new(false);
static RECORD: Mutex<Option<Snapshot>> = Mutex::new(None);

pub struct Guard;

/// Arm the one fixed activation for one comparison process. No arbitrary
/// guest identity or capability token is stored in the observer.
pub fn arm() -> Option<Guard> {
    if ARMED
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return None;
    }
    let Ok(mut record) = RECORD.try_lock() else {
        ARMED.store(false, Ordering::SeqCst);
        return None;
    };
    *record = Some(Snapshot::default());
    LOST.store(false, Ordering::SeqCst);
    Some(Guard)
}

impl Guard {
    pub fn snapshot(&self) -> Option<Snapshot> {
        if LOST.load(Ordering::SeqCst) {
            return None;
        }
        RECORD.try_lock().ok()?.as_ref().copied()
    }
}

impl Drop for Guard {
    fn drop(&mut self) {
        ARMED.store(false, Ordering::SeqCst);
        if let Ok(mut record) = RECORD.try_lock() {
            *record = None;
        }
    }
}

pub(crate) fn selected(activation: &str, operation: &str) -> bool {
    ARMED.load(Ordering::SeqCst) && activation == ACTIVATION && operation == "register"
}

pub(crate) fn record(mut event: Snapshot) {
    if let Ok(mut slot) = RECORD.try_lock() {
        if let Some(first) = slot.as_mut() {
            if first.calls == 0 {
                event.calls = 1;
                *first = event;
            } else {
                first.calls = first.calls.saturating_add(1);
            }
            return;
        }
    }
    LOST.store(true, Ordering::SeqCst);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn observation_is_opt_in_fixed_and_detects_duplicates() {
        assert!(!selected(ACTIVATION, "register"));
        let guard = arm().unwrap();
        assert!(arm().is_none());
        assert!(!selected("another-activation", "register"));
        assert!(!selected(ACTIVATION, "settle"));
        assert!(selected(ACTIVATION, "register"));
        assert_eq!(guard.snapshot().unwrap().calls, 0);
        record(Snapshot {
            granted_bytes: 42,
            owner: Owner {
                before: 0,
                after: 1,
                capacity: 1,
                tasks: 1,
                other_owners: 0,
                live_token: true,
                same_original_budget: true,
            },
            ..Snapshot::default()
        });
        let first = guard.snapshot().unwrap();
        assert_eq!(first.calls, 1);
        assert_eq!(first.granted_bytes, 42);
        assert_eq!(first.owner.capacity, 1);
        record(Snapshot::default());
        assert_eq!(guard.snapshot().unwrap().calls, 2);
        assert_eq!(guard.snapshot().unwrap().granted_bytes, 42);
        drop(guard);
        assert!(!selected(ACTIVATION, "register"));
    }
}
