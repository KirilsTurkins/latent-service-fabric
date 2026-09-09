use latent_core::{
    DeadlineDiagnosticDecision, DeadlineDiagnosticObservation, DeadlineDiagnosticObserver,
};

use super::*;

#[test]
fn diagnostic_seam_preserves_frozen_grants_and_the_strict_feasibility_floor() {
    let h = Harness::new(node_policy(), revision_policy());
    let observer = DeadlineDiagnosticObserver::new(h.sample.monotonic());
    let token = observer
        .begin(DeadlineDiagnosticObservation::Ingress {
            observed_at: h.sample.monotonic(),
            expires_at: None,
            deadline_unix_millis: None,
        })
        .unwrap();
    assert!(observer.bind(token, "observed"));
    for (millis, decision) in [
        (10, DeadlineDiagnosticDecision::QueueInfeasible),
        (11, DeadlineDiagnosticDecision::Accepted),
    ] {
        let mut request = Harness::request("observed");
        request.requested_budget.wall_time_limit_millis = Some(millis);
        let plain = h.controller.admit_at(request.clone(), h.sample);
        let expected = plain
            .as_ref()
            .map(|permit| permit.deadline().clone())
            .map_err(|error| error.code);
        drop(plain);
        let instrumented_grant = h
            .controller
            .admit_at_with_diagnostics(request, h.sample, &observer);
        assert_eq!(
            instrumented_grant
                .as_ref()
                .map(|permit| permit.deadline().clone())
                .map_err(|error| error.code),
            expected
        );
        let snapshot = observer.snapshot();
        let DeadlineDiagnosticObservation::AdmissionCheck {
            observed_at,
            remaining,
            required,
            decision: actual,
            ..
        } = &snapshot.records.last().unwrap().observation
        else {
            panic!("missing actual admission witness");
        };
        assert_eq!(*observed_at, h.sample.monotonic());
        assert_eq!(*remaining, Some(Duration::from_millis(millis)));
        assert_eq!(*required, Some(Duration::from_millis(10)));
        assert_eq!(*actual, decision);
        drop(instrumented_grant);
        h.assert_empty();
    }
    let before = observer.snapshot();
    assert!(!before.overflowed);
    assert_eq!(before.records.len(), 3);
    drop(
        h.controller
            .admit_at_with_diagnostics(Harness::request("ordinary"), h.sample, &observer)
            .unwrap(),
    );
    assert_eq!(observer.snapshot(), before);
    h.assert_empty();
}
