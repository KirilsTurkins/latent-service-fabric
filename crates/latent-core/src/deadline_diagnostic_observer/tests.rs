use super::*;

fn ingress(now: Instant) -> DeadlineDiagnosticObservation {
    DeadlineDiagnosticObservation::Ingress {
        observed_at: now,
        expires_at: Some(now + Duration::from_micros(750)),
        deadline_unix_millis: Some(1_001),
    }
}

fn decoded(now: Instant) -> DeadlineDiagnosticObservation {
    DeadlineDiagnosticObservation::BodyDecoded {
        observed_at: now,
        request_deadline_unix_millis: None,
        request_wall_time_limit_millis: Some(1),
    }
}

#[test]
fn ingress_binding_and_records_preserve_exact_values_without_owners() {
    let origin = Instant::now();
    let observer = DeadlineDiagnosticObserver::new(origin);
    let token = observer.begin(ingress(origin)).unwrap();
    assert_eq!(token.id(), 0);
    assert_eq!(observer.snapshot().identities[0].activation_id, None);
    assert!(observer.bind(token, "activation-1"));
    observer.record_for_activation("activation-1", decoded(origin + Duration::from_nanos(317)));
    observer.record_for_activation("unobserved", decoded(origin));
    let snapshot = observer.snapshot();
    assert_eq!(snapshot.origin, origin);
    assert!(!snapshot.overflowed);
    assert_eq!(snapshot.identities.len(), 1);
    assert_eq!(
        snapshot.identities[0].activation_id.as_deref(),
        Some("activation-1")
    );
    assert_eq!(snapshot.records.len(), 2);
    assert_eq!(snapshot.records[0].sequence, 0);
    assert_eq!(snapshot.records[0].observation, ingress(origin));
    assert_eq!(snapshot.records[1].sequence, 1);
    assert_eq!(snapshot.records[1].token, token);
    assert_eq!(
        snapshot.records[1].observation,
        decoded(origin + Duration::from_nanos(317))
    );
    assert_eq!(Arc::strong_count(&observer.inner), 1);
    drop(observer);
    // Snapshot/token ownership does not retain the recorder or an invocation.
    assert_eq!(snapshot.records[0].token, token);
}

#[test]
fn foreign_tokens_and_duplicate_bindings_cannot_alias_identity() {
    let now = Instant::now();
    let first = DeadlineDiagnosticObserver::new(now);
    let second = DeadlineDiagnosticObserver::new(now);
    let a = first.begin(ingress(now)).unwrap();
    let b = second.begin(ingress(now)).unwrap();
    assert_eq!(a.id(), b.id());
    assert_ne!(a, b);
    assert!(!second.bind(a, "wrong-owner"));
    second.record(a, decoded(now));
    assert_eq!(second.snapshot().records.len(), 1);
    assert!(second.snapshot().overflowed);
    assert!(first.bind(a, "id"));
    assert!(!first.bind(a, "id"));
    assert!(!first.bind(a, "replacement"));
    let other = first.begin(ingress(now)).unwrap();
    assert!(!first.bind(other, "id"));
    let snapshot = first.snapshot();
    assert!(snapshot.overflowed);
    assert_eq!(snapshot.identities[0].activation_id.as_deref(), Some("id"));
    assert_eq!(snapshot.identities[1].activation_id, None);
}

#[test]
fn population_and_record_exhaustion_preserve_every_retained_sequence() {
    let now = Instant::now();
    let observer = DeadlineDiagnosticObserver::new(now);
    for expected in 0..DeadlineDiagnosticObserver::MAXIMUM_IDENTITIES {
        let token = observer.begin(ingress(now)).unwrap();
        assert_eq!(token.id(), u64::try_from(expected).unwrap());
    }
    assert!(observer.begin(ingress(now)).is_none());
    let token = observer.snapshot().identities[0].token;
    for _ in
        DeadlineDiagnosticObserver::MAXIMUM_IDENTITIES..=DeadlineDiagnosticObserver::MAXIMUM_RECORDS
    {
        observer.record(token, decoded(now));
    }
    let snapshot = observer.snapshot();
    assert!(snapshot.overflowed);
    assert_eq!(snapshot.identities.len(), 23);
    assert_eq!(snapshot.records.len(), 512);
    for (index, record) in snapshot.records.iter().enumerate() {
        assert_eq!(record.sequence, u64::try_from(index).unwrap());
    }
}

#[test]
fn identifier_bound_and_invalid_begin_do_not_retain_unbounded_input() {
    let now = Instant::now();
    let observer = DeadlineDiagnosticObserver::new(now);
    assert!(observer.begin(decoded(now)).is_none());
    let first = observer.begin(ingress(now)).unwrap();
    assert!(!observer.bind(first, ""));
    assert!(!observer.bind(first, &"a".repeat(257)));
    assert!(observer.bind(first, &"a".repeat(256)));
    let snapshot = observer.snapshot();
    assert!(snapshot.overflowed);
    assert_eq!(snapshot.identities.len(), 1);
    assert_eq!(
        snapshot.identities[0].activation_id.as_ref().unwrap().len(),
        256
    );
}

#[test]
fn concurrent_registration_stays_bounded_and_generation_failure_is_explicit() {
    let now = Instant::now();
    let observer = DeadlineDiagnosticObserver::new(now);
    std::thread::scope(|scope| {
        for _ in 0..2 {
            let recorder = &observer;
            scope.spawn(move || {
                for _ in 0..23 {
                    let _ = recorder.begin(ingress(now));
                }
            });
        }
    });
    let snapshot = observer.snapshot();
    assert!(snapshot.overflowed);
    assert_eq!(snapshot.identities.len(), 23);
    assert_eq!(snapshot.records.len(), 23);
    for (index, identity) in snapshot.identities.iter().enumerate() {
        assert_eq!(identity.token.id(), u64::try_from(index).unwrap());
    }
    let exhausted = DeadlineDiagnosticObserver::new(now);
    {
        let mut state = exhausted.lock();
        state.owner = None;
        state.snapshot.overflowed = true;
    }
    assert!(exhausted.begin(ingress(now)).is_none());
    assert!(exhausted.snapshot().overflowed);
    assert!(exhausted.snapshot().records.is_empty());
}

#[test]
fn pre_origin_and_absent_times_remain_distinct_from_zero() {
    let before = Instant::now();
    let observer = DeadlineDiagnosticObserver::new(before + Duration::from_millis(1));
    let event = DeadlineDiagnosticObservation::Ingress {
        observed_at: before,
        expires_at: None,
        deadline_unix_millis: None,
    };
    let token = observer.begin(event.clone()).unwrap();
    observer.record(
        token,
        DeadlineDiagnosticObservation::TerminalDecision {
            observed_at: before,
            expires_at: Some(before),
            decision: DeadlineDiagnosticDecision::DeadlineExceeded,
        },
    );
    let snapshot = observer.snapshot();
    assert_eq!(snapshot.records[0].observation, event);
    assert!(snapshot.origin > before);
    assert!(!snapshot.overflowed);
}
