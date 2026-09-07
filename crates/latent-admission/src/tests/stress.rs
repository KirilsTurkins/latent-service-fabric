use super::*;

#[test]
fn concurrent_tenant_trust_and_queue_class_reservations_are_linearized() {
    for scope_name in ["tenant", "trust-class", "queue-class", "deadline"] {
        let mut node = node_policy();
        let expected = if scope_name == "deadline" { 2 } else { 3 };
        match scope_name {
            "tenant" => {
                node.tenants
                    .get_mut(&TenantId("tenant-a".to_owned()))
                    .unwrap()
                    .limits
                    .maximum_concurrent_activations = 3
            }
            "trust-class" => {
                node.trust_classes
                    .get_mut("sandbox")
                    .unwrap()
                    .limits
                    .maximum_concurrent_activations = 3
            }
            "queue-class" => {
                node.queue_classes
                    .get_mut("normal")
                    .unwrap()
                    .maximum_queued_activations = 3
            }
            _ => node.cell_classes.get_mut("tiny").unwrap().parallelism = 1,
        }
        let h = Harness::new(node, revision_policy());
        let start = Arc::new(Barrier::new(33));
        let counted = Arc::new(Barrier::new(33));
        let release = Arc::new(Barrier::new(33));
        let winners = AtomicUsize::new(0);
        std::thread::scope(|scope| {
            for index in 0..32 {
                let start = start.clone();
                let counted = counted.clone();
                let release = release.clone();
                let controller = h.controller.clone();
                let mut request = Harness::request(&format!("scope-race-{index}"));
                if scope_name == "deadline" {
                    request.deadline_unix_millis = Some(10_120);
                }
                let sample = h.sample;
                let winners = &winners;
                scope.spawn(move || {
                    start.wait();
                    let result = controller.admit_at(request, sample);
                    if result.is_ok() {
                        winners.fetch_add(1, Ordering::SeqCst);
                    }
                    // All participants reach both barriers even if a result is
                    // incorrect, so a regression produces an assertion, not a hang.
                    counted.wait();
                    release.wait();
                    if let Err(error) = &result {
                        assert_eq!(
                            detail(
                                error,
                                if scope_name == "deadline" {
                                    "dimension"
                                } else {
                                    "scope"
                                }
                            ),
                            scope_name
                        );
                    }
                    drop(result);
                });
            }
            start.wait();
            counted.wait();
            let count = winners.load(Ordering::SeqCst);
            let usage = h.quotas.usage().unwrap();
            release.wait();
            assert_eq!(count, expected, "{scope_name}");
            assert_eq!(usize::try_from(usage.active_activations).unwrap(), expected);
        });
        h.assert_empty();
    }
}

struct DelayedSource {
    inner: Arc<Source>,
}

impl RevisionPolicySource for DelayedSource {
    fn admission_policy(
        &self,
        revision: &ResolvedRevision,
    ) -> Result<RevisionAdmissionPolicy, PlatformError> {
        // This is deliberately one-sided: oversleeping cannot make the test
        // fail. The original 50ms deadline must be past before lookup returns.
        std::thread::sleep(Duration::from_millis(75));
        self.inner.admission_policy(revision)
    }
}

#[test]
fn live_admission_resamples_time_after_policy_lookup_instead_of_granting_expired_work() {
    let mut node = node_policy();
    node.overload.maximum_sample_age_millis = u64::MAX;
    let h = Harness::new(node, revision_policy());
    let controller = h.controller.with_policy_source(Arc::new(DelayedSource {
        inner: h.source.clone(),
    }));
    let mut request = Harness::request("delayed");
    request.requested_budget.wall_time_limit_millis = Some(50);
    let error = controller.admit_now(request).unwrap_err();
    assert_eq!(error.code, Code::DeadlineExceeded);
    assert_eq!(h.source.calls.load(Ordering::Relaxed), 1);
    h.assert_empty();
}

#[test]
fn final_timing_check_rejects_stale_observations_and_exact_expiry() {
    use crate::timing::{AdmissionClock, ReservationTiming};
    let mut node = node_policy();
    node.overload.maximum_sample_age_millis = 100;
    let sample = ClockSample::new(10_000, Instant::now());
    let grant = latent_core::EffectiveActivationBudget::admit_at(
        &budget(),
        &node.budget_ceiling,
        &node.budget_ceiling,
        None,
        sample,
    )
    .unwrap();
    let stale = ReservationTiming {
        clock: AdmissionClock::Fixed(sample.monotonic() + Duration::from_millis(101)),
        observed_queue_delay_millis: 0,
        load_observed_at: sample.monotonic(),
    };
    assert_eq!(
        stale.validate(&node, &grant, 0, 1).unwrap_err().code,
        Code::Unavailable
    );
    let expired = ReservationTiming {
        clock: AdmissionClock::Fixed(grant.deadline.monotonic().unwrap()),
        ..stale
    };
    assert_eq!(
        expired.validate(&node, &grant, 0, 1).unwrap_err().code,
        Code::DeadlineExceeded
    );
}

#[test]
fn metadata_limits_cover_all_three_maps_at_the_exact_boundary() {
    let mut node = node_policy();
    node.maximum_metadata_entries = 3;
    node.maximum_metadata_bytes = 6;
    let h = Harness::new(node, revision_policy());
    let mut exact = Harness::request("metadata-boundary");
    exact
        .principal
        .claims
        .insert("a".to_owned(), "x".to_owned());
    exact.attributes.insert("b".to_owned(), "y".to_owned());
    exact
        .revision
        .attributes
        .insert("c".to_owned(), "z".to_owned());
    drop(h.controller.admit_at(exact.clone(), h.sample).unwrap());
    let mut byte_overflow = exact.clone();
    byte_overflow
        .attributes
        .insert("b".to_owned(), "yy".to_owned());
    assert_eq!(
        detail(
            &h.controller.admit_at(byte_overflow, h.sample).unwrap_err(),
            "dimension"
        ),
        "metadata"
    );
    exact.attributes.insert("d".to_owned(), String::new());
    assert_eq!(
        detail(
            &h.controller.admit_at(exact, h.sample).unwrap_err(),
            "dimension"
        ),
        "metadata"
    );
    h.assert_empty();
}

#[test]
fn unavailable_load_is_sanitized_and_old_samples_cannot_replace_newer_ones() {
    struct FailedLoad;
    impl NodeLoadSource for FailedLoad {
        fn snapshot(&self) -> Result<NodeLoadSnapshot, PlatformError> {
            Err(PlatformError {
                code: Code::Internal,
                message: "private-pressure-source-token".to_owned(),
                retryable: false,
                details: vec![],
            })
        }
    }
    let h = Harness::standard();
    let controller =
        LocalAdmissionController::new(h.source.clone(), h.quotas.clone(), Arc::new(FailedLoad));
    let error = controller
        .admit_now(Harness::request("unavailable"))
        .unwrap_err();
    assert_eq!(error.code, Code::Unavailable);
    assert!(!format!("{error:?}").contains("private-pressure-source-token"));
    assert_eq!(h.source.calls.load(Ordering::Relaxed), 0);
    let mut older = h.load.snapshot().unwrap();
    older.observed_at = older
        .observed_at
        .checked_sub(Duration::from_nanos(1))
        .unwrap();
    assert!(h.load.publish(older).is_err());
    assert_eq!(h.load.snapshot().unwrap().observed_at, h.sample.monotonic());
    h.assert_empty();
}

#[test]
fn memory_without_a_compatible_configured_cell_is_rejected() {
    let mut node = node_policy();
    node.cell_classes.retain(|name, _| name == "tiny");
    for tenant in node.tenants.values_mut() {
        tenant.allowed_cell_classes = names(&["tiny"]);
    }
    node.trust_classes
        .get_mut("sandbox")
        .unwrap()
        .allowed_cell_classes = names(&["tiny"]);
    let h = Harness::new(node, revision_policy());
    let mut request = Harness::request("no-cell");
    request.requested_budget.memory_bytes = 65_537;
    let error = h.controller.admit_at(request, h.sample).unwrap_err();
    assert_eq!(error.code, Code::ResourceExhausted);
    assert_eq!(detail(&error, "dimension"), "memory-bytes");
    h.assert_empty();
}

#[cfg(target_os = "linux")]
#[test]
fn admission_state_does_not_grow_with_rejected_service_cardinality() {
    const CHILD: &str = "LSF_ADMISSION_DORMANCY_CHILD";
    if std::env::var(CHILD).as_deref() != Ok("1") {
        let output = std::process::Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "tests::stress::admission_state_does_not_grow_with_rejected_service_cardinality",
                "--nocapture",
                "--test-threads=1",
            ])
            .env(CHILD, "1")
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}\n{}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        print!("{}", String::from_utf8_lossy(&output.stdout));
        return;
    }
    let h = Harness::standard();
    let resources = || {
        let threads = std::fs::read_dir("/proc/self/task").unwrap().count();
        let descriptors = std::fs::read_dir("/proc/self/fd").unwrap().count();
        let sockets = std::fs::read_dir("/proc/self/fd")
            .unwrap()
            .filter_map(Result::ok)
            .filter_map(|entry| std::fs::read_link(entry.path()).ok())
            .filter(|target| target.to_string_lossy().starts_with("socket:"))
            .count();
        let children = std::fs::read_dir("/proc/self/task")
            .unwrap()
            .filter_map(Result::ok)
            .map(|entry| {
                std::fs::read_to_string(entry.path().join("children"))
                    .unwrap()
                    .split_whitespace()
                    .count()
            })
            .sum::<usize>();
        (threads, descriptors, sockets, children)
    };
    let before = resources();
    for index in 0..100_000 {
        let mut request = Harness::request("not-retained");
        request.revision.target.service = ServiceId(format!("dormant-{index}"));
        assert!(h.controller.admit_at(request, h.sample).is_err());
    }
    for index in 0..1000 {
        drop(h.admit(&format!("completed-{index}")).unwrap());
    }
    h.assert_empty();
    let after = resources();
    assert_eq!(before, after);
    println!("rejected_services=100000 completed=1000 resources_before={before:?} resources_after={after:?} retained_tenants=0");
}

#[test]
fn permanent_input_failures_are_not_retryable_and_execution_obligations_are_pinned() {
    let h = Harness::standard();
    let permit = h.admit("obligations").unwrap();
    assert_eq!(
        permit.obligations().backend,
        ExecutionBackendKind::WasmComponent
    );
    assert_eq!(
        permit.obligations().threading,
        ThreadingModel::SingleThreaded
    );
    assert_eq!(permit.obligations().state_model, StateModel::Stateless);
    drop(permit);
    let mut oversized = Harness::request("oversized");
    oversized.payload_bytes = 4096;
    assert!(
        !h.controller
            .admit_at(oversized, h.sample)
            .unwrap_err()
            .retryable
    );
    let mut no_capacity = Harness::request("zero");
    no_capacity.requested_budget.cpu_fuel = 0;
    assert!(
        !h.controller
            .admit_at(no_capacity, h.sample)
            .unwrap_err()
            .retryable
    );
    let mut load = h.load.snapshot().unwrap();
    load.cpu_pressure_milli = 900;
    h.load.publish(load).unwrap();
    assert!(h.admit("overloaded").unwrap_err().retryable);
    h.assert_empty();
}
