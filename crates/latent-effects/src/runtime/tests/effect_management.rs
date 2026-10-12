use super::*;
use crate::dispatch_store::effect_management::{
    EffectManagementAction as Action, EffectManagementError as Error,
};
mod fixture;
use fixture::{access, global, plan, receipt, request, setup, setup_with_send};

#[tokio::test]
async fn detached_reconciliation_waiter_retains_original_capacity_until_cleanup_and_receipt() {
    let (fixture, mut dispatcher, authority, adapter, mut entered) = setup().await;
    let port = dispatcher.management_port();
    let global = global();
    let access = access(&global);
    let plan = plan(
        &port,
        request(
            &fixture,
            &authority,
            Action::Reconcile,
            "reconcile-original",
        )
        .await,
        &access,
    )
    .await;
    let finished = Arc::new(AtomicUsize::new(0));
    let completed = Arc::clone(&finished);
    let job = port
        .mutate_effect_retained(plan.clone(), access.clone(), (), 256, move |result, ()| {
            if let Err(error) = result {
                panic!("detached disposition failed: {error:?}");
            }
            completed.fetch_add(1, Ordering::SeqCst);
            Ok(())
        })
        .unwrap();
    let event = event(&mut entered).await;
    let retained = Arc::downgrade(&access);
    drop(access);
    drop(job);
    assert!(retained.upgrade().is_some());
    assert_eq!(global.snapshot().unwrap().recovery.slots, 1);
    assert_eq!(port.snapshot().unwrap().physical_owners, 1);
    assert!(receipt(&fixture, &plan).await.is_none());
    adapter.gates.release(event.ticket.unwrap()).unwrap();
    with_watchdog(WATCHDOG, async {
        loop {
            if finished.load(Ordering::SeqCst) == 1 && retained.upgrade().is_none() {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await;
    assert!(receipt(&fixture, &plan).await.is_some());
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::ProviderAcknowledged
    );
    assert_eq!(adapter.lookups.load(Ordering::SeqCst), 1);
    assert_eq!(adapter.sends.load(Ordering::SeqCst), 0);
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn unknown_provider_status_preserves_original_uncertainty_and_preallocated_plan() {
    let (fixture, mut dispatcher, authority, adapter, mut entered) = setup().await;
    adapter.positive.store(false, Ordering::Release);
    let port = dispatcher.management_port();
    let global = global();
    let access = access(&global);
    let plan = plan(
        &port,
        request(&fixture, &authority, Action::Reconcile, "unknown-original").await,
        &access,
    )
    .await;
    let job = port
        .mutate_effect_retained(plan.clone(), access, (), 256, |_, ()| Ok(()))
        .unwrap();
    let event = event(&mut entered).await;
    adapter.gates.release(event.ticket.unwrap()).unwrap();
    assert!(matches!(
        job.await.unwrap().unwrap().outcome,
        Err(Error::RecoveryRequired)
    ));
    assert!(receipt(&fixture, &plan).await.is_none());
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::Uncertain
    );
    assert_eq!(adapter.sends.load(Ordering::SeqCst), 0);
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn current_management_revocation_after_lookup_acceptance_prevents_disposition_write() {
    let (fixture, mut dispatcher, authority, adapter, mut entered) = setup().await;
    let port = dispatcher.management_port();
    let global = global();
    let access = access(&global);
    let plan = plan(
        &port,
        request(&fixture, &authority, Action::Reconcile, "revoked-original").await,
        &access,
    )
    .await;
    let job = port
        .mutate_effect_retained(plan.clone(), access.clone(), (), 256, |_, ()| Ok(()))
        .unwrap();
    let event = event(&mut entered).await;
    access.allowed.store(false, Ordering::Release);
    assert_eq!(port.snapshot().unwrap().physical_owners, 1);
    adapter.gates.release(event.ticket.unwrap()).unwrap();
    assert!(matches!(
        job.await.unwrap().unwrap().outcome,
        Err(Error::PermissionDenied)
    ));
    assert!(receipt(&fixture, &plan).await.is_none());
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::Uncertain
    );
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn administrator_stop_and_expired_receipt_recovery_do_not_manufacture_provider_ack() {
    let (fixture, mut dispatcher, authority, adapter, _) = setup().await;
    let port = dispatcher.management_port();
    let global = global();
    let access = access(&global);
    let plan = plan(
        &port,
        request(&fixture, &authority, Action::Terminate, "terminal-original").await,
        &access,
    )
    .await;
    let result = port
        .mutate_effect_retained(plan.clone(), access.clone(), (), 256, |_, ()| Ok(()))
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    match result.outcome.unwrap() {
        EffectManagementOutcome::Mutation { receipt, replayed } => {
            assert!(!replayed);
            assert_eq!(
                receipt.fact(),
                crate::dispatch::EffectManagementFact::AdministratorTerminated
            );
            assert!(receipt.provider_receipt().is_none());
        }
        _ => panic!("expected terminal receipt"),
    }
    fixture
        .clock
        .millis
        .store(plan.expires_at_millis() + 1, Ordering::SeqCst);
    let result = port
        .lookup_effect_receipt_retained(plan, access, (), 256, |_, ()| Ok(()))
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(
        result.outcome,
        Ok(EffectManagementOutcome::Receipt(Some(_)))
    ));
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::DeadLettered
    );
    assert_eq!(adapter.sends.load(Ordering::SeqCst), 0);
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn fresh_lookup_recovers_revoked_expired_execution_without_renewing_old_send() {
    let (fixture, mut dispatcher, authority, adapter, mut entered) = setup().await;
    fixture
        .authority
        .prepare_namespace_close("tenant-a", "orders", 7)
        .unwrap()
        .accept(|| Ok::<(), ()>(()))
        .unwrap();
    fixture
        .clock
        .millis
        .store(authority.expires_at_millis() + 1, Ordering::SeqCst);
    let port = dispatcher.management_port();
    let global = global();
    let access = access(&global);
    let plan = plan(
        &port,
        request(
            &fixture,
            &authority,
            Action::Reconcile,
            "fresh-lookup-original",
        )
        .await,
        &access,
    )
    .await;
    let job = port
        .mutate_effect_retained(plan, access, (), 256, |_, ()| Ok(()))
        .unwrap();
    let event = event(&mut entered).await;
    adapter.gates.release(event.ticket.unwrap()).unwrap();
    assert!(job.await.unwrap().unwrap().outcome.is_ok());
    assert_eq!(adapter.sends.load(Ordering::SeqCst), 0);
    assert!(matches!(
        fixture
            .authority
            .accept(&authority, 1, fixture.clock.observe()),
        Err(AuthorityError::PolicyBlocked)
    ));
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn changed_original_row_rejects_stale_lookup_plan_before_provider_work() {
    let (fixture, mut dispatcher, authority, adapter, _) = setup().await;
    let port = dispatcher.management_port();
    let global = global();
    let access = access(&global);
    let lookup = plan(
        &port,
        request(&fixture, &authority, Action::Reconcile, "stale-lookup").await,
        &access,
    )
    .await;
    let stop = plan(
        &port,
        request(&fixture, &authority, Action::Terminate, "separate-stop").await,
        &access,
    )
    .await;
    assert!(port
        .mutate_effect_retained(stop, access.clone(), (), 256, |_, ()| Ok(()))
        .unwrap()
        .await
        .unwrap()
        .unwrap()
        .outcome
        .is_ok());
    let result = port
        .mutate_effect_retained(lookup, access, (), 256, |_, ()| Ok(()))
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(result.outcome, Err(Error::Conflict)));
    assert_eq!(adapter.lookups.load(Ordering::SeqCst), 0);
    assert_eq!(adapter.sends.load(Ordering::SeqCst), 0);
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn explicit_lookup_progresses_with_ordinary_native_workers_slots_and_global_admission_full() {
    use latent_core::native_capacity::{
        NativeAdmissionClass, NativeCapacityError, NativeReservationRequest,
    };
    let (fixture, mut dispatcher, authority, adapter, mut entered) = setup().await;
    let port = dispatcher.management_port();
    let global = global();
    let access = access(&global);
    let plan = plan(
        &port,
        request(
            &fixture,
            &authority,
            Action::Reconcile,
            "saturated-original",
        )
        .await,
        &access,
    )
    .await;
    let mut ordinary = Vec::new();
    loop {
        match global.reserve(
            NativeAdmissionClass::Ordinary,
            NativeReservationRequest {
                request_bytes: 1,
                ..NativeReservationRequest::default()
            },
            Instant::now() + WATCHDOG,
        ) {
            Ok(reservation) => ordinary.push(reservation),
            Err(NativeCapacityError::SlotsFull) => break,
            Err(error) => panic!("unexpected global pressure: {error:?}"),
        }
    }
    let mut pins = Vec::new();
    loop {
        match fixture.store.reserve_operation() {
            Ok(pin) => pins.push(pin),
            Err(ProtectedStoreError::Io(latent_state::store_io::StoreIoError::AcceptedFull)) => {
                break
            }
            Err(error) => panic!("unexpected native pressure: {error:?}"),
        }
    }
    let workers = dispatcher.services.config.workers;
    let gates = Rendezvous::new(workers);
    let (notice, receiver) = std::sync::mpsc::channel();
    let mut tickets = Vec::new();
    let mut jobs = Vec::new();
    for _ in 0..workers {
        let worker = gates.clone();
        let notice = notice.clone();
        jobs.push(
            port.jobs
                .submit(StoreIoKind::Read, 0, move |_| {
                    let (registration, mut owned) = worker.track(vec![0_u8; 32]).unwrap();
                    owned.commit(Stage::Entered).unwrap();
                    let mut paused = Box::pin(owned.pause());
                    PollProbe::default().pending(paused.as_mut());
                    notice
                        .send(worker.blocked(registration, Stage::Entered).unwrap())
                        .unwrap();
                    latent_core::test_support::block_on(paused);
                })
                .unwrap(),
        );
        tickets.push(receiver.recv_timeout(WATCHDOG).unwrap());
    }
    let job = port
        .mutate_effect_retained(plan, access, (), 256, |_, ()| Ok(()))
        .unwrap();
    let event = event(&mut entered).await;
    assert_eq!(adapter.lookups.load(Ordering::SeqCst), 1);
    adapter.gates.release(event.ticket.unwrap()).unwrap();
    assert!(with_watchdog(WATCHDOG, job)
        .await
        .unwrap()
        .unwrap()
        .outcome
        .is_ok());
    assert_eq!(adapter.sends.load(Ordering::SeqCst), 0);
    for ticket in tickets {
        gates.release(ticket).unwrap();
    }
    for job in jobs {
        job.await.unwrap();
    }
    for pin in pins {
        pin.retire().await;
    }
    drop(ordinary);
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn affirmative_original_nonexecution_redrive_commits_schedule_without_provider_work() {
    let (fixture, mut dispatcher, authority, adapter, _) = setup_with_send(false).await;
    let port = dispatcher.management_port();
    let global = global();
    let access = access(&global);
    let plan = plan(
        &port,
        request(
            &fixture,
            &authority,
            Action::Redrive,
            "safe-original-redrive",
        )
        .await,
        &access,
    )
    .await;
    assert_eq!(
        plan.safety(),
        crate::dispatch_store::effect_management::EffectManagementSafety::KnownNonexecution
    );
    let result = port
        .mutate_effect_retained(plan.clone(), access, (), 256, |_, ()| Ok(()))
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    let EffectManagementOutcome::Mutation { receipt, replayed } = result.outcome.unwrap() else {
        panic!("expected redrive receipt");
    };
    assert!(!replayed);
    assert_eq!(receipt.after(), Disposition::RetryScheduled);
    assert_eq!(fixture.record(&authority).await.attempts(), 1);
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::RetryScheduled
    );
    assert!(receipt.provider_receipt().is_none());
    assert_eq!(adapter.sends.load(Ordering::SeqCst), 0);
    assert_eq!(adapter.lookups.load(Ordering::SeqCst), 0);
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn original_effect_revocation_after_redrive_plan_preserves_known_failure_and_reservation() {
    let (fixture, mut dispatcher, authority, adapter, _) = setup_with_send(false).await;
    let port = dispatcher.management_port();
    let global = global();
    let access = access(&global);
    let plan = plan(
        &port,
        request(
            &fixture,
            &authority,
            Action::Redrive,
            "revoked-original-redrive",
        )
        .await,
        &access,
    )
    .await;
    fixture
        .authority
        .prepare_namespace_close("tenant-a", "orders", 7)
        .unwrap()
        .accept(|| Ok::<(), ()>(()))
        .unwrap();
    let result = port
        .mutate_effect_retained(plan.clone(), access, (), 256, |_, ()| Ok(()))
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(
        result.outcome,
        Err(Error::Authority(AuthorityError::PolicyBlocked))
    ));
    assert!(receipt(&fixture, &plan).await.is_none());
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::KnownFailed
    );
    assert_eq!(adapter.sends.load(Ordering::SeqCst), 0);
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn restore_review_prevents_safe_redrive_without_preventing_administrative_stop() {
    let (fixture, mut dispatcher, authority, adapter, _) = setup_with_send(false).await;
    let port = dispatcher.management_port();
    let global = global();
    let access = access(&global);
    let redrive = plan(
        &port,
        request(
            &fixture,
            &authority,
            Action::Redrive,
            "review-original-redrive",
        )
        .await,
        &access,
    )
    .await;
    dispatcher.require_restore_review().unwrap();
    let result = port
        .mutate_effect_retained(redrive.clone(), access.clone(), (), 256, |_, ()| Ok(()))
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(result.outcome, Err(Error::RestoreReviewRequired)));
    assert!(receipt(&fixture, &redrive).await.is_none());
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::KnownFailed
    );
    let stop = plan(
        &port,
        request(
            &fixture,
            &authority,
            Action::Terminate,
            "review-original-stop",
        )
        .await,
        &access,
    )
    .await;
    assert!(port
        .mutate_effect_retained(stop, access, (), 256, |_, ()| Ok(()))
        .unwrap()
        .await
        .unwrap()
        .unwrap()
        .outcome
        .is_ok());
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::DeadLettered
    );
    assert!(port.snapshot().unwrap().control.restore_review_required);
    assert!(port.snapshot().unwrap().paused);
    assert_eq!(adapter.sends.load(Ordering::SeqCst), 0);
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn uncertain_send_without_original_provider_dedup_qualification_cannot_plan_redrive() {
    let (fixture, mut dispatcher, authority, adapter, _) = setup().await;
    let port = dispatcher.management_port();
    let global = global();
    let access = access(&global);
    let result = port
        .plan_effect_retained(
            request(
                &fixture,
                &authority,
                Action::Redrive,
                "unsafe-original-redrive",
            )
            .await,
            access,
            (),
            256,
            |_, ()| Ok(()),
        )
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(result.outcome, Err(Error::PermissionDenied)));
    assert_eq!(
        fixture.record(&authority).await.disposition(),
        Disposition::Uncertain
    );
    assert_eq!(adapter.sends.load(Ordering::SeqCst), 0);
    assert_eq!(adapter.lookups.load(Ordering::SeqCst), 0);
    assert!(
        dispatcher
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}
