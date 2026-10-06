use super::support::*;
use latent_effects::{
    dispatch::EffectRecord,
    payload::PayloadRecord,
    runtime::{CommandAdmissionSource, DeferredEffectAdapter, EffectTimeSource},
};
use latent_nats::deferred::JetStreamQualification;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    mpsc, Arc,
};

struct RoleClock {
    source: CommandAdmissionSource,
    observing_allowed: Arc<AtomicBool>,
}
impl EffectTimeSource for RoleClock {
    fn observe(&self) -> latent_effects::authority::EffectTime {
        // Fail deterministically before a regression can wait on the actual
        // opposing protected role mutex while holding the effect mutex.
        assert!(
            self.observing_allowed.load(Ordering::Acquire),
            "role clock observed inside synchronous effect acceptance"
        );
        self.source.command_time().unwrap()
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires tools/run_nats_deferred_tests.py owned pinned real JetStream"]
async fn real_deferred_synchronous_acceptance_respects_opposing_role_and_effect_fences() {
    let qualification: JetStreamQualification = serde_json::from_value(control("reset")).unwrap();
    let fixture = Fixture::new(config(), qualification.clone()).await;
    let effect = fixture.commit("opposing-locks").await;
    let source = fixture.owner.as_ref().unwrap().command_admission_source();
    let allowed = Arc::new(AtomicBool::new(false));
    let adapter = fixture
        .publisher
        .deferred_adapter(
            "tests",
            "updated",
            qualification,
            Arc::new(RoleClock {
                source: source.clone(),
                observing_allowed: allowed.clone(),
            }),
        )
        .unwrap();
    let (payload, attempt) = acceptance_metadata(&fixture, &effect).await;
    let command = source.capture().unwrap();
    let mut physical = fixture
        .authority
        .accept(&effect, 1, fixture.clock.observe())
        .unwrap();
    let (role_held, role_ready) = mpsc::sync_channel(1);
    let (effect_held, effect_ready) = mpsc::sync_channel(1);
    let (approaching_effect, proceed) = mpsc::sync_channel(1);
    let authority = fixture.authority.clone();
    let fenced = effect.clone();
    let role_thread = std::thread::spawn(move || {
        command
            .with_current(|_, time| {
                role_held.send(()).unwrap();
                effect_ready.recv_timeout(WATCHDOG).unwrap();
                approaching_effect.send(()).unwrap();
                let fence = authority
                    .commit_fence(std::slice::from_ref(&fenced), time)
                    .unwrap();
                drop(fence);
            })
            .unwrap();
        command.retire();
    });
    role_ready.recv_timeout(WATCHDOG).unwrap();
    let time = fixture.clock.observe();
    let effect_thread = std::thread::spawn(move || {
        let accepted = physical
            .accept_with(&effect, 1, time, |grant| {
                effect_held.send(()).unwrap();
                proceed.recv_timeout(WATCHDOG).unwrap();
                adapter.accept(grant, payload, attempt)
            })
            .unwrap()
            .unwrap();
        // No physical send is permitted by this copied acceptance description:
        // the future is never polled, and owns no durable dispatcher claim.
        drop(accepted);
        physical.retire().unwrap();
    });
    effect_thread.join().unwrap();
    role_thread.join().unwrap();
    allowed.store(true, Ordering::Release);
    assert_eq!(control("info")["state"]["messages"], 0);
    fixture.finish().await;
}

async fn acceptance_metadata(
    fixture: &Fixture,
    effect: &latent_effects::authority::DurableEffectAuthority,
) -> (PayloadRecord, latent_effects::dispatch::AttemptIdentity) {
    let effect = effect.link().effect.clone();
    call(
        &fixture.store,
        latent_state::store_io::StoreIoKind::Read,
        move |db| {
            let view = db.snapshot().unwrap();
            let mut description = EffectRecord::decode(
                &view
                    .get(&latent_effects::dispatch_store::effect_row_key(&effect).unwrap())
                    .unwrap()
                    .unwrap(),
            )
            .unwrap();
            let attempt = description
                .claim(
                    1,
                    latent_effects::authority::EffectTime {
                        unix_millis: 100,
                        continuity_proven: true,
                    },
                )
                .unwrap();
            let payload = PayloadRecord::decode(
                &view
                    .get(&latent_effects::dispatch_store::effect_payload_key(&effect).unwrap())
                    .unwrap()
                    .unwrap(),
            )
            .unwrap();
            (payload, attempt)
        },
    )
    .await
}
