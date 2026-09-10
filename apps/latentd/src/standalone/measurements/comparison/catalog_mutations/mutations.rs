use std::task::{Context, Poll, Waker};

use latent_control_store::{CatalogWorkObserver, CatalogWorkOperation, DeploymentStore};
use latent_core::{BoxFuture, DeploymentId, TenantId};
use latent_manifest::DeploymentManifest;
use serde_json::{json, Value};

use super::{
    frames::{self, ApplyResult},
    observation::{self, Counts, Operation},
    oracle::Oracle,
    Clock, Node, Plan, Result, Writer,
};

pub(super) struct Mutation<'a> {
    pub node: &'a mut Node,
    pub writer: &'a mut Writer,
    pub counts: &'a mut Counts,
    pub plan: &'a Plan,
    pub clock: Clock,
    pub observer: &'a CatalogWorkObserver,
}

impl Mutation<'_> {
    pub async fn run(
        &mut self,
        index: usize,
        input: Option<DeploymentManifest>,
        oracle: &Oracle,
    ) -> Result<()> {
        if index == 2 {
            self.delete(oracle).await
        } else {
            self.apply(index, input.ok_or("mutation apply input missing")?, oracle)
                .await
        }
    }
    fn row(&mut self, index: usize, mut row: Value, outcome: Value, frame: Value) -> Result<()> {
        row["kind"] = json!("mutation");
        row["label"] = json!(super::sequence::LABELS[index]);
        row["ordinal"] = json!(self.node.work.commands.to_string());
        row["expected_generation"] = json!(if index == 3 {
            "0".to_owned()
        } else {
            (index + 1).to_string()
        });
        row["generation_before"] = json!((index + 1).to_string());
        row["outcome"] = outcome;
        row["allocation_frame"] = frame;
        self.writer.sample(&row)
    }
    async fn apply(
        &mut self,
        index: usize,
        input: DeploymentManifest,
        oracle: &Oracle,
    ) -> Result<()> {
        let tenant = TenantId(self.node.fixture.tenant.clone());
        let expected = if index == 3 {
            0
        } else {
            u64::try_from(index)? + 1
        };
        let before = observation::Before::capture(self.node, self.observer, self.clock)?;
        self.counts.issued(self.node, Operation::Apply)?;
        let mut result = None;
        let mut polls = 0_u64;
        let started = self.clock.elapsed();
        let mut future = self
            .node
            .deployments
            .apply_versioned(&tenant, input, Some(expected));
        if self.plan.profiled() {
            std::future::poll_fn(|cx| {
                polls += 1;
                apply_frame(index, Some(&mut future), cx, &mut result)
            })
            .await;
        } else {
            result = Some(future.as_mut().await);
        }
        let finished = self.clock.elapsed();
        let mut timing = before.finish(self.node, self.observer, self.clock)?;
        timing["started_nanos"] = json!(started.to_string());
        timing["finished_nanos"] = json!(finished.to_string());
        drop(future);
        let actual = result.as_ref().ok_or("mutation result missing")?;
        self.counts.returned(Operation::Apply, actual.is_ok());
        let (outcome, valid) = match actual {
            Ok(receipt) => (
                json!({"result":{"deployment":observation::versioned(&receipt.deployment)?,"catalog_generation":receipt.catalog_generation.0.to_string()}}),
                oracle.states[index]
                    .named
                    .as_ref()
                    .ok_or("mutation expected named")?
                    .versioned(u64::try_from(index)? + 2, &receipt.deployment)
                    .and_then(|()| {
                        if receipt.catalog_generation.0 == u64::try_from(index).unwrap() + 2 {
                            Ok(())
                        } else {
                            Err("mutation apply catalog generation".into())
                        }
                    }),
            ),
            Err(error) => (
                json!({"error":observation::error(error)}),
                Err("mutation apply returned error".into()),
            ),
        };
        let frame = if self.plan.profiled() {
            let _ = apply_frame(
                index,
                None,
                &mut Context::from_waker(Waker::noop()),
                &mut result,
            );
            frame(super::sequence::LABELS[index], polls, 1)
        } else {
            drop(result);
            Value::Null
        };
        self.row(index, timing, outcome, frame)?;
        valid?;
        observation::associated(
            &before.observer,
            &self.observer.snapshot(),
            CatalogWorkOperation::ApplyVersioned,
            u64::try_from(index)? + 2,
        )
    }
    async fn delete(&mut self, oracle: &Oracle) -> Result<()> {
        let tenant = TenantId(self.node.fixture.tenant.clone());
        let id = DeploymentId(super::super::catalog::fixture::id(0));
        let before = observation::Before::capture(self.node, self.observer, self.clock)?;
        self.counts.issued(self.node, Operation::Delete)?;
        let mut result = None;
        let mut polls = 0_u64;
        let started = self.clock.elapsed();
        let mut future = self
            .node
            .deployments
            .delete_versioned(&tenant, &id, Some(3));
        if self.plan.profiled() {
            std::future::poll_fn(|cx| {
                polls += 1;
                frames::measured_delete_and_drop(Some(&mut future), cx, &mut result)
            })
            .await;
        } else {
            result = Some(future.as_mut().await);
        }
        let finished = self.clock.elapsed();
        let mut timing = before.finish(self.node, self.observer, self.clock)?;
        timing["started_nanos"] = json!(started.to_string());
        timing["finished_nanos"] = json!(finished.to_string());
        drop(future);
        let actual = result.as_ref().ok_or("mutation delete missing")?;
        self.counts.returned(Operation::Delete, actual.is_ok());
        let (outcome, valid) = match actual {
            Ok(receipt) => (
                json!({"result":{"deleted":observation::versioned(&receipt.deleted)?,"catalog_generation":receipt.catalog_generation.0.to_string()}}),
                oracle.states[1]
                    .named
                    .as_ref()
                    .ok_or("mutation delete expected")?
                    .versioned(3, &receipt.deleted)
                    .and_then(|()| {
                        if receipt.catalog_generation.0 == 4 {
                            Ok(())
                        } else {
                            Err("mutation delete catalog generation".into())
                        }
                    }),
            ),
            Err(error) => (
                json!({"error":observation::error(error)}),
                Err("mutation delete returned error".into()),
            ),
        };
        let allocation = if self.plan.profiled() {
            let _ = frames::measured_delete_and_drop(
                None,
                &mut Context::from_waker(Waker::noop()),
                &mut result,
            );
            frame("delete", polls, 1)
        } else {
            drop(result);
            Value::Null
        };
        self.row(2, timing, outcome, allocation)?;
        valid?;
        observation::associated(
            &before.observer,
            &self.observer.snapshot(),
            CatalogWorkOperation::DeleteVersioned,
            4,
        )
    }
}

fn apply_frame(
    index: usize,
    future: Option<&mut BoxFuture<'_, ApplyResult>>,
    cx: &mut Context<'_>,
    result: &mut Option<ApplyResult>,
) -> Poll<()> {
    match index {
        0 => frames::measured_unchanged_apply_and_drop(future, cx, result),
        1 => frames::measured_weight_apply_and_drop(future, cx, result),
        3 => frames::measured_reapply_and_drop(future, cx, result),
        _ => unreachable!("fixed apply case"),
    }
}
fn frame(case: &str, polls: u64, drops: u64) -> Value {
    json!({"case":case,"poll_calls":polls.to_string(),"drop_calls":drops.to_string(),"catalog_moved_to_node":false})
}
