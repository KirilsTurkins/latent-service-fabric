//! Deterministic parent/child load freshness without a minute-long sleep.
use super::fixture::{Fixture, SyntheticFixtureLoad};
use latent_activation::ActivationOutcome;
use latent_admission::{NodeLoadSnapshot, NodeLoadSource};
use latent_core::{
    ActivationPhase, ActivationTerminalState, BudgetConsumption, PlatformError, PlatformErrorCode,
};
use std::{
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

struct ObservedLoad {
    stale_child: bool,
    samples: Mutex<Vec<NodeLoadSnapshot>>,
}

impl NodeLoadSource for ObservedLoad {
    fn snapshot(&self) -> Result<NodeLoadSnapshot, PlatformError> {
        let mut samples = self.samples.lock().unwrap();
        let mut sample = SyntheticFixtureLoad.snapshot()?;
        // Emulate a parent cold compile exceeding the unchanged 60 s load age.
        // Only the child's load observation is aged; clocks, deadlines, quota
        // limits and the actual canonical-async components remain unchanged.
        if self.stale_child && samples.len() == 1 {
            sample.observed_at -= Duration::from_secs(61);
        }
        assert!(samples.len() < 2, "neither admission may be retried");
        samples.push(sample);
        Ok(sample)
    }
}

#[test]
fn synthetic_profile_is_unchanged_and_observed_on_each_read() {
    for _ in 0..2 {
        let before = Instant::now();
        let sample = SyntheticFixtureLoad.snapshot().unwrap();
        let after = Instant::now();
        assert!(sample.accepting);
        assert_eq!(sample.cpu_pressure_milli, 0);
        assert_eq!(sample.memory_pressure_milli, 0);
        assert_eq!(sample.queue_delay_millis, 0);
        assert!((before..=after).contains(&sample.observed_at));
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn stale_child_load_fails_closed_before_admission_without_consumption_or_retry() {
    parent_and_child(true).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn fresh_per_admission_fixture_load_admits_the_real_parent_and_child_once() {
    parent_and_child(false).await;
}

async fn parent_and_child(stale_child: bool) {
    let load = Arc::new(ObservedLoad {
        stale_child,
        samples: Mutex::new(vec![]),
    });
    let fixture = Fixture::with_load_source(load.clone()).await;
    let receipt = fixture
        .manager
        .start(fixture.request("load-parent", 0))
        .unwrap()
        .await;
    let ActivationOutcome::Succeeded(success) = receipt.outcome else {
        panic!("the parent must receive a typed child outcome: {receipt:?}");
    };
    let expected = if stale_child {
        2000 // The real WAT caller decodes the WIT platform-error unavailable.
    } else {
        u32::from_le_bytes(*b"[42]")
    };
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&success.output).unwrap(),
        [expected]
    );
    assert_eq!(success.consumption.child_calls, u32::from(!stale_child));
    fixture.idle().await;
    assert_eq!(load.samples.lock().unwrap().len(), 2);
    let starts = fixture.observations.starts.lock().unwrap();
    assert_eq!(starts.len(), 2);
    assert_eq!(
        starts[1].parent_activation_id.as_ref().unwrap().0,
        "load-parent"
    );
    let terminals = fixture.observations.terminals.lock().unwrap();
    assert_eq!(terminals.len(), 2);
    let (context, child) = terminals
        .iter()
        .find(|(context, _)| context.parent_activation_id.is_some())
        .unwrap();
    assert_eq!(context.activation_id.0, "child-1");
    if stale_child {
        assert_eq!(child.last_phase, ActivationPhase::Resolved);
        assert_eq!(
            child.terminal_state,
            ActivationTerminalState::DependencyFailed
        );
        assert_eq!(child.platform_code, Some(PlatformErrorCode::Unavailable));
        assert_eq!(child.consumption, BudgetConsumption::default());
    } else {
        assert_eq!(child.terminal_state, ActivationTerminalState::Completed);
        assert_eq!(child.platform_code, None);
        assert!(child.consumption.cpu_fuel > 0);
    }
    assert_eq!(fixture.quotas.usage().unwrap().active_activations, 0);
}
