use super::*;

fn request(
    owner: &DispatcherOwner,
    operation: &str,
    action: DispatcherControlAction,
) -> DispatcherControlRequest {
    DispatcherControlRequest::new(
        "node-operator-tenant".into(),
        "node-operator".into(),
        operation.into(),
        owner.snapshot().unwrap().control.generation,
        action,
    )
    .unwrap()
}

async fn apply(
    owner: &DispatcherOwner,
    request: DispatcherControlRequest,
) -> DispatcherControlOutcome {
    let prepared = owner.prepare_control(request).unwrap();
    with_watchdog(
        WATCHDOG,
        owner.submit_control(prepared, |accept| accept()).unwrap(),
    )
    .await
    .unwrap()
    .unwrap()
    .unwrap()
}

#[tokio::test]
async fn detached_control_waiter_keeps_actual_writer_and_original_receipt_on_shared_owner() {
    let fixture = Fixture::new().await;
    let mut owner = fixture.start(config(), vec![], None).await.unwrap();
    let request = request(
        &owner,
        "lost-pause-response",
        DispatcherControlAction::Pause,
    );
    let prepared = owner.prepare_control(request.clone()).unwrap();
    drop(owner.submit_control(prepared, |accept| accept()).unwrap());
    let receipt = with_watchdog(WATCHDOG, async {
        loop {
            match owner.lookup_control(request.clone()) {
                Ok(job) => {
                    if let Some(receipt) = job.await.unwrap().unwrap() {
                        break receipt;
                    }
                }
                Err(DispatcherControlError::PhysicalOwner(ProtectedStoreError::Io(
                    latent_state::store_io::StoreIoError::QueueFull
                    | latent_state::store_io::StoreIoError::AcceptedFull
                    | latent_state::store_io::StoreIoError::ByteBudget,
                ))) => {}
                Err(error) => panic!("control observation failed {error:?}"),
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
    assert_eq!(receipt.request(), &request);
    let snapshot = with_watchdog(WATCHDOG, async {
        loop {
            let snapshot = owner.snapshot().unwrap();
            // A read worker may observe the durable receipt before the writer
            // publishes metadata. Neither receipt nor waiter drop proves that
            // the separate accepted control has finished publication.
            if !snapshot.control.pending {
                break snapshot;
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
    assert!(snapshot.paused && !snapshot.control.pending);
    assert_eq!(snapshot.control.generation, receipt.generation());
    assert!(
        owner
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn durable_pause_never_refunds_an_already_accepted_provider_or_claims_retirement() {
    let fixture = Fixture::new().await;
    let authority = fixture
        .seed(1, "tenant-a", "publication", profile("test.v1"))
        .await;
    let (adapter, mut entered) = Adapter::new("test.v1", Some("tenant-a"));
    let mut owner = fixture
        .start(config(), vec![adapter.clone()], None)
        .await
        .unwrap();
    let parked = event(&mut entered).await;
    let result = apply(
        &owner,
        request(
            &owner,
            "pause-live-provider",
            DispatcherControlAction::Pause,
        ),
    )
    .await;
    assert!(result.published && result.paused);
    let snapshot = owner.snapshot().unwrap();
    assert_eq!(snapshot.physical_owners, 1);
    assert_eq!(snapshot.accepted_effects, 1);
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    assert_eq!(adapter.physical.load(Ordering::SeqCst), 1);
    adapter.gates.release(parked.ticket.unwrap()).unwrap();
    wait_disposition(&fixture, &authority, Disposition::ProviderAcknowledged).await;
    assert!(
        owner
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    fixture.finish().await;
}

#[tokio::test]
async fn affine_control_rejects_foreign_engine_owner_and_generic_restore_resume() {
    let first = Fixture::new().await;
    let second = Fixture::new().await;
    let mut first_owner = first.start(config(), vec![], None).await.unwrap();
    let mut second_owner = second
        .start(
            DispatcherConfig {
                start_in_restore_review: true,
                ..config()
            },
            vec![],
            None,
        )
        .await
        .unwrap();
    let prepared = first_owner
        .prepare_control(request(
            &first_owner,
            "foreign-pause",
            DispatcherControlAction::Pause,
        ))
        .unwrap();
    assert!(matches!(
        second_owner.submit_control(prepared, |accept| accept()),
        Err(DispatcherControlError::Conflict)
    ));
    assert!(matches!(
        second_owner.prepare_control(request(
            &second_owner,
            "generic-resume",
            DispatcherControlAction::Resume
        )),
        Err(DispatcherControlError::RestoreReviewRequired)
    ));
    assert_eq!(
        second_owner.resume(),
        Err(DispatcherError::CheckpointRequired)
    );
    assert!(
        second_owner
            .snapshot()
            .unwrap()
            .control
            .restore_review_required
    );
    assert!(
        first_owner
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    assert!(
        second_owner
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    first.finish().await;
    second.finish().await;
}

#[tokio::test]
async fn persisted_pause_survives_actual_role_retirement_and_explicit_fresh_epoch_resume() {
    let fixture = Fixture::new().await;
    let mut first = fixture.start(config(), vec![], None).await.unwrap();
    let receipt = apply(
        &first,
        request(&first, "persisted-pause", DispatcherControlAction::Pause),
    )
    .await
    .receipt;
    assert!(
        first
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    drop(first);
    let authority = fixture
        .seed(3, "tenant-a", "publication", profile("test.v1"))
        .await;
    let (adapter, _entered) = Adapter::new("test.v1", None);
    let mut restarted = fixture
        .start(
            config(),
            vec![adapter.clone()],
            Some((receipt.generation().owner_epoch(), 100)),
        )
        .await
        .unwrap();
    let snapshot = restarted.snapshot().unwrap();
    assert!(snapshot.paused);
    assert_ne!(
        snapshot.control.generation.owner_epoch(),
        receipt.generation().owner_epoch()
    );
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 0);
    let resume = request(
        &restarted,
        "reviewed-new-epoch-resume",
        DispatcherControlAction::Resume,
    );
    let result = apply(&restarted, resume).await;
    assert!(result.published && !result.paused);
    wait_disposition(&fixture, &authority, Disposition::ProviderAcknowledged).await;
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    assert!(
        restarted
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}
