use super::{proxy, support::*};
use latent_effects::{
    authority::{AuthorityError, DurableEffectAuthority, EffectTime},
    dispatch::{Disposition, RetryProof},
    dispatch_store::{effect_payload_key, effect_row_key, DispatchCatalog},
    payload::PayloadRecord,
    runtime::{DeferredEffectAdapter, ProviderReconciliationRequest},
};
use latent_nats::deferred::JetStreamQualification;
use latent_state::store_io::StoreIoKind;
use std::sync::atomic::Ordering;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires tools/run_nats_deferred_tests.py owned pinned real JetStream"]
async fn real_deferred_redrive_qualification_keeps_original_payload_profile_and_finite_horizon() {
    let qualification: JetStreamQualification = serde_json::from_value(control("reset")).unwrap();
    let proxy = proxy::Proxy::new(config()).await;
    proxy.mode.store(proxy::DROP_ACK, Ordering::Release);
    let fixture = Fixture::new(proxy.config.clone(), qualification).await;
    let effect = fixture.commit("manual-redrive").await;
    fixture.owner.as_ref().unwrap().resume().unwrap();
    tokio::time::timeout(WATCHDOG, proxy.seen.notified())
        .await
        .unwrap();
    fixture.settled(&effect, Disposition::RetryScheduled).await;
    fixture.owner.as_ref().unwrap().pause();
    tokio::time::timeout(WATCHDOG, async {
        loop {
            let snapshot = fixture.owner.as_ref().unwrap().snapshot().unwrap();
            if snapshot.physical_owners == 0
                && snapshot.accepted_effects == 0
                && fixture.publisher.snapshot().active_publishes == 0
            {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("actual original attempt did not physically retire");
    assert_eq!(control("info")["state"]["messages"], 1);
    let request = original_request(&fixture, &effect).await;
    assert_eq!(request.attempt().attempt(), 1);
    assert_horizon(
        fixture
            .adapter
            .qualify_redrive(&request, time(100, true))
            .unwrap(),
        30_100,
    );
    original_bounds(&fixture, &request);
    let mut attempt = serde_json::to_value(request.attempt()).unwrap();
    attempt["retry_horizon_millis"] = serde_json::json!(150);
    let narrower = candidate(&request, attempt.clone());
    assert_horizon(
        fixture
            .adapter
            .qualify_redrive(&narrower, time(100, true))
            .unwrap(),
        150,
    );
    assert!(matches!(
        fixture.adapter.qualify_redrive(&narrower, time(150, true)),
        Err(AuthorityError::PolicyBlocked)
    ));
    attempt["attempt"] = serde_json::json!(effect.ceiling().maximum_attempts);
    assert!(matches!(
        fixture
            .adapter
            .qualify_redrive(&candidate(&request, attempt), time(100, true)),
        Err(AuthorityError::Capacity)
    ));
    let replacement: JetStreamQualification = serde_json::from_value(control("recreate")).unwrap();
    let changed = fixture
        .publisher
        .deferred_adapter("tests", "updated", replacement, fixture.clock.clone())
        .unwrap();
    assert!(matches!(
        changed.qualify_redrive(&request, time(100, true)),
        Err(AuthorityError::PolicyBlocked)
    ));
    assert_eq!(fixture.record(&effect).await.attempts(), 1);
    assert_eq!(fixture.publisher.snapshot().connection_attempts, 1);
    assert_eq!(control("info")["state"]["messages"], 0);
    drop(changed);
    drop(request);
    drop(narrower);
    fixture.finish().await;
    proxy.close().await;
}

fn original_bounds(fixture: &Fixture, request: &ProviderReconciliationRequest) {
    for observed in [time(100, false), time(99, true)] {
        assert!(matches!(
            fixture.adapter.qualify_redrive(request, observed),
            Err(AuthorityError::ClockDiscontinuity)
        ));
    }
    assert!(matches!(
        fixture.adapter.qualify_redrive(request, time(30_100, true)),
        Err(AuthorityError::PolicyBlocked)
    ));
    let mut changed = request.payload().value().clone();
    changed.bytes[0] ^= 1;
    assert!(matches!(
        PayloadRecord::new(request.authority(), changed),
        Err(AuthorityError::Invalid)
    ));
}

fn candidate(
    original: &ProviderReconciliationRequest,
    attempt: serde_json::Value,
) -> ProviderReconciliationRequest {
    // Deliberately narrowed/exhausted metadata candidates test the adapter
    // boundary. They never replace actual engine history or authorize a send.
    ProviderReconciliationRequest::new(
        original.authority().clone(),
        original.payload().clone(),
        serde_json::from_value(attempt).unwrap(),
        original.record_version(),
    )
    .unwrap()
}

fn assert_horizon(proof: RetryProof, expected: u64) {
    assert!(matches!(
        proof,
        RetryProof::QualifiedDeduplication {
            valid_until_millis,
            same_payload: true,
            same_provider_incarnation: true,
        } if valid_until_millis == expected
    ));
}

fn time(unix_millis: u64, continuity_proven: bool) -> EffectTime {
    EffectTime {
        unix_millis,
        continuity_proven,
    }
}

async fn original_request(
    fixture: &Fixture,
    authority: &DurableEffectAuthority,
) -> ProviderReconciliationRequest {
    let authority = authority.clone();
    call(&fixture.store, StoreIoKind::Read, move |db| {
        let view = db.snapshot().unwrap();
        let identity = &authority.link().effect;
        let raw = view
            .get(&effect_row_key(identity).unwrap())
            .unwrap()
            .unwrap();
        let original = DispatchCatalog::last_completed_attempt(&view, identity)
            .unwrap()
            .unwrap();
        let payload = view
            .get(&effect_payload_key(identity).unwrap())
            .unwrap()
            .unwrap();
        ProviderReconciliationRequest::new(
            authority,
            PayloadRecord::decode(&payload).unwrap(),
            original,
            latent_effects::dispatch::effect_record_version(&raw).unwrap(),
        )
        .unwrap()
    })
    .await
}
