//! Framed canonical request/receipt hashing over already bounded borrowed data.
//! Exhaustive destructuring makes newly added semantic fields a compile error.

use latent_control_store::VersionedDeployment;
use latent_core::{ArtifactBlobDigest, DeploymentId, ResourceBudget, RouteGeneration};
use latent_manifest::{
    AvailabilityPolicy, CapabilityGrantSpec, DeploymentManifest, ObjectMetadata, PlacementPolicy,
};
use sha2::{Digest, Sha256};

struct Hash(Sha256);
impl Hash {
    fn part(&mut self, bytes: &[u8]) {
        self.0.update((bytes.len() as u64).to_le_bytes());
        self.0.update(bytes);
    }
    fn number(&mut self, value: u64) {
        self.part(&value.to_le_bytes());
    }
    fn optional_number(&mut self, value: Option<u64>) {
        self.number(u64::from(value.is_some()));
        if let Some(value) = value {
            self.number(value);
        }
    }
    fn optional(&mut self, value: Option<&str>) {
        self.number(u64::from(value.is_some()));
        if let Some(value) = value {
            self.part(value.as_bytes());
        }
    }
    fn strings(&mut self, values: &[String]) {
        self.number(values.len() as u64);
        for value in values {
            self.part(value.as_bytes());
        }
    }
    fn metadata(&mut self, values: &latent_core::Metadata) {
        self.number(values.len() as u64);
        for (key, value) in values {
            self.part(key.as_bytes());
            self.part(value.as_bytes());
        }
    }
    fn finish(self) -> ArtifactBlobDigest {
        format!("sha256:{:x}", self.0.finalize())
            .parse()
            .expect("canonical SHA256")
    }
}

pub(super) fn apply(manifest: &DeploymentManifest, expected: Option<u64>) -> ArtifactBlobDigest {
    let mut hash = Hash(Sha256::new());
    hash.part(b"lsf-audit-deployment-apply-v1");
    hash.optional_number(expected);
    deployment(&mut hash, manifest);
    hash.finish()
}

pub(super) fn delete(id: &DeploymentId, expected: Option<u64>) -> ArtifactBlobDigest {
    let mut hash = Hash(Sha256::new());
    hash.part(b"lsf-audit-deployment-delete-v1");
    hash.part(id.0.as_bytes());
    hash.optional_number(expected);
    hash.finish()
}

pub(super) fn receipt(
    value: &VersionedDeployment,
    generation: RouteGeneration,
    delete: bool,
) -> ArtifactBlobDigest {
    let mut hash = Hash(Sha256::new());
    hash.part(b"lsf-audit-deployment-receipt-v1");
    hash.number(u64::from(delete));
    hash.number(value.generation);
    hash.number(generation.0);
    deployment(&mut hash, &value.manifest);
    hash.finish()
}

fn deployment(hash: &mut Hash, manifest: &DeploymentManifest) {
    let DeploymentManifest {
        api_version,
        id,
        metadata,
        service,
        release,
        route_weight,
        grants,
        resources,
        availability,
        placement,
    } = manifest;
    let ObjectMetadata {
        name,
        tenant,
        namespace,
        labels,
        annotations,
    } = metadata;
    for field in [api_version, &id.0, name, &service.0, &release.0] {
        hash.part(field.as_bytes());
    }
    hash.optional(tenant.as_ref().map(|value| value.0.as_str()));
    hash.optional(namespace.as_deref());
    hash.metadata(labels);
    hash.metadata(annotations);
    hash.number(u64::from(*route_weight));
    hash.number(grants.len() as u64);
    for CapabilityGrantSpec {
        capability,
        policy,
        operations,
        constraints,
    } in grants
    {
        hash.part(capability.0.as_bytes());
        hash.part(policy.0.as_bytes());
        hash.strings(operations);
        hash.metadata(constraints);
    }
    let ResourceBudget {
        cpu_fuel,
        memory_bytes,
        wall_time_limit_millis,
        child_calls,
        outbound_requests,
        state_read_bytes,
        state_write_bytes,
        blob_read_bytes,
        blob_write_bytes,
        log_bytes,
        effect_count,
    } = resources;
    for value in [
        cpu_fuel,
        memory_bytes,
        state_read_bytes,
        state_write_bytes,
        blob_read_bytes,
        blob_write_bytes,
        log_bytes,
    ] {
        hash.number(*value);
    }
    for value in [child_calls, outbound_requests, effect_count] {
        hash.number(u64::from(*value));
    }
    hash.optional_number(*wall_time_limit_millis);
    let AvailabilityPolicy {
        minimum_cached_copies,
        minimum_zones,
    } = availability;
    hash.number(u64::from(*minimum_cached_copies));
    hash.number(u64::from(*minimum_zones));
    let PlacementPolicy {
        trust_class,
        architectures,
        regions,
        zones,
        required_features,
    } = placement;
    hash.part(trust_class.as_bytes());
    for values in [architectures, regions, zones, required_features] {
        hash.strings(values);
    }
}
