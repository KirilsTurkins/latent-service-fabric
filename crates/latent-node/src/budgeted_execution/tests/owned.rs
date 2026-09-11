use super::*;

pub(super) struct Owner(Arc<AtomicU64>);

impl Drop for Owner {
    fn drop(&mut self) {
        self.0.fetch_add(1, Ordering::Relaxed);
    }
}

#[tokio::test]
async fn owned_invocation_forwards_identity_guard_accounting_and_cleanup() {
    let recorder = Arc::new(Recorder::default());
    let backend =
        BudgetedExecutionBackend::new(recorder.clone(), ActivationBudgetRegistry::default());
    let release = ReleaseDigest("pinned-release".to_owned());
    assert_eq!(
        backend.preparation_key(&release).unwrap(),
        recorder.preparation_key(&release).unwrap()
    );
    let request = request();
    let owner = ActivationBudget::new(
        EffectiveActivationBudget::admit_at(
            &request.budget,
            &request.budget,
            &request.budget,
            None,
            ClockSample::new(1_000, Instant::now()),
        )
        .unwrap(),
    );
    let cancellation = Cancellation {
        id: request.activation.activation_id.clone(),
        accounting: Some(owner.clone()),
    };
    let drops = Arc::new(AtomicU64::new(0));
    let prepared = PreparedUse::new(request.prepared.clone(), Owner(Arc::clone(&drops)));
    let report = backend
        .invoke_prepared_contained(request, prepared, &cancellation)
        .await;
    assert!(report.outcome.is_ok());
    assert_eq!(
        report.cleanup,
        ExecutionCleanup::Quarantine {
            reason: "fixture cleanup proof".to_owned()
        }
    );
    assert_eq!(drops.load(Ordering::Relaxed), 1);
    assert_eq!(recorder.calls.load(Ordering::Relaxed), 1);
    assert!(recorder.seen.lock().unwrap()[0]
        .as_ref()
        .unwrap()
        .is_same_instance(&owner));
    assert!(owner.finalization().is_none());
    assert_eq!(owner.snapshot_at(Instant::now()).cpu_fuel, 3);
    assert_eq!(owner.snapshot_at(Instant::now()).log_bytes, 7);
}

#[tokio::test]
async fn rejected_or_unpolled_owned_invocations_release_without_calling_backend() {
    let recorder = Arc::new(Recorder::default());
    let backend =
        BudgetedExecutionBackend::new(recorder.clone(), ActivationBudgetRegistry::default());
    let request = request();
    let cancellation = Cancellation {
        id: ActivationId("another-activation".to_owned()),
        accounting: None,
    };
    let drops = Arc::new(AtomicU64::new(0));
    let prepared = PreparedUse::new(request.prepared.clone(), Owner(Arc::clone(&drops)));
    let report = backend
        .invoke_prepared_contained(request.clone(), prepared, &cancellation)
        .await;
    assert_eq!(
        report.outcome.unwrap_err().code,
        PlatformErrorCode::InvalidArgument
    );
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert_eq!(drops.load(Ordering::Relaxed), 1);
    let prepared = PreparedUse::new(request.prepared.clone(), Owner(Arc::clone(&drops)));
    drop(backend.invoke_prepared_contained(request, prepared, &cancellation));
    assert_eq!(drops.load(Ordering::Relaxed), 2);
    assert_eq!(recorder.calls.load(Ordering::Relaxed), 0);
}
