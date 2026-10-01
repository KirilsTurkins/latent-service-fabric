//! Real TLS lookup purpose and cleanup admission. Authenticated Wire decisions
//! have separate kernel tests; this controlled current gate tests the provider.
use super::{fixture::*, proxy::Fault};
use latent_capabilities::broker::pools::{IngressRequest, ProviderPoolLimits};
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeReservation,
    NativeReservationRequest,
};
use latent_effects::{
    authority::{
        AuthorityError, DispatchContext, DurableEffectAuthority, ProviderLookupAuthorization,
    },
    dispatch::Disposition,
    dispatch_store::{effect_payload_key, effect_row_key, DispatchCatalog},
    payload::PayloadRecord,
    runtime::{
        DeferredEffectAdapter, EffectTimeSource, ProviderReconciliationOutcome,
        ProviderReconciliationReason, ProviderReconciliationRequest,
    },
};
use latent_state::store_io::StoreIoKind;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

struct Gate {
    allowed: AtomicBool,
    reservation: NativeReservation,
    _buffers: NativeBufferPermit,
}
impl ProviderLookupAuthorization for Gate {
    fn with_current(
        &self,
        accept: &mut dyn FnMut() -> Result<(), AuthorityError>,
    ) -> Result<(), AuthorityError> {
        if !self.allowed.load(Ordering::Acquire) {
            return Err(AuthorityError::PolicyBlocked);
        }
        accept()
    }
    fn with_live(
        &self,
        accept: &mut dyn FnMut() -> Result<(), AuthorityError>,
    ) -> Result<(), AuthorityError> {
        self.reservation
            .with_live(accept)
            .map_err(|_| AuthorityError::Expired)?
    }
}

fn gate(fixture: &Fixture) -> Arc<Gate> {
    let reservation = fixture
        .native_capacity
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                work_bytes: 8 * 1024 * 1024,
                ..NativeReservationRequest::default()
            },
            Instant::now() + Duration::from_secs(2),
        )
        .unwrap();
    let buffers = reservation
        .reserve_buffer(NativeBufferClass::Work, 8 * 1024 * 1024)
        .unwrap();
    Arc::new(Gate {
        allowed: AtomicBool::new(true),
        reservation,
        _buffers: buffers,
    })
}

async fn request(
    fixture: &Fixture,
    effect: &DurableEffectAuthority,
) -> ProviderReconciliationRequest {
    let authority = effect.clone();
    call(&fixture.store, StoreIoKind::RecoveryRead, move |db| {
        let view = db.snapshot().unwrap();
        let raw = view
            .get(&effect_row_key(&authority.link().effect).unwrap())
            .unwrap()
            .unwrap();
        let version = latent_effects::dispatch::effect_record_version(&raw).unwrap();
        let attempt = DispatchCatalog::last_completed_attempt(&view, &authority.link().effect)
            .unwrap()
            .unwrap();
        let payload = PayloadRecord::decode(
            &view
                .get(&effect_payload_key(&authority.link().effect).unwrap())
                .unwrap()
                .unwrap(),
        )
        .unwrap();
        ProviderReconciliationRequest::new(authority, payload, attempt, version).unwrap()
    })
    .await
}

fn context(
    fixture: &Fixture,
    request: &ProviderReconciliationRequest,
    gate: &Arc<Gate>,
) -> DispatchContext {
    let mut context = fixture
        .authority
        .accept_lookup(
            request.authority(),
            request.attempt().attempt(),
            fixture.clock.observe(),
            gate.reservation.original_deadline(),
            gate.clone(),
        )
        .unwrap();
    context
        .retain_owner(gate.clone())
        .unwrap_or_else(|_| panic!("original lookup keeper"));
    context
}

async fn uncertain(fixture: &Fixture, effect: &DurableEffectAuthority) {
    fixture.owner.as_ref().unwrap().resume().unwrap();
    fixture.settled(effect, Disposition::RetryScheduled).await;
    fixture.owner.as_ref().unwrap().pause();
    tokio::time::timeout(WATCHDOG, async {
        while fixture
            .owner
            .as_ref()
            .unwrap()
            .snapshot()
            .unwrap()
            .accepted_effects
            != 0
        {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("actual ordinary provider and receipt retirement");
    assert_eq!(
        fixture.native_capacity.snapshot().unwrap().ordinary.slots,
        0
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn fresh_lookup_confirms_revoked_expired_execution_under_original_ordinary_pressure_without_post(
) {
    let mut fixture = Fixture::new(Fault::LosePostReply).await;
    fixture.rule.ceiling.maximum_age_millis = 1000;
    fixture.rule.policy_revision = 2;
    fixture.authority.publish(fixture.rule.clone()).unwrap();
    let effect = fixture.commit("fresh-expired-lookup").await;
    uncertain(&fixture, &effect).await;
    fixture
        .authority
        .prepare_namespace_close("tests", "aggregate", 1)
        .unwrap()
        .accept(|| Ok::<_, ()>(()))
        .unwrap();
    fixture
        .clock
        .0
        .store(effect.expires_at_millis(), Ordering::Release);
    fixture
        .endpoint
        .clock
        .store(effect.expires_at_millis(), Ordering::Release);
    assert!(fixture
        .authority
        .accept(&effect, 1, fixture.clock.observe())
        .is_err());
    let (ordinary, native_ordinary) = ordinary_pressure(&fixture);
    let gate = gate(&fixture);
    let pin = fixture
        .store
        .reserve_recovery_operation_retaining(gate.clone())
        .unwrap();
    let request = request(&fixture, &effect).await;
    let attempt = request.attempt().clone();
    let version = request.record_version();
    let mut physical = context(&fixture, &request, &gate);
    let before = fixture.pool_snapshot().await;
    let denied = physical
        .accept_with(
            &effect,
            attempt.attempt(),
            fixture.clock.observe(),
            |grant| {
                fixture
                    .adapter
                    .accept(grant, request.payload().clone(), attempt.clone())
            },
        )
        .unwrap();
    assert!(matches!(denied, Err(AuthorityError::PolicyBlocked)));
    assert_eq!(fixture.pool_snapshot().await, before);
    physical.retire().unwrap();
    let mut physical = context(&fixture, &request, &gate);
    let lookup = physical
        .accept_with(
            &effect,
            attempt.attempt(),
            fixture.clock.observe(),
            |grant| {
                assert_eq!(grant.expires_at_millis(), effect.expires_at_millis());
                fixture.adapter.accept_reconciliation(grant, request)
            },
        )
        .unwrap()
        .unwrap();
    let admitted = fixture.pool_snapshot().await;
    assert_eq!(admitted.running_requests, 1);
    assert_eq!(admitted.cleanup_jobs, 1);
    assert_eq!(
        fixture.native_capacity.snapshot().unwrap().ordinary.slots,
        128
    );
    let ProviderReconciliationOutcome::Confirmed(confirmation) = lookup.await else {
        panic!("exact positive lookup")
    };
    confirmation.validate_for(&attempt, version).unwrap();
    assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 1);
    assert_eq!(fixture.proxy.lookups.load(Ordering::Acquire), 1);
    assert_eq!(fixture.endpoint.counter().await, 1);
    assert_eq!(fixture.pool_snapshot().await.cleanup_jobs, 0);
    physical.retire().unwrap();
    drop(gate);
    assert_eq!(
        fixture.native_capacity.snapshot().unwrap().recovery.slots,
        1
    );
    pin.retire().await;
    assert_eq!(
        fixture.native_capacity.snapshot().unwrap().recovery.slots,
        0
    );
    drop((ordinary, native_ordinary));
    fixture.finish().await;
}

fn ordinary_pressure(fixture: &Fixture) -> (IngressRequest, Vec<NativeReservation>) {
    fixture
        .pools
        .lower_limits(ProviderPoolLimits {
            maximum_running_requests: 1,
            maximum_running_per_tenant: 1,
            maximum_running_per_provider: 1,
            ..ProviderPoolLimits::default()
        })
        .unwrap();
    let client = fixture.provider.inner.client(0).unwrap();
    let ordinary = fixture
        .pools
        .ingress(
            &client,
            "tests",
            Instant::now() + Duration::from_secs(2),
            1,
            4096,
        )
        .unwrap();
    let native_ordinary = (0..128)
        .map(|_| {
            fixture
                .native_capacity
                .reserve(
                    NativeAdmissionClass::Ordinary,
                    NativeReservationRequest::default(),
                    Instant::now() + Duration::from_secs(2),
                )
                .unwrap()
        })
        .collect();
    (ordinary, native_ordinary)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn fresh_lookup_absence_recreation_and_status_retention_expiry_never_authorize_execution() {
    for mode in 0..3 {
        let fixture = Fixture::new(Fault::LosePostReply).await;
        let effect = fixture.commit("fresh-uncertain-lookup").await;
        uncertain(&fixture, &effect).await;
        let gate = gate(&fixture);
        let request = request(&fixture, &effect).await;
        if mode == 0 {
            fixture.endpoint.erase_receipts().await;
        }
        if mode == 1 {
            fixture.endpoint.recreate().await;
        }
        if mode == 2 {
            fixture.clock.0.store(10_100, Ordering::Release);
            fixture.endpoint.clock.store(10_100, Ordering::Release);
        }
        let mut physical = context(&fixture, &request, &gate);
        let lookup = physical
            .accept_with(
                &effect,
                request.attempt().attempt(),
                fixture.clock.observe(),
                |grant| fixture.adapter.accept_reconciliation(grant, request),
            )
            .unwrap()
            .unwrap();
        let ProviderReconciliationOutcome::Uncertain(reason) = lookup.await else {
            panic!("ambiguous status cannot authorize execution")
        };
        assert_eq!(
            reason,
            match mode {
                0 => ProviderReconciliationReason::NotFound,
                2 => ProviderReconciliationReason::Expired,
                _ => ProviderReconciliationReason::Ambiguous,
            }
        );
        physical.retire().unwrap();
        drop(gate);
        assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 1);
        assert_eq!(fixture.endpoint.counter().await, 1);
        assert_eq!(fixture.pool_snapshot().await.cleanup_jobs, 0);
        assert_eq!(
            fixture.native_capacity.snapshot().unwrap().recovery.slots,
            0
        );
        fixture.finish().await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn fresh_lookup_revocation_during_real_tls_keeps_original_recovery_owners_until_cleanup() {
    let fixture = Fixture::new(Fault::LosePostReplyHoldLookupTls).await;
    let effect = fixture.commit("held-fresh-lookup").await;
    uncertain(&fixture, &effect).await;
    let gate = gate(&fixture);
    let request = request(&fixture, &effect).await;
    let mut physical = context(&fixture, &request, &gate);
    let lookup = physical
        .accept_with(
            &effect,
            request.attempt().attempt(),
            fixture.clock.observe(),
            |grant| fixture.adapter.accept_reconciliation(grant, request),
        )
        .unwrap()
        .unwrap();
    let running = tokio::spawn(lookup);
    fixture.proxy.wait_gate().await;
    assert_eq!(fixture.pool_snapshot().await.cleanup_jobs, 1);
    assert_eq!(fixture.pool_snapshot().await.connections, 1);
    assert_eq!(
        fixture.native_capacity.snapshot().unwrap().recovery.slots,
        1
    );
    gate.allowed.store(false, Ordering::Release);
    assert_eq!(fixture.pool_snapshot().await.cleanup_jobs, 1);
    assert_eq!(fixture.authority.owners().unwrap().physical, 1);
    fixture.proxy.release();
    assert!(matches!(
        running.await.unwrap(),
        ProviderReconciliationOutcome::Uncertain(_)
    ));
    assert_eq!(fixture.proxy.lookups.load(Ordering::Acquire), 0);
    assert_eq!(fixture.proxy.posts.load(Ordering::Acquire), 1);
    assert_eq!(fixture.endpoint.counter().await, 1);
    assert_eq!(fixture.pool_snapshot().await.cleanup_jobs, 0);
    assert_eq!(fixture.pool_snapshot().await.connections, 0);
    physical.retire().unwrap();
    drop(gate);
    assert_eq!(
        fixture.native_capacity.snapshot().unwrap().recovery.slots,
        0
    );
    fixture.finish().await;
}
