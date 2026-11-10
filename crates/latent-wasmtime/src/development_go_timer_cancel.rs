//! Fixed test-process rendezvous for one selected returned-timer activation.
//!
//! This is not an activation resource or a production synchronization API.
//! The existing charged witness supplies the causal evidence. The flag only
//! lets the single signed test issue the real root cancellation at that edge.
use std::sync::atomic::{AtomicU64, Ordering};

pub(crate) const ACTIVATION: &str = "go-timer-returned-cancel";
pub(crate) const PROBE_LIMIT: u64 = 16_384;
const MASK: u64 = 7;
const STEP: u64 = 8;
const IDLE: u64 = 0;
const ARMED: u64 = 1;
const BOUND: u64 = 2;
const READY: u64 = 3;
const CLAIMED: u64 = 4;
const ACCEPTED: u64 = 5;
const DONE: u64 = 6;
const FAILED: u64 = 7;
static GATE: AtomicU64 = AtomicU64::new(IDLE);

fn transition(from: u64, to: u64) -> bool {
    GATE.fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
        (value & MASK == from).then_some((value & !MASK) | to)
    })
    .is_ok()
}

fn fail() {
    let _ = GATE.fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
        (value & MASK != IDLE).then_some((value & !MASK) | FAILED)
    });
}

pub(crate) fn invalid() {
    fail();
}

/// The gate can be armed once, before the exact test activation starts.
#[doc(hidden)]
pub struct ReturnedCancellationGate {
    _private: (),
}
impl ReturnedCancellationGate {
    #[must_use]
    pub fn arm() -> Option<Self> {
        if transition(IDLE, ARMED) {
            Some(Self { _private: () })
        } else {
            None
        }
    }
    #[must_use]
    pub fn ready(&self) -> bool {
        GATE.load(Ordering::Acquire) & MASK == READY
    }
    #[must_use]
    pub fn failed(&self) -> bool {
        GATE.load(Ordering::Acquire) & MASK == FAILED
    }
    pub fn claim(&self) -> bool {
        transition(READY, CLAIMED)
    }
    pub fn accepted(&self) -> bool {
        transition(CLAIMED, ACCEPTED)
    }
    #[must_use]
    pub fn completed(&self) -> bool {
        GATE.load(Ordering::Acquire) & MASK == DONE
    }
}
impl Drop for ReturnedCancellationGate {
    fn drop(&mut self) {
        GATE.store(IDLE, Ordering::Release);
    }
}

pub(crate) fn bind() -> bool {
    if transition(ARMED, BOUND) {
        true
    } else {
        // A second matching activation cannot share the first one's evidence.
        fail();
        false
    }
}

pub(crate) fn ready() -> bool {
    if transition(BOUND, READY) {
        true
    } else {
        fail();
        false
    }
}

/// Count only successful diagnostic probes while the event is still held.
/// The final bounded probe fails the gate *before* the guest can time out.
pub(crate) fn held_probe() -> bool {
    GATE.fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
        let phase = value & MASK;
        let count = value >> 3;
        if !matches!(phase, READY | CLAIMED) || count + 1 >= PROBE_LIMIT {
            Some((value & !MASK) | FAILED)
        } else {
            Some(value + STEP)
        }
    })
    .is_ok_and(|_| GATE.load(Ordering::Acquire) & MASK != FAILED)
}

/// Called synchronously when the selected Wasmtime export finishes, before
/// later asynchronous cleanup. An earlier trap cannot be relabelled by a
/// cancellation that the coordinator requests afterwards.
pub(crate) fn export_finished() {
    if GATE.load(Ordering::Acquire) & MASK != ACCEPTED {
        fail();
    }
}

pub(crate) fn finish(valid: bool) -> bool {
    if valid && transition(ACCEPTED, DONE) {
        true
    } else {
        fail();
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    static LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn selected_root_requires_binding_ready_acceptance_and_valid_retirement() {
        let _lock = LOCK.lock().unwrap();
        let gate = ReturnedCancellationGate::arm().unwrap();
        assert!(!gate.ready() && !gate.claim());
        assert!(bind() && ready() && gate.ready() && held_probe());
        assert!(gate.claim() && gate.accepted() && finish(true) && gate.completed());
    }

    #[test]
    fn duplicate_binding_and_early_export_fail_closed() {
        let _lock = LOCK.lock().unwrap();
        let gate = ReturnedCancellationGate::arm().unwrap();
        assert!(ReturnedCancellationGate::arm().is_none());
        assert!(bind());
        assert!(!bind() && gate.failed());
        drop(gate);
        let gate = ReturnedCancellationGate::arm().unwrap();
        assert!(bind() && ready());
        export_finished();
        assert!(gate.failed() && !gate.claim());
    }

    #[test]
    fn exhausted_loop_or_invalid_report_cannot_be_relabelled_cancelled() {
        let _lock = LOCK.lock().unwrap();
        let gate = ReturnedCancellationGate::arm().unwrap();
        assert!(bind() && ready());
        for _ in 1..PROBE_LIMIT {
            assert!(held_probe());
        }
        assert!(!held_probe() && gate.failed() && !gate.claim());
        drop(gate);
        let gate = ReturnedCancellationGate::arm().unwrap();
        assert!(bind() && ready() && gate.claim() && gate.accepted());
        assert!(!finish(false) && gate.failed());
    }
}
