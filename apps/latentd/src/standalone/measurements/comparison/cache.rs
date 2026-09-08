//! Common real-node five-component/four-slot ownership and locality experiment.
mod collector;
mod direct;
mod fixture;
mod observation;
mod ownership;
mod plan;
mod sequence;

use latent_executor::PreparedComponent;
use serde::Serialize;

use super::super::{fixtures::Fixture, Result};
use super::{cold, node::Node, writer::Writer};

#[derive(Default, Serialize)]
struct DirectWork {
    readiness_acquisitions: u64,
    materializations: u64,
    executions: u64,
    releases: u64,
}

#[derive(Default)]
struct State {
    events: observation::Events,
    descriptors: [Option<PreparedComponent>; 5],
    direct: DirectWork,
}

#[test]
#[ignore = "explicit cache revision profile supplies bounded plan and exact inputs"]
fn phase1_cache_collector() {
    collector::collect();
}

async fn run(
    node: &mut Node,
    writer: &mut Writer,
    clock: cold::call::Clock,
    plan: &plan::Plan,
    releases: &[String],
    state: &mut State,
) -> Result<()> {
    observation::checkpoint(node, writer, clock, "empty", true)?;
    let cold_plan = plan.cold();
    for (phase, keys, count) in [
        ("warmup", &[0][..], cold_plan.warmup()),
        ("baseline", &[0][..], cold_plan.baseline()),
        ("round-robin-warmup", &[0, 1, 2, 3, 4][..], 5),
        ("round-robin", &[0, 1, 2, 3, 4][..], plan.round_robin()),
        ("locality-warmup", &[0, 0, 1, 1, 2, 2, 3, 3, 4, 4][..], 10),
        (
            "locality",
            &[0, 0, 1, 1, 2, 2, 3, 3, 4, 4][..],
            plan.locality(),
        ),
    ] {
        sequence::run(
            node,
            writer,
            clock,
            state,
            releases,
            sequence::Sequence { phase, keys, count },
        )
        .await?;
        observation::checkpoint(node, writer, clock, &format!("after-{phase}"), true)?;
    }
    ownership::run(node, writer, clock, state, releases).await?;
    for key in 1..5 {
        ownership::release(node, writer, clock, state, key, "concurrent-reset").await?;
    }
    observation::checkpoint(node, writer, clock, "before-concurrent", true)?;
    cold::schedule::burst_at_generation(
        node,
        writer,
        clock,
        &cold_plan,
        releases,
        cold::schedule::BurstOptions {
            phase: "concurrent",
            cold_keys: &[1, 2, 3, 4],
            cancel: false,
        },
        (6, std::time::Duration::from_millis(16)),
    )
    .await?;
    state
        .events
        .export(node, writer, clock, "after-concurrent")?;
    observation::checkpoint(node, writer, clock, "after-concurrent", true)?;
    sequence::run(
        node,
        writer,
        clock,
        state,
        releases,
        sequence::Sequence {
            phase: "healthy",
            keys: &[0],
            count: cold_plan.healthy(),
        },
    )
    .await?;
    cold::observation::drain(&node.owner.backend.preparation_observer(), clock).await?;
    state.events.export(node, writer, clock, "complete")?;
    observation::checkpoint(node, writer, clock, "after-healthy", true)
}
