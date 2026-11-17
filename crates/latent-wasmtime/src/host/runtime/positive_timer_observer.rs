//! Explicit, bounded positive observations for selected timer fixtures.
//! No record changes a guest result, runtime owner, authority or error path.
use latent_core::activation_runtime::{OwnerKind, RuntimeToken};
use std::{
    future::Future,
    io::Write,
    pin::Pin,
    sync::atomic::{AtomicBool, AtomicU8, Ordering},
    task::{Context, Poll},
};

const ENVIRONMENT: &str = "LSF_GO_NODE_STOP_TIMER_OBSERVER";
const PREFIX: &str = "LSF-GO-NODE-STOP-TIMER-V1";
const TYPESCRIPT_ENVIRONMENT: &str = "LSF_TYPESCRIPT_ROOT_DRAIN_TIMER_OBSERVER";
const TYPESCRIPT_PREFIX: &str = "LSF-TYPESCRIPT-ROOT-DRAIN-TIMER-V1";
const MAXIMUM_MODE_RECORDS: u8 = 8;
// Reserve the sixteenth and last possible record for one closed overflow marker.
const MAXIMUM_EVENTS: u8 = 15;
static BUDGET: Budget = Budget::new();

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Mode {
    Pending,
    Drain,
    TypescriptDrain,
}
impl Mode {
    const fn label(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Drain => "drain",
            Self::TypescriptDrain => "typescript",
        }
    }
}

#[derive(Clone, Copy)]
pub(super) enum Event {
    RootAdmitted,
    RootSettled,
    StartAccepted,
    NextEntered,
    RootClose,
    WaitPending,
}
impl Event {
    const fn label(self) -> &'static str {
        match self {
            Self::RootAdmitted => "root-admitted",
            Self::RootSettled => "root-settled",
            Self::StartAccepted => "start-accepted",
            Self::NextEntered => "next-entered",
            Self::RootClose => "root-close",
            Self::WaitPending => "wait-pending",
        }
    }
}

struct Budget {
    pending: AtomicU8,
    drain: AtomicU8,
    typescript: AtomicU8,
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
            typescript: AtomicU8::new(0),
            events: AtomicU8::new(0),
            overflow: AtomicBool::new(false),
        }
    }
    fn claim(&self, mode: Mode) -> Claim {
        let counter = match mode {
            Mode::Pending => &self.pending,
            Mode::Drain => &self.drain,
            Mode::TypescriptDrain => &self.typescript,
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

#[derive(Clone, Copy)]
pub(super) struct Observer {
    mode: Mode,
    root: Option<RuntimeToken>,
    duplicate_root: bool,
}
impl Observer {
    pub(super) fn for_activation(activation: &str) -> Option<Self> {
        if activation == "typescript-accepted-after-root" {
            let enabled =
                std::env::var_os(TYPESCRIPT_ENVIRONMENT).is_some_and(|value| value == "1");
            return Self::select_typescript(activation, enabled);
        }
        let enabled = std::env::var_os(ENVIRONMENT).is_some_and(|value| value == "1");
        Self::select(activation, enabled)
    }
    fn select_typescript(activation: &str, enabled: bool) -> Option<Self> {
        (enabled && activation == "typescript-accepted-after-root").then_some(Self {
            mode: Mode::TypescriptDrain,
            root: None,
            duplicate_root: false,
        })
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
        Some(Self {
            mode,
            root: None,
            duplicate_root: false,
        })
    }
    pub(super) fn root_admitted(
        &mut self,
        kind: OwnerKind,
        parent: Option<RuntimeToken>,
        token: RuntimeToken,
        owners: [u32; 7],
    ) {
        if !self.remember_root(kind, parent, token) {
            return;
        }
        self.record(Event::RootAdmitted, owners);
    }
    pub(super) fn root_settled(&self, token: RuntimeToken, before: Option<u32>, owners: [u32; 7]) {
        if !self.matches_root(token) {
            return;
        }
        let _ = write_root_record(
            &mut std::io::stderr().lock(),
            BUDGET.claim(self.mode),
            Event::RootSettled,
            owners,
            true,
            before.and_then(|count| count.checked_sub(1)) == Some(owners[0]),
        );
    }
    fn remember_root(
        &mut self,
        kind: OwnerKind,
        parent: Option<RuntimeToken>,
        token: RuntimeToken,
    ) -> bool {
        if self.mode != Mode::TypescriptDrain || kind != OwnerKind::Task || parent.is_some() {
            return false;
        }
        if self.root.is_some() {
            self.duplicate_root = true;
            return false;
        }
        self.root = Some(token);
        true
    }
    fn matches_root(&self, token: RuntimeToken) -> bool {
        self.mode == Mode::TypescriptDrain && !self.duplicate_root && self.root == Some(token)
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

fn write_root_record(
    output: &mut impl Write,
    claim: Claim,
    event: Event,
    owners: [u32; 7],
    same_original_root: bool,
    original_task_count_reduced: bool,
) -> std::io::Result<()> {
    match claim {
        Claim::Event(sequence) => writeln!(
            output,
            "{TYPESCRIPT_PREFIX}|typescript|{}|{sequence}|{}|{}|{}|{same_original_root}|{original_task_count_reduced}",
            event.label(),
            owners[0],
            owners[3],
            owners[4]
        ),
        Claim::Overflow => writeln!(output, "{TYPESCRIPT_PREFIX}|overflow"),
        Claim::Ignore => Ok(()),
    }
}

/// Poll the original owned timer registration once. A ready/error path must
/// never produce a pending witness; repeated wake polls emit at most once.
pub(super) fn poll_pending<F: Future<Output = ()> + ?Sized>(
    wait: Pin<&mut F>,
    context: &mut Context<'_>,
    observed: &mut bool,
    record: impl FnOnce(),
) -> Poll<()> {
    let result = wait.poll(context);
    if result.is_pending() && !*observed {
        *observed = true;
        record();
    }
    result
}

fn write_record(
    output: &mut impl Write,
    claim: Claim,
    mode: Mode,
    event: Event,
    owners: [u32; 7],
) -> std::io::Result<()> {
    let prefix = if mode == Mode::TypescriptDrain {
        TYPESCRIPT_PREFIX
    } else {
        PREFIX
    };
    match claim {
        Claim::Event(sequence) => writeln!(
            output,
            "{prefix}|{}|{}|{sequence}|{}|{}|{}",
            mode.label(),
            event.label(),
            owners[0],
            owners[3],
            owners[4],
        ),
        Claim::Overflow => writeln!(output, "{prefix}|overflow"),
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
        for id in [
            "",
            "node-stop-drain",
            "typescript-accepted-after-root-extra",
        ] {
            assert!(Observer::select_typescript(id, true).is_none());
        }
        assert!(Observer::select_typescript("typescript-accepted-after-root", false).is_none());
        assert!(Observer::select_typescript("typescript-accepted-after-root", true).is_some());
    }

    #[test]
    fn typescript_witness_is_opt_in_fixed_format_and_bounded() {
        let budget = Budget::new();
        let mut output = Vec::new();
        for _ in 0..9 {
            write_record(
                &mut output,
                budget.claim(Mode::TypescriptDrain),
                Mode::TypescriptDrain,
                Event::RootClose,
                [2, 0, 0, 1, 1, 0, 0],
            )
            .unwrap();
        }
        let text = std::str::from_utf8(&output).unwrap();
        assert_eq!(text.lines().count(), 9);
        assert!(text
            .lines()
            .next()
            .unwrap()
            .starts_with("LSF-TYPESCRIPT-ROOT-DRAIN-TIMER-V1|typescript|root-close|1|2|1|1"));
        assert_eq!(
            text.lines().last(),
            Some("LSF-TYPESCRIPT-ROOT-DRAIN-TIMER-V1|overflow")
        );
    }

    #[test]
    fn typescript_root_witness_matches_the_original_without_logging_token_values() {
        assert!(Observer::select_typescript("typescript-accepted-after-root", false).is_none());
        let mut observer =
            Observer::select_typescript("typescript-accepted-after-root", true).unwrap();
        let original = RuntimeToken {
            generation: 913,
            id: 427,
        };
        assert!(!observer.remember_root(OwnerKind::Native, None, original));
        assert!(!observer.remember_root(OwnerKind::Task, Some(original), original));
        assert!(observer.remember_root(OwnerKind::Task, None, original));
        assert!(!observer.matches_root(RuntimeToken {
            generation: 914,
            id: 427
        }));
        assert!(!observer.matches_root(RuntimeToken {
            generation: 913,
            id: 428
        }));
        assert!(observer.matches_root(original));
        let mut output = Vec::new();
        write_root_record(
            &mut output,
            Claim::Event(1),
            Event::RootSettled,
            [1; 7],
            true,
            true,
        )
        .unwrap();
        let text = std::str::from_utf8(&output).unwrap();
        assert!(text.ends_with("|true|true\n"));
        assert!(!text.contains("913") && !text.contains("427"));
        assert!(!observer.remember_root(OwnerKind::Task, None, original));
        assert!(!observer.matches_root(original));
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
    fn ready_wait_never_produces_a_pending_observation() {
        let mut ready = std::future::ready(());
        let mut context = Context::from_waker(std::task::Waker::noop());
        let mut observed = false;
        assert!(
            poll_pending(Pin::new(&mut ready), &mut context, &mut observed, || {
                panic!("ready is not a positive pending witness");
            })
            .is_ready()
        );
        assert!(!observed);
    }

    #[test]
    fn original_wait_is_polled_and_only_first_pending_is_observed() {
        struct PendingWait(usize);
        impl Future for PendingWait {
            type Output = ();
            fn poll(mut self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<()> {
                self.0 += 1;
                Poll::Pending
            }
        }
        let mut wait = PendingWait(0);
        let mut context = Context::from_waker(std::task::Waker::noop());
        let mut observed = false;
        let mut records = 0;
        for _ in 0..3 {
            assert!(
                poll_pending(Pin::new(&mut wait), &mut context, &mut observed, || {
                    records += 1;
                })
                .is_pending()
            );
        }
        assert_eq!(wait.0, 3);
        assert_eq!(records, 1);
    }

    #[test]
    fn wait_pending_record_retains_original_closed_format_and_owner_counts() {
        let mut output = Vec::new();
        write_record(
            &mut output,
            Claim::Event(1),
            Mode::Pending,
            Event::WaitPending,
            [1, 0, 0, 1, 1, 0, 0],
        )
        .unwrap();
        assert_eq!(
            output,
            b"LSF-GO-NODE-STOP-TIMER-V1|pending|wait-pending|1|1|1|1\n"
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
