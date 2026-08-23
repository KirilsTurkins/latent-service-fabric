#[tokio::test(flavor = "current_thread")]
async fn queue_race_prefers_cancellation_then_deadline_over_cell_grant() {
    let deadline = now().saturating_add(250);
    let id = ActivationId("queue-cancel-deadline-grant".to_owned());
    let (pool, grant) = QueuePool::new(true);
    let (backend, _) = Backend::new(success_report(consumption()));
    let runner = runner(pool.clone(), backend);
    let task = spawn(runner.clone(), envelope(id.clone(), Some(deadline)));

    grant.entered("grant reached queue barrier").await;
    tokio::task::yield_now().await;
    spin_past(deadline);
    runner
        .cancel(&id, "three-way race cancellation")
        .await
        .expect("cancellation remains registered");

    assert_failure(
        join(task, "three-way queue race").await,
        ActivationTerminalState::Cancelled,
        PlatformErrorCode::Cancelled,
        "activation.cancelled",
        &BudgetConsumption::default(),
    );
    assert_eq!(pool.cancel_calls.load(Ordering::Acquire), 2);

    let deadline = now().saturating_add(250);
    let id = ActivationId("queue-deadline-grant".to_owned());
    let (pool, grant) = QueuePool::new(false);
    let (backend, _) = Backend::new(success_report(consumption()));
    let runner = runner(pool.clone(), backend);
    let task = spawn(runner, envelope(id, Some(deadline)));

    grant.entered("grant reached deadline barrier").await;
    tokio::task::yield_now().await;
    spin_past(deadline);
    grant.proceed("deadline and grant become ready together").await;

    assert_failure(
        join(task, "deadline versus grant").await,
        ActivationTerminalState::DeadlineExceeded,
        PlatformErrorCode::DeadlineExceeded,
        "activation.deadline-exceeded",
        &BudgetConsumption::default(),
    );
    assert_eq!(pool.cancel_calls.load(Ordering::Acquire), 1);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancellation_and_deadline_override_guest_completion_at_handoff() {
    let used = consumption();
    let deadline = now().saturating_add(30);
    let id = ActivationId("handoff-cancellation".to_owned());
    let (backend, gate) = Backend::new(success_report(used.clone()));
    let runner = runner(Pool::immediate(), backend);
    let task = spawn(runner.clone(), envelope(id.clone(), Some(deadline)));

    gate.entered("backend reached cancellation handoff").await;
    wait_past(deadline).await;
    runner
        .cancel(&id, "visible at handoff")
        .await
        .expect("cancellation is accepted before handoff release");
    gate.proceed("backend result released").await;
    assert_failure(
        join(task, "cancellation handoff").await,
        ActivationTerminalState::Cancelled,
        PlatformErrorCode::Cancelled,
        "activation.cancelled",
        &used,
    );

    let used = consumption();
    let deadline = now().saturating_add(30);
    let (backend, gate) = Backend::new(success_report(used.clone()));
    let runner = runner(Pool::immediate(), backend);
    let task = spawn(
        runner,
        envelope(ActivationId("handoff-deadline".to_owned()), Some(deadline)),
    );

    gate.entered("backend reached deadline handoff").await;
    wait_past(deadline).await;
    gate.proceed("deadline result released").await;
    assert_failure(
        join(task, "deadline handoff").await,
        ActivationTerminalState::DeadlineExceeded,
        PlatformErrorCode::DeadlineExceeded,
        "activation.deadline-exceeded",
        &used,
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancellation_is_linearizable_against_registration_removal() {
    let used = consumption();
    let id = ActivationId("registration-removal".to_owned());
    let (backend, handoff) = Backend::new(success_report(used.clone()));
    let (pool, release) = Pool::release(false);
    let runner = runner(pool.clone(), backend);
    let task = spawn(runner.clone(), envelope(id.clone(), Some(now() + 10_000)));

    handoff.entered("backend reached result handoff").await;
    handoff.proceed("guest result accepted").await;
    release.entered("release blocks before registration removal").await;
    runner
        .cancel(&id, "accepted after handoff")
        .await
        .expect("registration remains live until disposition completes");
    release.proceed("release completes").await;

    assert_success(join(task, "registration removal").await, &used);
    let error = runner
        .cancel(&id, "after removal")
        .await
        .expect_err("registration is removed after completion");
    assert_eq!(error.code, PlatformErrorCode::NotFound);
    assert_eq!(runner.snapshot().active_cancellation_registrations, 0);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn release_failure_overrides_guest_result_and_preserves_consumption() {
    let used = consumption();
    let report = ExecutionReport::reusable(Ok(GuestOutcome::Trapped {
        trap: GuestTrap {
            code: "controlled-trap".to_owned(),
            message: "mapped before release".to_owned(),
            guest_backtrace: Vec::new(),
            metadata: Metadata::new(),
        },
        consumption: used.clone(),
    }));
    let (backend, handoff) = Backend::new(report);
    let (pool, release) = Pool::release(true);
    let runner = runner(pool.clone(), backend);
    let task = spawn(
        runner.clone(),
        envelope(ActivationId("release-failure".to_owned()), Some(now() + 10_000)),
    );

    handoff.entered("backend reached release handoff").await;
    handoff.proceed("mapped trap proceeds to release").await;
    release.entered("release failure held at boundary").await;
    release.proceed("release failure published").await;

    assert_failure(
        join(task, "release failure").await,
        ActivationTerminalState::PlatformFailed,
        PlatformErrorCode::Internal,
        "cell-disposition.release-failed",
        &used,
    );
    assert_disposition_failure(&runner, &pool);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn quarantine_failure_overrides_guest_result_and_preserves_consumption() {
    let used = consumption();
    let report = ExecutionReport::quarantine(
        Ok(returned(b"completed before quarantine", used.clone())),
        "backend cannot prove safe reuse",
    );
    let (backend, handoff) = Backend::new(report);
    let (pool, quarantine) = Pool::quarantine(true);
    let runner = runner(pool.clone(), backend);
    let task = spawn(
        runner.clone(),
        envelope(
            ActivationId("quarantine-failure".to_owned()),
            Some(now() + 10_000),
        ),
    );

    handoff.entered("backend reached quarantine handoff").await;
    handoff
        .proceed("mapped completion proceeds to quarantine")
        .await;
    quarantine
        .entered("quarantine failure held at boundary")
        .await;
    quarantine.proceed("quarantine failure published").await;

    assert_failure(
        join(task, "quarantine failure").await,
        ActivationTerminalState::PlatformFailed,
        PlatformErrorCode::Internal,
        "cell-disposition.quarantine-failed",
        &used,
    );
    assert_disposition_failure(&runner, &pool);
}
