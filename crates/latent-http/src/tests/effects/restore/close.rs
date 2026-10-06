//! Explicit abandonment uses the installed offline worker and the original TLS
//! recipient. The old approved-deduplication restore test remains independent.
use super::*;
use latent_effects::recovery_close::{self, ClosePlan, CloseReceipt, CloseScope};
use latent_state::{
    embedded::ReadView,
    recovery::offline::{PreparedRetainedReconciliation, RetainedReconciliationRequest},
};

fn scope(codecs: &codecs::Codecs) -> CloseScope {
    let original = codecs.authority.scope();
    CloseScope {
        tenant: original.tenant.clone(),
        namespace: original.namespace.clone(),
        incarnation: original.incarnation,
    }
}
pub(super) fn inspect(
    codecs: &codecs::Codecs,
    view: &ReadView,
    request: &RetainedReconciliationRequest,
) -> Result<Vec<u8>, StoreError> {
    codecs.check_operator(&request.operator_id)?;
    if request.payload != b"inspect-close" {
        return Err(StoreError::Invalid);
    }
    codecs.validate_view(view)?;
    recovery_close::inspect(
        view,
        scope(codecs),
        request.operator_id.clone(),
        request.operation_id.clone(),
        vec![codecs.authority.link().effect.clone()],
        "abandon restored work after independently observed remote application".into(),
    )?
    .encode()
}
pub(super) fn prepare(
    codecs: &codecs::Codecs,
    view: &ReadView,
    request: &RetainedReconciliationRequest,
) -> Result<PreparedRetainedReconciliation, StoreError> {
    accept(codecs, request)?;
    let plan = ClosePlan::decode(&request.payload)?;
    let acknowledgement = codecs
        .close_approval
        .lock()
        .map_err(|_| StoreError::Unavailable)?
        .ok_or(StoreError::Unavailable)?;
    let prepared = recovery_close::prepare(
        view,
        &plan,
        &scope(codecs),
        &request.operator_id,
        &request.operation_id,
        acknowledgement,
        codecs.clock.observe(),
    )?;
    Ok(PreparedRetainedReconciliation {
        batch: prepared.batch,
        receipt: prepared.receipt.encode()?,
        replay: prepared.replay,
    })
}
pub(super) fn accept(
    codecs: &codecs::Codecs,
    request: &RetainedReconciliationRequest,
) -> Result<(), StoreError> {
    let plan = ClosePlan::decode(&request.payload)?;
    let acknowledgement = codecs
        .close_approval
        .lock()
        .map_err(|_| StoreError::Unavailable)?
        .ok_or(StoreError::Unavailable)?;
    if plan.scope != scope(codecs) || plan.operation_id != request.operation_id {
        return Err(StoreError::Conflict);
    }
    codecs.check_review(&request.operator_id, plan.digest()?, acknowledgement)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn applied_tls_effect_restored_pending_closes_without_redrive_and_stays_closed_after_resume()
{
    let endpoint = Endpoint::new(Arc::new(Clock(AtomicU64::new(100))), Fault::Normal).await;
    let proxy = proxy::Proxy::new(&endpoint, proxy::Loss::AfterApply).await;
    let mut fixture = Fixture::new(proxy.port, proxy.root_certificate.clone(), 2000).await;
    let mut original = Store::new().await;
    let workload = command::commit(&original, &fixture).await;
    let codecs = codecs::Codecs::with_close(&fixture, &workload);
    command::quiesce(&original).await;
    original.close().await;
    let source = physical::offline(&original.config, codecs.clone(), false).await;
    let backup_root = physical::root();
    let input = SnapshotFile {
        root: backup_root.path().into(),
        file_name: "pending-before-apply".into(),
    };
    let snapshot = physical::backup(&source, &codecs, &input).await;
    review::resume(&source, "original-after-backup").await;
    physical::close_offline(&source).await;
    drop(source);
    physical::reopen(&mut original).await;
    let first = physical::deliver(&original, &fixture, &workload.authority).await;
    assert_eq!(endpoint.attempts(), (1, 1));
    assert_eq!(endpoint.counter(), 1);
    endpoint.assert_applied_id(&workload.authority.link().effect, BODY, &first, 10_100);
    command::quiesce(&original).await;
    original.close().await;
    let source = physical::offline(&original.config, codecs.clone(), false).await;
    let destination = physical::root();
    let restored = physical::restore(&source, &codecs, input, &snapshot, destination.path()).await;
    physical::close_offline(&source).await;
    drop(source);
    let config = ProtectedStoreConfig::bounded_linux(destination.path().into());
    let source = physical::offline(&config, codecs.clone(), true).await;
    let receipt = close_pending(&source, &codecs, &mut fixture, &endpoint).await;
    assert_eq!(receipt.outcome, "closed-without-redrive");
    assert_eq!(
        receipt.plan.effects[0].effect_id,
        workload.authority.link().effect
    );
    assert_eq!(
        review::observe(&source).await.guard.as_ref(),
        Some(&restored.guard)
    );
    review::reconcile(&source, &codecs, &restored.guard, &endpoint, &first).await;
    review::resume_with_current_authority(&source, &fixture, &endpoint).await;
    physical::close_offline(&source).await;
    drop(source);
    let recovered = physical::open_restored(destination).await;
    physical::assert_workload(&recovered, &workload, true).await;
    assert_old_decoder_refuses(&recovered, codecs::Codecs::new(&fixture, &workload)).await;
    assert_closed_dispatch(&recovered, &fixture, &workload, &endpoint).await;
    recovered.finish().await;
    original.finish().await;
    fixture.finish().await;
    proxy.finish().await;
    endpoint.finish(1).await;
}

async fn assert_old_decoder_refuses(store: &Store, old: Arc<codecs::Codecs>) {
    store
        .owner
        .with_store(StoreIoKind::Read, 8 * 1024 * 1024, move |store| {
            let view = store.snapshot()?;
            assert_eq!(
                old.validate_view(&view).err(),
                Some(StoreError::UnsupportedFormat)
            );
            assert_eq!(
                view.scan(
                    latent_state::embedded::Family::Maintenance,
                    recovery_close::RECEIPT_PREFIX,
                    16,
                    65536
                )?
                .len(),
                1
            );
            // This refuses a decoder downgrade; it cannot reclaim the selected
            // original command, result, inbox, payload, history or close receipt.
            Ok(())
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
}

async fn close_pending(
    source: &OfflineRecoverySource,
    codecs: &codecs::Codecs,
    fixture: &mut Fixture,
    endpoint: &Endpoint,
) -> CloseReceipt {
    let mut request = RetainedReconciliationRequest {
        operator_id: "operator".into(),
        operation_id: "explicit-abandon-restored-effect".into(),
        payload: b"inspect-close".to_vec(),
    };
    let bytes = source
        .inspect_retained_reconciliation(request.clone(), physical::deadline())
        .unwrap()
        .await
        .unwrap();
    let plan = ClosePlan::decode(&bytes).unwrap();
    assert_eq!(plan.effects[0].original_disposition, Disposition::Pending);
    request.payload = bytes;
    assert_eq!(
        source
            .reconcile_retained(request.clone(), physical::deadline())
            .unwrap()
            .await
            .err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    *codecs.close_approval.lock().unwrap() = Some(plan.digest().unwrap());
    let mut revoked = fixture.rule.clone();
    revoked.enabled = false;
    revoked.policy_revision += 1;
    let mut enabled = fixture.rule.clone();
    enabled.policy_revision = revoked.policy_revision + 1;
    fixture.authority.publish(revoked).unwrap();
    assert_eq!(
        source
            .reconcile_retained(request.clone(), physical::deadline())
            .unwrap()
            .await
            .err(),
        Some(OfflineRecoveryError::Review(StoreError::Unavailable))
    );
    assert_eq!(endpoint.attempts(), (1, 1));
    fixture.authority.publish(enabled.clone()).unwrap();
    // Keep the fixture's next independent resume/revocation sequence based on
    // the actual installed revision. The captured original authority stays
    // unchanged, and stale policy publications still refuse normally.
    fixture.rule = enabled;
    let accepted = source
        .reconcile_retained(request.clone(), physical::deadline())
        .unwrap()
        .await
        .unwrap();
    let replay = source
        .reconcile_retained(request, physical::deadline())
        .unwrap()
        .await
        .unwrap();
    assert_eq!(accepted, replay);
    assert_eq!(endpoint.attempts(), (1, 1));
    assert_eq!(endpoint.counter(), 1);
    CloseReceipt::decode(&accepted).unwrap()
}

async fn assert_closed_dispatch(
    store: &Store,
    fixture: &Fixture,
    workload: &command::Workload,
    endpoint: &Endpoint,
) {
    let record = store.record(&workload.authority).await;
    assert_eq!(record.disposition(), Disposition::DeadLettered);
    assert_eq!(record.attempts(), 0);
    assert_eq!(record.latest(), None);
    assert_eq!(record.authority().unwrap(), workload.authority);
    assert!(record.recovery_close_digest().is_some());
    let mut dispatcher = DispatcherOwner::start(
        dispatcher::config(false),
        store.owner.clone(),
        fixture.authority.clone(),
        vec![Arc::new(fixture.adapter.clone())],
        fixture.clock.clone(),
        None,
    )
    .await
    .unwrap();
    let observed = dispatcher.refresh_counts().await.unwrap();
    assert_eq!(observed.durable.pending, 0);
    assert_eq!(observed.claims, 0);
    assert!(!observed.paused);
    let retired = dispatcher.shutdown(physical::deadline()).await.unwrap();
    assert!(retired.clean && retired.physically_retired && retired.scheduling_owner_retired);
    assert_eq!(endpoint.attempts(), (1, 1));
    assert_eq!(endpoint.counter(), 1);
}
