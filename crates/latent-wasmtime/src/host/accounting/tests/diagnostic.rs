use latent_core::{DeadlineDiagnosticObservation, DeadlineDiagnosticObserver, IncomingDeadline};

use super::*;

struct ObservedClock {
    clock: Clock,
    observer: DeadlineDiagnosticObserver,
}

impl ActivationClock for ObservedClock {
    fn sample(&self) -> ClockSample {
        self.clock.sample()
    }

    fn monotonic_now(&self) -> Instant {
        self.clock.monotonic_now()
    }

    fn deadline_diagnostic_observer(&self) -> Option<&DeadlineDiagnosticObserver> {
        Some(&self.observer)
    }
}

#[test]
fn execution_hook_records_the_precise_deadline_and_the_actual_expiry_check_sample() {
    let mut request = request();
    let initial = Clock::new();
    let now = initial.admitted;
    let observer = DeadlineDiagnosticObserver::new(now);
    let token = observer
        .begin(DeadlineDiagnosticObservation::Ingress {
            observed_at: now,
            expires_at: Some(now + Duration::from_micros(750)),
            deadline_unix_millis: Some(1_001),
        })
        .unwrap();
    assert!(observer.bind(token, &request.activation.activation_id.0));
    let grant = EffectiveActivationBudget::admit_with_deadline_at(
        &request.budget,
        &request.budget,
        &request.budget,
        &IncomingDeadline::new(now + Duration::from_micros(750), 1_001),
        ClockSample::new(1_000, now),
    )
    .unwrap();
    request.activation.deadline_unix_millis = grant.deadline.unix_millis();
    let original = grant.deadline.clone();
    let cancellation = Cancellation {
        id: request.activation.activation_id.clone(),
        budget: Some(ActivationBudget::new(grant)),
        deadline: None,
    };
    let mut clock = ObservedClock {
        clock: initial,
        observer,
    };
    let accounting = InvocationAccounting::new(&request, &cancellation, &clock).unwrap();
    assert_eq!(accounting.deadline(), &original);
    let expected = DeadlineDiagnosticObservation::ExecutionDeadline {
        observed_at: now,
        deadline: original.clone(),
        budget: request.budget.clone(),
    };
    assert_eq!(clock.observer.snapshot().records[1].observation, expected);
    clock.clock.admitted = original.monotonic().unwrap();
    assert_eq!(
        InvocationAccounting::new(&request, &cancellation, &clock)
            .unwrap_err()
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(
        clock.observer.snapshot().records[2].observation,
        DeadlineDiagnosticObservation::ExecutionDeadline {
            observed_at: original.monotonic().unwrap(),
            deadline: original,
            budget: request.budget,
        }
    );
    assert_eq!(clock.clock.samples.load(Ordering::Relaxed), 0);
    assert!(!clock.observer.snapshot().overflowed);
}
