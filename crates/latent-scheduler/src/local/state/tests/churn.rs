use std::time::Duration;

use super::super::ClassState;
use super::fixture::{key, Fixture};

#[test]
fn non_power_of_two_arenas_reuse_bounded_capacity_and_reject_old_slot_sequences() {
    for capacity in [0, 1, 3, 5, 64] {
        churn(capacity);
    }
}

fn churn(capacity: u32) {
    let tenants = capacity.clamp(1, 32);
    let fixture = Fixture::new(tenants);
    let mut state = ClassState::new(capacity);
    assert_eq!(state.queue.retained_capacity(), (0, 0));
    let mut old_locations = Vec::new();
    let mut retained = None;
    for cycle in 0..8_u64 {
        let mut locations = Vec::new();
        for index in 0..capacity {
            let sequence = cycle * 64 + u64::from(index) + 1;
            let expected = key(&fixture, sequence, index % tenants);
            locations.push((state.push(fixture.entry(&expected)), sequence));
        }
        for &(slot, sequence) in &old_locations {
            assert!(
                state.remove(slot, sequence).is_none(),
                "retired sequence must not unlink a replacement"
            );
        }
        assert_eq!(state.depth, capacity);
        let current = state.queue.retained_capacity();
        assert!(
            current.0 <= usize::try_from(capacity).unwrap()
                && current.1 <= usize::try_from(capacity).unwrap()
        );
        if let Some(previous) = retained {
            assert_eq!(current, previous, "churn cannot grow retained capacity");
        }
        retained = Some(current);
        let mut removed = Vec::new();
        state.drain_into(&mut removed);
        assert_eq!(removed.len(), usize::try_from(capacity).unwrap());
        assert_eq!(state.depth, 0);
        assert_eq!(state.tenant_count(), 0);
        assert_eq!(state.queue.retained_capacity(), current);
        assert_eq!(fixture.quotas.usage().unwrap().active_activations, capacity);
        drop(removed);
        fixture.idle();
        old_locations = locations;
    }
    assert!(state
        .select(fixture.base, Duration::from_millis(100))
        .is_none());
}

#[test]
fn direct_head_middle_tail_removal_preserves_remaining_entry_owners() {
    let fixture = Fixture::new(1);
    let mut state = ClassState::new(5);
    let slots = (1..=5)
        .map(|sequence| state.push(fixture.entry(&key(&fixture, sequence, 0))))
        .collect::<Vec<_>>();
    for (index, sequence) in [(0, 1), (2, 3), (4, 5)] {
        let removed = state.remove(slots[index], sequence).unwrap();
        assert_eq!(removed.sequence, sequence);
        drop(removed);
        assert!(state.remove(slots[index], sequence).is_none());
    }
    assert_eq!(state.depth, 2);
    assert_eq!(state.tenant_count(), 1);
    assert_eq!(fixture.quotas.usage().unwrap().active_activations, 2);
    let mut remaining = Vec::new();
    state.drain_into(&mut remaining);
    let mut sequences = remaining
        .iter()
        .map(|entry| entry.sequence)
        .collect::<Vec<_>>();
    sequences.sort_unstable();
    assert_eq!(sequences, vec![2, 4]);
    drop(remaining);
    fixture.idle();
}
