use super::*;
use latent_core::{ClockSample, EffectiveActivationBudget, ResourceBudget};
use std::{
    sync::{
        atomic::{AtomicU64, Ordering},
        Barrier,
    },
    time::Instant,
};

fn budget() -> ActivationBudget {
    let limits = ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 2 * 1024 * 1024,
        wall_time_limit_millis: Some(1000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    };
    let grant = EffectiveActivationBudget::admit_profile_at(
        BudgetProfile::Phase3,
        &limits,
        &limits,
        &limits,
        None,
        ClockSample::new(1000, Instant::now()),
    )
    .unwrap();
    ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap()
}
struct Observed {
    budget: ActivationBudget,
    seen: Arc<AtomicU64>,
    panic: bool,
}
impl Drop for Observed {
    fn drop(&mut self) {
        self.seen
            .store(self.budget.host_memory_bytes(), Ordering::Release);
        assert!(!self.panic, "observed audit payload destructor");
    }
}

#[test]
fn audit_original_envelope_precedes_copy_and_abandoned_preparation_does_not_invent_storage() {
    let budget = budget();
    let memory = AuditCallMemory::activation(&budget, 2048).unwrap();
    let reserved = budget.host_memory_bytes();
    let before = budget.snapshot_at(Instant::now()).peak_memory_bytes;
    let preparation = memory.prepare_arc::<[u64; 4]>(256).unwrap();
    assert_eq!(budget.host_memory_bytes(), reserved);
    assert_eq!(budget.snapshot_at(Instant::now()).peak_memory_bytes, before);
    assert!(memory.prepare_arc::<[u64; 4]>(usize::MAX).is_err());
    assert!(memory.prepare_owned(2049).is_err());
    drop(preparation);
    drop(memory);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}
#[test]
fn audit_original_arc_last_concurrent_clones_keep_payload_and_billing_headers_paid() {
    let budget = budget();
    let seen = Arc::new(AtomicU64::new(0));
    let memory = AuditCallMemory::activation(&budget, 4096).unwrap();
    let reserved = budget.host_memory_bytes();
    let first = memory.prepare_arc::<Observed>(0).unwrap().allocate(
        Observed {
            budget: budget.clone(),
            seen: seen.clone(),
            panic: false,
        },
        0,
    );
    let second = first.clone();
    let start = Arc::new(Barrier::new(3));
    drop(memory);
    std::thread::scope(|threads| {
        let gate = start.clone();
        threads.spawn(move || {
            gate.wait();
            drop(first);
        });
        let gate = start.clone();
        threads.spawn(move || {
            gate.wait();
            drop(second);
        });
        start.wait();
    });
    assert_eq!(seen.load(Ordering::Acquire), reserved);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}
#[test]
fn audit_original_box_unwind_destroys_actual_payload_before_any_physical_refund() {
    let budget = budget();
    let seen = Arc::new(AtomicU64::new(0));
    let memory = AuditCallMemory::activation(&budget, 4096).unwrap();
    let reserved = budget.host_memory_bytes();
    let value = memory.prepare_box::<Observed>(0).unwrap().allocate(
        Observed {
            budget: budget.clone(),
            seen: seen.clone(),
            panic: true,
        },
        0,
    );
    drop(memory);
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(value))).is_err());
    assert_eq!(seen.load(Ordering::Acquire), reserved);
    assert_eq!(budget.host_memory_bytes(), 0);
    assert_eq!(budget.outstanding_reservations(), 0);
}
#[test]
fn audit_confirmation_failure_unwind_keeps_payload_paid_and_refunds_once() {
    for boxed in [true, false] {
        let budget = budget();
        let seen = Arc::new(AtomicU64::new(0));
        let memory = AuditCallMemory::activation(&budget, 4096).unwrap();
        let reserved = budget.host_memory_bytes();
        if boxed {
            let prepared = memory.prepare_box::<Observed>(0).unwrap();
            drop(memory);
            assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let _ = prepared.allocate(
                    Observed {
                        budget: budget.clone(),
                        seen: seen.clone(),
                        panic: false,
                    },
                    1,
                );
            }))
            .is_err());
        } else {
            let prepared = memory.prepare_arc::<Observed>(0).unwrap();
            drop(memory);
            assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let _ = prepared.allocate(
                    Observed {
                        budget: budget.clone(),
                        seen: seen.clone(),
                        panic: false,
                    },
                    1,
                );
            }))
            .is_err());
        }
        assert_eq!(seen.load(Ordering::Acquire), reserved);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

#[test]
fn audit_borrowed_graph_bound_keeps_original_json_limits_and_measures_canonical_capacity() {
    use crate::durable::{codec, tests::attempt};
    let mut source = attempt();
    // Spare capacity supplied by a caller is not retained by normalization.
    source.operation_id.reserve(65536);
    let raw = codec::encode(&source, 16384).unwrap();
    let bound = codec::owned_graph_bound(&raw, 16384).unwrap();
    let normalized: super::super::AuditOperationAttempt = codec::decode(&raw, 16384).unwrap();
    assert!(normalized.heap_bytes().unwrap() <= bound);
    assert!(normalized.operation_id.capacity() < source.operation_id.capacity());
    assert!(bound <= AuditCallMemory::owned_heap_bound(16384).unwrap());
    for (text, expected) in [
        (r#""\u00e9""#, 2 + 64),
        (r#"["a","b"]"#, 8 * 64 + 64 + 2 * 65),
    ] {
        assert_eq!(
            codec::owned_graph_bound(text.as_bytes(), 16384).unwrap(),
            expected
        );
    }
    assert!(codec::owned_graph_bound(br#"[0,0,0,0,0,0,0,0]"#, 16384).is_ok());
    assert!(codec::owned_graph_bound(br#"[0,0,0,0,0,0,0,0,0]"#, 16384).is_err());
    assert!(codec::owned_graph_bound(b"null", 16384).is_err());
    assert!(codec::owned_graph_bound(&raw, raw.len() - 1).is_err());
}
