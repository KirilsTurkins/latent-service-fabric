use latent_control_store::{CatalogWorkObserver, CatalogWorkOperation};
use serde_json::json;

use super::super::catalog::fixture;
use super::{
    mutations::Mutation,
    observation::{self, Counts, Operation},
    oracle::Oracle,
    proofs::Proof,
    Clock, Node, Plan, Result, Writer,
};

pub(super) const LABELS: [&str; 4] = ["unchanged-apply", "weight-update", "delete", "reapply"];

pub(super) async fn run(
    node: &mut Node,
    writer: &mut Writer,
    counts: &mut Counts,
    plan: &Plan,
    clock: Clock,
    observer: &CatalogWorkObserver,
) -> Result<()> {
    if plan.reopen() {
        return reopen(node, writer, counts, plan, clock).await;
    }
    initial(node, writer, counts, plan, clock, observer).await
}

async fn reopen(
    node: &mut Node,
    writer: &mut Writer,
    counts: &mut Counts,
    plan: &Plan,
    clock: Clock,
) -> Result<()> {
    observation::checkpoint(
        node,
        writer,
        clock,
        "reopened-idle",
        plan.populated_size,
        false,
    )?;
    let oracle = Oracle::new(&node.fixture, plan)?;
    observation::checkpoint(
        node,
        writer,
        clock,
        "oracle-released",
        plan.populated_size,
        false,
    )?;
    Proof {
        node,
        writer,
        counts,
        clock,
    }
    .reopen(&oracle)
    .await?;
    drop(oracle);
    observation::checkpoint(
        node,
        writer,
        clock,
        "reopened-output-released",
        plan.populated_size,
        false,
    )?;
    Ok(())
}

async fn initial(
    node: &mut Node,
    writer: &mut Writer,
    counts: &mut Counts,
    plan: &Plan,
    clock: Clock,
    observer: &CatalogWorkObserver,
) -> Result<()> {
    observation::checkpoint(node, writer, clock, "empty", 0, false)?;
    super::publication::publish(node, writer, counts, plan, clock).await?;
    observation::checkpoint(
        node,
        writer,
        clock,
        "artifact-only",
        plan.populated_size,
        false,
    )?;
    seed(node, writer, counts, plan, clock, observer).await?;
    observation::checkpoint(
        node,
        writer,
        clock,
        "post-seed-idle",
        plan.populated_size,
        false,
    )?;
    let oracle = Oracle::new(&node.fixture, plan)?;
    let original = fixture::deployment_for_shape(&node.fixture, &plan.shape, 0);
    let mut weighted = original.clone();
    weighted.route_weight = 2;
    let mut inputs = [Some(original.clone()), Some(weighted), None, Some(original)];
    observation::checkpoint(
        node,
        writer,
        clock,
        "oracle-released",
        plan.populated_size,
        false,
    )?;
    let old = Proof {
        node,
        writer,
        counts,
        clock,
    }
    .pin("old-pin", 1)?;
    for (index, input) in inputs.iter_mut().enumerate() {
        deadline(plan, clock)?;
        Mutation {
            node,
            writer,
            counts,
            plan,
            clock,
            observer,
        }
        .run(index, input.take(), &oracle)
        .await?;
        Proof {
            node,
            writer,
            counts,
            clock,
        }
        .after(index, &old, &oracle)
        .await?;
        observation::checkpoint(
            node,
            writer,
            clock,
            LABELS[index],
            plan.populated_size - u32::from(index == 2),
            true,
        )?;
    }
    drop(inputs);
    drop(oracle);
    observation::checkpoint(
        node,
        writer,
        clock,
        "overlap-before-pin-drop",
        plan.populated_size,
        true,
    )?;
    drop(old);
    observation::checkpoint(
        node,
        writer,
        clock,
        "pin-released",
        plan.populated_size,
        false,
    )?;
    Ok(())
}

async fn seed(
    node: &mut Node,
    writer: &mut Writer,
    counts: &mut Counts,
    plan: &Plan,
    clock: Clock,
    observer: &CatalogWorkObserver,
) -> Result<()> {
    let inputs = (0..plan.populated_size)
        .map(|index| fixture::deployment_for_shape(&node.fixture, &plan.shape, index))
        .collect();
    let before = observation::Before::capture(node, observer, clock)?;
    counts.issued(node, Operation::Seed)?;
    let started = clock.elapsed();
    let result = node.deployments.apply_many(inputs).await;
    let finished = clock.elapsed();
    let mut row = before.finish(node, observer, clock)?;
    counts.returned(Operation::Seed, result.is_ok());
    row["kind"] = json!("seed");
    row["ordinal"] = json!(node.work.commands.to_string());
    row["count"] = json!(plan.populated_size.to_string());
    row["generation_before"] = json!("0");
    row["started_nanos"] = json!(started.to_string());
    row["finished_nanos"] = json!(finished.to_string());
    row["outcome"] = match &result {
        Ok(generation) => json!({"result":{"generation":generation.0.to_string()}}),
        Err(error) => json!({"error":observation::error(error)}),
    };
    writer.sample(&row)?;
    if result.map_err(crate::standalone::measurements::platform)?.0 != 1 {
        return Err("mutation seed generation".into());
    }
    observation::associated(
        &before.observer,
        &observer.snapshot(),
        CatalogWorkOperation::ApplyMany,
        1,
    )
}

pub(super) fn deadline(plan: &Plan, clock: Clock) -> Result<()> {
    if clock.elapsed() >= u128::from(plan.seconds()) * 1_000_000_000 {
        return Err("catalog mutation source deadline".into());
    }
    Ok(())
}
