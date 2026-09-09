use latent_core::IncomingDeadline;

use super::*;

struct LedgerOnly {
    id: ActivationId,
    ledger: ActivationBudget,
}

impl ExecutionCancellation for LedgerOnly {
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
        Some(&self.ledger)
    }

    fn effective_deadline(&self) -> Option<&EffectiveDeadline> {
        // The ledger is independently authoritative even if this optional
        // compatibility accessor does not supply another deadline token.
        None
    }
}

fn precise_grant(request: &ExecutionRequest, clock: &Clock) -> EffectiveActivationBudget {
    EffectiveActivationBudget::admit_with_deadline_at(
        &request.budget,
        &request.budget,
        &request.budget,
        &IncomingDeadline::new(clock.admitted + Duration::from_micros(750), 1_001),
        ClockSample::new(1_000, clock.admitted),
    )
    .unwrap()
}

#[test]
fn shared_ledger_keeps_submillisecond_deadline_without_a_second_deadline_token() {
    let mut request = request();
    let mut clock = Clock::new();
    let grant = precise_grant(&request, &clock);
    // This is the actual manager handoff: the envelope carries the admitted
    // grant's projection, while the ledger retains precise timing authority.
    request.activation.deadline_unix_millis = grant.deadline.unix_millis();
    let original = grant.deadline.clone();
    let cancellation = LedgerOnly {
        id: request.activation.activation_id.clone(),
        ledger: ActivationBudget::new(grant),
    };
    for supplied in [Some(1_001), Some(1_050), None] {
        request.activation.deadline_unix_millis = supplied;
        let accounting = InvocationAccounting::new(&request, &cancellation, &clock).unwrap();
        assert_eq!(accounting.deadline(), &original);
        assert!(accounting.budget().is_same_instance(&cancellation.ledger));
    }
    clock.admitted = original.monotonic().unwrap();
    assert_eq!(
        InvocationAccounting::new(&request, &cancellation, &clock)
            .unwrap_err()
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(clock.samples.load(Ordering::Relaxed), 0);
}

#[test]
fn legacy_precise_token_is_validated_without_extending_its_unix_projection() {
    let mut request = request();
    let clock = Clock::new();
    let grant = precise_grant(&request, &clock);
    request.activation.deadline_unix_millis = grant.deadline.unix_millis();
    let cancellation = Cancellation {
        id: request.activation.activation_id.clone(),
        budget: None,
        deadline: Some(grant.deadline.clone()),
    };
    let accounting = InvocationAccounting::new(&request, &cancellation, &clock).unwrap();
    assert_eq!(accounting.deadline(), &grant.deadline);
    assert_eq!(accounting.budget().deadline(), &grant.deadline);
    assert_eq!(clock.samples.load(Ordering::Relaxed), 0);
    request.budget.memory_bytes += 1;
    assert_eq!(
        InvocationAccounting::new(&request, &cancellation, &clock)
            .unwrap_err()
            .code,
        PlatformErrorCode::InvalidArgument
    );
}

#[test]
fn relative_ceiling_after_a_wall_jump_preserves_the_managers_grant_projection() {
    let mut request = request();
    request.budget.wall_time_limit_millis = Some(1);
    request.activation.budget = request.budget.clone();
    let mut clock = Clock::new();
    let grant = EffectiveActivationBudget::admit_with_deadline_at(
        &request.budget,
        &request.budget,
        &request.budget,
        &IncomingDeadline::new(clock.admitted + Duration::from_millis(2), 1_002),
        ClockSample::new(9_000, clock.admitted),
    )
    .unwrap();
    assert_eq!(grant.deadline.unix_millis(), Some(9_001));
    request.activation.deadline_unix_millis = grant.deadline.unix_millis();
    let original = grant.deadline.clone();
    let cancellation = LedgerOnly {
        id: request.activation.activation_id.clone(),
        ledger: ActivationBudget::new(grant),
    };
    let accounting = InvocationAccounting::new(&request, &cancellation, &clock).unwrap();
    assert_eq!(accounting.deadline(), &original);
    assert_eq!(clock.samples.load(Ordering::Relaxed), 0);
    clock.elapsed_millis = 1;
    assert_eq!(
        InvocationAccounting::new(&request, &cancellation, &clock)
            .unwrap_err()
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
}
