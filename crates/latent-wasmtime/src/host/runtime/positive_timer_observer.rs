//! Explicit, bounded positive observations for two public node-stop fixtures.
//! No record changes a guest result, runtime owner, authority or error path.
use std::{
    io::Write,
    sync::atomic::{AtomicBool, AtomicU8, Ordering},
};

const ENVIRONMENT: &str = "LSF_GO_NODE_STOP_TIMER_OBSERVER";
const PREFIX: &str = "LSF-GO-NODE-STOP-TIMER-V1";
const MAXIMUM_MODE_RECORDS: u8 = 8;
// Reserve the sixteenth and last possible record for one closed overflow marker.
const MAXIMUM_EVENTS: u8 = 15;
static BUDGET: Budget = Budget::new();

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Mode {
    Pending,
    Drain,
}
impl Mode {
    const fn label(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Drain => "drain",
        }
    }
}

#[derive(Clone, Copy)]
pub(super) enum Event {
    StartAccepted,
    NextEntered,
    RootClose,
}
impl Event {
    const fn label(self) -> &'static str {
        match self {
            Self::StartAccepted => "start-accepted",
            Self::NextEntered => "next-entered",
            Self::RootClose => "root-close",
        }
    }
}

struct Budget {
    pending: AtomicU8,
    drain: AtomicU8,
    events: AtomicU8,
    overflow: AtomicBool,
}
#[derive(Debug, PartialEq, Eq)]
enum Claim {
    Event(u8),
    Overflow,
    Ignore,
}
impl Budget {
    const fn new() -> Self {
        Self {
            pending: AtomicU8::new(0),
            drain: AtomicU8::new(0),
            events: AtomicU8::new(0),
            overflow: AtomicBool::new(false),
        }
    }
    fn claim(&self, mode: Mode) -> Claim {
        let counter = match mode {
            Mode::Pending => &self.pending,
            Mode::Drain => &self.drain,
        };
        let mode_slot = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
            (value < MAXIMUM_MODE_RECORDS).then(|| value + 1)
        });
        let sequence = mode_slot.ok().and_then(|_| {
            self.events
                .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                    (value < MAXIMUM_EVENTS).then(|| value + 1)
                })
                .ok()
        });
        if let Some(previous) = sequence {
            return Claim::Event(previous + 1);
        }
        if self
            .overflow
            .compare_exchange(false, true, Ordering::Relaxed, Ordering::Relaxed)
            .is_ok()
        {
            Claim::Overflow
        } else {
            Claim::Ignore
        }
    }
}

pub(super) struct Observer {
    mode: Mode,
}
impl Observer {
    pub(super) fn for_activation(activation: &str) -> Option<Self> {
        let enabled = std::env::var_os(ENVIRONMENT).is_some_and(|value| value == "1");
        Self::select(activation, enabled)
    }
    fn select(activation: &str, enabled: bool) -> Option<Self> {
        if !enabled {
            return None;
        }
        let mode = match activation {
            "node-stop-pending" => Mode::Pending,
            "node-stop-drain" => Mode::Drain,
            _ => return None,
        };
        Some(Self { mode })
    }
    pub(super) fn record(&self, event: Event, owners: [u32; 7]) {
        // Fixed formatting only; broken/full diagnostic output cannot replace
        // the original runtime result. Missing records cannot qualify a test.
        let _ = write_record(
            &mut std::io::stderr().lock(),
            BUDGET.claim(self.mode),
            self.mode,
            event,
            owners,
        );
    }
}

fn write_record(
    output: &mut impl Write,
    claim: Claim,
    mode: Mode,
    event: Event,
    owners: [u32; 7],
) -> std::io::Result<()> {
    match claim {
        Claim::Event(sequence) => writeln!(
            output,
            "{PREFIX}|{}|{}|{sequence}|{}|{}|{}",
            mode.label(),
            event.label(),
            owners[0],
            owners[3],
            owners[4],
        ),
        Claim::Overflow => writeln!(output, "{PREFIX}|overflow"),
        Claim::Ignore => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disabled_or_any_other_activation_has_no_observer() {
        for enabled in [false, true] {
            for id in [
                "",
                "private",
                "node-stop-pending-before",
                "node-stop-drain-after",
            ] {
                assert!(Observer::select(id, enabled).is_none());
            }
        }
        for id in ["node-stop-pending", "node-stop-drain"] {
            assert!(Observer::select(id, false).is_none());
            assert!(Observer::select(id, true).is_some());
        }
    }

    #[test]
    fn repeated_tables_share_the_process_bound_including_one_overflow_record() {
        let budget = Budget::new();
        let mut output = Vec::new();
        for _ in 0..32 {
            for mode in [Mode::Pending, Mode::Drain] {
                write_record(
                    &mut output,
                    budget.claim(mode),
                    mode,
                    Event::NextEntered,
                    [1; 7],
                )
                .unwrap();
            }
        }
        let text = std::str::from_utf8(&output).unwrap();
        assert_eq!(text.lines().count(), 16);
        assert_eq!(
            text.lines()
                .filter(|line| line.ends_with("|overflow"))
                .count(),
            1
        );
        assert!(
            text.lines()
                .filter(|line| !line.ends_with("|overflow"))
                .count()
                <= 15
        );
    }

    #[test]
    fn each_selected_mode_has_at_most_eight_events() {
        let budget = Budget::new();
        for expected in 1..=8 {
            assert_eq!(budget.claim(Mode::Pending), Claim::Event(expected));
        }
        assert_eq!(budget.claim(Mode::Pending), Claim::Overflow);
        assert_eq!(budget.claim(Mode::Pending), Claim::Ignore);
        assert_eq!(budget.claim(Mode::Drain), Claim::Event(9));
    }

    #[test]
    fn closed_record_has_only_static_labels_and_actual_count_fields() {
        let mut output = Vec::new();
        write_record(
            &mut output,
            Claim::Event(3),
            Mode::Drain,
            Event::RootClose,
            [2, 0, 0, 1, 1, 0, 0],
        )
        .unwrap();
        assert_eq!(
            output,
            b"LSF-GO-NODE-STOP-TIMER-V1|drain|root-close|3|2|1|1\n"
        );
        assert!(output.len() <= 128);
    }

    #[test]
    fn failed_output_does_not_panic_or_return_a_guest_result() {
        struct Closed;
        impl Write for Closed {
            fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
                Err(std::io::ErrorKind::BrokenPipe.into())
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        assert!(write_record(
            &mut Closed,
            Claim::Event(1),
            Mode::Pending,
            Event::StartAccepted,
            [1; 7]
        )
        .is_err());
    }
}
