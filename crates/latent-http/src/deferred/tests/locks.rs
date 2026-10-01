use super::{fixture::*, proxy::Fault};
use latent_effects::runtime::{CommandAdmissionSource, DeferredEffectAdapter, EffectTimeSource};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

struct RoleClock {
    source: CommandAdmissionSource,
    observing_allowed: Arc<AtomicBool>,
}
impl EffectTimeSource for RoleClock {
    fn observe(&self) -> latent_effects::authority::EffectTime {
        // A regression fails at the forbidden observation rather than blocking
        // forever while recursively acquiring the actual protected role mutex.
        assert!(
            self.observing_allowed.load(Ordering::Acquire),
            "role clock observed under Role -> Effect acceptance fences"
        );
        self.source.command_time().unwrap()
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn synchronous_acceptance_does_not_reverse_actual_role_and_effect_lock_order() {
    let fixture = Fixture::new(Fault::Normal).await;
    let effect = fixture.commit("lock-order").await;
    let source = fixture.owner.as_ref().unwrap().command_admission_source();
    let allowed = Arc::new(AtomicBool::new(false));
    let adapter = fixture
        .provider
        .deferred_adapter(
            "tests",
            qualification(&fixture.proxy.config()),
            Arc::new(RoleClock {
                source: source.clone(),
                observing_allowed: allowed.clone(),
            }),
        )
        .unwrap();
    let effect_id = effect.link().effect.clone();
    let (payload, attempt) = call(
        &fixture.store,
        latent_state::store_io::StoreIoKind::Read,
        move |db| {
            let view = db.snapshot().unwrap();
            let mut description = latent_effects::dispatch::EffectRecord::decode(
                &view
                    .get(&latent_effects::dispatch_store::effect_row_key(&effect_id).unwrap())
                    .unwrap()
                    .unwrap(),
            )
            .unwrap();
            // This is acceptance-only metadata. Its future is never polled and no
            // physical request can send before a real durable dispatcher claim.
            let attempt = description
                .claim(
                    1,
                    latent_effects::authority::EffectTime {
                        unix_millis: 100,
                        continuity_proven: true,
                    },
                )
                .unwrap();
            let payload = latent_effects::payload::PayloadRecord::decode(
                &view
                    .get(&latent_effects::dispatch_store::effect_payload_key(&effect_id).unwrap())
                    .unwrap()
                    .unwrap(),
            )
            .unwrap();
            (payload, attempt)
        },
    )
    .await;
    let command = source.capture().unwrap();
    let mut physical = fixture
        .authority
        .accept(&effect, 1, fixture.clock.observe())
        .unwrap();
    let accepted = command
        .with_current(|_, time| {
            physical.accept_with(&effect, 1, time, |grant| {
                adapter.accept(grant, payload, attempt)
            })
        })
        .unwrap()
        .unwrap()
        .unwrap();
    allowed.store(true, Ordering::Release);
    // Dropping this unpolled operation destroys its prepaid payload/slot. It
    // supplies no receipt or claim, and does not contact the reference endpoint.
    drop(accepted);
    physical.retire().unwrap();
    command.retire();
    drop(adapter);
    assert!(fixture.proxy.requests.lock().unwrap().is_empty());
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 0);
    fixture.finish().await;
}
