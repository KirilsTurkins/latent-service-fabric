//! Actual nonsuspending production state, with explicit admitted-token ports.
//! No canonical suspension, timer provider or physical retirement is executed.
pub use std::mem;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Token {
    generation: u64,
    id: u64,
}
impl Token {
    fn valid(self) -> bool {
        self.generation != 0 && self.id != 0
    }
}
#[path = "../thread_wait_registry.rs"]
mod registry;
use registry::{Domain, Error, Registry, Start, Wake, MAX_WAITS};

fn token(id: u64) -> Token {
    Token { generation: 17, id }
}
fn plain() -> Registry {
    let mut r = Registry::new();
    r.insert(token(1), 0, 8, Domain::CanonicalSuspend).unwrap();
    r
}
fn timer() -> Registry {
    let mut r = Registry::new();
    r.insert(token(1), 0, 8, Domain::EngineTimerAwait { timer: token(2) })
        .unwrap();
    r
}

#[test]
fn notification_before_suspension_cannot_be_lost_or_resume_a_running_thread() {
    for domain in [
        Domain::CanonicalSuspend,
        Domain::EngineTimerAwait { timer: token(2) },
    ] {
        let mut r = Registry::new();
        r.insert(token(1), 0, 8, domain).unwrap();
        assert_eq!(r.notify(token(1), 0), Ok(Wake::BeforeSuspension));
        assert_eq!(r.start(token(1), 0), Ok(Start::AlreadyNotified));
        assert_eq!(r.returned(token(1), 0), Err(Error::Identity));
        assert_eq!(r.notify(token(1), 0), Ok(Wake::AlreadyReady));
        r.remove(token(1), 0, 8).unwrap();
        assert!(r.is_empty());
    }
}

#[test]
fn plain_wait_can_resume_only_the_exact_explicitly_suspended_canonical_thread() {
    let mut r = plain();
    assert_eq!(r.start(token(1), 0), Ok(Start::SuspendCanonical));
    assert_eq!(
        r.notify(token(1), 0),
        Ok(Wake::ResumeExplicitlySuspended { canonical: 0 })
    );
    assert_eq!(r.remove(token(1), 0, 8), Err(Error::State));
    assert_eq!(r.notify(token(1), 0), Ok(Wake::AlreadyReady));
    r.returned(token(1), 0).unwrap();
    r.remove(token(1), 0, 8).unwrap();
}

#[test]
fn timed_host_await_is_stopped_by_its_timer_and_never_canonically_resumed() {
    let mut r = timer();
    assert_eq!(
        r.start(token(1), 0),
        Ok(Start::AwaitTimer { timer: token(2) })
    );
    assert_eq!(
        r.notify(token(1), 0),
        Ok(Wake::StopTimer { timer: token(2) })
    );
    // A notify cannot free the node/frame while its actual host await is live.
    assert_eq!(r.remove(token(1), 0, 8), Err(Error::State));
    assert_eq!(r.start(token(1), 0), Err(Error::Identity));
    r.returned(token(1), 0).unwrap();
    r.remove(token(1), 0, 8).unwrap();
}

#[test]
fn elapsed_readiness_requires_exact_live_timer_and_wait_identity() {
    let mut r = timer();
    assert_eq!(r.elapsed(token(1), token(2), 0), Err(Error::Identity));
    r.start(token(1), 0).unwrap();
    assert_eq!(r.elapsed(token(1), token(3), 0), Err(Error::Identity));
    assert_eq!(r.elapsed(token(1), token(2), 1), Err(Error::Identity));
    assert_eq!(r.elapsed(token(3), token(2), 0), Err(Error::Stale));
    assert_eq!(r.returned(token(1), 0), Err(Error::State));
    assert_eq!(r.elapsed(token(1), token(2), 0), Ok(true));
    assert_eq!(r.elapsed(token(1), token(2), 0), Err(Error::State));
    assert_eq!(r.notify(token(1), 0), Ok(Wake::AlreadyReady));
    r.returned(token(1), 0).unwrap();
    r.remove(token(1), 0, 8).unwrap();
    let mut r = plain();
    r.start(token(1), 0).unwrap();
    assert_eq!(r.elapsed(token(1), token(2), 0), Err(Error::Identity));
}

#[test]
fn matching_notification_wins_without_fabricating_elapsed_timer_completion() {
    let mut r = timer();
    r.start(token(1), 0).unwrap();
    r.notify(token(1), 0).unwrap();
    assert_eq!(r.elapsed(token(1), token(2), 0), Ok(false));
    r.returned(token(1), 0).unwrap();
    assert_eq!(r.elapsed(token(1), token(2), 0), Err(Error::Identity));
    r.remove(token(1), 0, 8).unwrap();
}

#[test]
fn fixed_table_capacity_is_not_permission_for_unowned_or_aliased_waits() {
    let mut r = Registry::new();
    for n in 0..MAX_WAITS {
        r.insert(
            token(n as u64 + 1),
            n as u32,
            8 * (n + 1),
            Domain::CanonicalSuspend,
        )
        .unwrap();
    }
    assert_eq!(
        r.insert(token(99), 99, 8 * 99, Domain::CanonicalSuspend),
        Err(Error::Capacity)
    );
    for n in 0..MAX_WAITS {
        r.remove(token(n as u64 + 1), n as u32, 8 * (n + 1))
            .unwrap();
    }
    assert!(r.is_empty());
    for (wait, index, pointer, domain) in [
        (token(0), 0, 8, Domain::CanonicalSuspend),
        (token(1), 0, 0, Domain::CanonicalSuspend),
        (token(1), 0, 9, Domain::CanonicalSuspend),
        (token(1), 0, 4, Domain::CanonicalSuspend),
        (token(1), 0, 8, Domain::EngineTimerAwait { timer: token(1) }),
        (token(1), 0, 8, Domain::EngineTimerAwait { timer: token(0) }),
    ] {
        assert_eq!(r.insert(wait, index, pointer, domain), Err(Error::Identity));
        assert!(r.is_empty());
    }
    let mut r = timer();
    for (wait, index, pointer, domain) in [
        (token(1), 1, 16, Domain::CanonicalSuspend),
        (token(3), 0, 16, Domain::CanonicalSuspend),
        (token(3), 1, 8, Domain::CanonicalSuspend),
        (
            token(3),
            1,
            16,
            Domain::EngineTimerAwait { timer: token(2) },
        ),
        (token(2), 1, 16, Domain::CanonicalSuspend),
        (
            token(3),
            1,
            16,
            Domain::EngineTimerAwait { timer: token(1) },
        ),
    ] {
        assert_eq!(r.insert(wait, index, pointer, domain), Err(Error::Identity));
    }
}

#[test]
fn stale_generation_or_pointer_cannot_target_a_reused_slot_or_stack() {
    let mut r = plain();
    assert_eq!(r.pointer(token(1), 0), Ok(8));
    assert_eq!(r.remove(token(1), 0, 16), Err(Error::Identity));
    assert_eq!(r.remove(token(1), 1, 8), Err(Error::Identity));
    r.remove(token(1), 0, 8).unwrap();
    let fresh = Token {
        generation: 18,
        id: 1,
    };
    r.insert(fresh, 0, 8, Domain::CanonicalSuspend).unwrap();
    assert_eq!(r.start(token(1), 0), Err(Error::Stale));
    assert_eq!(r.notify(token(1), 0), Err(Error::Stale));
    assert_eq!(r.pointer(token(1), 0), Err(Error::Stale));
    assert_eq!(r.pointer(fresh, 0), Ok(8));
}

#[test]
fn registry_capacity_is_reserved_before_admission_and_survives_interleaved_work() {
    let mut r = Registry::new();
    let tickets: Vec<_> = (0..MAX_WAITS)
        .map(|n| r.reserve(n as u32).unwrap())
        .collect();
    assert_eq!(r.reserve(99), Err(Error::Capacity));
    assert_eq!(r.reserve(0), Err(Error::Identity));
    assert!(!r.is_empty());
    let old = tickets[0];
    assert_eq!(
        r.install(old, token(1), 99, 8, Domain::CanonicalSuspend),
        Err(Error::Identity)
    );
    r.cancel(old).unwrap();
    let fresh = r.reserve(0).unwrap();
    assert_ne!(old, fresh);
    assert_eq!(r.cancel(old), Err(Error::Stale));
    assert_eq!(
        r.install(old, token(1), 0, 8, Domain::CanonicalSuspend),
        Err(Error::Identity)
    );
    r.install(fresh, token(1), 0, 8, Domain::CanonicalSuspend)
        .unwrap();
    for ticket in tickets.into_iter().skip(1) {
        r.cancel(ticket).unwrap();
    }
    r.remove(token(1), 0, 8).unwrap();
    assert!(r.is_empty());
}

#[test]
fn only_a_notifier_that_started_the_actual_timer_stop_claims_its_final_close() {
    let mut r = timer();
    assert!(!r.notified(token(1), 0).unwrap());
    r.notify(token(1), 0).unwrap();
    assert!(r.notified(token(1), 0).unwrap());
    assert_eq!(r.remove(token(1), 0, 8), Ok(Some(token(2))));
    let mut r = timer();
    r.start(token(1), 0).unwrap();
    assert_eq!(
        r.notify(token(1), 0),
        Ok(Wake::StopTimer { timer: token(2) })
    );
    r.returned(token(1), 0).unwrap();
    assert_eq!(r.remove(token(1), 0, 8), Ok(None));
    let mut r = timer();
    r.start(token(1), 0).unwrap();
    r.elapsed(token(1), token(2), 0).unwrap();
    r.returned(token(1), 0).unwrap();
    assert_eq!(r.remove(token(1), 0, 8), Ok(Some(token(2))));
}
