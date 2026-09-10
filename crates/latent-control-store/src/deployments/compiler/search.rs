use latent_core::{PlatformError, PlatformErrorCode};
use latent_routing::{InvocationTarget, ResolvedRevision};
use sha2::{Digest, Sha256};

use super::{
    error, valid_identifier, CompiledCatalog, DirectoryDeploymentRepositoryConfig, EndpointRow,
    RouteRow,
};

impl CompiledCatalog {
    pub(super) fn find_route(&self, target: &InvocationTarget) -> Option<&RouteRow> {
        let key = (
            target.tenant.0.as_str(),
            target.service.0.as_str(),
            target.route.as_deref().unwrap_or("default"),
        );
        self.routes
            .binary_search_by(|row| self.route_key(row).cmp(&key))
            .ok()
            .map(|index| &self.routes[index])
    }

    pub(super) fn find_endpoint(
        &self,
        route: &RouteRow,
        target: &InvocationTarget,
    ) -> Option<&EndpointRow> {
        let key = (&target.contract, &target.function);
        let endpoints = &self.endpoints[route.endpoints.clone()];
        endpoints
            .binary_search_by(|row| (&row.contract, &row.function).cmp(&key))
            .ok()
            .map(|index| &endpoints[index])
    }

    pub(in crate::deployments) fn resolve(
        &self,
        target: &InvocationTarget,
        routing_key: Option<&str>,
        config: DirectoryDeploymentRepositoryConfig,
    ) -> Result<ResolvedRevision, PlatformError> {
        let route = target.route.as_deref().unwrap_or("default");
        let key = routing_key.unwrap_or("");
        let identifiers = [
            target.tenant.0.as_str(),
            target.service.0.as_str(),
            target.contract.0.as_str(),
            target.function.0.as_str(),
            route,
        ];
        if identifiers
            .iter()
            .any(|id| !valid_identifier(id, config.max_identifier_bytes))
            || key.len() > config.max_routing_key_bytes
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-invocation-target",
            ));
        }
        let route = self
            .find_route(target)
            .ok_or_else(|| error(PlatformErrorCode::RouteUnavailable, "route-not-found"))?;
        let endpoint = self.find_endpoint(route, target).ok_or_else(|| {
            error(
                PlatformErrorCode::IncompatibleContract,
                "contract-or-function-not-exported",
            )
        })?;
        let candidates = &self.candidates[endpoint.candidates.clone()];
        let bucket = selection_hash(target, key) % endpoint.total_weight;
        let index = candidates.partition_point(|candidate| candidate.cumulative_weight <= bucket);
        let record = self.record(candidates[index].record);
        Ok(ResolvedRevision {
            target: target.clone(),
            revision: record.revision.clone(),
            release: record.deployment.release.clone(),
            route_generation: self.generation,
            attributes: record.attributes.clone(),
        })
    }
}

pub(super) fn selection_hash(target: &InvocationTarget, key: &str) -> u64 {
    let mut hash = Sha256::new();
    hash.update(b"lsf-route-selection-v1\0");
    for part in [
        target.tenant.0.as_str(),
        target.service.0.as_str(),
        target.route.as_deref().unwrap_or("default"),
        target.contract.0.as_str(),
        target.function.0.as_str(),
        key,
    ] {
        hash.update((part.len() as u64).to_be_bytes());
        hash.update(part.as_bytes());
    }
    let bytes = hash.finalize();
    u64::from_be_bytes(
        bytes[..8]
            .try_into()
            .expect("SHA-256 has eight prefix bytes"),
    )
}
