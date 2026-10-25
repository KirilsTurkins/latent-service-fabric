//! Deadline-only fixture observer. The generic trap/memory gate is unchanged.
use std::collections::BTreeSet;
use std::sync::{Arc, Mutex, Weak};
use std::time::Duration;

use latent_wasmtime::{CapturedLog, LogSinkError, Phase0WasmtimeBackend, StructuredLogSink};

use super::{MixedMemoryRendezvous, MixedMemoryRendezvousSnapshot, MIXED_MEMORY_READY_LOG_MESSAGE};

pub(super) struct MixedDeadlineLogSink {
    gate: Arc<MixedMemoryRendezvous>,
    failure: String,
    // The backend owns its log sink. A strong reverse edge would form a cycle.
    backend: Mutex<Option<Weak<Phase0WasmtimeBackend>>>,
}

impl MixedDeadlineLogSink {
    pub(super) fn new(gate: Arc<MixedMemoryRendezvous>, failure: String) -> Self {
        Self {
            gate,
            failure,
            backend: Mutex::new(None),
        }
    }

    pub(super) fn bind_backend(&self, backend: &Arc<Phase0WasmtimeBackend>) {
        let mut selected = self
            .backend
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        assert!(
            selected.is_none(),
            "deadline observer binds exactly one backend"
        );
        *selected = Some(Arc::downgrade(backend));
    }
}

impl StructuredLogSink for MixedDeadlineLogSink {
    fn try_emit(&self, entry: &CapturedLog, _encoded: &[u8]) -> Result<(), LogSinkError> {
        if entry.message != MIXED_MEMORY_READY_LOG_MESSAGE {
            return Ok(());
        }
        if self.gate.arrive(&entry.activation_id.0) {
            return Ok(());
        }
        if entry.activation_id.0 == self.failure {
            let backend = {
                self.backend
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .as_ref()
                    .and_then(Weak::upgrade)
            };
            if let Some(backend) = backend {
                // This is the current fifth guest callback, after all four
                // healthy guests entered their closed gate. The generic gate
                // also requires the complete exact arrival set, no unexpected
                // identity, and no timeout. These are not historical peak stats.
                // The backend view is atomic-only; no sink lock is held here.
                self.gate
                    .release_if_ready(|| backend.resource_snapshot().active_invocations == 5);
            }
            if self.gate.snapshot().opened {
                return Ok(());
            }
        }
        Err(LogSinkError::Unavailable)
    }
}

pub(super) async fn wait_for_healthy(
    gate: &MixedMemoryRendezvous,
    healthy: &BTreeSet<String>,
    all_unfinished: impl Fn() -> bool,
) -> MixedMemoryRendezvousSnapshot {
    let observed = tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let snapshot = gate.snapshot();
            if snapshot.opened
                || snapshot.timed_out
                || !snapshot.unexpected.is_empty()
                || snapshot.departed_before_release
            {
                return snapshot;
            }
            if !all_unfinished() {
                gate.timeout_now();
                return gate.snapshot();
            }
            if snapshot.arrived == *healthy {
                return snapshot;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await;
    observed.unwrap_or_else(|_| {
        gate.timeout_now();
        gate.snapshot()
    })
}
