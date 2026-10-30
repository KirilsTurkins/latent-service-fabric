use super::*;
use std::sync::{atomic::AtomicUsize, Barrier};

#[test]
fn original_node_metadata_identity_exact_ceiling_refusal_and_rollback_are_shared() {
    let base = NodeMetadataOwner::bootstrap_bytes().unwrap();
    let original = NodeMetadataOwner::new(base + 128).unwrap();
    let other = NodeMetadataOwner::new(base + 128).unwrap();
    let retained = original.clone();
    let first = original.reserve(48).unwrap();
    let second = retained.reserve(80).unwrap();
    assert!(first.is_from_owner(&original));
    assert!(second.is_from_owner(&retained));
    assert!(!first.is_from_owner(&other));
    assert!(!original.same_owner(&other));
    assert_eq!(
        original.reserve(1).err(),
        Some(NodeMetadataError::Exhausted)
    );
    assert_eq!(original.occupied_bytes(), base + 128);
    assert_eq!(other.occupied_bytes(), base);
    drop(first);
    let replacement = original.reserve(48).unwrap();
    drop(second);
    drop(replacement);
    assert_eq!(original.occupied_bytes(), base);
}

#[test]
fn original_node_metadata_prepares_both_real_arc_allocations_before_payload_birth() {
    let base = NodeMetadataOwner::bootstrap_bytes().unwrap();
    let required = NodeMetadataArc::<[u64; 4]>::allocation_bytes(256).unwrap();
    let original = NodeMetadataOwner::new(base + required - 1).unwrap();
    assert_eq!(
        NodeMetadataArc::<[u64; 4]>::prepare(&original, 256).err(),
        Some(NodeMetadataError::Exhausted)
    );
    assert_eq!(original.occupied_bytes(), base);
    assert_eq!(
        NodeMetadataArc::<[u64; 4]>::prepare(&original, usize::MAX).err(),
        Some(NodeMetadataError::ArithmeticOverflow)
    );
    let enough = NodeMetadataOwner::new(base + required).unwrap();
    let pending = NodeMetadataArc::<[u64; 4]>::prepare(&enough, 256).unwrap();
    assert_eq!(enough.occupied_bytes(), base + required);
    // Abandoning pre-admission returns only capacity whose payload never existed.
    drop(pending);
    assert_eq!(enough.occupied_bytes(), base);
    let payload = NodeMetadataArc::<[u64; 4]>::prepare(&enough, 256)
        .unwrap()
        .allocate([3, 5, 7, 11]);
    assert_eq!(*payload, [3, 5, 7, 11]);
    assert_eq!(enough.occupied_bytes(), base + required);
    drop(payload);
    assert_eq!(enough.occupied_bytes(), base);
}

struct ObservedPayload {
    original: NodeMetadataOwner,
    seen: Arc<AtomicUsize>,
}
impl Drop for ObservedPayload {
    fn drop(&mut self) {
        self.seen
            .store(self.original.occupied_bytes(), Ordering::Release);
    }
}

#[test]
fn original_node_metadata_weak_headers_stay_paid_without_reviving_payload() {
    let original = NodeMetadataOwner::new(4096).unwrap();
    let base = NodeMetadataOwner::bootstrap_bytes().unwrap();
    let required = NodeMetadataArc::<ObservedPayload>::allocation_bytes(0).unwrap();
    let seen = Arc::new(AtomicUsize::new(0));
    let payload = NodeMetadataArc::prepare(&original, 0)
        .unwrap()
        .allocate(ObservedPayload {
            original: original.clone(),
            seen: Arc::clone(&seen),
        });
    let weak = payload.downgrade();
    drop(payload);
    assert_eq!(seen.load(Ordering::Acquire), base + required);
    assert!(weak.upgrade().is_none());
    assert_eq!(original.occupied_bytes(), base + required);
    drop(weak);
    assert_eq!(original.occupied_bytes(), base);
}

#[test]
fn original_node_metadata_concurrent_last_strong_and_weak_refund_once() {
    let original = NodeMetadataOwner::new(4096).unwrap();
    let base = NodeMetadataOwner::bootstrap_bytes().unwrap();
    let payload = NodeMetadataArc::prepare(&original, 0)
        .unwrap()
        .allocate(37_u64);
    let weak = payload.downgrade();
    let start = Arc::new(Barrier::new(3));
    std::thread::scope(|threads| {
        let strong_start = Arc::clone(&start);
        threads.spawn(move || {
            strong_start.wait();
            drop(payload);
        });
        let weak_start = Arc::clone(&start);
        threads.spawn(move || {
            weak_start.wait();
            drop(weak);
        });
        start.wait();
    });
    assert_eq!(original.occupied_bytes(), base);
}

#[test]
fn original_node_fixed_and_transient_observations_conserve_one_admission_bank() {
    let base = NodeMetadataOwner::bootstrap_bytes().unwrap();
    let owner = NodeMetadataOwner::new(base + 128).unwrap();
    let fixed = owner.reserve_fixed(48).unwrap();
    let transient = owner.reserve(80).unwrap();
    let observed = owner.snapshot();
    assert_eq!(observed.reserved_bytes, base + 128);
    assert_eq!(observed.fixed_reserved_bytes, base + 48);
    assert_eq!(observed.transient_reserved_bytes, 80);
    assert_eq!(
        owner.reserve_fixed(1).err(),
        Some(NodeMetadataError::Exhausted)
    );
    drop(fixed);
    assert_eq!(owner.snapshot().fixed_reserved_bytes, base);
    assert_eq!(owner.snapshot().transient_reserved_bytes, 80);
    drop(transient);
    assert_eq!(owner.snapshot().reserved_bytes, base);
}
