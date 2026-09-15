use super::{
    model,
    support::{finish, tenant, Harness},
};
use latent_activation::ActivationOutcome;
use latent_core::{
    ActivationClock, IncomingDeadline, PlatformError, PlatformErrorCode, RouteGeneration,
};
use latent_node::InboundActivationReservation;
use std::{sync::atomic::Ordering, time::Duration};

fn reserve(
    h: &Harness,
    id: &str,
    maximum: usize,
) -> Result<InboundActivationReservation, PlatformError> {
    let mut request = model::request(id);
    request.input = Vec::new();
    let sample = h.clock.sample();
    h.manager.reserve_inbound(
        request,
        maximum,
        IncomingDeadline::new(
            sample.monotonic() + Duration::from_secs(2),
            sample.unix_millis() + 2000,
        ),
    )
}

#[tokio::test]
async fn reserve_before_receiving_pins_route_budget_and_input_without_preparing_a_guest() {
    let h = Harness::standard();
    let mut pending = reserve(&h, "inbound-first", 512).unwrap();
    let deadline = pending.deadline();
    assert_eq!(pending.revision().route_generation, RouteGeneration(1));
    assert_eq!(
        h.quotas.snapshot_now(&tenant()).unwrap().active_activations,
        1
    );
    assert_eq!(h.backend.preparation_calls.load(Ordering::Acquire), 0);
    assert_eq!(
        h.scheduler
            .observations(latent_scheduler::CellClass::Tiny)
            .active_leases,
        0
    );
    h.catalog.generation.store(2, Ordering::Release);
    pending.input_buffer()[..5].copy_from_slice(b"hello");
    let receipt = finish(pending.start(5).unwrap()).await;
    assert!(matches!(receipt.outcome, ActivationOutcome::Succeeded(_)));
    assert_eq!(
        receipt.resolved_revision.unwrap().route_generation,
        RouteGeneration(1)
    );
    assert_eq!(
        h.backend.requests.lock().unwrap()[0].activation.input,
        b"hello"
    );
    assert_eq!(*h.backend.deadlines.lock().unwrap(), vec![Some(deadline)]);
    let next = reserve(&h, "inbound-next", 512).unwrap();
    assert_eq!(next.revision().route_generation, RouteGeneration(2));
    drop(next);
    h.assert_idle();
}

#[tokio::test]
async fn full_admission_refuses_another_pull_and_drop_returns_actual_capacity() {
    let h = Harness::standard();
    let mut reservations = Vec::new();
    for n in 0..8 {
        reservations.push(reserve(&h, &format!("inbound-{n}"), 512).unwrap());
    }
    assert!(reserve(&h, "inbound-overload", 512).is_err());
    assert_eq!(
        h.quotas.snapshot_now(&tenant()).unwrap().active_activations,
        8
    );
    assert_eq!(h.backend.preparation_calls.load(Ordering::Acquire), 0);
    drop(reservations.pop());
    let replacement = reserve(&h, "inbound-replacement", 512).unwrap();
    drop((replacement, reservations));
    h.assert_idle();
}

#[tokio::test]
async fn reserved_input_is_subject_to_policy_and_cannot_grow_at_dispatch() {
    let h = Harness::standard();
    assert!(reserve(&h, "too-large-for-policy", 1025).is_err());
    h.assert_idle();
    let pending = reserve(&h, "oversized-delivery", 16).unwrap();
    assert!(matches!(pending.start(17), Err(e) if e.code == PlatformErrorCode::InvalidArgument));
    assert_eq!(h.backend.preparation_calls.load(Ordering::Acquire), 0);
    h.assert_idle();
}

#[tokio::test]
async fn an_expired_pull_cannot_receive_a_fresh_activation_deadline() {
    let h = Harness::standard();
    let pending = reserve(&h, "inbound-expired", 512).unwrap();
    h.clock.advance(Duration::from_secs(3));
    assert!(
        matches!(pending.checkpoint(), Err(e) if e.code == PlatformErrorCode::DeadlineExceeded)
    );
    assert!(matches!(pending.start(0), Err(e) if e.code == PlatformErrorCode::DeadlineExceeded));
    assert_eq!(h.backend.preparation_calls.load(Ordering::Acquire), 0);
    h.assert_idle();
}
