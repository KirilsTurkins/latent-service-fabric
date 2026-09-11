//! Bounded diagnostic timing storage shared by the node backend.

use std::collections::{HashMap, VecDeque};

/// Bounded timing-store state exposed to long-running resource probes.
///
/// Timing records are diagnostic data rather than activation-owned state.  The
/// snapshot makes their retention limit observable without exposing the timing
/// records themselves or allowing a benchmark to depend on their internals.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct InvocationTimingStoreSnapshot {
    pub entries: usize,
    pub maximum_entries: usize,
}

/// Generic backend boundaries for one contained invocation.
/// The original public type name is retained for profiling compatibility.
///
/// `host_call_micros` is intentionally a subset of `guest_call_micros`, so
/// host-import work is observable without being counted twice in latency sums.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Phase0InvocationTiming {
    /// Validation, host-state/store construction, and instance preparation
    /// before entering the guest export.
    pub backend_setup_micros: u64,
    /// Time in the guest export call, including Wasmtime's automatic
    /// canonical-ABI component post-return before the call yields.
    pub guest_call_micros: u64,
    /// Time spent in activation host imports during the guest-call interval.
    pub host_call_micros: u64,
    pub host_call_count: u64,
    /// Host-visible post-return/result accounting after the guest call
    /// completes. Canonical-ABI post-return itself is included in
    /// `guest_call_micros` because Wasmtime completes it inside the safe Component Model
    /// call API.
    pub component_post_return_micros: u64,
    /// Sum of the store/instance/host-state and temporary-buffer drop span,
    /// and the final runtime/permit drop span after error classification.
    /// The intervening classification work is excluded.
    pub activation_resource_reclamation_micros: u64,
    /// Guest result classification after stores and buffers are reclaimed,
    /// including native error destruction before the final runtime release.
    pub outcome_classification_micros: u64,
    /// Final cancellation/log cleanup and construction of the reusable proof.
    pub reusable_proof_micros: u64,
    /// End-to-end backend interval through return of the reusable proof.
    pub backend_total_micros: u64,
}

pub(crate) struct InvocationTimingStore {
    entries: HashMap<String, Phase0InvocationTiming>,
    insertion_order: VecDeque<String>,
    maximum_entries: usize,
}

impl InvocationTimingStore {
    pub(crate) fn new(maximum_entries: usize) -> Self {
        Self {
            entries: HashMap::new(),
            insertion_order: VecDeque::new(),
            maximum_entries,
        }
    }

    pub(crate) fn insert(&mut self, activation_id: String, timing: Phase0InvocationTiming) {
        self.remove(&activation_id);
        while self.entries.len() >= self.maximum_entries {
            let Some(oldest) = self.insertion_order.pop_front() else {
                break;
            };
            self.entries.remove(&oldest);
        }
        self.insertion_order.push_back(activation_id.clone());
        self.entries.insert(activation_id, timing);
    }

    pub(crate) fn update_reusable_proof(&mut self, activation_id: &str, elapsed_micros: u64) {
        if let Some(timing) = self.entries.get_mut(activation_id) {
            timing.reusable_proof_micros =
                timing.reusable_proof_micros.saturating_add(elapsed_micros);
            timing.backend_total_micros =
                timing.backend_total_micros.saturating_add(elapsed_micros);
        }
    }

    pub(crate) fn remove(&mut self, activation_id: &str) -> Option<Phase0InvocationTiming> {
        let timing = self.entries.remove(activation_id)?;
        if let Some(position) = self
            .insertion_order
            .iter()
            .position(|candidate| candidate == activation_id)
        {
            self.insertion_order.remove(position);
        }
        Some(timing)
    }

    pub(crate) fn snapshot(&self) -> InvocationTimingStoreSnapshot {
        InvocationTimingStoreSnapshot {
            entries: self.entries.len(),
            maximum_entries: self.maximum_entries,
        }
    }
}

#[cfg(test)]
mod timing_tests {
    use super::{InvocationTimingStore, Phase0InvocationTiming};

    #[test]
    fn timing_store_snapshot_reports_bounded_occupancy() {
        let mut store = InvocationTimingStore::new(2);
        assert_eq!(store.snapshot().entries, 0);
        assert_eq!(store.snapshot().maximum_entries, 2);

        store.insert("first".to_owned(), Phase0InvocationTiming::default());
        store.insert("second".to_owned(), Phase0InvocationTiming::default());
        assert_eq!(store.snapshot().entries, 2);

        store.insert("third".to_owned(), Phase0InvocationTiming::default());
        assert_eq!(store.snapshot().entries, 2);
        assert!(store.remove("first").is_none());
        assert!(store.remove("second").is_some());
        assert_eq!(store.snapshot().entries, 1);
    }
}
