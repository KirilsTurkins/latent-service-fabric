use super::*;
use crate::broker::tests::audit::Journal;
use latent_audit::{AuditProviderOutcome, AuditRecordData, Phase2AuditEventKind};

#[tokio::test]
async fn clock_contention_has_one_terminal_grant_and_one_work_observation() {
    for cancel in [false, true] {
        let journal = Journal::new(32);
        let base = Fixture::audited(
            CapabilityBrokerLimits::default(),
            journal.handle.clone(),
            false,
            true,
        );
        let f = ClockFixture::from_base(base, HostClock::Wall, false);
        let (request, control) = f.request();
        let session = f.base.session(&request, &control);
        let before = f.base.broker.snapshot();
        let timer = Timer::new();
        f.fence.hold_at.store(2, Ordering::SeqCst);
        let mut future = Box::pin(session.begin_host_clock(f.clock, &timer));
        pending(future.as_mut());
        for _ in 0..3 {
            timer.advance(Duration::from_millis(10));
            pending(future.as_mut());
        }
        journal.drained().await;
        let page = journal.query("a").await;
        assert_eq!(page.records().len(), 1);
        let AuditRecordData::Observation(observation) = &page.records()[0].data else {
            panic!("grant observation");
        };
        assert_eq!(
            observation.kind,
            Phase2AuditEventKind::CapabilityGrantAllowed
        );
        drop(page);
        if cancel {
            drop(future);
        } else {
            f.fence.hold_at.store(0, Ordering::SeqCst);
            timer.advance(Duration::from_millis(10));
            let mut call = ready(future).unwrap();
            call.record_provider_outcome(AuditProviderOutcome::HostCompleted)
                .unwrap();
            drop(call);
        }
        journal.drained().await;
        let page = journal.query("a").await;
        assert_eq!(page.records().len(), 2);
        let AuditRecordData::Observation(observation) = &page.records()[1].data else {
            panic!("provider observation");
        };
        assert_eq!(
            observation.kind,
            Phase2AuditEventKind::CapabilityProviderOutcome
        );
        assert_eq!(
            observation
                .identities
                .capability
                .as_ref()
                .unwrap()
                .provider_outcome,
            Some(if cancel {
                AuditProviderOutcome::NotStarted
            } else {
                AuditProviderOutcome::HostCompleted
            })
        );
        assert_eq!(control.budget.outstanding_reservations(), 0);
        assert_eq!(timer.registrations.load(Ordering::SeqCst), 0);
        f.idle(&session, before);
    }
}

#[tokio::test]
async fn dropped_binding_wait_observes_one_denied_grant_without_provider_outcome() {
    let journal = Journal::new(32);
    let f = ClockFixture::from_base(
        Fixture::audited(
            CapabilityBrokerLimits::default(),
            journal.handle.clone(),
            false,
            true,
        ),
        HostClock::Wall,
        false,
    );
    let (request, control) = f.request();
    let session = f.base.session(&request, &control);
    let before = f.base.broker.snapshot();
    let timer = Timer::new();
    f.fence.hold_at.store(1, Ordering::SeqCst);
    let mut future = Box::pin(session.begin_host_clock(f.clock, &timer));
    pending(future.as_mut());
    timer.advance(Duration::from_millis(10));
    pending(future.as_mut());
    assert_eq!(journal.query("a").await.records().len(), 0);
    drop(future);
    journal.drained().await;
    let page = journal.query("a").await;
    assert_eq!(page.records().len(), 1);
    let AuditRecordData::Observation(observation) = &page.records()[0].data else {
        panic!("denied observation");
    };
    assert_eq!(
        observation.kind,
        Phase2AuditEventKind::CapabilityGrantDenied
    );
    assert_eq!(control.budget.outstanding_reservations(), 0);
    f.idle(&session, before);
}
