use super::*;

fn joined() -> ActivationCleanupSnapshot {
    ActivationCleanupSnapshot {
        capacity: 68,
        accepting: false,
        driver_alive: false,
        driver_joined: true,
        reserved: 0,
        queued: 0,
        running: 0,
        handoffs: 7,
        completed: 7,
        timed_out: 0,
        panicked: 0,
        fallbacks: 0,
        failed: false,
    }
}

#[test]
fn cleanup_requires_actual_join_and_no_retained_owner() {
    assert!(cleanup_reclaimed(&joined()));
    for field in 0..11 {
        let mut value = joined();
        match field {
            0 => value.accepting = true,
            1 => value.driver_alive = true,
            2 => value.driver_joined = false,
            3 => value.reserved = 1,
            4 => value.queued = 1,
            5 => value.running = 1,
            6 => value.failed = true,
            7 => value.timed_out = 1,
            8 => value.panicked = 1,
            9 => value.fallbacks = 1,
            _ => value.completed = 6,
        }
        assert!(!cleanup_reclaimed(&value));
    }
}

#[test]
fn forced_cleanup_gets_one_bounded_phase_after_natural_drain() {
    let began = tokio::time::Instant::now();
    let natural_cutoff = began + Duration::from_secs(1);
    let forced_start = natural_cutoff + Duration::from_millis(3);
    let deadline = forced_cleanup_deadline(forced_start, Duration::from_millis(100)).unwrap();
    assert!(deadline > natural_cutoff);
    assert_eq!(
        deadline.duration_since(forced_start),
        Duration::from_millis(200)
    );
    assert!(forced_cleanup_deadline(forced_start, Duration::MAX).is_err());
}
