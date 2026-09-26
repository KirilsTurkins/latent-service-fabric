use super::support::{complete, register, Fixture};
use latent_core::PlatformErrorCode;
use latent_scheduler::{ActivationScheduler, CellClass};
use std::time::Duration;

#[tokio::test(start_paused = true)]
async fn occupied_parent_cells_reject_children_without_waiting_or_refunding_parents() {
    let fixture = Fixture::new(2, 8, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let parent = scheduler
        .try_enqueue(fixture.request("parent", "a"))
        .unwrap();
    let other = scheduler
        .try_enqueue(fixture.request("other-parent", "b"))
        .unwrap();
    for index in 0..8 {
        let failure = scheduler
            .try_enqueue(fixture.request(&format!("child-{index}"), "a"))
            .unwrap_err();
        assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
        assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 0);
        assert_eq!(fixture.quotas.usage().unwrap().active_activations, 2);
    }
    assert_eq!(scheduler.observations(CellClass::Tiny).quarantined, 0);
    other.release().await.unwrap();
    let child = scheduler
        .try_enqueue(fixture.request("child", "a"))
        .unwrap();
    assert_eq!(fixture.quotas.usage().unwrap().active_activations, 2);
    child.release().await.unwrap();
    parent.release().await.unwrap();
    fixture.assert_no_quota();
}

#[tokio::test(start_paused = true)]
async fn immediate_children_respect_the_existing_fair_queue_and_release_unused_handoffs() {
    let fixture = Fixture::new(1, 8, Duration::from_secs(1));
    let scheduler = &fixture.scheduler;
    let parent = scheduler
        .try_enqueue(fixture.request("parent", "a"))
        .unwrap();
    let mut prior = scheduler.enqueue(fixture.request("prior", "b"));
    register(&mut prior);
    parent.release().await.unwrap();
    assert_eq!(
        scheduler
            .try_enqueue(fixture.request("new-child", "a"))
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(scheduler.observations(CellClass::Tiny).queue_depth, 0);
    drop(prior); // the unaccepted prior assignment is reclaimed, not quarantined
    assert_eq!(scheduler.observations(CellClass::Tiny).quarantined, 0);
    fixture.assert_no_quota();
    complete(scheduler.enqueue(fixture.request("after", "c")))
        .await
        .release()
        .await
        .unwrap();
    fixture.assert_no_quota();
}
