use latent_control_store::{DeploymentStore, PinnedRouteResolver};
use latent_core::DeploymentId;
use latent_routing::{
    ActivationCatalog, InvocationTarget, ResolvedRevision, RevisionAdmissionPolicy, RouteResolver,
};
use serde_json::{json, Value};

use super::{
    observation::{self, Counts, Operation},
    oracle::{Expected, Oracle, KEY},
    Clock, Node, Result, Writer,
};
use crate::standalone::measurements::platform;

pub(super) struct Proof<'a> {
    pub node: &'a mut Node,
    pub writer: &'a mut Writer,
    pub counts: &'a mut Counts,
    pub clock: Clock,
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
    pub fn pin(&mut self, label: &str, generation: u64) -> Result<PinnedRouteResolver> {
        self.counts.issued(self.node, Operation::Pin)?;
        let started = self.clock.elapsed();
        let result = self.node.deployments.pin();
        let finished = self.clock.elapsed();
        self.counts.returned(Operation::Pin, result.is_ok());
        let value = match &result {
            Ok(pin) => json!({"result":{"generation":pin.generation().0.to_string()}}),
            Err(error) => json!({"error":observation::error(error)}),
        };
        self.row(label, "pin", started, finished, value)?;
        let pin = result.map_err(platform)?;
        if pin.generation().0 != generation {
            return Err("mutation pin generation".into());
        }
        Ok(pin)
    }
    pub async fn get(
        &mut self,
        label: &str,
        expected: Option<&Expected>,
        generation: u64,
    ) -> Result<()> {
        let tenant = latent_core::TenantId(self.node.fixture.tenant.clone());
        let id = DeploymentId(super::super::catalog::fixture::id(0));
        self.counts.issued(self.node, Operation::Get)?;
        let started = self.clock.elapsed();
        let result = self.node.deployments.get_versioned(&tenant, &id).await;
        let finished = self.clock.elapsed();
        self.counts.returned(Operation::Get, result.is_ok());
        let value = match &result {
            Ok(record) => {
                json!({"result":record.as_ref().map(observation::versioned).transpose()?})
            }
            Err(error) => json!({"error":observation::error(error)}),
        };
        self.row(label, "get", started, finished, value)?;
        match (expected, result.map_err(platform)?) {
            (Some(expected), Some(actual)) => expected.versioned(generation, &actual),
            (None, None) => Ok(()),
            _ => Err("mutation get presence".into()),
        }
    }
    fn resolve(
        &mut self,
        label: &str,
        catalog: &dyn ActivationCatalog,
        target: &InvocationTarget,
        expected: Option<&Expected>,
        generation: u64,
    ) -> Result<Option<ResolvedRevision>> {
        self.counts.issued(self.node, Operation::Resolve)?;
        let started = self.clock.elapsed();
        let result = catalog.resolve(target, Some(KEY));
        let finished = self.clock.elapsed();
        self.counts.returned(Operation::Resolve, result.is_ok());
        let mut value = super::super::catalog::resolve::outcome(&result)?;
        value["target"] = json!({"tenant":target.tenant.0,"service":target.service.0,"contract":target.contract.0,"function":target.function.0,"route":target.route});
        value["routing_key"] = json!(KEY);
        self.row(label, "resolve", started, finished, value)?;
        if let Some(expected) = expected {
            let actual = result.map_err(platform)?;
            expected.resolve(target, generation, &actual)?;
            Ok(Some(actual))
        } else {
            super::super::catalog::resolve::validate_miss("route-miss", &result)?;
            Ok(None)
        }
    }
    fn policy(
        &mut self,
        label: &str,
        catalog: &dyn ActivationCatalog,
        resolved: &ResolvedRevision,
    ) -> Result<()> {
        self.counts.issued(self.node, Operation::Policy)?;
        let started = self.clock.elapsed();
        let result = catalog.admission_policy(resolved);
        let finished = self.clock.elapsed();
        self.counts.returned(Operation::Policy, result.is_ok());
        let value = match &result {
            Ok(policy) => json!({"result":self.policy_value(policy)?}),
            Err(error) => json!({"error":observation::error(error)}),
        };
        self.row(label, "policy", started, finished, value)?;
        let policy = result.map_err(platform)?;
        if policy.deployment_ceiling != self.node.fixture.deployment.resources
            || policy.placement != self.node.fixture.deployment.placement
            || policy.execution != self.node.fixture.artifact.manifest.execution
        {
            return Err("mutation admission policy mismatch".into());
        }
        Ok(())
    }
    fn policy_value(&self, policy: &RevisionAdmissionPolicy) -> Result<Value> {
        let mut deployment = self.node.fixture.deployment.clone();
        deployment.resources = policy.deployment_ceiling.clone();
        deployment.placement = policy.placement.clone();
        let mut capsule = self.node.fixture.artifact.manifest.clone();
        capsule.execution = policy.execution.clone();
        let deployment = serde_json::to_value(deployment)?;
        let capsule = serde_json::to_value(capsule)?;
        let mut value = json!({"deployment_ceiling":deployment["spec"]["resources"],"placement":deployment["spec"]["placement"],"execution":capsule["execution"]});
        observation::decimals(&mut value);
        Ok(value)
    }
    pub async fn after(
        &mut self,
        index: usize,
        old: &PinnedRouteResolver,
        oracle: &Oracle,
    ) -> Result<()> {
        let label = super::sequence::LABELS[index];
        let generation = u64::try_from(index)? + 2;
        let state = &oracle.states[index];
        self.get(&format!("{label}/get"), state.named.as_ref(), generation)
            .await?;
        let old_result = self
            .resolve(
                &format!("{label}/old-named"),
                old,
                &oracle.named,
                Some(&oracle.original),
                1,
            )?
            .ok_or("old named absent")?;
        self.policy(&format!("{label}/old-policy"), old, &old_result)?;
        drop(old_result);
        let current = self.pin(&format!("{label}/current-pin"), generation)?;
        for (suffix, target, expected) in [
            ("current-named", &oracle.named, state.named.as_ref()),
            ("current-default", &oracle.default, state.default.as_ref()),
        ] {
            if let Some(result) = self.resolve(
                &format!("{label}/{suffix}"),
                &current,
                target,
                expected,
                generation,
            )? {
                self.policy(&format!("{label}/{suffix}-policy"), &current, &result)?;
            }
        }
        Ok(())
    }
    pub async fn reopen(&mut self, oracle: &Oracle) -> Result<()> {
        self.get("reopen-get", Some(&oracle.original), 5).await?;
        let pin = self.pin("reopen-pin", 5)?;
        for (suffix, target, expected) in [
            ("named", &oracle.named, Some(&oracle.original)),
            (
                "default",
                &oracle.default,
                oracle.states[3].default.as_ref(),
            ),
        ] {
            let resolved = self
                .resolve(&format!("reopen-{suffix}"), &pin, target, expected, 5)?
                .ok_or("reopen resolve absent")?;
            self.policy(&format!("reopen-{suffix}-policy"), &pin, &resolved)?;
        }
        Ok(())
    }
}
