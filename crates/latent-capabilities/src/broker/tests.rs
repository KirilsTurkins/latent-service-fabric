use super::*;
use latent_artifacts::ArtifactRepository;
use latent_policy::capability::ResourceTarget;
use std::{sync::atomic::Ordering, time::Duration};
pub(super) mod fixture;
use fixture::*;

fn output() -> CapabilityCallCost {
    CapabilityCallCost::new(32)
}
fn call(
    session: &CapabilitySession,
    handle: GuestCapabilityHandle,
) -> Result<OwnedCapabilityResponse, PlatformError> {
    ready(session.call(
        handle,
        "read",
        resource(),
        b"input",
        output(),
        |call| async move { call.complete(b"secret") },
    ))
}
#[test]
fn exact_session_handles_cannot_cross_reused_ids_cells_or_slots() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("same-id");
    let s = f.session(&request, &control);
    let h = s.bind(CAP, "read", resource()).unwrap();
    assert_eq!(call(&s, h).unwrap().bytes(), b"secret");
    assert!(call(
        &s,
        GuestCapabilityHandle::from_wire(h.wire_parts().0, h.wire_parts().1 + 1)
    )
    .is_err());
    assert!(call(
        &s,
        GuestCapabilityHandle::from_wire(u16::MAX, h.wire_parts().1)
    )
    .is_err());
    assert!(f
        .broker
        .open_session(f.plan.clone(), &request, &control, &f.publication)
        .is_err());
    let (other_request, other_control) = f.request("same-id");
    let other = f.session(&other_request, &other_control);
    let other_handle = other.bind(CAP, "read", resource()).unwrap();
    assert_ne!(h, other_handle);
    assert!(call(&other, h).is_err());
    s.close_handle(h).unwrap();
    assert!(s.close_handle(h).is_err());
    let replacement = s.bind(CAP, "read", resource()).unwrap();
    assert_eq!(replacement.wire_parts().0, h.wire_parts().0);
    assert_ne!(replacement.wire_parts().1, h.wire_parts().1);
    assert!(call(&s, h).is_err());
    assert!(call(&s, replacement).is_ok());
}
#[test]
fn stopped_sessions_keep_response_and_original_ledger_until_actual_drop() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("one");
    let s = f.session(&request, &control);
    let observer = s.observer();
    let h = s.bind(CAP, "read", resource()).unwrap();
    let response = call(&s, h).unwrap();
    assert!(response.session.budget.is_same_instance(&control.budget));
    assert_eq!(observer.live_calls(), 0);
    assert_eq!(observer.retained_results(), 1);
    s.close_handle(h).unwrap();
    drop(s);
    assert!(!observer.is_quiescent());
    assert_eq!(f.broker.snapshot().sessions, 1);
    assert_eq!(f.broker.snapshot().buffer_bytes, 32);
    drop(response);
    assert!(observer.is_quiescent());
    assert_eq!(control.budget.outstanding_reservations(), 0);
    let snapshot = f.broker.snapshot();
    assert_eq!(
        (
            snapshot.sessions,
            snapshot.handles,
            snapshot.calls,
            snapshot.results,
            snapshot.buffer_bytes
        ),
        (0, 0, 0, 0, 0)
    );
}
#[test]
fn import_operation_resource_and_principal_cannot_be_widened_by_descriptive_data() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (mut request, control) = f.request("one");
    request.imports[0].contract = "latent:random/random@0.1.0".into();
    assert!(f
        .broker
        .open_session(f.plan.clone(), &request, &control, &f.publication)
        .is_err());
    request.imports[0].contract = CAP.into();
    request.activation.principal.subject = "bob".into();
    request
        .activation
        .principal
        .claims
        .insert("subject".into(), "alice".into());
    let s = f.session(&request, &control);
    assert!(s.bind(CAP, "read", resource()).is_err());
    drop(s);
    request.activation.principal.subject = "alice".into();
    let s = f.session(&request, &control);
    assert!(s.bind(CAP, "write", resource()).is_err());
    assert!(s
        .bind(
            CAP,
            "read",
            ResourceTarget::Secrets {
                reference: "another-key"
            }
        )
        .is_err());
    let h = s.bind(CAP, "read", resource()).unwrap();
    assert!(ready(s.call(
        h,
        "read",
        ResourceTarget::Secrets {
            reference: "another-key"
        },
        b"",
        output(),
        |c| async move { c.complete(b"") }
    ))
    .is_err());
    assert!(s.core.principal.claims.is_empty());
}
#[test]
fn foreign_catalog_plan_tenant_publication_and_ledger_shapes_fail_closed() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let other = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("one");
    assert!(f
        .broker
        .open_session(other.plan.clone(), &request, &control, &f.publication)
        .is_err());
    assert!(f
        .broker
        .open_session(f.plan.clone(), &request, &control, &other.publication)
        .is_err());
    let p = publish(&f.catalog, "same-wasm-correction", "a");
    let proof = f
        .catalog
        .execution_eligibility_selected(f.publication.release(), Some(&p.publication.id))
        .unwrap()
        .unwrap();
    assert_ne!(proof.publication(), f.publication.publication());
    assert!(f
        .broker
        .open_session(f.plan.clone(), &request, &control, &proof)
        .is_err());
    let mut wrong = request.clone();
    wrong.activation.target.tenant.0 = "b".into();
    assert!(f
        .broker
        .open_session(f.plan.clone(), &wrong, &control, &f.publication)
        .is_err());
    wrong = request.clone();
    wrong.budget.cpu_fuel += 1;
    assert!(f
        .broker
        .open_session(f.plan.clone(), &wrong, &control, &f.publication)
        .is_err());
    wrong = request.clone();
    wrong
        .activation
        .resolved_revision
        .as_mut()
        .unwrap()
        .route_generation
        .0 += 1;
    assert!(f
        .broker
        .open_session(f.plan.clone(), &wrong, &control, &f.publication)
        .is_err());
}
#[test]
fn unpolled_calls_reserve_nothing_and_revocation_denies_before_dispatch() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("one");
    let s = f.session(&request, &control);
    let h = s.bind(CAP, "read", resource()).unwrap();
    let before = f.broker.snapshot();
    let future = s.call(h, "read", resource(), b"", output(), |_| async {
        panic!("revoked call dispatched")
    });
    assert_eq!(f.broker.snapshot(), before);
    assert_eq!(control.budget.outstanding_reservations(), 0);
    f.revoke_policy();
    assert!(ready(future).is_err());
    assert_eq!(f.broker.snapshot(), before);
}
#[test]
fn accepted_provider_runs_without_authority_locks_and_may_finish_after_policy_revocation() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("one");
    let s = f.session(&request, &control);
    let h = s.bind(CAP, "read", resource()).unwrap();
    let result = ready(s.call(h, "read", resource(), b"", output(), |call| {
        f.revoke_policy();
        *f.provider
            .reference()
            .entry
            .live
            .try_write()
            .expect("provider fence must be released") = false;
        async move { call.complete(b"accepted-before-revocation") }
    }))
    .unwrap();
    assert_eq!(result.bytes(), b"accepted-before-revocation");
    assert!(call(&s, h).is_err());
}
#[test]
fn provider_registration_retirement_rejects_held_handles() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("one");
    let s = f.session(&request, &control);
    let h = s.bind(CAP, "read", resource()).unwrap();
    f.provider.retire();
    assert!(call(&s, h).is_err());
    assert!(s.bind(CAP, "read", resource()).is_err());
}
#[test]
fn cancellation_and_finalized_budget_are_live_checks() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("one");
    let s = f.session(&request, &control);
    let h = s.bind(CAP, "read", resource()).unwrap();
    control.probe.0.store(true, Ordering::Release);
    assert!(call(&s, h).is_err());
    assert!(s.bind(CAP, "read", resource()).is_err());
    s.close();
    s.close();
    assert!(s.observer().is_quiescent());
    let (request, control) = f.request("finalized");
    let session = f.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let _ = control.budget.finalize_at(None, std::time::Instant::now());
    assert!(call(&session, handle).is_err());
    assert!(session.bind(CAP, "read", resource()).is_err());
}
#[test]
fn handle_input_output_and_result_limits_reject_without_leaking_owners() {
    let f = Fixture::new(CapabilityBrokerLimits {
        maximum_handles_per_session: 1,
        maximum_results: 1,
        ..Default::default()
    });
    let (request, control) = f.request("one");
    let s = f.session(&request, &control);
    let h = s.bind(CAP, "read", resource()).unwrap();
    assert!(s.bind(CAP, "read", resource()).is_err());
    let before = f.broker.snapshot();
    assert!(ready(
        s.call(h, "read", resource(), &[1; 129], output(), |_| async {
            panic!("oversized request dispatched")
        })
    )
    .is_err());
    assert!(ready(s.call(
        h,
        "read",
        resource(),
        b"",
        CapabilityCallCost::new(257),
        |_| async { panic!("oversized response dispatched") }
    ))
    .is_err());
    assert_eq!(f.broker.snapshot(), before);
    let held = call(&s, h).unwrap();
    assert!(call(&s, h).is_err());
    drop(held);
    assert!(call(&s, h).is_ok());
    assert!(ready(
        s.call(h, "read", resource(), b"", output(), |c| async move {
            c.complete(&[1; 33])
        })
    )
    .is_err());
    assert_eq!(f.broker.snapshot(), before);
    assert_eq!(control.budget.outstanding_reservations(), 0);
}
#[test]
fn detached_actual_work_keeps_capacity_after_its_waiter_and_session_drop() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("one");
    let s = f.session(&request, &control);
    let observer = s.observer();
    let h = s.bind(CAP, "read", resource()).unwrap();
    let (release, wait) = std::sync::mpsc::channel();
    let (done, result) = tokio::sync::oneshot::channel();
    let expected_budget = control.budget.clone();
    let mut worker = None;
    let mut future = Box::pin(s.call(h, "read", resource(), b"input", output(), |call| {
        worker = Some(std::thread::spawn(move || {
            assert!(call.budget_accounting().is_same_instance(&expected_budget));
            wait.recv_timeout(Duration::from_secs(5)).unwrap();
            assert!(call.is_cancelled());
            let result = call.complete(b"late");
            assert!(result.is_err());
            let _ = done.send(result);
        }));
        async move { result.await.unwrap() }
    }));
    pending(future.as_mut());
    drop(future);
    drop(s);
    assert!(!observer.is_quiescent());
    assert_eq!(observer.live_calls(), 1);
    assert_eq!(f.broker.snapshot().buffer_bytes, 37);
    assert_eq!(control.budget.outstanding_reservations(), 0);
    release.send(()).unwrap();
    worker.unwrap().join().unwrap();
    assert!(observer.is_quiescent());
    assert_eq!(f.broker.snapshot().buffer_bytes, 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
}

#[test]
fn actual_provider_budget_charges_are_atomic_required_and_committed_before_dispatch() {
    use latent_core::BudgetDimension::{CpuFuel, LogBytes};
    let f = Fixture::with_minimum(
        CapabilityBrokerLimits::default(),
        &[ProviderBudgetRequirement {
            operation: "read",
            dimension: LogBytes,
            minimum: 2,
        }],
    );
    let (request, control) = f.request("charged");
    let session = f.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    assert!(call(&session, handle).is_err());
    let too_large = CapabilityCallCost::new(32)
        .with_charge(CpuFuel, 3)
        .unwrap()
        .with_charge(LogBytes, 1025)
        .unwrap();
    assert!(ready(
        session.call(handle, "read", resource(), b"", too_large, |_| async {
            panic!("unfunded provider started")
        })
    )
    .is_err());
    let before = control.budget.snapshot_at(std::time::Instant::now());
    assert_eq!((before.cpu_fuel, before.log_bytes), (0, 0));
    assert_eq!(control.budget.outstanding_reservations(), 0);
    let cost = CapabilityCallCost::new(32)
        .with_charge(CpuFuel, 3)
        .unwrap()
        .with_charge(LogBytes, 5)
        .unwrap();
    let response = ready(session.call(handle, "read", resource(), b"", cost, |call| {
        let used = call
            .budget_accounting()
            .snapshot_at(std::time::Instant::now());
        assert_eq!((used.cpu_fuel, used.log_bytes), (3, 5));
        assert_eq!(call.budget_accounting().outstanding_reservations(), 0);
        async move { call.complete(b"charged") }
    }))
    .unwrap();
    drop(response);
    let used = control.budget.snapshot_at(std::time::Instant::now());
    assert_eq!((used.cpu_fuel, used.log_bytes), (3, 5));
}
#[test]
fn unused_multi_dimension_reservations_refund_together_without_refunding_other_work() {
    use latent_core::BudgetDimension::{CpuFuel, LogBytes};
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (_, control) = f.request("group");
    let group = control
        .budget
        .reserve_group(&[(CpuFuel, 3), (LogBytes, 5)])
        .unwrap();
    control.budget.consume(CpuFuel, 7).unwrap();
    assert_eq!(control.budget.outstanding_reservations(), 1);
    drop(group);
    let used = control.budget.snapshot_at(std::time::Instant::now());
    assert_eq!((used.cpu_fuel, used.log_bytes), (7, 0));
    assert_eq!(control.budget.outstanding_reservations(), 0);
    assert!(control
        .budget
        .reserve_group(&[(CpuFuel, 1), (CpuFuel, 2)])
        .is_err());
    assert!(control.budget.reserve_group(&[]).is_err());
}

#[test]
fn provider_errors_unwind_and_foreign_responses_cannot_leak_work_or_identity() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("first");
    let s = f.session(&request, &control);
    let h = s.bind(CAP, "read", resource()).unwrap();
    let before = f.broker.snapshot();
    let failure = ready(s.call(h, "read", resource(), b"", output(), |_call| async {
        Err(PlatformError {
            code: PlatformErrorCode::Unavailable,
            message: "provider-credential".into(),
            retryable: true,
            details: vec![],
        })
    }))
    .err()
    .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::Unavailable);
    assert!(!failure.message.contains("credential"));
    assert!(failure.details.is_empty());
    assert_eq!(f.broker.snapshot(), before);
    let unwind = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        ready(s.call(h, "read", resource(), b"", output(), |_call| async {
            panic!("provider panic");
        }))
    }));
    assert!(unwind.is_err());
    assert_eq!(f.broker.snapshot(), before);
    let response = call(&s, h).unwrap();
    let (request, control) = f.request("other");
    let other = f.session(&request, &control);
    let handle = other.bind(CAP, "read", resource()).unwrap();
    assert!(ready(
        other.call(handle, "read", resource(), b"", output(), |_call| async {
            Ok(response)
        })
    )
    .is_err());
    assert_eq!(f.broker.snapshot().calls, 0);
    assert_eq!(f.broker.snapshot().results, 0);
    assert_eq!(f.broker.snapshot().buffer_bytes, 0);
}

#[test]
fn typed_input_reservations_precede_construction_and_survive_session_close() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = f.request("typed");
    let s = f.session(&request, &control);
    let observer = s.observer();
    let h = s.bind(CAP, "read", resource()).unwrap();
    let before = f.broker.snapshot();
    assert!(s
        .dispatch(
            h,
            "read",
            resource(),
            b"",
            output().with_typed_input_bytes(129),
            |_| panic!("policy input bound bypassed")
        )
        .is_err());
    assert_eq!(f.broker.snapshot(), before);
    assert!(s
        .dispatch(
            h,
            "read",
            resource(),
            b"x",
            output().with_typed_input_bytes(usize::MAX),
            |_| panic!("overflow dispatched")
        )
        .is_err());
    assert_eq!(f.broker.snapshot(), before);
    let actual = s
        .dispatch(
            h,
            "read",
            resource(),
            b"",
            output().with_typed_input_bytes(64),
            |call| {
                assert_eq!(f.broker.snapshot().buffer_bytes, 96);
                call
            },
        )
        .unwrap();
    s.close_handle(h).unwrap();
    drop(s);
    assert!(!observer.is_quiescent());
    assert!(actual.is_cancelled());
    drop(actual);
    assert!(observer.is_quiescent());
    assert_eq!(f.broker.snapshot().buffer_bytes, 0);
}

#[test]
fn incarnation_exhaustion_never_wraps_or_reissues_an_old_slot_identity() {
    let counter = std::sync::atomic::AtomicU64::new(u64::MAX - 1);
    assert_eq!(
        super::session::issue_incarnation(&counter).unwrap(),
        u64::MAX - 1
    );
    assert!(super::session::issue_incarnation(&counter).is_err());
    assert!(super::session::issue_incarnation(&counter).is_err());
    assert_eq!(counter.load(Ordering::Acquire), u64::MAX);
}

#[test]
fn binding_compile_rejects_substituted_provider_configuration_and_expired_work() {
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let wrong = f
        .broker
        .register_provider(ProviderConfiguration {
            capability: CAP,
            profile: "local-secrets-v1",
            configuration_digest: &format!("sha256:{}", "3".repeat(64)),
            configuration_epoch: 1,
            restriction_json: br#"{"operations":[]}"#,
            minimum_call_charges: &[],
        })
        .unwrap();
    let imports = [CapabilityBindingSpec {
        provider: &wrong.reference(),
        imported_operations: &["read".into()],
        policy_ids: &["p".into()],
        provider_binding_id: "binding",
        deployment_restriction_json: br#"{"operations":[]}"#,
    }];
    assert!(f
        .broker
        .compile_plan(
            &f.revision,
            &imports,
            &f.publication,
            std::time::Instant::now() + Duration::from_secs(5)
        )
        .is_err());
    let expired = f
        .broker
        .compile_plan(
            &f.revision,
            &imports,
            &f.publication,
            std::time::Instant::now()
                .checked_sub(Duration::from_secs(1))
                .unwrap(),
        )
        .err()
        .unwrap();
    assert_eq!(expired.code, PlatformErrorCode::DeadlineExceeded);
    let (mut request, mut control) = f.request("expired");
    let sample = latent_core::ClockSample::new(
        1,
        std::time::Instant::now()
            .checked_sub(Duration::from_secs(31))
            .unwrap(),
    );
    control.budget = latent_core::ActivationBudget::new(
        latent_core::EffectiveActivationBudget::admit_at(
            &request.budget,
            &request.budget,
            &request.budget,
            None,
            sample,
        )
        .unwrap(),
    );
    request.activation.deadline_unix_millis = control.budget.deadline().unix_millis();
    let error = f
        .broker
        .open_session(f.plan.clone(), &request, &control, &f.publication)
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::DeadlineExceeded);
}

#[test]
fn runtime_passes_the_tighter_store_deadline_without_minting_another_ledger() {
    struct Plan(Arc<CompiledCapabilityPlan>);
    impl CapabilityPlanSource for Plan {
        fn plan(
            &self,
            _: &latent_routing::ResolvedRevision,
        ) -> Result<Arc<CompiledCapabilityPlan>, PlatformError> {
            Ok(self.0.clone())
        }
    }
    let f = Fixture::new(CapabilityBrokerLimits::default());
    let (mut request, control) = f.request("tight-deadline");
    let sample = latent_core::ClockSample::system_now();
    let deadline = latent_core::EffectiveActivationBudget::admit_at(
        &request.budget,
        &request.budget,
        &request.budget,
        Some(sample.unix_millis() + 1000),
        sample,
    )
    .unwrap()
    .deadline;
    request.activation.deadline_unix_millis = deadline.unix_millis();
    let runtime =
        ActivationCapabilityRuntime::new(f.broker.clone(), Arc::new(Plan(f.plan.clone())));
    assert!(runtime
        .open_session(
            &request,
            &control,
            &f.publication,
            control.budget.deadline()
        )
        .is_err());
    let session = runtime
        .open_session(&request, &control, &f.publication, &deadline)
        .unwrap();
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let call = session
        .dispatch(handle, "read", resource(), b"", output(), |call| call)
        .unwrap();
    assert_eq!(call.deadline(), deadline.monotonic().unwrap());
    assert!(call.budget_accounting().is_same_instance(&control.budget));
}
