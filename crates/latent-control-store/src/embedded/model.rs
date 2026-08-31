use std::collections::{BTreeMap, BTreeSet};

use latent_core::{
    BindingId, CapabilityId, ContractId, DeploymentId, FunctionId, PlatformError, PolicyId,
    ReleaseDigest, ResourceBudget, RevisionId, RouteGeneration, RouteId, ServiceId, TenantId,
};
use latent_manifest::{
    AvailabilityPolicy, BindingMode, CapabilityGrantSpec, DeploymentManifest, ObjectMetadata,
    PlacementPolicy,
};
use latent_routing::{BindingRoute, RevisionRoute, RouteContract, RouteSnapshot, ServiceRoute};
use serde::{Deserialize, Serialize};

use super::{platform_error, stable_fields};
use latent_core::PlatformErrorCode;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct PersistedCatalogState {
    deployments: Vec<PersistedDeployment>,
    snapshot: PersistedRouteSnapshot,
}

impl PersistedCatalogState {
    pub(crate) fn from_domain(
        deployments: &BTreeMap<DeploymentId, DeploymentManifest>,
        snapshot: &RouteSnapshot,
    ) -> Self {
        Self {
            deployments: deployments
                .values()
                .map(PersistedDeployment::from_manifest)
                .collect(),
            snapshot: PersistedRouteSnapshot::from_snapshot(snapshot),
        }
    }

    pub(crate) fn generation(&self) -> u64 {
        self.snapshot.generation()
    }

    pub(crate) fn into_domain(
        self,
    ) -> Result<(BTreeMap<DeploymentId, DeploymentManifest>, RouteSnapshot), PlatformError> {
        let mut deployments = BTreeMap::new();
        for deployment in self.deployments {
            let deployment = deployment.into_manifest();
            let id = deployment.id.clone();
            if deployments.insert(id.clone(), deployment).is_some() {
                return Err(platform_error(
                    PlatformErrorCode::CorruptArtifact,
                    "duplicate-persisted-deployment-id",
                    "the persisted deployment generation contains a duplicate deployment ID",
                    stable_fields([("deployment_id", id.0)]),
                ));
            }
        }
        Ok((deployments, self.snapshot.into_snapshot()?))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedDeployment {
    api_version: String,
    id: String,
    metadata: PersistedObjectMetadata,
    service: String,
    release: String,
    route_weight: u16,
    grants: Vec<PersistedCapabilityGrant>,
    resources: PersistedResourceBudget,
    availability: PersistedAvailability,
    placement: PersistedPlacement,
}

impl PersistedDeployment {
    fn from_manifest(manifest: &DeploymentManifest) -> Self {
        Self {
            api_version: manifest.api_version.clone(),
            id: manifest.id.0.clone(),
            metadata: PersistedObjectMetadata::from_metadata(&manifest.metadata),
            service: manifest.service.0.clone(),
            release: manifest.release.0.clone(),
            route_weight: manifest.route_weight,
            grants: manifest
                .grants
                .iter()
                .map(PersistedCapabilityGrant::from_grant)
                .collect(),
            resources: PersistedResourceBudget::from_budget(&manifest.resources),
            availability: PersistedAvailability::from_policy(&manifest.availability),
            placement: PersistedPlacement::from_policy(&manifest.placement),
        }
    }

    fn into_manifest(self) -> DeploymentManifest {
        DeploymentManifest {
            api_version: self.api_version,
            id: DeploymentId(self.id),
            metadata: self.metadata.into_metadata(),
            service: ServiceId(self.service),
            release: ReleaseDigest(self.release),
            route_weight: self.route_weight,
            grants: self
                .grants
                .into_iter()
                .map(PersistedCapabilityGrant::into_grant)
                .collect(),
            resources: self.resources.into_budget(),
            availability: self.availability.into_policy(),
            placement: self.placement.into_policy(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedObjectMetadata {
    name: String,
    tenant: Option<String>,
    namespace: Option<String>,
    labels: BTreeMap<String, String>,
    annotations: BTreeMap<String, String>,
}

impl PersistedObjectMetadata {
    fn from_metadata(metadata: &ObjectMetadata) -> Self {
        Self {
            name: metadata.name.clone(),
            tenant: metadata.tenant.as_ref().map(|tenant| tenant.0.clone()),
            namespace: metadata.namespace.clone(),
            labels: metadata.labels.clone(),
            annotations: metadata.annotations.clone(),
        }
    }

    fn into_metadata(self) -> ObjectMetadata {
        ObjectMetadata {
            name: self.name,
            tenant: self.tenant.map(TenantId),
            namespace: self.namespace,
            labels: self.labels,
            annotations: self.annotations,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedCapabilityGrant {
    capability: String,
    policy: String,
}

impl PersistedCapabilityGrant {
    fn from_grant(grant: &CapabilityGrantSpec) -> Self {
        Self {
            capability: grant.capability.0.clone(),
            policy: grant.policy.0.clone(),
        }
    }

    fn into_grant(self) -> CapabilityGrantSpec {
        CapabilityGrantSpec {
            capability: CapabilityId(self.capability),
            policy: PolicyId(self.policy),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedResourceBudget {
    cpu_fuel: u64,
    memory_bytes: u64,
    wall_time_limit_millis: Option<u64>,
    child_calls: u32,
    outbound_requests: u32,
    state_read_bytes: u64,
    state_write_bytes: u64,
    blob_read_bytes: u64,
    blob_write_bytes: u64,
    log_bytes: u64,
    effect_count: u32,
}

impl PersistedResourceBudget {
    fn from_budget(budget: &ResourceBudget) -> Self {
        Self {
            cpu_fuel: budget.cpu_fuel,
            memory_bytes: budget.memory_bytes,
            wall_time_limit_millis: budget.wall_time_limit_millis,
            child_calls: budget.child_calls,
            outbound_requests: budget.outbound_requests,
            state_read_bytes: budget.state_read_bytes,
            state_write_bytes: budget.state_write_bytes,
            blob_read_bytes: budget.blob_read_bytes,
            blob_write_bytes: budget.blob_write_bytes,
            log_bytes: budget.log_bytes,
            effect_count: budget.effect_count,
        }
    }

    fn into_budget(self) -> ResourceBudget {
        ResourceBudget {
            cpu_fuel: self.cpu_fuel,
            memory_bytes: self.memory_bytes,
            wall_time_limit_millis: self.wall_time_limit_millis,
            child_calls: self.child_calls,
            outbound_requests: self.outbound_requests,
            state_read_bytes: self.state_read_bytes,
            state_write_bytes: self.state_write_bytes,
            blob_read_bytes: self.blob_read_bytes,
            blob_write_bytes: self.blob_write_bytes,
            log_bytes: self.log_bytes,
            effect_count: self.effect_count,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedAvailability {
    minimum_cached_copies: u32,
    minimum_zones: u32,
}

impl PersistedAvailability {
    fn from_policy(policy: &AvailabilityPolicy) -> Self {
        Self {
            minimum_cached_copies: policy.minimum_cached_copies,
            minimum_zones: policy.minimum_zones,
        }
    }

    fn into_policy(self) -> AvailabilityPolicy {
        AvailabilityPolicy {
            minimum_cached_copies: self.minimum_cached_copies,
            minimum_zones: self.minimum_zones,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedPlacement {
    trust_class: String,
    architectures: Vec<String>,
    regions: Vec<String>,
    zones: Vec<String>,
    required_features: Vec<String>,
}

impl PersistedPlacement {
    fn from_policy(policy: &PlacementPolicy) -> Self {
        Self {
            trust_class: policy.trust_class.clone(),
            architectures: policy.architectures.clone(),
            regions: policy.regions.clone(),
            zones: policy.zones.clone(),
            required_features: policy.required_features.clone(),
        }
    }

    fn into_policy(self) -> PlacementPolicy {
        PlacementPolicy {
            trust_class: self.trust_class,
            architectures: self.architectures,
            regions: self.regions,
            zones: self.zones,
            required_features: self.required_features,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedRouteSnapshot {
    generation: u64,
    generated_at_unix_millis: u64,
    snapshot_digest: String,
    services: Vec<PersistedServiceRoute>,
    bindings: Vec<PersistedBindingRoute>,
    policy_digests: Vec<String>,
}

impl PersistedRouteSnapshot {
    fn from_snapshot(snapshot: &RouteSnapshot) -> Self {
        Self {
            generation: snapshot.generation.0,
            generated_at_unix_millis: snapshot.generated_at_unix_millis,
            snapshot_digest: snapshot.snapshot_digest.clone(),
            services: snapshot
                .services
                .iter()
                .map(PersistedServiceRoute::from_route)
                .collect(),
            bindings: snapshot
                .bindings
                .iter()
                .map(PersistedBindingRoute::from_route)
                .collect(),
            policy_digests: snapshot.policy_digests.clone(),
        }
    }

    fn into_snapshot(self) -> Result<RouteSnapshot, PlatformError> {
        Ok(RouteSnapshot {
            generation: RouteGeneration(self.generation),
            generated_at_unix_millis: self.generated_at_unix_millis,
            snapshot_digest: self.snapshot_digest,
            services: self
                .services
                .into_iter()
                .map(PersistedServiceRoute::into_route)
                .collect(),
            bindings: self
                .bindings
                .into_iter()
                .map(PersistedBindingRoute::into_route)
                .collect::<Result<Vec<_>, _>>()?,
            policy_digests: self.policy_digests,
        })
    }

    fn generation(&self) -> u64 {
        self.generation
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedServiceRoute {
    id: String,
    tenant: String,
    service: String,
    route: Option<String>,
    revisions: Vec<PersistedRevisionRoute>,
}

impl PersistedServiceRoute {
    fn from_route(route: &ServiceRoute) -> Self {
        Self {
            id: route.id.0.clone(),
            tenant: route.tenant.0.clone(),
            service: route.service.0.clone(),
            route: route.route.clone(),
            revisions: route
                .revisions
                .iter()
                .map(PersistedRevisionRoute::from_route)
                .collect(),
        }
    }

    fn into_route(self) -> ServiceRoute {
        ServiceRoute {
            id: RouteId(self.id),
            tenant: TenantId(self.tenant),
            service: ServiceId(self.service),
            route: self.route,
            revisions: self
                .revisions
                .into_iter()
                .map(PersistedRevisionRoute::into_route)
                .collect(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedRevisionRoute {
    revision: String,
    release: String,
    weight: u16,
    contracts: Vec<PersistedRouteContract>,
    attributes: BTreeMap<String, String>,
}

impl PersistedRevisionRoute {
    fn from_route(route: &RevisionRoute) -> Self {
        Self {
            revision: route.revision.0.clone(),
            release: route.release.0.clone(),
            weight: route.weight,
            contracts: route
                .contracts
                .iter()
                .map(PersistedRouteContract::from_contract)
                .collect(),
            attributes: route.attributes.clone(),
        }
    }

    fn into_route(self) -> RevisionRoute {
        RevisionRoute {
            revision: RevisionId(self.revision),
            release: ReleaseDigest(self.release),
            weight: self.weight,
            contracts: self
                .contracts
                .into_iter()
                .map(PersistedRouteContract::into_contract)
                .collect(),
            attributes: self.attributes,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedRouteContract {
    contract: String,
    functions: Vec<String>,
}

impl PersistedRouteContract {
    fn from_contract(contract: &RouteContract) -> Self {
        Self {
            contract: contract.contract.0.clone(),
            functions: contract
                .functions
                .iter()
                .map(|function| function.0.clone())
                .collect(),
        }
    }

    fn into_contract(self) -> RouteContract {
        RouteContract {
            contract: ContractId(self.contract),
            functions: self.functions.into_iter().map(FunctionId).collect(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedBindingRoute {
    id: String,
    consumer_tenant: String,
    consumer_service: String,
    imported_contract: String,
    provider_tenant: String,
    provider_service: String,
    provider_contract: String,
    mode: String,
    policy_digest: String,
}

impl PersistedBindingRoute {
    fn from_route(route: &BindingRoute) -> Self {
        Self {
            id: route.id.0.clone(),
            consumer_tenant: route.consumer_tenant.0.clone(),
            consumer_service: route.consumer_service.0.clone(),
            imported_contract: route.imported_contract.0.clone(),
            provider_tenant: route.provider_tenant.0.clone(),
            provider_service: route.provider_service.0.clone(),
            provider_contract: route.provider_contract.0.clone(),
            mode: binding_mode_name(&route.mode).to_owned(),
            policy_digest: route.policy_digest.clone(),
        }
    }

    fn into_route(self) -> Result<BindingRoute, PlatformError> {
        Ok(BindingRoute {
            id: BindingId(self.id),
            consumer_tenant: TenantId(self.consumer_tenant),
            consumer_service: ServiceId(self.consumer_service),
            imported_contract: ContractId(self.imported_contract),
            provider_tenant: TenantId(self.provider_tenant),
            provider_service: ServiceId(self.provider_service),
            provider_contract: ContractId(self.provider_contract),
            mode: parse_binding_mode(&self.mode)?,
            policy_digest: self.policy_digest,
        })
    }
}

fn binding_mode_name(mode: &BindingMode) -> &'static str {
    match mode {
        BindingMode::Host => "host",
        BindingMode::Inline => "inline",
        BindingMode::IsolatedLocal => "isolated-local",
        BindingMode::Remote => "remote",
        BindingMode::Auto => "auto",
    }
}

fn parse_binding_mode(value: &str) -> Result<BindingMode, PlatformError> {
    match value {
        "host" => Ok(BindingMode::Host),
        "inline" => Ok(BindingMode::Inline),
        "isolated-local" => Ok(BindingMode::IsolatedLocal),
        "remote" => Ok(BindingMode::Remote),
        "auto" => Ok(BindingMode::Auto),
        _ => Err(platform_error(
            PlatformErrorCode::CorruptArtifact,
            "invalid-persisted-binding-mode",
            "the persisted route generation contains an unknown binding mode",
            stable_fields([("mode", value.to_owned())]),
        )),
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CanonicalDeployment {
    api_version: String,
    id: String,
    name: String,
    tenant: Option<String>,
    namespace: Option<String>,
    labels: BTreeMap<String, String>,
    annotations: BTreeMap<String, String>,
    service: String,
    release: String,
    route_weight: u16,
    grants: Vec<(String, String)>,
    resources: PersistedResourceBudget,
    minimum_cached_copies: u32,
    minimum_zones: u32,
    trust_class: String,
    architectures: Vec<String>,
    regions: Vec<String>,
    zones: Vec<String>,
    required_features: Vec<String>,
}

pub(crate) fn canonical_deployment_bytes(
    deployment: &DeploymentManifest,
) -> Result<Vec<u8>, PlatformError> {
    let mut grants: Vec<_> = deployment
        .grants
        .iter()
        .map(|grant| (grant.capability.0.clone(), grant.policy.0.clone()))
        .collect();
    grants.sort();

    let canonical = CanonicalDeployment {
        api_version: deployment.api_version.clone(),
        id: deployment.id.0.clone(),
        name: deployment.metadata.name.clone(),
        tenant: deployment
            .metadata
            .tenant
            .as_ref()
            .map(|tenant| tenant.0.clone()),
        namespace: deployment.metadata.namespace.clone(),
        labels: deployment.metadata.labels.clone(),
        annotations: deployment.metadata.annotations.clone(),
        service: deployment.service.0.clone(),
        release: deployment.release.0.clone(),
        route_weight: deployment.route_weight,
        grants,
        resources: PersistedResourceBudget::from_budget(&deployment.resources),
        minimum_cached_copies: deployment.availability.minimum_cached_copies,
        minimum_zones: deployment.availability.minimum_zones,
        trust_class: deployment.placement.trust_class.clone(),
        architectures: sorted_unique(&deployment.placement.architectures),
        regions: sorted_unique(&deployment.placement.regions),
        zones: sorted_unique(&deployment.placement.zones),
        required_features: sorted_unique(&deployment.placement.required_features),
    };

    serde_json::to_vec(&canonical).map_err(|error| {
        platform_error(
            PlatformErrorCode::Internal,
            "canonical-deployment-encoding-failed",
            "the deployment could not be encoded for deterministic revision identity",
            stable_fields([("reason", error.to_string())]),
        )
    })
}

fn sorted_unique(values: &[String]) -> Vec<String> {
    values
        .iter()
        .cloned()
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect()
}
