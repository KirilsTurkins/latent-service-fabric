use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use latent_core::{ActivationId, BudgetConsumption};
use wasmtime::ResourceLimiter;

use super::*;

mod support;
use support::request;

struct Clock {
    admitted: Instant,
    elapsed_millis: u64,
    samples: AtomicU64,
}

impl Clock {
    fn new() -> Self {
        Self {
            admitted: Instant::now(),
            elapsed_millis: 0,
            samples: AtomicU64::new(0),
        }
    }
}

impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        self.samples.fetch_add(1, Ordering::Relaxed);
        ClockSample::new(9_000, self.monotonic_now())
    }
    fn monotonic_now(&self) -> Instant {
        self.admitted + Duration::from_millis(self.elapsed_millis)
    }
}

struct Cancellation {
    id: ActivationId,
    budget: Option<ActivationBudget>,
    deadline: Option<EffectiveDeadline>,
}

impl ExecutionCancellation for Cancellation {
    fn activation_id(&self) -> &ActivationId {
        &self.id
    }
    fn is_cancelled(&self) -> bool {
        false
    }
    fn reason(&self) -> Option<String> {
        None
    }
    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        self.budget.as_ref()
    }
    fn effective_deadline(&self) -> Option<&EffectiveDeadline> {
        self.deadline
            .as_ref()
            .or_else(|| self.budget.as_ref().map(ActivationBudget::deadline))
    }
}

fn cancellation(request: &ExecutionRequest, clock: &Clock) -> Cancellation {
    let budget = &request.budget;
    let grant = EffectiveActivationBudget::admit_at(
        budget,
        budget,
        budget,
        request.activation.deadline_unix_millis,
        ClockSample::new(1_000, clock.admitted),
    )
    .expect("grant");
    Cancellation {
        id: request.activation.activation_id.clone(),
        budget: Some(ActivationBudget::new(grant)),
        deadline: None,
    }
}

#[test]
fn shares_the_original_ledger_and_charges_only_new_fuel_deltas() {
    let request = request();
    let clock = Clock::new();
    let cancellation = cancellation(&request, &clock);
    let owner = cancellation.budget.as_ref().expect("owner");
    owner.consume_cpu_fuel(25).expect("prior consumption");
    let mut accounting =
        InvocationAccounting::new(&request, &cancellation, &clock).expect("accounting");
    assert!(owner.is_same_instance(accounting.budget()));
    assert_eq!(accounting.deadline(), owner.deadline());
    assert_eq!(clock.samples.load(Ordering::Relaxed), 0);
    assert_eq!(accounting.initial_fuel(), 75);
    accounting.observe_runtime(70, 32).expect("first sample");
    accounting.observe_runtime(60, 64).expect("second sample");
    accounting.observe_runtime(60, 64).expect("repeated sample");
    assert_eq!(owner.snapshot_at(clock.admitted).cpu_fuel, 40);
    assert_eq!(
        accounting
            .remaining_at(clock.admitted, 80)
            .expect("remaining")
            .memory_bytes,
        16
    );
    assert_eq!(
        accounting
            .remaining_at(clock.admitted, 80)
            .expect("remaining")
            .cpu_fuel,
        60
    );
    let finalization = owner.finalize_at(
        Some(&BudgetConsumption {
            cpu_fuel: 15,
            peak_memory_bytes: 64,
            ..BudgetConsumption::default()
        }),
        clock.admitted,
    );
    assert_eq!(finalization.consumption().cpu_fuel, 40);
    assert_eq!(finalization.consumption().peak_memory_bytes, 64);
}

#[test]
fn original_clock_sample_and_tighter_request_deadline_survive_wall_adjustment() {
    let mut request = request();
    let mut clock = Clock::new();
    let cancellation = cancellation(&request, &clock);
    request.activation.deadline_unix_millis = Some(1_030);
    clock.elapsed_millis = 20;
    let accounting =
        InvocationAccounting::new(&request, &cancellation, &clock).expect("original clock domain");
    assert_eq!(accounting.deadline().unix_millis(), Some(1_030));
    assert_eq!(
        accounting.deadline().admitted_at_monotonic(),
        clock.admitted
    );
    assert_eq!(
        accounting
            .remaining_at(clock.monotonic_now(), request.budget.memory_bytes)
            .expect("remaining")
            .wall_time_limit_millis,
        Some(10)
    );
    assert_eq!(clock.samples.load(Ordering::Relaxed), 0);
    clock.elapsed_millis = 30;
    assert_eq!(
        InvocationAccounting::new(&request, &cancellation, &clock)
            .expect_err("expired original grant")
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
}

#[test]
fn legacy_deadline_token_is_used_without_renewing_its_relative_grant() {
    let request = request();
    let mut clock = Clock::new();
    let mut cancellation = cancellation(&request, &clock);
    cancellation.deadline = Some(
        cancellation
            .budget
            .take()
            .expect("owner")
            .deadline()
            .clone(),
    );
    clock.elapsed_millis = 15;
    let accounting =
        InvocationAccounting::new(&request, &cancellation, &clock).expect("legacy admitted token");
    assert_eq!(
        accounting
            .remaining_at(clock.monotonic_now(), request.budget.memory_bytes)
            .expect("remaining")
            .wall_time_limit_millis,
        Some(35)
    );
    assert_eq!(clock.samples.load(Ordering::Relaxed), 0);
}

#[test]
fn stricter_cancellation_monotonic_deadline_is_retained_with_a_supplied_ledger() {
    let request = request();
    let mut clock = Clock::new();
    let mut cancellation = cancellation(&request, &clock);
    let mut shorter = request.budget.clone();
    shorter.wall_time_limit_millis = Some(10);
    cancellation.deadline = Some(
        EffectiveActivationBudget::admit_at(
            &shorter,
            &shorter,
            &shorter,
            Some(9_010),
            ClockSample::new(9_000, clock.admitted),
        )
        .expect("short cancellation deadline")
        .deadline,
    );
    let accounting =
        InvocationAccounting::new(&request, &cancellation, &clock).expect("both constraints");
    assert_eq!(
        accounting.deadline(),
        cancellation.deadline.as_ref().expect("supplied deadline")
    );
    assert_eq!(accounting.deadline().unix_millis(), Some(9_010));
    clock.elapsed_millis = 10;
    assert_eq!(
        InvocationAccounting::new(&request, &cancellation, &clock)
            .expect_err("expired monotonic token despite later Unix representation")
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
}

#[test]
fn fallback_is_one_local_ledger_per_invocation_and_uses_one_sample() {
    let mut request = request();
    request.activation.deadline_unix_millis = None;
    let clock = Clock::new();
    let cancellation = Cancellation {
        id: request.activation.activation_id.clone(),
        budget: None,
        deadline: None,
    };
    let first = InvocationAccounting::new(&request, &cancellation, &clock).expect("first fallback");
    first.budget().consume_log_bytes(7).expect("first log");
    assert_eq!(clock.samples.load(Ordering::Relaxed), 1);
    let second =
        InvocationAccounting::new(&request, &cancellation, &clock).expect("second fallback");
    assert!(!first.budget().is_same_instance(second.budget()));
    assert_eq!(second.budget().snapshot_at(clock.admitted).log_bytes, 0);
    assert_eq!(clock.samples.load(Ordering::Relaxed), 2);
}

#[test]
fn log_reservations_refund_and_terminal_reports_cannot_overwrite_host_charges() {
    let request = request();
    let clock = Clock::new();
    let cancellation = cancellation(&request, &clock);
    let mut accounting =
        InvocationAccounting::new(&request, &cancellation, &clock).expect("accounting");
    let reservation = accounting.budget().reserve_log_bytes(10).expect("reserve");
    assert_eq!(
        accounting
            .remaining_at(clock.admitted, 1024)
            .expect("remaining")
            .log_bytes,
        90
    );
    drop(reservation);
    accounting
        .budget()
        .reserve_log_bytes(7)
        .expect("reserve accepted log")
        .commit()
        .expect("commit");
    assert_eq!(accounting.budget().outstanding_reservations(), 0);
    let finalization = accounting.budget().finalize_at(
        Some(&BudgetConsumption {
            log_bytes: 99,
            ..BudgetConsumption::default()
        }),
        clock.admitted,
    );
    assert_eq!(finalization.consumption().log_bytes, 7);
    assert!(accounting.observe_runtime(100, 0).is_err());
    assert!(accounting.remaining_at(clock.admitted, 1024).is_err());
    assert!(InvocationAccounting::new(&request, &cancellation, &clock).is_err());
    assert_eq!(
        accounting.budget().finalization().expect("frozen"),
        finalization
    );
}

#[test]
fn failed_growth_does_not_charge_a_provisional_memory_peak() {
    const PAGE: usize = 64 * 1024;
    let mut request = request();
    request.budget.memory_bytes = 2 * u64::try_from(PAGE).expect("page");
    request.activation.budget = request.budget.clone();
    let clock = Clock::new();
    let cancellation = cancellation(&request, &clock);
    let mut accounting =
        InvocationAccounting::new(&request, &cancellation, &clock).expect("accounting");
    let mut limiter = crate::host::TrackingLimiter::new(2 * PAGE);
    assert!(limiter
        .memory_growing(0, PAGE, None)
        .expect("initial allocation"));
    accounting
        .observe_runtime(99, limiter.peak_memory_bytes())
        .expect("confirmed initial memory");
    assert!(limiter
        .memory_growing(PAGE, 2 * PAGE, None)
        .expect("provisional growth"));
    assert!(limiter
        .memory_grow_failed(wasmtime::Error::msg("injected allocation failure"))
        .is_err());
    accounting
        .observe_runtime(98, limiter.peak_memory_bytes())
        .expect("rolled back observation");
    assert_eq!(
        accounting
            .budget()
            .snapshot_at(clock.admitted)
            .peak_memory_bytes,
        u64::try_from(PAGE).expect("page")
    );
}

#[test]
fn invalid_owners_grants_and_runtime_counter_increases_fail_closed() {
    let request = request();
    let clock = Clock::new();
    let mut cancellation = cancellation(&request, &clock);
    cancellation.id.0 = "other".to_owned();
    assert!(InvocationAccounting::new(&request, &cancellation, &clock).is_err());
    cancellation.id = request.activation.activation_id.clone();
    let mut wrong = request.clone();
    wrong.budget.cpu_fuel += 1;
    wrong.activation.budget = wrong.budget.clone();
    assert!(InvocationAccounting::new(&wrong, &cancellation, &clock).is_err());
    let mut accounting =
        InvocationAccounting::new(&request, &cancellation, &clock).expect("valid owner");
    assert!(accounting.observe_runtime(101, 0).is_err());
    assert_eq!(accounting.budget().snapshot_at(clock.admitted).cpu_fuel, 0);
    accounting
        .budget()
        .consume_cpu_fuel(100)
        .expect("consume prior allowance");
    assert_eq!(
        InvocationAccounting::new(&request, &cancellation, &clock)
            .expect_err("no remaining fuel")
            .code,
        PlatformErrorCode::ResourceExhausted
    );
}
