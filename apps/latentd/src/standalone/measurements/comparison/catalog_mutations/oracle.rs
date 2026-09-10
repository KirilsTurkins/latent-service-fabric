use latent_control_store::{deployment_revision_id, VersionedDeployment};
use latent_core::{ContractId, FunctionId, ReleaseDigest, RevisionId, ServiceId, TenantId};
use latent_manifest::{DeploymentManifest, JsonManifestCodec, ManifestCodec};
use latent_routing::{InvocationTarget, ResolvedRevision};

use super::super::catalog::{fixture, resolve};
use super::{Plan, Result};
use crate::standalone::measurements::{fixtures::Fixture, platform};

pub(super) const KEY: &str = "catalog-key-00000";

#[derive(Clone)]
pub(super) struct Expected {
    pub revision: RevisionId,
    pub release: ReleaseDigest,
    pub manifest_digest: ReleaseDigest,
}

impl Expected {
    pub fn new(manifest: &DeploymentManifest) -> Result<Self> {
        Ok(Self {
            revision: deployment_revision_id(manifest).map_err(platform)?,
            release: manifest.release.clone(),
            manifest_digest: latent_artifacts::content_digest(
                &JsonManifestCodec::default()
                    .encode_deployment(manifest)
                    .map_err(|_| "mutation oracle deployment encoding")?,
            ),
        })
    }
    pub fn resolve(
        &self,
        target: &InvocationTarget,
        generation: u64,
        result: &ResolvedRevision,
    ) -> Result<()> {
        if result.target != *target
            || result.revision != self.revision
            || result.release != self.release
            || result.route_generation.0 != generation
            || result.attributes.len() != 2
            || !result.attributes.contains_key("lsf.exports")
            || result
                .attributes
                .get("lsf.deployment")
                .map(|bytes| latent_artifacts::content_digest(bytes.as_bytes()))
                .as_ref()
                != Some(&self.manifest_digest)
        {
            return Err("mutation resolved receipt mismatch".into());
        }
        Ok(())
    }
    pub fn versioned(&self, generation: u64, result: &VersionedDeployment) -> Result<()> {
        if result.generation != generation
            || Self::new(&result.manifest)?.manifest_digest != self.manifest_digest
        {
            return Err("mutation versioned receipt mismatch".into());
        }
        Ok(())
    }
}

pub(super) struct State {
    pub named: Option<Expected>,
    pub default: Option<Expected>,
}
pub(super) struct Oracle {
    pub original: Expected,
    pub named: InvocationTarget,
    pub default: InvocationTarget,
    pub states: [State; 4],
}

impl Oracle {
    pub fn new(fixture: &Fixture, plan: &Plan) -> Result<Self> {
        let target = InvocationTarget {
            tenant: TenantId(fixture.tenant.clone()),
            service: ServiceId(fixture::service_for_shape(&plan.shape, 0)),
            contract: ContractId(fixture.contract.clone()),
            function: FunctionId("echo".to_owned()),
            route: Some(fixture::id(0)),
        };
        let mut default = target.clone();
        default.route = None;
        // Only this construction owns an N-sized table. It is destroyed before
        // returning the four compact expected selections to the measured sequence.
        let mut ordered = (0..plan.populated_size)
            .map(|index| {
                let manifest = fixture::deployment_for_shape(fixture, &plan.shape, index);
                Ok((index, deployment_revision_id(&manifest).map_err(platform)?))
            })
            .collect::<Result<Vec<_>>>()?;
        ordered.sort_unstable_by(|a, b| a.1.cmp(&b.1));
        let original = Expected::new(&fixture::deployment_for_shape(fixture, &plan.shape, 0))?;
        let mut states = Vec::with_capacity(4);
        for state in 0..4 {
            let mut changed = fixture::deployment_for_shape(fixture, &plan.shape, 0);
            if state == 1 {
                changed.route_weight = 2;
            }
            let named = if state == 2 {
                None
            } else {
                Some(Expected::new(&changed)?)
            };
            let selected = if plan.shape == "shared" {
                let total =
                    u64::from(plan.populated_size) + u64::from(state == 1) - u64::from(state == 2);
                let mut bucket = resolve::selection_hash(&default, KEY) % total;
                let index = ordered
                    .iter()
                    .find_map(|(index, _)| {
                        let weight = if *index == 0 && state == 2 {
                            0
                        } else if *index == 0 && state == 1 {
                            2
                        } else {
                            1
                        };
                        if bucket < weight {
                            Some(*index)
                        } else {
                            bucket -= weight;
                            None
                        }
                    })
                    .ok_or("mutation weighted selection")?;
                let mut selected = fixture::deployment_for_shape(fixture, &plan.shape, index);
                if index == 0 && state == 1 {
                    selected.route_weight = 2;
                }
                Some(Expected::new(&selected)?)
            } else {
                named.clone()
            };
            states.push(State {
                named,
                default: selected,
            });
        }
        drop(ordered);
        Ok(Self {
            original,
            named: target,
            default,
            states: states.try_into().map_err(|_| "mutation four states")?,
        })
    }
}
