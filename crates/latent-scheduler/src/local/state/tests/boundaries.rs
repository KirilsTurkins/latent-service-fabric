use std::time::Duration;

use super::super::ClassState;
use super::fixture::{key, Fixture};

#[test]
fn priority_deadline_sequence_and_exact_aging_boundary_have_fixed_winners() {
    let fixture = Fixture::new(1);
    // Priority, enqueue offset in ms, and deadline offset in seconds.
    let cases = [
        ("priority", (10, 0, 2), (255, 0, 5), 2),
        ("deadline", (10, 0, 5), (10, 0, 2), 2),
        ("sequence tie", (10, 0, 5), (10, 0, 5), 1),
        ("before aging", (0, -99, 5), (255, 0, 2), 2),
        ("exact aging", (0, -100, 5), (255, 0, 2), 1),
        ("both aged use sequence", (0, -100, 5), (255, -101, 2), 1),
        ("future enqueue is not aged", (0, 1, 2), (255, 0, 5), 2),
    ];
    for (name, first, second, expected) in cases {
        let mut state = ClassState::new(2);
        // Reverse insertion makes the sequence tie independent of list order.
        for (sequence, (priority, enqueue, deadline)) in [(2, second), (1, first)] {
            let mut row = key(&fixture, sequence, 0);
            row.priority = priority;
            let offset = Duration::from_millis(u64::from(i32::unsigned_abs(enqueue)));
            row.enqueued = if enqueue < 0 {
                fixture.base.checked_sub(offset).unwrap()
            } else {
                fixture.base + offset
            };
            row.deadline = Some(fixture.base + Duration::from_secs(deadline));
            state.push(fixture.entry(&row));
        }
        let (_, selected) = state
            .select(fixture.base, Duration::from_millis(100))
            .unwrap();
        assert_eq!(selected.sequence, expected, "{name}");
        state.depth -= 1;
        drop(selected);
        let mut remaining = Vec::new();
        state.drain_into(&mut remaining);
        assert_eq!(remaining.len(), 1);
        drop(remaining);
        fixture.idle();
    }
}
