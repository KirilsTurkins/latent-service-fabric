use latent_control_store::{
    CatalogWorkObserver, CatalogWorkOperation, CatalogWorkOutcome, CatalogWorkSnapshot,
    VersionedDeployment,
};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use serde_json::{json, Value};

pub(in crate::standalone::measurements::comparison) use super::super::catalog::observation::{
    checkpoint, decimals, error, verification,
};
use super::{Clock, Node, Plan, Result};

#[derive(Clone, Copy)]
pub(super) enum Operation {
    Publish,
    Seed,
    Apply,
    Delete,
    Get,
    Resolve,
    Policy,
    Pin,
}

#[derive(Default, Clone, Copy)]
struct Count {
    attempted: u64,
    ok: u64,
    error: u64,
}
#[derive(Default)]
pub(super) struct Counts([Count; 8]);

impl Counts {
    pub fn issued(&mut self, node: &mut Node, operation: Operation) -> Result<()> {
        node.command(false)?;
        self.0[operation as usize].attempted += 1;
        Ok(())
    }
    pub fn returned(&mut self, operation: Operation, ok: bool) {
        let count = &mut self.0[operation as usize];
        if ok {
            count.ok += 1;
        } else {
            count.error += 1;
        }
    }
    pub fn snapshot(&self) -> Value {
        Value::Object(super::plan::OPERATIONS.into_iter().zip(self.0).map(|(name,row)|
            (name.to_owned(),json!({"attempted":row.attempted.to_string(),"returned_ok":row.ok.to_string(),"returned_error":row.error.to_string()}))).collect())
    }
    pub fn complete(&self, plan: &Plan, commands: u64) -> Result<()> {
        for (count, expected) in self.0.iter().zip(plan.counts()) {
            if count.attempted != expected || count.ok + count.error != expected {
                return Err("catalog mutation operation population incomplete".into());
            }
        }
        if commands != plan.commands() {
            return Err("catalog mutation commands incomplete".into());
        }
        Ok(())
    }
}

pub(in crate::standalone::measurements::comparison) fn snapshot(
    observer: &CatalogWorkObserver,
) -> Result<Value> {
    project(&observer.snapshot())
}

pub(in crate::standalone::measurements::comparison) fn project(
    value: &CatalogWorkSnapshot,
) -> Result<Value> {
    let mut value = serde_json::to_value(value)?;
    decimals(&mut value);
    Ok(value)
}

pub(super) fn associated(
    before: &CatalogWorkSnapshot,
    after: &CatalogWorkSnapshot,
    operation: CatalogWorkOperation,
    generation: u64,
) -> Result<()> {
    let receipt = after.last.ok_or("catalog work missing receipt")?;
    if before.overflowed
        || before.poisoned
        || after.overflowed
        || after.poisoned
        || receipt.overflowed
        || before.active != 0
        || after.active != 0
        || after.maximum_active != 1
        || before.started.checked_add(1) != Some(after.started)
        || before.finished.checked_add(1) != Some(after.finished)
        || receipt.sequence != after.started
        || receipt.operation != operation
        || receipt.outcome != CatalogWorkOutcome::ReturnedOk
        || receipt.compiled_generation != Some(generation)
    {
        return Err("catalog work association mismatch".into());
    }
    Ok(())
}

pub(super) struct Before {
    pub observer: CatalogWorkSnapshot,
    pub verification: Value,
    pub cpu: Value,
}

impl Before {
    pub fn capture(node: &Node, observer: &CatalogWorkObserver, clock: Clock) -> Result<Self> {
        Ok(Self {
            observer: observer.snapshot(),
            verification: verification(node)?,
            cpu: super::super::budget::cpu::sample(clock)?,
        })
    }
    pub fn finish(
        &self,
        node: &Node,
        observer: &CatalogWorkObserver,
        clock: Clock,
    ) -> Result<Value> {
        let cpu = super::super::budget::cpu::sample(clock)?;
        Ok(
            json!({"observer_before":project(&self.observer)?,"observer_after":snapshot(observer)?,
            "verification_before":self.verification,"verification_after":verification(node)?,"cpu_before":self.cpu,"cpu_after":cpu}),
        )
    }
}

pub(super) fn versioned(value: &VersionedDeployment) -> Result<Value> {
    let manifest = &value.manifest;
    let bytes = JsonManifestCodec::default()
        .encode_deployment(manifest)
        .map_err(|_| "mutation returned deployment encoding")?;
    Ok(
        json!({"id":manifest.id.0,"tenant":manifest.metadata.tenant.as_ref().map(|tenant|tenant.0.as_str()),"service":manifest.service.0,"release":manifest.release.0,
        "weight":manifest.route_weight.to_string(),"object_generation":value.generation.to_string(),
        "manifest_digest":latent_artifacts::content_digest(&bytes).0}),
    )
}
