use latent_control_store::PinnedRouteResolver;
use latent_core::PlatformError;
use latent_routing::{
    ResolvedRevision, RevisionAdmissionPolicy, RevisionPolicySource, RouteResolver,
};
use serde_json::{json, Value};

use super::super::super::platform;
use super::observation::{self, Counts, Operation};
use super::resolve::{self, Input, Oracle};
use super::{fixture, Clock, Node, Plan, Result, Writer};

struct Proof<'a> {
    node: &'a mut Node,
    writer: &'a mut Writer,
    counts: &'a mut Counts,
    plan: &'a Plan,
    clock: Clock,
}

impl Proof<'_> {
    fn row(
        &mut self,
        label: &str,
        operation: &str,
        started: u128,
        finished: u128,
        mut outcome: Value,
    ) -> Result<()> {
        outcome["kind"] = json!("proof-operation");
        outcome["label"] = json!(label);
        outcome["operation"] = json!(operation);
        outcome["ordinal"] = json!(self.node.work.commands.to_string());
        outcome["started_nanos"] = json!(started.to_string());
        outcome["finished_nanos"] = json!(finished.to_string());
        self.writer.sample(&outcome)
    }

    fn pin(&mut self, label: &str, generation: u64) -> Result<PinnedRouteResolver> {
        self.counts.issued(self.node, Operation::Pin)?;
        let started = self.clock.elapsed();
        let result = self.node.deployments.pin();
        let finished = self.clock.elapsed();
        self.counts.returned(Operation::Pin, result.is_ok());
        let row = match &result {
            Ok(pin) => json!({"result":{"generation":pin.generation().0.to_string()}}),
            Err(error) => failure(error),
        };
        self.row(label, "pin", started, finished, row)?;
        let pin = result.map_err(platform)?;
        if pin.generation().0 != generation {
            return Err("catalog pinned generation mismatch".into());
        }
        Ok(pin)
    }

    fn resolve(
        &mut self,
        label: &str,
        pin: &PinnedRouteResolver,
        input: &Input,
        case: &str,
        oracle: &Oracle,
    ) -> Result<resolve::Outcome> {
        self.counts.issued(self.node, Operation::Resolve)?;
        let started = self.clock.elapsed();
        let result = pin.resolve(&input.target, Some(&input.key));
        let finished = self.clock.elapsed();
        self.counts.returned(Operation::Resolve, result.is_ok());
        self.row(
            label,
            "resolve",
            started,
            finished,
            resolve::outcome(&result)?,
        )?;
        oracle.validate(
            &self.node.fixture,
            self.plan,
            input,
            case,
            pin.generation().0,
            &result,
        )?;
        Ok(result)
    }

    fn policy(
        &mut self,
        label: &str,
        pin: &PinnedRouteResolver,
        revision: &ResolvedRevision,
    ) -> Result<()> {
        self.counts.issued(self.node, Operation::Policy)?;
        let started = self.clock.elapsed();
        let result = pin.admission_policy(revision);
        let finished = self.clock.elapsed();
        self.counts.returned(Operation::Policy, result.is_ok());
        let row = match &result {
            Ok(policy) => json!({"result":self.policy_value(policy)?}),
            Err(error) => failure(error),
        };
        self.row(label, "policy", started, finished, row)?;
        let policy = result.map_err(platform)?;
        if policy.deployment_ceiling != self.node.fixture.deployment.resources
            || policy.placement != self.node.fixture.deployment.placement
            || policy.execution != self.node.fixture.artifact.manifest.execution
        {
            return Err("catalog pinned policy mismatch".into());
        }
        Ok(())
    }

    fn policy_value(&self, policy: &RevisionAdmissionPolicy) -> Result<Value> {
        // Serialize the actual returned values through the existing canonical DTO
        // encoders, not a second budget/placement encoding convention.
        let mut deployment = self.node.fixture.deployment.clone();
        deployment.resources = policy.deployment_ceiling.clone();
        deployment.placement = policy.placement.clone();
        let mut capsule = self.node.fixture.artifact.manifest.clone();
        capsule.execution = policy.execution.clone();
        let deployment = serde_json::to_value(deployment)?;
        let capsule = serde_json::to_value(capsule)?;
        let mut value = json!({"deployment_ceiling":deployment["spec"]["resources"],
            "execution":capsule["execution"],"placement":deployment["spec"]["placement"]});
        decimals(&mut value);
        Ok(value)
    }

    async fn apply(&mut self, generation: u64) -> Result<()> {
        let mut changed = fixture::deployment(&self.node.fixture, self.plan, 0);
        changed.route_weight = 2;
        let batch = vec![changed];
        self.counts.issued(self.node, Operation::Apply)?;
        let started = self.clock.elapsed();
        let result = self.node.deployments.apply_many(batch).await;
        let finished = self.clock.elapsed();
        self.counts.returned(Operation::Apply, result.is_ok());
        let row = match &result {
            Ok(generation) => json!({"result":{"generation":generation.0.to_string()}}),
            Err(error) => failure(error),
        };
        self.row("update-apply", "apply", started, finished, row)?;
        if result.map_err(platform)?.0 != generation {
            return Err("catalog update generation mismatch".into());
        }
        Ok(())
    }
}

fn decimals(value: &mut Value) {
    match value {
        Value::Number(number) => *value = json!(number.to_string()),
        Value::Array(rows) => rows.iter_mut().for_each(decimals),
        Value::Object(rows) => rows.values_mut().for_each(decimals),
        _ => {}
    }
}

fn failure(error: &PlatformError) -> Value {
    json!({"error":observation::error(error)})
}

pub(super) async fn update(
    node: &mut Node,
    writer: &mut Writer,
    counts: &mut Counts,
    plan: &Plan,
    count: u32,
    clock: Clock,
) -> Result<()> {
    let mut proof = Proof {
        node,
        writer,
        counts,
        plan,
        clock,
    };
    let generation = u64::try_from(plan.scales().len())?;
    let input = resolve::input(&proof.node.fixture, plan, count, "named-success", 0);
    // Named index zero has one member. Avoid retaining a second N-sized oracle.
    let old_oracle = Oracle::new(&proof.node.fixture, plan, 1, false)?;
    let new_oracle = Oracle::new(&proof.node.fixture, plan, 1, true)?;
    let old = proof.pin("update-old-pin", generation)?;
    let before = proof
        .resolve(
            "update-old-resolve-before",
            &old,
            &input,
            "named-success",
            &old_oracle,
        )?
        .map_err(platform)?;
    proof.policy("update-old-policy-before", &old, &before)?;
    proof.apply(generation + 1).await?;
    let after = proof
        .resolve(
            "update-old-resolve-after",
            &old,
            &input,
            "named-success",
            &old_oracle,
        )?
        .map_err(platform)?;
    proof.policy("update-old-policy-after", &old, &after)?;
    if before != after {
        return Err("catalog old pin changed after publication".into());
    }
    let new = proof.pin("update-new-pin", generation + 1)?;
    let current = proof
        .resolve(
            "update-new-resolve",
            &new,
            &input,
            "named-success",
            &new_oracle,
        )?
        .map_err(platform)?;
    proof.policy("update-new-policy", &new, &current)?;
    if current.revision != before.revision
        || current.release != before.release
        || current.attributes == before.attributes
    {
        return Err("catalog weight-only update identity mismatch".into());
    }
    drop((before, after, current, new, input, old_oracle, new_oracle));
    observation::checkpoint(
        proof.node,
        proof.writer,
        clock,
        "old-pin-overlap",
        count,
        true,
    )?;
    drop(old);
    observation::checkpoint(
        proof.node,
        proof.writer,
        clock,
        "old-pin-released",
        count,
        false,
    )
}

pub(super) fn reopen(
    node: &mut Node,
    writer: &mut Writer,
    counts: &mut Counts,
    plan: &Plan,
    count: u32,
    clock: Clock,
) -> Result<()> {
    let mut proof = Proof {
        node,
        writer,
        counts,
        plan,
        clock,
    };
    let oracle = Oracle::new(&proof.node.fixture, plan, count, true)?;
    let pin = proof.pin("reopen-pin", u64::try_from(plan.scales().len())? + 1)?;
    for (case, label, policy_label) in [
        (
            "default-success",
            "reopen-default-resolve",
            Some("reopen-default-policy"),
        ),
        (
            "named-success",
            "reopen-named-resolve",
            Some("reopen-named-policy"),
        ),
        ("route-miss", "reopen-route-miss", None),
        ("export-miss", "reopen-export-miss", None),
    ] {
        let input = resolve::input(&proof.node.fixture, plan, count, case, 0);
        let result = proof.resolve(label, &pin, &input, case, &oracle)?;
        if let Some(policy_label) = policy_label {
            proof.policy(policy_label, &pin, &result.map_err(platform)?)?;
        }
    }
    drop((pin, oracle));
    Ok(())
}
