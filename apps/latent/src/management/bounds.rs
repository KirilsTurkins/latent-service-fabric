//! Fixed-schema response traversal before conversion or JSON allocation.

use std::collections::HashMap;

use latent_wire::management::proto;
use prost::Message;

use crate::error::Failure;

use super::invalid_response;

pub(super) trait Check {
    fn check(&self, bounds: &mut Bounds) -> Result<(), Failure>;
}

pub(super) fn checked<T: Message + Check>(value: &T, maximum: usize) -> Result<(), Failure> {
    value.check(&mut Bounds { remaining: 65_536 })?;
    if value.encoded_len() > maximum {
        return Err(invalid_response());
    }
    Ok(())
}

pub(super) struct Bounds {
    remaining: usize,
}

impl Bounds {
    fn count(&mut self, count: usize) -> Result<(), Failure> {
        if count > 4096 {
            return Err(invalid_response());
        }
        self.remaining = self
            .remaining
            .checked_sub(count)
            .ok_or_else(invalid_response)?;
        Ok(())
    }

    fn text(&mut self, value: &str) -> Result<(), Failure> {
        self.count(1)?;
        if value.len() > 4096 {
            return Err(invalid_response());
        }
        Ok(())
    }

    fn id(&mut self, value: &str) -> Result<(), Failure> {
        self.text(value)?;
        if value.is_empty() || value.len() > 512 || value.chars().any(char::is_control) {
            return Err(invalid_response());
        }
        Ok(())
    }

    fn digest(&mut self, value: &str) -> Result<(), Failure> {
        self.text(value)?;
        if !super::canonical_digest(value) {
            return Err(invalid_response());
        }
        Ok(())
    }

    fn texts(&mut self, values: &[String]) -> Result<(), Failure> {
        self.count(values.len())?;
        for value in values {
            self.text(value)?;
        }
        Ok(())
    }

    fn optional(&mut self, value: Option<&str>) -> Result<(), Failure> {
        if let Some(value) = value {
            self.text(value)?;
        }
        Ok(())
    }

    fn map(&mut self, values: &HashMap<String, String>) -> Result<(), Failure> {
        self.count(values.len())?;
        for (key, value) in values {
            self.text(key)?;
            self.text(value)?;
        }
        Ok(())
    }

    fn rows<T: Check>(&mut self, values: &[T]) -> Result<(), Failure> {
        self.count(values.len())?;
        for value in values {
            value.check(self)?;
        }
        Ok(())
    }

    fn page(&mut self, page: Option<&proto::PageResponse>) -> Result<(), Failure> {
        self.count(1)?;
        let page = page.ok_or_else(invalid_response)?;
        if page.next_page_token.as_ref().is_some_and(|token| {
            token.is_empty() || token.len() > 8192 || token.chars().any(char::is_control)
        }) {
            return Err(invalid_response());
        }
        Ok(())
    }
}

impl Check for proto::ReleaseDescriptor {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        b.digest(&self.digest)?;
        b.id(&self.artifact_reference)?;
        b.id(&self.service)?;
        b.id(&self.semantic_version)?;
        b.id(&self.world)?;
        b.text(&self.publisher)?;
        b.id(&self.media_type)?;
        b.id(self.tenant.as_deref().ok_or_else(invalid_response)?)?;
        b.map(&self.annotations)
    }
}

impl Check for proto::PublishReleaseResponse {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        self.release
            .as_ref()
            .ok_or_else(invalid_response)?
            .check(b)?;
        b.texts(&self.admission_warnings)
    }
}
impl Check for proto::GetReleaseResponse {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        self.release.as_ref().map_or(Ok(()), |value| value.check(b))
    }
}
impl Check for proto::ListReleasesResponse {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        b.rows(&self.releases)?;
        b.page(self.page.as_ref())
    }
}

impl Check for proto::Deployment {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        b.id(&self.id)?;
        b.id(&self.service)?;
        b.digest(&self.release_digest)?;
        let metadata = self.metadata.as_ref().ok_or_else(invalid_response)?;
        b.id(&metadata.name)?;
        b.id(metadata.tenant.as_deref().ok_or_else(invalid_response)?)?;
        b.optional(metadata.namespace.as_deref())?;
        b.map(&metadata.labels)?;
        b.map(&metadata.annotations)?;
        b.count(self.grants.len())?;
        for grant in &self.grants {
            b.id(&grant.capability)?;
            b.id(&grant.policy)?;
            b.texts(&grant.operations)?;
            b.map(&grant.constraints)?;
        }
        let placement = self.placement.as_ref().ok_or_else(invalid_response)?;
        b.text(&placement.trust_class)?;
        b.texts(&placement.architectures)?;
        b.texts(&placement.regions)?;
        b.texts(&placement.zones)?;
        b.texts(&placement.required_features)?;
        if self.generation == 0 {
            return Err(invalid_response());
        }
        Ok(())
    }
}
impl Check for proto::ApplyDeploymentResponse {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        self.deployment
            .as_ref()
            .ok_or_else(invalid_response)?
            .check(b)?;
        b.texts(&self.warnings)
    }
}
impl Check for proto::GetDeploymentResponse {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        self.deployment
            .as_ref()
            .map_or(Ok(()), |value| value.check(b))
    }
}
impl Check for proto::ListDeploymentsResponse {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        b.rows(&self.deployments)?;
        b.page(self.page.as_ref())
    }
}
impl Check for proto::Empty {
    fn check(&self, _: &mut Bounds) -> Result<(), Failure> {
        Ok(())
    }
}

impl Check for proto::GetRouteSnapshotResponse {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        let Some(snapshot) = &self.snapshot else {
            return Ok(());
        };
        let tenant = snapshot.tenant.as_deref().ok_or_else(invalid_response)?;
        b.id(tenant)?;
        b.digest(&snapshot.snapshot_digest)?;
        b.count(snapshot.services.len())?;
        for service in &snapshot.services {
            b.id(&service.route_id)?;
            b.id(&service.service)?;
            b.id(&service.tenant)?;
            if service.tenant != tenant {
                return Err(invalid_response());
            }
            b.count(service.revisions.len())?;
            for revision in &service.revisions {
                b.id(&revision.revision_id)?;
                b.digest(&revision.release_digest)?;
                b.map(&revision.attributes)?;
            }
        }
        b.count(snapshot.bindings.len())?;
        for binding in &snapshot.bindings {
            for value in [
                &binding.binding_id,
                &binding.consumer_service,
                &binding.imported_contract,
                &binding.provider_service,
                &binding.provider_contract,
                &binding.mode,
                &binding.policy_digest,
                &binding.consumer_tenant,
                &binding.provider_tenant,
            ] {
                b.id(value)?;
            }
            if binding.consumer_tenant != tenant || binding.provider_tenant != tenant {
                return Err(invalid_response());
            }
        }
        b.texts(&snapshot.policy_digests)
    }
}

impl Check for proto::NodeInventory {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        let node = self.node.as_ref().ok_or_else(invalid_response)?;
        for value in [
            &node.id,
            &node.architecture,
            &node.operating_system,
            &node.endpoint,
            &node.identity,
        ] {
            b.id(value)?;
        }
        b.texts(&node.cpu_features)?;
        b.texts(&node.trust_classes)?;
        b.optional(node.region.as_deref())?;
        b.optional(node.zone.as_deref())?;
        b.map(&node.attributes)?;
        b.count(self.cell_capacity.len())?;
        for cell in &self.cell_capacity {
            b.id(&cell.class)?;
        }
        b.count(self.cache_entries.len())?;
        for entry in &self.cache_entries {
            b.id(&entry.key)?;
            b.digest(&entry.release_digest)?;
            b.id(&entry.tier)?;
        }
        let health = self.health.as_ref().ok_or_else(invalid_response)?;
        b.texts(&health.reasons)?;
        let topology = self.topology.as_ref().ok_or_else(invalid_response)?;
        b.count(topology.entries.len())?;
        for entry in &topology.entries {
            b.id(&entry.name)?;
            b.id(&entry.kind)?;
            b.map(&entry.attributes)?;
        }
        Ok(())
    }
}
impl Check for proto::GetNodeResponse {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        self.inventory
            .as_ref()
            .map_or(Ok(()), |value| value.check(b))
    }
}
impl Check for proto::ListNodesResponse {
    fn check(&self, b: &mut Bounds) -> Result<(), Failure> {
        b.rows(&self.nodes)?;
        b.page(self.page.as_ref())
    }
}
