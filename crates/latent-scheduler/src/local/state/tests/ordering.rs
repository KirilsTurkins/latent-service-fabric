use std::collections::BTreeMap;
use std::time::Duration;

use super::super::ClassState;
use super::fixture::{key, tenant, Fixture};
use super::oracle::Oracle;

#[test]
fn selected_sequence_and_tenant_rotation_match_original_comparator_for_clock_histories() {
    for tenants in [1, 2, 32] {
        for reverse_clock in [false, true] {
            compare_history(tenants, reverse_clock);
        }
    }
}

fn compare_history(tenants: u32, reverse_clock: bool) {
    let fixture = Fixture::new(tenants);
    let mut state = ClassState::new(64);
    let mut oracle = Oracle::default();
    let mut locations = BTreeMap::new();
    for index in 0..64_u32 {
        let expected = key(&fixture, u64::from(index) + 1, index % tenants);
        let slot = state.push(fixture.entry(&expected));
        locations.insert(expected.sequence, slot);
        oracle.push(expected);
    }
    let mut round = 0;
    let aging = Duration::from_millis(100);
    while !locations.is_empty() {
        assert!(round < 160, "finite differential drain");
        if round % 5 == 2 {
            let (&sequence, &slot) = locations.last_key_value().unwrap();
            let actual = state.remove(slot, sequence).expect("located cancellation");
            let expected = oracle.remove(sequence).expect("reference cancellation");
            assert_eq!(actual.sequence, expected.sequence);
            drop(actual);
            locations.remove(&sequence);
        }
        if locations.is_empty() {
            break;
        }
        let offset = if reverse_clock {
            [100, 99, 101, 0, 200, 1][round % 6]
        } else {
            u64::try_from(round).unwrap()
        };
        let now = fixture.base + Duration::from_millis(offset);
        let expected = oracle.select(now, aging).expect("reference winner");
        let (_, actual) = state.select(now, aging).expect("candidate winner");
        assert_eq!(
            actual.sequence, expected.sequence,
            "tenants={tenants}, reverse={reverse_clock}, round={round}"
        );
        assert_eq!(actual.request.permit.tenant(), &tenant(expected.tenant));
        assert_eq!(
            usize::try_from(state.depth).unwrap(),
            oracle.len() + 1,
            "selected slot remains logically reserved"
        );
        if round % 7 == 0 {
            let sequence = actual.sequence;
            let slot = state.restore(actual);
            locations.insert(sequence, slot);
            oracle.restore(expected);
        } else {
            locations.remove(&actual.sequence);
            state.depth -= 1;
            state.rotate_after_grant(actual.request.permit.tenant());
            oracle.rotate(expected.tenant);
            drop(actual);
        }
        assert_eq!(usize::try_from(state.depth).unwrap(), oracle.len());
        assert_eq!(state.tenant_count(), oracle.tenants());
        round += 1;
    }
    assert_eq!(state.depth, 0);
    assert!(state.select(fixture.base, aging).is_none());
    assert_eq!(state.tenant_count(), 0);
    fixture.idle();
}

#[test]
fn restoring_a_selected_last_entry_uses_the_recreated_current_tenant() {
    let fixture = Fixture::new(2);
    let mut state = ClassState::new(5);
    let first = key(&fixture, 1, 0);
    let other = key(&fixture, 2, 1);
    state.push(fixture.entry(&first));
    state.push(fixture.entry(&other));
    let (_, selected) = state
        .select(fixture.base, Duration::from_millis(100))
        .unwrap();
    assert_eq!(selected.sequence, 1);
    // A same-tenant enqueue can recreate the tenant while the original entry is selected.
    let newer = key(&fixture, 3, 0);
    let newer_slot = state.push(fixture.entry(&newer));
    let selected_slot = state.restore(selected);
    assert_eq!(state.depth, 3);
    assert_eq!(state.tenant_count(), 2);
    assert_eq!(state.remove(newer_slot, 3).unwrap().sequence, 3);
    assert_eq!(state.remove(selected_slot, 1).unwrap().sequence, 1);
    let (_, last) = state
        .select(fixture.base, Duration::from_millis(100))
        .unwrap();
    assert_eq!(last.sequence, 2);
    state.depth -= 1;
    drop(last);
    assert_eq!(state.tenant_count(), 0);
    fixture.idle();
}
