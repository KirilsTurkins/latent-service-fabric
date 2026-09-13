use std::collections::BTreeSet;
use std::sync::Mutex;
use std::time::{Duration, Instant};

#[derive(Debug, Clone)]
pub(crate) struct MixedMemoryRendezvousSnapshot {
    pub(crate) expected: BTreeSet<String>,
    pub(crate) arrived: BTreeSet<String>,
    pub(crate) unexpected: BTreeSet<String>,
    pub(crate) opened: bool,
    pub(crate) timed_out: bool,
    pub(crate) departed_before_release: bool,
}

#[derive(Debug, Default)]
struct State {
    first_arrival: Option<Instant>,
    arrived: BTreeSet<String>,
    unexpected: BTreeSet<String>,
    opened: bool,
    timed_out: bool,
    departed_before_release: bool,
}

#[derive(Debug)]
pub(crate) struct MixedMemoryRendezvous {
    expected: BTreeSet<String>,
    timeout: Duration,
    state: Mutex<State>,
}

impl MixedMemoryRendezvous {
    pub(crate) fn new(expected: BTreeSet<String>, timeout: Duration) -> Self {
        Self {
            expected,
            timeout,
            state: Mutex::new(State::default()),
        }
    }

    pub(crate) fn snapshot(&self) -> MixedMemoryRendezvousSnapshot {
        let state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        MixedMemoryRendezvousSnapshot {
            expected: self.expected.clone(),
            arrived: state.arrived.clone(),
            unexpected: state.unexpected.clone(),
            opened: state.opened,
            timed_out: state.timed_out,
            departed_before_release: state.departed_before_release,
        }
    }

    pub(crate) fn timeout_now(&self) {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .timed_out = true;
    }

    // Only the observer may open the gate, while every activation task remains
    // unfinished. The arrival set alone contains no evidence of current liveness.
    pub(crate) fn release_if_ready(&self, all_unfinished: impl FnOnce() -> bool) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.opened || state.timed_out {
            return;
        }
        if state
            .first_arrival
            .is_some_and(|first| first.elapsed() >= self.timeout)
        {
            state.timed_out = true;
            return;
        }
        if state.arrived == self.expected && state.unexpected.is_empty() {
            if all_unfinished() {
                state.opened = true;
            } else {
                state.departed_before_release = true;
                state.timed_out = true;
            }
        }
    }

    // A failed rendezvous also releases guests so bounded diagnostics can join
    // them. Its opened flag stays false, so cleanup cannot become a witness.
    pub(crate) fn arrive(&self, activation_id: &str) -> bool {
        let now = Instant::now();
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.opened || state.timed_out {
            return true;
        }
        let first_arrival = *state.first_arrival.get_or_insert(now);
        if self.expected.contains(activation_id) {
            state.arrived.insert(activation_id.to_owned());
        } else {
            state.unexpected.insert(activation_id.to_owned());
        }
        if now.duration_since(first_arrival) >= self.timeout {
            state.timed_out = true;
            return true;
        }
        false
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;
    use std::time::{Duration, Instant};

    use super::MixedMemoryRendezvous;

    fn gate() -> MixedMemoryRendezvous {
        MixedMemoryRendezvous::new(
            BTreeSet::from(["pressure".to_owned(), "healthy".to_owned()]),
            Duration::from_secs(2),
        )
    }

    #[test]
    fn arrivals_wait_for_explicit_live_task_observation() {
        let gate = gate();
        assert!(!gate.arrive("pressure"));
        gate.release_if_ready(|| panic!("all arrivals are required first"));
        assert!(!gate.arrive("healthy"));
        assert!(!gate.snapshot().opened);
        gate.release_if_ready(|| true);
        let witness = gate.snapshot();
        assert_eq!(witness.arrived, witness.expected);
        assert!(witness.unexpected.is_empty());
        assert!(witness.opened);
        assert!(!witness.timed_out);
        assert!(!witness.departed_before_release);
        assert!(gate.arrive("pressure"));
        assert!(gate.arrive("healthy"));
    }

    #[test]
    fn historical_arrival_cannot_authorize_release_after_a_task_finishes() {
        let gate = gate();
        assert!(!gate.arrive("pressure"));
        let departed = std::thread::spawn(|| ());
        let deadline = Instant::now() + Duration::from_secs(1);
        while !departed.is_finished() {
            assert!(Instant::now() < deadline, "tiny test thread must finish");
            std::thread::yield_now();
        }
        assert!(!gate.arrive("healthy"));
        gate.release_if_ready(|| !departed.is_finished());
        departed.join().expect("test thread joins");
        let witness = gate.snapshot();
        assert_eq!(witness.arrived, witness.expected);
        assert!(!witness.opened);
        assert!(witness.timed_out);
        assert!(witness.departed_before_release);
        assert!(gate.arrive("healthy"), "cleanup releases remaining guests");
        gate.release_if_ready(|| true);
        assert!(!gate.snapshot().opened, "failure cannot be reopened");
    }

    #[test]
    fn timeout_cleanup_never_opens_the_gate() {
        let gate = gate();
        assert!(!gate.arrive("pressure"));
        gate.timeout_now();
        assert!(gate.arrive("healthy"));
        gate.release_if_ready(|| true);
        assert!(gate.snapshot().timed_out);
        assert!(!gate.snapshot().opened);
    }
}
