use std::sync::atomic::{AtomicU64, AtomicU8, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use latent_core::{BudgetConsumption, Metadata, PlatformError, PlatformErrorCode};
use latent_executor::{ExecutionCancellationProbe, GuestInterruptionKind, GuestOutcome, GuestTrap};
use wasmtime::{Engine, Store, Trap, UpdateDeadline};

pub(crate) const MAX_DIAGNOSTIC_BYTES: usize = 512;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct RuntimeResourceSnapshot {
    pub active_invocations: u64,
    pub live_stores: u64,
    pub live_host_states: u64,
    pub live_temporary_buffers: u64,
    pub live_cancellation_probes: u64,
    pub stores_created: u64,
}

#[derive(Debug, Default)]
pub(crate) struct RuntimeResourceCounters {
    active_invocations: AtomicU64,
    live_stores: AtomicU64,
    live_host_states: AtomicU64,
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
            live_temporary_buffers: self.live_temporary_buffers.load(Ordering::Relaxed),
            live_cancellation_probes: self.live_cancellation_probes.load(Ordering::Relaxed),
            stores_created: self.stores_created.load(Ordering::Relaxed),
        }
    }
}

pub(crate) struct CounterGuard<'a> {
    counter: &'a AtomicU64,
}

impl CounterGuard<'_> {
    fn new(counter: &AtomicU64) -> CounterGuard<'_> {
        counter.fetch_add(1, Ordering::Relaxed);
        CounterGuard { counter }
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
}

impl StopControl {
    pub(crate) fn new(
        deadline: Option<Instant>,
        cancellation: Option<Arc<dyn ExecutionCancellationProbe>>,
    ) -> Self {
        Self {
            deadline,
            cancellation,
            cause: AtomicU8::new(StopCause::None as u8),
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
            .is_some_and(|deadline| Instant::now() >= deadline)
        {
            self.record(StopCause::DeadlineExceeded);
            return stop_kind(self.cause());
        }
        None
    }

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

pub(crate) fn start_epoch_ticker(engine: &Engine, interval: Duration) -> Result<(), PlatformError> {
    #[cfg(target_has_atomic = "64")]
    {
        let weak_engine = engine.weak();
        thread::Builder::new()
            .name("latent-wasmtime-epoch".to_owned())
            .spawn(move || loop {
                thread::sleep(interval);
                let Some(engine) = weak_engine.upgrade() else {
                    break;
                };
                engine.increment_epoch();
            })
            .map(|_| ())
            .map_err(|_| {
                platform_error(
                    PlatformErrorCode::Internal,
                    "failed to start the Wasmtime epoch ticker",
                    false,
                )
            })
    }
    #[cfg(not(target_has_atomic = "64"))]
    {
        let _ = (engine, interval);
        Err(platform_error(
            PlatformErrorCode::Internal,
            "Wasmtime epoch interruption requires 64-bit atomics",
            false,
        ))
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

pub(crate) fn monotonic_deadline(
    deadline_unix_millis: Option<u64>,
) -> Result<Option<Instant>, PlatformError> {
    let Some(deadline) = deadline_unix_millis else {
        return Ok(None);
    };
    let now_wall = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    let now_wall = u64::try_from(now_wall).unwrap_or(u64::MAX);
    let now = Instant::now();
    if deadline <= now_wall {
        return Ok(Some(now));
    }
    now.checked_add(Duration::from_millis(deadline - now_wall))
        .map(Some)
        .ok_or_else(|| {
            platform_error(
                PlatformErrorCode::InvalidArgument,
                "activation deadline cannot be represented by the monotonic clock",
                false,
            )
        })
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
    if let Some(kind) = stop.kind() {
        return Ok(interrupted_outcome(kind, stop.reason(kind), consumption));
    }
    if memory_exhausted {
        return Ok(interrupted_outcome(
            GuestInterruptionKind::MemoryExhausted,
            "activation linear-memory limit exceeded".to_owned(),
            consumption,
        ));
    }

    if let Some(trap) = error.downcast_ref::<Trap>() {
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

    Err(platform_error(
        PlatformErrorCode::Internal,
        "Wasmtime execution failed without a classifiable guest trap",
        false,
    ))
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

    #[test]
    fn bounded_text_preserves_utf8_boundaries() {
        assert_eq!(bounded_text("aéz", 2), "a");
        assert_eq!(bounded_text("aéz", 3), "aé");
    }
}
