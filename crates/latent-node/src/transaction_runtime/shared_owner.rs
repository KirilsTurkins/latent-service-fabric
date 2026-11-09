//! Affine handoff decision for one already-reserved command lifecycle.
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

const CLOSED: usize = 1 << (usize::BITS - 1);

/// This grants no execution authority and owns no task or native capacity.
/// The transport retains the actual activation and its previously reserved slot.
#[derive(Default)]
pub struct SharedCommandOwner {
    state: AtomicUsize,
}

impl SharedCommandOwner {
    /// Attach only after current authorization and the duplicate waiter cap.
    pub(crate) fn try_subscribe(self: &Arc<Self>) -> Option<SharedCommandWaiter> {
        let mut state = self.state.load(Ordering::Acquire);
        loop {
            if state & CLOSED != 0 || state == CLOSED - 1 {
                return None;
            }
            match self.state.compare_exchange_weak(
                state,
                state + 1,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => return Some(SharedCommandWaiter(Arc::clone(self))),
                Err(current) => state = current,
            }
        }
    }

    /// Atomically close sponsorship and decide whether an accepted waiter
    /// covered the original transport loss. The original deadline is unchanged.
    pub fn close_for_disconnect(&self) -> bool {
        let previous = self.state.fetch_or(CLOSED, Ordering::AcqRel);
        previous & CLOSED == 0 && previous != 0
    }

    /// Close without transferring useful work, for normal completion or expiry.
    pub fn close(&self) {
        self.state.fetch_or(CLOSED, Ordering::AcqRel);
    }
}

pub(crate) struct SharedCommandWaiter(Arc<SharedCommandOwner>);
impl Drop for SharedCommandWaiter {
    fn drop(&mut self) {
        self.0.state.fetch_sub(1, Ordering::AcqRel);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disconnect_decision_is_affine_and_requires_a_live_waiter() {
        let owner = Arc::new(SharedCommandOwner::default());
        let waiter = owner.try_subscribe().unwrap();
        assert!(owner.close_for_disconnect());
        assert!(!owner.close_for_disconnect());
        assert!(owner.try_subscribe().is_none());
        drop(waiter);
        let unshared = Arc::new(SharedCommandOwner::default());
        let waiter = unshared.try_subscribe().unwrap();
        drop(waiter);
        assert!(!unshared.close_for_disconnect());
    }

    #[test]
    fn concurrent_disconnect_and_sponsorship_have_one_winner() {
        for _ in 0..128 {
            let owner = Arc::new(SharedCommandOwner::default());
            let peer = Arc::clone(&owner);
            let task = std::thread::spawn(move || peer.try_subscribe());
            let shared = owner.close_for_disconnect();
            let waiter = task.join().unwrap();
            assert_eq!(shared, waiter.is_some());
        }
    }
}
