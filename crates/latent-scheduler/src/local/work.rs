//! Per-class test-only mechanism counts; never a CPU or mutex-time estimate.

use super::{CellClass, LocalScheduler};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(super) struct Snapshot {
    pub enabled: bool,
    pub overflowed: bool,
    /// Actual predicate visits while locating a tenant by linear search.
    pub tenant_linear_visits: u64,
    /// Actual calls to the unchanged within-tenant winner comparator.
    pub winner_comparisons: u64,
    /// Actual sequence predicate visits in queued cancellation/drop lookup.
    pub cancel_entry_visits: u64,
    /// Logical trailing Vec slots displaced by an entry removal.
    pub entry_shifted_slots: u64,
    /// Logical min(prefix, suffix) `VecDeque` slots displaced by tenant removal.
    pub tenant_shifted_slots: u64,
    /// Physical entry detachments, including selections subsequently restored.
    pub entry_unlinks: u64,
    /// Ordered tenant-index lookup calls, not tree comparator calls.
    pub tenant_index_lookups: u64,
}

#[derive(Default)]
pub(super) struct Work {
    snapshot: Snapshot,
}

impl Work {
    pub fn reset(&mut self, enabled: bool) {
        self.snapshot = Snapshot {
            enabled,
            ..Snapshot::default()
        };
    }

    pub fn snapshot(&self) -> Snapshot {
        self.snapshot
    }

    pub fn visit_tenant(&mut self) {
        self.add(|snapshot| &mut snapshot.tenant_linear_visits, 1);
    }

    pub fn compare_winners(&mut self) {
        self.add(|snapshot| &mut snapshot.winner_comparisons, 1);
    }

    pub fn visit_cancel_entry(&mut self) {
        self.add(|snapshot| &mut snapshot.cancel_entry_visits, 1);
    }

    pub fn unlink_entries(&mut self, entries: usize, shifted_slots: usize) {
        self.add(|snapshot| &mut snapshot.entry_unlinks, entries);
        self.add(|snapshot| &mut snapshot.entry_shifted_slots, shifted_slots);
    }

    pub fn shift_tenants(&mut self, slots: usize) {
        self.add(|snapshot| &mut snapshot.tenant_shifted_slots, slots);
    }

    pub fn lookup_tenant(&mut self) {
        self.add(|snapshot| &mut snapshot.tenant_index_lookups, 1);
    }

    fn add(&mut self, counter: fn(&mut Snapshot) -> &mut u64, amount: usize) {
        if !self.snapshot.enabled {
            return;
        }
        let value = counter(&mut self.snapshot);
        if let Some(sum) = u64::try_from(amount)
            .ok()
            .and_then(|amount| value.checked_add(amount))
        {
            *value = sum;
        } else {
            // Retain the last representable value and invalidate the snapshot;
            // diagnostic overflow never changes the scheduler's outcome.
            self.snapshot.overflowed = true;
        }
    }
}

impl LocalScheduler {
    pub(super) fn reset_work(&self, class: CellClass, enabled: bool) -> bool {
        let mut state = self.inner.lock();
        let Some(queue) = state.classes.get_mut(&class) else {
            return false;
        };
        queue.work.reset(enabled);
        true
    }

    pub(super) fn work_snapshot(&self, class: CellClass) -> Option<Snapshot> {
        self.inner
            .lock()
            .classes
            .get(&class)
            .map(|queue| queue.work.snapshot())
    }
}

#[cfg(test)]
mod tests {
    use super::{Snapshot, Work};

    fn exercise(work: &mut Work) {
        work.visit_tenant();
        work.compare_winners();
        work.visit_cancel_entry();
        work.unlink_entries(2, 3);
        work.shift_tenants(4);
        work.lookup_tenant();
    }

    #[test]
    fn disabled_and_reset_windows_do_not_retain_counts() {
        let mut work = Work::default();
        exercise(&mut work);
        assert_eq!(work.snapshot(), Snapshot::default());
        work.reset(true);
        exercise(&mut work);
        assert_eq!(
            work.snapshot(),
            Snapshot {
                enabled: true,
                tenant_linear_visits: 1,
                winner_comparisons: 1,
                cancel_entry_visits: 1,
                entry_shifted_slots: 3,
                tenant_shifted_slots: 4,
                entry_unlinks: 2,
                tenant_index_lookups: 1,
                ..Snapshot::default()
            }
        );
        work.reset(false);
        exercise(&mut work);
        assert_eq!(work.snapshot(), Snapshot::default());
        work.reset(true);
        assert_eq!(
            work.snapshot(),
            Snapshot {
                enabled: true,
                ..Snapshot::default()
            }
        );
    }

    #[test]
    fn overflow_is_latched_and_independent_per_class() {
        let mut first = Work::default();
        let mut second = Work::default();
        first.reset(true);
        second.reset(true);
        first.snapshot.entry_unlinks = u64::MAX;
        first.unlink_entries(1, 2);
        assert!(first.snapshot().overflowed);
        assert_eq!(first.snapshot().entry_unlinks, u64::MAX);
        assert_eq!(first.snapshot().entry_shifted_slots, 2);
        second.unlink_entries(1, 0);
        assert!(!second.snapshot().overflowed);
        assert_eq!(second.snapshot().entry_unlinks, 1);
        first.reset(true);
        assert!(!first.snapshot().overflowed);
    }
}
