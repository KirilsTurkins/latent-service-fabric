use std::sync::atomic::{AtomicU64, AtomicU8, Ordering};
use std::sync::Arc;
use std::time::Instant;

use latent_core::{ActivationClock, BudgetConsumption, Metadata, PlatformError, PlatformErrorCode};
use latent_executor::{ExecutionCancellationProbe, GuestInterruptionKind, GuestOutcome, GuestTrap};
use wasmtime::{Store, Trap, UpdateDeadline};

mod epoch;
#[cfg(test)]
pub(crate) use epoch::EpochObservation;
pub(crate) use epoch::EpochTicker;

pub(crate) const MAX_DIAGNOSTIC_BYTES: usize = 512;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct RuntimeResourceSnapshot {
    pub active_invocations: u64,
    pub live_stores: u64,
    pub live_host_states: u64,
    pub live_component_instances: u64,
    pub live_temporary_buffers: u64,
    pub live_cancellation_probes: u64,
    pub stores_created: u64,
}

#[derive(Debug, Default)]
pub(crate) struct RuntimeResourceCounters {
    active_invocations: AtomicU64,
    live_stores: AtomicU64,
    live_host_states: AtomicU64,
    live_component_instances: AtomicU64,
    live_temporary_buffers: AtomicU64,
    live_cancellation_probes: AtomicU64,
    stores_created: AtomicU64,
}

impl RuntimeResourceCounters {
    pub(crate) fn active_invocation(&self) -> CounterGuard<'_> {
        CounterGuard::new(&self.active_invocations)
    }

    pub(crate) fn store(&self) -> CounterGuard<'_> {
        self.stores_created.fetch_add(1, Ordering::Relaxed);
        CounterGuard::new(&self.live_stores)
    }

    pub(crate) fn host_state(&self) -> CounterGuard<'_> {
        CounterGuard::new(&self.live_host_states)
    }

    pub(crate) fn component_instance(&self) -> CounterGuard<'_> {
        CounterGuard::new(&self.live_component_instances)
    }

    pub(crate) fn temporary_buffer(&self) -> CounterGuard<'_> {
        CounterGuard::new(&self.live_temporary_buffers)
    }

    pub(crate) fn cancellation_probe(&self) -> CounterGuard<'_> {
        CounterGuard::new(&self.live_cancellation_probes)
    }

    pub(crate) fn snapshot(&self) -> RuntimeResourceSnapshot {
        RuntimeResourceSnapshot {
            active_invocations: self.active_invocations.load(Ordering::Relaxed),
            live_stores: self.live_stores.load(Ordering::Relaxed),
            live_host_states: self.live_host_states.load(Ordering::Relaxed),
            live_component_instances: self.live_component_instances.load(Ordering::Relaxed),
            live_temporary_buffers: self.live_temporary_buffers.load(Ordering::Relaxed),
            live_cancellation_probes: self.live_cancellation_probes.load(Ordering::Relaxed),
            stores_created: self.stores_created.load(Ordering::Relaxed),
        }
    }
}

pub(crate) struct CounterGuard<'a> {
    counter: &'a AtomicU64,
}

impl<'a> CounterGuard<'a> {
    fn new(counter: &'a AtomicU64) -> Self {
        counter.fetch_add(1, Ordering::Relaxed);
        Self { counter }
    }
}

impl Drop for CounterGuard<'_> {
    fn drop(&mut self) {
        let previous = self.counter.fetch_sub(1, Ordering::Relaxed);
        debug_assert!(previous > 0, "runtime resource counter underflow");
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
enum StopCause {
    None = 0,
    Cancelled = 1,
    DeadlineExceeded = 2,
}

impl StopCause {
    fn from_u8(value: u8) -> Self {
        match value {
            1 => Self::Cancelled,
            2 => Self::DeadlineExceeded,
            _ => Self::None,
        }
    }
}

pub(crate) struct StopControl {
    deadline: Option<Instant>,
    cancellation: Option<Arc<dyn ExecutionCancellationProbe>>,
    cause: AtomicU8,
    clock: Arc<dyn ActivationClock>,
}

impl StopControl {
    #[cfg(test)]
    pub(crate) fn new(
        deadline: Option<Instant>,
        cancellation: Option<Arc<dyn ExecutionCancellationProbe>>,
    ) -> Self {
        Self::with_clock(
            deadline,
            cancellation,
            Arc::new(latent_core::SystemActivationClock),
        )
    }

    pub(crate) fn with_clock(
        deadline: Option<Instant>,
        cancellation: Option<Arc<dyn ExecutionCancellationProbe>>,
        clock: Arc<dyn ActivationClock>,
    ) -> Self {
        Self {
            deadline,
            cancellation,
            cause: AtomicU8::new(StopCause::None as u8),
            clock,
        }
    }

    /// Records the first observed stop cause. Cancellation is checked first, so
    /// cancellation wins when both conditions are visible at the same epoch
    /// checkpoint. Once recorded, the cause never changes.
    pub(crate) fn observe(&self) -> Option<GuestInterruptionKind> {
        let existing = self.cause();
        if existing != StopCause::None {
            return stop_kind(existing);
        }

        if self
            .cancellation
            .as_ref()
            .is_some_and(|probe| probe.is_cancelled())
        {
            self.record(StopCause::Cancelled);
            return stop_kind(self.cause());
        }
        if self
            .deadline
            .is_some_and(|deadline| self.clock.monotonic_now() >= deadline)
        {
            self.record(StopCause::DeadlineExceeded);
            return stop_kind(self.cause());
        }
        None
    }

    #[cfg(test)]
    pub(crate) fn kind(&self) -> Option<GuestInterruptionKind> {
        stop_kind(self.cause())
    }

    pub(crate) fn reason(&self, kind: GuestInterruptionKind) -> String {
        match kind {
            GuestInterruptionKind::Cancelled => self
                .cancellation
                .as_ref()
                .and_then(|probe| probe.reason())
                .map_or_else(
                    || "activation cancelled".to_owned(),
                    |reason| bounded_text(&reason, MAX_DIAGNOSTIC_BYTES),
                ),
            GuestInterruptionKind::DeadlineExceeded => {
                "activation wall-clock deadline exceeded".to_owned()
            }
            GuestInterruptionKind::FuelExhausted => "activation CPU fuel exhausted".to_owned(),
            GuestInterruptionKind::MemoryExhausted => {
                "activation linear-memory limit exceeded".to_owned()
            }
        }
    }

    fn cause(&self) -> StopCause {
        StopCause::from_u8(self.cause.load(Ordering::Acquire))
    }

    fn record(&self, cause: StopCause) {
        let _ = self.cause.compare_exchange(
            StopCause::None as u8,
            cause as u8,
            Ordering::AcqRel,
            Ordering::Acquire,
        );
    }
}

fn stop_kind(cause: StopCause) -> Option<GuestInterruptionKind> {
    match cause {
        StopCause::None => None,
        StopCause::Cancelled => Some(GuestInterruptionKind::Cancelled),
        StopCause::DeadlineExceeded => Some(GuestInterruptionKind::DeadlineExceeded),
    }
}

pub(crate) fn configure_epoch<T: 'static>(
    store: &mut Store<T>,
    stop: Arc<StopControl>,
    deadline_ticks: u64,
) {
    #[cfg(target_has_atomic = "64")]
    {
        store.epoch_deadline_callback(move |_| {
            if stop.observe().is_some() {
                Ok(UpdateDeadline::Interrupt)
            } else {
                Ok(UpdateDeadline::Yield(deadline_ticks))
            }
        });
        store.set_epoch_deadline(deadline_ticks);
    }
    #[cfg(not(target_has_atomic = "64"))]
    {
        let _ = (store, stop, deadline_ticks);
    }
}

pub(crate) fn interrupted_outcome(
    kind: GuestInterruptionKind,
    reason: String,
    consumption: BudgetConsumption,
) -> GuestOutcome {
    GuestOutcome::Interrupted {
        kind,
        reason: bounded_text(&reason, MAX_DIAGNOSTIC_BYTES),
        consumption,
    }
}

pub(crate) fn classify_runtime_error(
    error: &wasmtime::Error,
    stop: &StopControl,
    memory_exhausted: bool,
    consumption: BudgetConsumption,
) -> Result<GuestOutcome, PlatformError> {
    if let Some(kind) = stop.observe() {
        return Ok(interrupted_outcome(kind, stop.reason(kind), consumption));
    }
    classify_runtime_failure(
        None,
        memory_exhausted,
        error.downcast_ref::<Trap>(),
        consumption,
    )
}

fn classify_runtime_failure(
    stop_kind: Option<GuestInterruptionKind>,
    memory_exhausted: bool,
    trap: Option<&Trap>,
    consumption: BudgetConsumption,
) -> Result<GuestOutcome, PlatformError> {
    if let Some(kind) = stop_kind {
        let reason = match kind {
            GuestInterruptionKind::Cancelled => "activation cancelled",
            GuestInterruptionKind::DeadlineExceeded => "activation wall-clock deadline exceeded",
            GuestInterruptionKind::FuelExhausted => "activation CPU fuel exhausted",
            GuestInterruptionKind::MemoryExhausted => "activation linear-memory limit exceeded",
        };
        return Ok(interrupted_outcome(kind, reason.to_owned(), consumption));
    }
    if memory_exhausted {
        return Ok(interrupted_outcome(
            GuestInterruptionKind::MemoryExhausted,
            "activation linear-memory limit exceeded".to_owned(),
            consumption,
        ));
    }

    if let Some(trap) = trap {
        if matches!(trap, Trap::OutOfFuel) {
            return Ok(interrupted_outcome(
                GuestInterruptionKind::FuelExhausted,
                "activation CPU fuel exhausted".to_owned(),
                consumption,
            ));
        }
        if matches!(trap, Trap::Interrupt) {
            return Err(platform_error(
                PlatformErrorCode::Internal,
                "Wasmtime interrupted execution without a registered stop cause",
                false,
            ));
        }

        let label = trap_label(trap);
        let mut metadata = Metadata::new();
        metadata.insert("trap".to_owned(), label.to_owned());
        return Ok(GuestOutcome::Trapped {
            trap: GuestTrap {
                code: "guest-trap".to_owned(),
                message: bounded_text(&format!("guest trapped: {label}"), MAX_DIAGNOSTIC_BYTES),
                guest_backtrace: Vec::new(),
                metadata,
            },
            consumption,
        });
    }

    // Host-import errors and component-model lifting failures are guest-visible
    // execution failures, not engine construction failures. Keep the diagnostic
    // generic and bounded so no guest-controlled value or Wasmtime context chain
    // escapes into the activation result.
    let mut metadata = Metadata::new();
    metadata.insert("classification".to_owned(), "runtime-error".to_owned());
    Ok(GuestOutcome::Trapped {
        trap: GuestTrap {
            code: "guest-runtime-error".to_owned(),
            message: "guest execution failed".to_owned(),
            guest_backtrace: Vec::new(),
            metadata,
        },
        consumption,
    })
}

fn trap_label(trap: &Trap) -> &'static str {
    match trap {
        Trap::StackOverflow => "stack-overflow",
        Trap::MemoryOutOfBounds => "memory-out-of-bounds",
        Trap::HeapMisaligned => "heap-misaligned",
        Trap::TableOutOfBounds => "table-out-of-bounds",
        Trap::IndirectCallToNull => "indirect-call-to-null",
        Trap::BadSignature => "bad-signature",
        Trap::IntegerOverflow => "integer-overflow",
        Trap::IntegerDivisionByZero => "integer-division-by-zero",
        Trap::BadConversionToInteger => "bad-conversion-to-integer",
        Trap::UnreachableCodeReached => "unreachable-code",
        Trap::AllocationTooLarge => "allocation-too-large",
        _ => "guest-fault",
    }
}

pub(crate) fn platform_error(
    code: PlatformErrorCode,
    message: &str,
    retryable: bool,
) -> PlatformError {
    PlatformError {
        code,
        message: bounded_text(message, MAX_DIAGNOSTIC_BYTES),
        retryable,
        details: Vec::new(),
    }
}

pub(crate) fn bounded_text(value: &str, maximum_bytes: usize) -> String {
    if value.len() <= maximum_bytes {
        return value.to_owned();
    }
    let mut end = maximum_bytes;
    while !value.is_char_boundary(end) {
        end -= 1;
    }
    value[..end].to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicBool;
    use std::time::Duration;

    struct TestCancellationProbe {
        cancelled: AtomicBool,
    }

    impl TestCancellationProbe {
        fn new(cancelled: bool) -> Self {
            Self {
                cancelled: AtomicBool::new(cancelled),
            }
        }

        fn cancel(&self) {
            self.cancelled.store(true, Ordering::Release);
        }
    }

    impl ExecutionCancellationProbe for TestCancellationProbe {
        fn is_cancelled(&self) -> bool {
            self.cancelled.load(Ordering::Acquire)
        }

        fn reason(&self) -> Option<String> {
            Some("controlled cancellation".to_owned())
        }
    }

    #[test]
    fn bounded_text_preserves_utf8_boundaries() {
        assert_eq!(bounded_text("aéz", 2), "a");
        assert_eq!(bounded_text("aéz", 3), "aé");
    }

    #[test]
    fn first_stop_cause_is_sticky_across_repeated_epoch_observations() {
        let probe = Arc::new(TestCancellationProbe::new(false));
        let stop = StopControl::new(
            Some(Instant::now() - Duration::from_millis(1)),
            Some(probe.clone()),
        );

        assert_eq!(
            stop.observe(),
            Some(GuestInterruptionKind::DeadlineExceeded)
        );
        probe.cancel();
        assert_eq!(
            stop.observe(),
            Some(GuestInterruptionKind::DeadlineExceeded),
            "a later cancellation must not replace the first deadline cause"
        );
        assert_eq!(stop.kind(), Some(GuestInterruptionKind::DeadlineExceeded));
    }

    #[test]
    fn injected_monotonic_clock_controls_deadline_without_wall_clock_or_sleep() {
        struct Clock(std::sync::Mutex<latent_core::ClockSample>);
        impl ActivationClock for Clock {
            fn sample(&self) -> latent_core::ClockSample {
                *self.0.lock().expect("test clock")
            }
            fn monotonic_now(&self) -> Instant {
                self.sample().monotonic()
            }
        }
        let origin = Instant::now() + Duration::from_secs(60);
        let deadline = origin + Duration::from_millis(10);
        let clock = Arc::new(Clock(std::sync::Mutex::new(latent_core::ClockSample::new(
            1000, origin,
        ))));
        let stop = StopControl::with_clock(Some(deadline), None, clock.clone());
        assert_eq!(stop.observe(), None);
        *clock.0.lock().expect("test clock") = latent_core::ClockSample::new(u64::MAX, origin);
        assert_eq!(
            stop.observe(),
            None,
            "wall adjustment does not expire a monotonic grant"
        );
        *clock.0.lock().expect("test clock") = latent_core::ClockSample::new(1, deadline);
        assert_eq!(
            stop.observe(),
            Some(GuestInterruptionKind::DeadlineExceeded)
        );
        *clock.0.lock().expect("test clock") = latent_core::ClockSample::new(2, origin);
        assert_eq!(
            stop.observe(),
            Some(GuestInterruptionKind::DeadlineExceeded)
        );
    }

    #[test]
    fn cancellation_wins_when_cancellation_and_deadline_are_first_visible_together() {
        let probe = Arc::new(TestCancellationProbe::new(true));
        let stop = StopControl::new(Some(Instant::now() - Duration::from_millis(1)), Some(probe));

        assert_eq!(stop.observe(), Some(GuestInterruptionKind::Cancelled));
        assert_eq!(stop.observe(), Some(GuestInterruptionKind::Cancelled));
    }

    #[test]
    fn cancellation_and_deadline_precede_fuel_exhaustion() {
        let cancellation = classify_runtime_failure(
            Some(GuestInterruptionKind::Cancelled),
            false,
            Some(&Trap::OutOfFuel),
            consumption(),
        )
        .expect("cancellation remains a guest interruption");
        assert_interruption(cancellation, GuestInterruptionKind::Cancelled);

        let deadline = classify_runtime_failure(
            Some(GuestInterruptionKind::DeadlineExceeded),
            false,
            Some(&Trap::OutOfFuel),
            consumption(),
        )
        .expect("deadline remains a guest interruption");
        assert_interruption(deadline, GuestInterruptionKind::DeadlineExceeded);
    }

    #[test]
    fn memory_precedes_fuel_and_guest_trap_classification() {
        let fuel = classify_runtime_failure(None, true, Some(&Trap::OutOfFuel), consumption())
            .expect("memory denial remains a guest interruption");
        assert_interruption(fuel, GuestInterruptionKind::MemoryExhausted);

        let trap = classify_runtime_failure(
            None,
            true,
            Some(&Trap::UnreachableCodeReached),
            consumption(),
        )
        .expect("memory denial remains a guest interruption");
        assert_interruption(trap, GuestInterruptionKind::MemoryExhausted);
    }

    #[test]
    fn fuel_exhaustion_precedes_generic_guest_trap_classification() {
        let outcome = classify_runtime_failure(None, false, Some(&Trap::OutOfFuel), consumption())
            .expect("fuel exhaustion remains a guest interruption");
        assert_interruption(outcome, GuestInterruptionKind::FuelExhausted);
    }

    fn consumption() -> BudgetConsumption {
        BudgetConsumption {
            cpu_fuel: 7,
            peak_memory_bytes: 4096,
            wall_time_micros: 11,
            ..BudgetConsumption::default()
        }
    }

    fn assert_interruption(outcome: GuestOutcome, expected: GuestInterruptionKind) {
        match outcome {
            GuestOutcome::Interrupted { kind, .. } => assert_eq!(kind, expected),
            other => panic!("expected {expected:?}, got {other:?}"),
        }
    }
}
