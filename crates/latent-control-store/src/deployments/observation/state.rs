use std::sync::{Arc, Mutex, MutexGuard};

use super::{
    CatalogWorkCounts, CatalogWorkOperation, CatalogWorkOutcome, CatalogWorkReceipt,
    CatalogWorkSnapshot,
};

/// Optional shared recorder retaining only fixed-size counters and the last receipt.
/// Overlap, exhaustion or poisoning must invalidate a collector's coverage claim.
#[derive(Clone, Default)]
pub struct CatalogWorkObserver {
    state: Arc<Mutex<CatalogWorkSnapshot>>,
}

impl CatalogWorkObserver {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Copies state without callbacks, payload ownership, resetting or a history allocation.
    #[must_use]
    pub fn snapshot(&self) -> CatalogWorkSnapshot {
        *self.lock()
    }

    fn lock(&self) -> MutexGuard<'_, CatalogWorkSnapshot> {
        self.state.lock().unwrap_or_else(|poisoned| {
            let mut state = poisoned.into_inner();
            state.poisoned = true;
            state
        })
    }

    pub(super) fn begin(&self, operation: CatalogWorkOperation) -> Option<Tracked> {
        let mut state = self.lock();
        let Some(sequence) = state.started.checked_add(1) else {
            state.overflowed = true;
            return None;
        };
        let Some(active) = state.active.checked_add(1) else {
            state.overflowed = true;
            return None;
        };
        state.started = sequence;
        state.active = active;
        state.maximum_active = state.maximum_active.max(active);
        drop(state);
        Some(Tracked {
            observer: self.clone(),
            receipt: CatalogWorkReceipt {
                sequence,
                operation,
                outcome: CatalogWorkOutcome::OwnerDropped,
                compiled_generation: None,
                overflowed: false,
                counts: CatalogWorkCounts::default(),
            },
        })
    }
}

pub(super) struct Tracked {
    observer: CatalogWorkObserver,
    pub(super) receipt: CatalogWorkReceipt,
}

impl Drop for Tracked {
    fn drop(&mut self) {
        let mut state = self.observer.lock();
        if let Some(active) = state.active.checked_sub(1) {
            state.active = active;
        } else {
            state.overflowed = true;
        }
        if let Some(finished) = state.finished.checked_add(1) {
            state.finished = finished;
        } else {
            state.overflowed = true;
        }
        state.overflowed |= self.receipt.overflowed;
        state.last = Some(self.receipt);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::deployments::observation::{Source, Work};

    #[test]
    fn receipts_belong_to_each_owner_even_when_completion_order_reverses() {
        let observer = CatalogWorkObserver::new();
        let source = Source::observed(observer.clone());
        let mut first = source.begin(CatalogWorkOperation::Open);
        let mut second = source.begin(CatalogWorkOperation::ApplyMany);
        first.add(|counts| &mut counts.compiler_calls, 3);
        second.add(|counts| &mut counts.compiler_calls, 7);
        assert_eq!(observer.snapshot().maximum_active, 2);
        second.finish(&Ok::<(), ()>(()));
        drop(second);
        let middle = observer.snapshot();
        assert_eq!((middle.started, middle.finished, middle.active), (2, 1, 1));
        assert_eq!(middle.last.unwrap().sequence, 2);
        assert_eq!(middle.last.unwrap().counts.compiler_calls, 7);
        drop(first);
        let final_state = observer.snapshot();
        assert_eq!(
            (
                final_state.started,
                final_state.finished,
                final_state.active
            ),
            (2, 2, 0)
        );
        let receipt = final_state.last.unwrap();
        assert_eq!(receipt.sequence, 1);
        assert_eq!(receipt.outcome, CatalogWorkOutcome::OwnerDropped);
        assert_eq!(receipt.counts.compiler_calls, 3);
        assert!(!final_state.overflowed);
    }

    #[test]
    fn counter_and_identity_exhaustion_invalidate_without_wrapping() {
        let observer = CatalogWorkObserver::new();
        let mut work = Source::observed(observer.clone()).begin(CatalogWorkOperation::Open);
        work.add(|counts| &mut counts.compiler_calls, u64::MAX);
        work.add(|counts| &mut counts.compiler_calls, 1);
        drop(work);
        assert!(observer.snapshot().overflowed);
        assert_eq!(
            observer.snapshot().last.unwrap().counts.compiler_calls,
            u64::MAX
        );
        observer.lock().started = u64::MAX;
        let denied = Source::observed(observer.clone()).begin(CatalogWorkOperation::Open);
        drop(denied);
        let state = observer.snapshot();
        assert_eq!(state.started, u64::MAX);
        assert_eq!((state.active, state.finished), (0, 1));
    }

    #[test]
    fn unknown_partial_write_count_stays_unknown_after_later_success() {
        let observer = CatalogWorkObserver::new();
        let mut work = Source::observed(observer.clone()).begin(CatalogWorkOperation::Open);
        work.written(Some(5));
        work.written(None);
        work.written(Some(9));
        drop(work);
        assert_eq!(
            observer.snapshot().last.unwrap().counts.stage_written_bytes,
            None
        );
        assert!(!observer.snapshot().overflowed);
    }

    #[test]
    fn disabled_work_has_no_observer_and_poisoned_observation_stays_explicit() {
        let observer = CatalogWorkObserver::new();
        let mut disabled = Work::default();
        disabled.add(|counts| &mut counts.compiler_calls, 1);
        drop(disabled);
        assert_eq!(observer.snapshot(), CatalogWorkSnapshot::default());
        let result = std::panic::catch_unwind(|| {
            let _guard = observer.lock();
            panic!("poison recorder only");
        });
        assert!(result.is_err());
        let mut work = Source::observed(observer.clone()).begin(CatalogWorkOperation::Open);
        work.finish(&Ok::<(), ()>(()));
        drop(work);
        assert!(observer.snapshot().poisoned);
        assert_eq!(observer.snapshot().active, 0);
        assert_eq!(
            observer.snapshot().last.unwrap().outcome,
            CatalogWorkOutcome::ReturnedOk
        );
    }
}
