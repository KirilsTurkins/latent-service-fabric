use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use latent_artifacts::ArtifactRepository;
use latent_contracts::ContractDescriptor;
use latent_core::{
    BoxFuture, ContractId, DeploymentId, FunctionId, Metadata, PlatformError, PlatformErrorCode,
    ReleaseDigest, ResourceBudget, RevisionId, RouteGeneration, RouteId, ServiceId, TenantId,
};
use latent_manifest::{DeploymentManifest, ExecutionBackendKind, StateModel};
use latent_routing::{
    BindingRoute, InvocationTarget, ResolvedBinding, ResolvedRevision, RevisionRoute,
    RouteContract, RouteSnapshot, ServiceRoute,
};

use super::model::canonical_deployment_bytes;
use super::{platform_error, stable_fields, EmbeddedCatalogOptions, ROUTE_ANNOTATION_KEY};

const NAMESPACE_ATTRIBUTE_KEY: &str = "latent.dev/namespace";

#[derive(Debug, Clone)]
pub(crate) struct ReleaseDefinition {
    pub(crate) release: ReleaseDigest,
    pub(crate) tenant: Option<TenantId>,
    pub(crate) namespace: Option<String>,
    pub(crate) service_name: String,
    pub(crate) wasm_component_backend: bool,
    pub(crate) stateless: bool,
    pub(crate) contracts: Vec<RouteContract>,
    pub(crate) resource_ceiling: ResourceBudget,
}

pub(crate) trait ReleaseInspector: Send + Sync {
    fn inspect<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<ReleaseDefinition, PlatformError>>;
}

pub(crate) struct ArtifactReleaseInspector {
    artifacts: Arc<dyn ArtifactRepository>,
}

impl ArtifactReleaseInspector {
    pub(crate) fn new(artifacts: Arc<dyn ArtifactRepository>) -> Self {
        Self { artifacts }
    }
}

impl ReleaseInspector for ArtifactReleaseInspector {
    fn inspect<'a>(
        &'a self,
        digest: &'a ReleaseDigest,
    ) -> BoxFuture<'a, Result<ReleaseDefinition, PlatformError>> {
        Box::pin(async move { inspect_artifact_release(self.artifacts.as_ref(), digest).await })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) struct RouteKey {
    tenant: TenantId,
    service: ServiceId,
    route: Option<String>,
}

impl RouteKey {
    fn from_target(target: &InvocationTarget) -> Result<Self, PlatformError> {
        Ok(Self {
            tenant: target.tenant.clone(),
            service: target.service.clone(),
            route: canonical_invocation_route(target)?,
        })
    }
}

#[derive(Debug)]
pub(crate) struct RouteIndex {
    snapshot: Arc<RouteSnapshot>,
    services: BTreeMap<RouteKey, ServiceRoute>,
}

impl RouteIndex {
    pub(crate) fn build(snapshot: Arc<RouteSnapshot>) -> Result<Self, PlatformError> {
        let expected_digest = snapshot_digest(&snapshot);
        if snapshot.snapshot_digest != expected_digest {
            return Err(platform_error(
                PlatformErrorCode::CorruptArtifact,
                "route-snapshot-digest-mismatch",
                "the route snapshot failed canonical digest verification",
                stable_fields([
                    ("generation", snapshot.generation.0.to_string()),
                    ("expected", expected_digest),
                    ("actual", snapshot.snapshot_digest.clone()),
                ]),
            ));
        }

        let mut services = BTreeMap::new();
        let mut namespaces_by_service = BTreeMap::new();
        for service in &snapshot.services {
            validate_service_route(service)?;
            let namespace = compiled_service_namespace(service)?;
            enforce_compiled_namespace_identity(
                &mut namespaces_by_service,
                &service.tenant,
                &service.service,
                namespace,
                &service.id,
            )?;

            let key = RouteKey {
                tenant: service.tenant.clone(),
                service: service.service.clone(),
                route: service.route.clone(),
            };
            if services.insert(key, service.clone()).is_some() {
                return Err(platform_error(
                    PlatformErrorCode::CorruptArtifact,
                    "duplicate-route-key",
                    "the route snapshot contains more than one service route for the same tenant-safe identity",
                    stable_fields([
                        ("tenant", service.tenant.0.clone()),
                        ("service", service.service.0.clone()),
                        ("route", display_route(service.route.as_deref())),
                    ]),
                ));
            }
        }
        Ok(Self { snapshot, services })
    }

    pub(crate) fn generation(&self) -> RouteGeneration {
        self.snapshot.generation
    }

    pub(crate) fn resolve(
        &self,
        target: &InvocationTarget,
        routing_key: Option<&str>,
    ) -> Result<ResolvedRevision, PlatformError> {
        let key = RouteKey::from_target(target)?;
        let canonical_route = key.route.clone();
        let route = self.services.get(&key).ok_or_else(|| {
            platform_error(
                PlatformErrorCode::RouteUnavailable,
                "route-not-found",
                "no complete local route exists for the requested tenant, service, and route",
                stable_fields([
                    ("tenant", target.tenant.0.clone()),
                    ("service", target.service.0.clone()),
                    ("route", display_route(canonical_route.as_deref())),
                ]),
            )
        })?;

        if !route_supports(route, &target.contract, &target.function) {
            return Err(platform_error(
                PlatformErrorCode::IncompatibleContract,
                "contract-function-mismatch",
                "the requested contract and function are not exported by the routed release set",
                stable_fields([
                    ("contract", target.contract.0.clone()),
                    ("function", target.function.0.clone()),
                    ("tenant", target.tenant.0.clone()),
                    ("service", target.service.0.clone()),
                ]),
            ));
        }

        let mut canonical_target = target.clone();
        canonical_target.route = canonical_route;
        let selected = select_revision(route, &canonical_target, routing_key)?;
        Ok(ResolvedRevision {
            target: canonical_target,
            revision: selected.revision.clone(),
            release: selected.release.clone(),
            route_generation: self.snapshot.generation,
            attributes: selected.attributes.clone(),
        })
    }

    pub(crate) fn resolve_binding(
        &self,
        consumer: &ResolvedRevision,
        imported_contract: &ContractId,
        routing_key: Option<&str>,
    ) -> Result<ResolvedBinding, PlatformError> {
        let binding = self
            .snapshot
            .bindings
            .iter()
            .find(|binding| {
                binding.consumer_tenant == consumer.target.tenant
                    && binding.consumer_service == consumer.target.service
                    && binding.imported_contract == *imported_contract
            })
            .cloned()
            .ok_or_else(|| {
                platform_error(
                    PlatformErrorCode::RouteUnavailable,
                    "binding-route-not-found",
                    "no compiled local binding exists for the requested import",
                    stable_fields([
                        ("tenant", consumer.target.tenant.0.clone()),
                        ("service", consumer.target.service.0.clone()),
                        ("contract", imported_contract.0.clone()),
                    ]),
                )
            })?;

        let provider_target = InvocationTarget {
            tenant: binding.provider_tenant.clone(),
            service: binding.provider_service.clone(),
            contract: binding.provider_contract.clone(),
            function: consumer.target.function.clone(),
            route: None,
        };
        let provider_revision = self.resolve(&provider_target, routing_key)?;
        Ok(ResolvedBinding {
            binding,
            provider_revision,
        })
    }
}

pub(crate) async fn compile_deployments(
    deployments: &BTreeMap<DeploymentId, DeploymentManifest>,
    releases: &dyn ReleaseInspector,
    previous: Option<&RouteSnapshot>,
    options: &EmbeddedCatalogOptions,
) -> Result<RouteSnapshot, PlatformError> {
    if deployments.len() > options.max_deployments {
        return Err(platform_error(
            PlatformErrorCode::ResourceExhausted,
            "deployment-count-limit",
            "the embedded deployment catalog reached its configured entry bound",
            stable_fields([
                ("count", deployments.len().to_string()),
                ("limit", options.max_deployments.to_string()),
            ]),
        ));
    }

    let generation = previous.map_or(1, |snapshot| {
        snapshot.generation.0.checked_add(1).unwrap_or(u64::MAX)
    });
    if previous.is_some_and(|snapshot| snapshot.generation.0 == u64::MAX) {
        return Err(platform_error(
            PlatformErrorCode::ResourceExhausted,
            "route-generation-exhausted",
            "the local route generation counter cannot be incremented",
            Metadata::new(),
        ));
    }

    let mut groups: BTreeMap<RouteKey, Vec<(DeploymentManifest, ReleaseDefinition)>> =
        BTreeMap::new();
    let mut namespaces_by_service = BTreeMap::new();
    for deployment in deployments.values() {
        let tenant = deployment_tenant(deployment)?;
        let route = deployment_route(deployment)?;
        validate_weight(deployment)?;

        let release = releases.inspect(&deployment.release).await?;
        validate_release(deployment, &tenant, &release)?;
        enforce_deployment_namespace_identity(
            &mut namespaces_by_service,
            &tenant,
            &deployment.service,
            deployment.metadata.namespace.clone(),
            &deployment.id,
        )?;
        groups
            .entry(RouteKey {
                tenant,
                service: deployment.service.clone(),
                route,
            })
            .or_default()
            .push((deployment.clone(), release));
    }

    let mut services = Vec::with_capacity(groups.len());
    for (key, mut group) in groups {
        group.sort_by(|left, right| left.0.id.cmp(&right.0.id));
        let total_weight: u32 = group
            .iter()
            .map(|(deployment, _)| u32::from(deployment.route_weight))
            .sum();
        if total_weight == 0 || total_weight > 10_000 {
            return Err(platform_error(
                PlatformErrorCode::InvalidArgument,
                "invalid-route-weight-total",
                "the aggregate weight for one tenant-safe route must be between 1 and 10000",
                stable_fields([
                    ("tenant", key.tenant.0.clone()),
                    ("service", key.service.0.clone()),
                    ("route", display_route(key.route.as_deref())),
                    ("total_weight", total_weight.to_string()),
                ]),
            ));
        }

        let expected_surface = group
            .first()
            .map(|(_, release)| release.contracts.clone())
            .unwrap_or_default();
        for (deployment, release) in &group {
            if release.contracts != expected_surface {
                return Err(platform_error(
                    PlatformErrorCode::IncompatibleContract,
                    "weighted-contract-surface-mismatch",
                    "all revisions participating in one weighted route must expose the same callable contract surface",
                    stable_fields([
                        ("deployment_id", deployment.id.0.clone()),
                        ("tenant", key.tenant.0.clone()),
                        ("service", key.service.0.clone()),
                    ]),
                ));
            }
        }

        let mut revisions = Vec::with_capacity(group.len());
        for (deployment, release) in group {
            let revision = deterministic_revision_id(&deployment, &release.contracts)?;
            let mut attributes = deployment.metadata.labels.clone();
            for reserved in [
                "latent.dev/deployment-id",
                "latent.dev/trust-class",
                NAMESPACE_ATTRIBUTE_KEY,
                ROUTE_ANNOTATION_KEY,
            ] {
                attributes.remove(reserved);
            }
            attributes.insert(
                "latent.dev/deployment-id".to_owned(),
                deployment.id.0.clone(),
            );
            attributes.insert(
                "latent.dev/trust-class".to_owned(),
                deployment.placement.trust_class,
            );
            if let Some(namespace) = deployment.metadata.namespace {
                attributes.insert(NAMESPACE_ATTRIBUTE_KEY.to_owned(), namespace);
            }
            if let Some(route) = key.route.as_ref() {
                attributes.insert(ROUTE_ANNOTATION_KEY.to_owned(), route.clone());
            }
            revisions.push(RevisionRoute {
                revision,
                release: release.release,
                weight: deployment.route_weight,
                contracts: release.contracts,
                attributes,
            });
        }
        revisions.sort_by(|left, right| left.revision.cmp(&right.revision));
        services.push(ServiceRoute {
            id: deterministic_route_id(&key),
            tenant: key.tenant,
            service: key.service,
            route: key.route,
            revisions,
        });
    }

    services.sort_by(|left, right| {
        (&left.tenant, &left.service, &left.route).cmp(&(
            &right.tenant,
            &right.service,
            &right.route,
        ))
    });
    let mut snapshot = RouteSnapshot {
        generation: RouteGeneration(generation),
        generated_at_unix_millis: now_unix_millis(),
        snapshot_digest: String::new(),
        services,
        bindings: Vec::new(),
        policy_digests: Vec::new(),
    };
    snapshot.snapshot_digest = snapshot_digest(&snapshot);
    Ok(snapshot)
}

pub(crate) fn empty_snapshot() -> RouteSnapshot {
    let mut snapshot = RouteSnapshot {
        generation: RouteGeneration(0),
        generated_at_unix_millis: 0,
        snapshot_digest: String::new(),
        services: Vec::new(),
        bindings: Vec::new(),
        policy_digests: Vec::new(),
    };
    snapshot.snapshot_digest = snapshot_digest(&snapshot);
    snapshot
}

pub(crate) fn snapshot_digest(snapshot: &RouteSnapshot) -> String {
    let mut hasher = blake3::Hasher::new();
    add_u64(&mut hasher, snapshot.generation.0);
    add_u64(&mut hasher, snapshot.generated_at_unix_millis);
    add_u64(&mut hasher, snapshot.services.len() as u64);
    for service in &snapshot.services {
        add_string(&mut hasher, &service.id.0);
        add_string(&mut hasher, &service.tenant.0);
        add_string(&mut hasher, &service.service.0);
        add_optional_string(&mut hasher, service.route.as_deref());
        add_u64(&mut hasher, service.revisions.len() as u64);
        for revision in &service.revisions {
            add_string(&mut hasher, &revision.revision.0);
            add_string(&mut hasher, &revision.release.0);
            add_u64(&mut hasher, u64::from(revision.weight));
            add_u64(&mut hasher, revision.contracts.len() as u64);
            for contract in &revision.contracts {
                add_string(&mut hasher, &contract.contract.0);
                add_u64(&mut hasher, contract.functions.len() as u64);
                for function in &contract.functions {
                    add_string(&mut hasher, &function.0);
                }
            }
            add_metadata(&mut hasher, &revision.attributes);
        }
    }
    add_u64(&mut hasher, snapshot.bindings.len() as u64);
    for binding in &snapshot.bindings {
        add_binding(&mut hasher, binding);
    }
    add_u64(&mut hasher, snapshot.policy_digests.len() as u64);
    for digest in &snapshot.policy_digests {
        add_string(&mut hasher, digest);
    }
    format!("blake3:{}", hasher.finalize().to_hex())
}

async fn inspect_artifact_release(
    artifacts: &dyn ArtifactRepository,
    digest: &ReleaseDigest,
) -> Result<ReleaseDefinition, PlatformError> {
    let artifact = artifacts.fetch(digest).await.map_err(|error| {
        if error.code == PlatformErrorCode::NotFound {
            missing_release(digest)
        } else {
            error
        }
    })?;

    if artifact.descriptor.release_digest != *digest
        || artifact.manifest.component_digest != *digest
    {
        return Err(platform_error(
            PlatformErrorCode::CorruptArtifact,
            "release-digest-mismatch",
            "the resolved artifact and capsule manifest do not agree with the requested release digest",
            stable_fields([("release_digest", digest.0.clone())]),
        ));
    }

    let contracts = exported_contracts(&artifact.manifest.exports, &artifact.contracts)?;
    Ok(ReleaseDefinition {
        release: digest.clone(),
        tenant: artifact.manifest.metadata.tenant.clone(),
        namespace: artifact.manifest.metadata.namespace.clone(),
        service_name: artifact.manifest.metadata.name,
        wasm_component_backend: artifact.manifest.execution.backend
            == ExecutionBackendKind::WasmComponent,
        stateless: artifact.manifest.execution.state_model == StateModel::Stateless,
        contracts,
        resource_ceiling: artifact.manifest.execution.resource_budget_ceiling,
    })
}

fn exported_contracts(
    exports: &[latent_manifest::ContractExport],
    descriptors: &[ContractDescriptor],
) -> Result<Vec<RouteContract>, PlatformError> {
    let by_id: BTreeMap<_, _> = descriptors
        .iter()
        .map(|descriptor| (descriptor.id.clone(), descriptor))
        .collect();
    let mut contracts = Vec::with_capacity(exports.len());
    for export in exports {
        let descriptor = by_id.get(&export.contract).ok_or_else(|| {
            platform_error(
                PlatformErrorCode::IncompatibleContract,
                "missing-export-contract-metadata",
                "the capsule export has no matching trusted contract descriptor",
                stable_fields([("contract", export.contract.0.clone())]),
            )
        })?;
        let mut functions = BTreeSet::new();
        for interface in &descriptor.interfaces {
            for function in &interface.functions {
                functions.insert(function.id.clone());
            }
        }
        if functions.is_empty() {
            return Err(platform_error(
                PlatformErrorCode::IncompatibleContract,
                "empty-export-contract-surface",
                "a routed exported contract must describe at least one callable function",
                stable_fields([("contract", export.contract.0.clone())]),
            ));
        }
        contracts.push(RouteContract {
            contract: export.contract.clone(),
            functions: functions.into_iter().collect(),
        });
    }
    contracts.sort_by(|left, right| left.contract.cmp(&right.contract));
    contracts.dedup_by(|left, right| left.contract == right.contract);
    if contracts.is_empty() {
        return Err(platform_error(
            PlatformErrorCode::IncompatibleContract,
            "missing-export-contracts",
            "a Phase 1 routed release must export at least one callable contract",
            Metadata::new(),
        ));
    }
    Ok(contracts)
}

fn validate_release(
    deployment: &DeploymentManifest,
    tenant: &TenantId,
    release: &ReleaseDefinition,
) -> Result<(), PlatformError> {
    if release.release != deployment.release {
        return Err(platform_error(
            PlatformErrorCode::CorruptArtifact,
            "release-digest-mismatch",
            "the release repository returned metadata for a different immutable digest",
            stable_fields([
                ("requested", deployment.release.0.clone()),
                ("resolved", release.release.0.clone()),
            ]),
        ));
    }
    if !release.wasm_component_backend {
        return Err(platform_error(
            PlatformErrorCode::InvalidArgument,
            "unsupported-execution-backend",
            "Phase 1 local routes support only the Wasmtime Component Model backend",
            stable_fields([("deployment_id", deployment.id.0.clone())]),
        ));
    }
    if !release.stateless {
        return Err(platform_error(
            PlatformErrorCode::InvalidArgument,
            "unsupported-state-model",
            "Phase 1 local routes support only stateless capsule releases",
            stable_fields([("deployment_id", deployment.id.0.clone())]),
        ));
    }
    if let Some(release_tenant) = release
        .tenant
        .as_ref()
        .filter(|release_tenant| *release_tenant != tenant)
    {
        return Err(platform_error(
            PlatformErrorCode::StateConflict,
            "tenant-scope-conflict",
            "the deployment and referenced release belong to different tenants",
            stable_fields([
                ("deployment_tenant", tenant.0.clone()),
                ("release_tenant", release_tenant.0.clone()),
            ]),
        ));
    }
    if let Some(release_namespace) = release.namespace.as_ref().filter(|release_namespace| {
        deployment.metadata.namespace.as_ref() != Some(*release_namespace)
    }) {
        return Err(platform_error(
            PlatformErrorCode::StateConflict,
            "namespace-scope-conflict",
            "a namespace-scoped release must be deployed in exactly the same namespace",
            stable_fields([
                (
                    "deployment_namespace",
                    namespace_label(deployment.metadata.namespace.as_deref()),
                ),
                ("release_namespace", release_namespace.clone()),
            ]),
        ));
    }
    if release.service_name != deployment.service.0 {
        return Err(platform_error(
            PlatformErrorCode::IncompatibleContract,
            "release-service-mismatch",
            "the referenced release metadata names a different service",
            stable_fields([
                ("deployment_service", deployment.service.0.clone()),
                ("release_service", release.service_name.clone()),
            ]),
        ));
    }
    if !budget_within(&deployment.resources, &release.resource_ceiling) {
        return Err(platform_error(
            PlatformErrorCode::InvalidArgument,
            "deployment-budget-exceeds-release",
            "the deployment resource ceiling exceeds the referenced release execution ceiling",
            stable_fields([("deployment_id", deployment.id.0.clone())]),
        ));
    }
    if release.contracts.is_empty() {
        return Err(platform_error(
            PlatformErrorCode::IncompatibleContract,
            "missing-export-contracts",
            "the referenced release has no callable exported contracts",
            stable_fields([("release_digest", release.release.0.clone())]),
        ));
    }
    Ok(())
}

fn enforce_deployment_namespace_identity(
    namespaces: &mut BTreeMap<(TenantId, ServiceId), Option<String>>,
    tenant: &TenantId,
    service: &ServiceId,
    namespace: Option<String>,
    deployment: &DeploymentId,
) -> Result<(), PlatformError> {
    let key = (tenant.clone(), service.clone());
    match namespaces.get(&key) {
        Some(existing) if existing != &namespace => {
            return Err(platform_error(
                PlatformErrorCode::StateConflict,
                "namespace-route-identity-conflict",
                "all routes for one tenant and service must belong to one explicit namespace identity",
                stable_fields([
                    ("deployment_id", deployment.0.clone()),
                    ("tenant", tenant.0.clone()),
                    ("service", service.0.clone()),
                    ("existing_namespace", namespace_label(existing.as_deref())),
                    ("deployment_namespace", namespace_label(namespace.as_deref())),
                ]),
            ));
        }
        Some(_) => {}
        None => {
            namespaces.insert(key, namespace);
        }
    }
    Ok(())
}

fn enforce_compiled_namespace_identity(
    namespaces: &mut BTreeMap<(TenantId, ServiceId), Option<String>>,
    tenant: &TenantId,
    service: &ServiceId,
    namespace: Option<String>,
    route: &RouteId,
) -> Result<(), PlatformError> {
    let key = (tenant.clone(), service.clone());
    match namespaces.get(&key) {
        Some(existing) if existing != &namespace => {
            return Err(platform_error(
                PlatformErrorCode::CorruptArtifact,
                "compiled-namespace-route-identity-conflict",
                "the route snapshot assigns one tenant and service identity to multiple namespaces",
                stable_fields([
                    ("route_id", route.0.clone()),
                    ("tenant", tenant.0.clone()),
                    ("service", service.0.clone()),
                    ("existing_namespace", namespace_label(existing.as_deref())),
                    ("route_namespace", namespace_label(namespace.as_deref())),
                ]),
            ));
        }
        Some(_) => {}
        None => {
            namespaces.insert(key, namespace);
        }
    }
    Ok(())
}

fn deployment_tenant(deployment: &DeploymentManifest) -> Result<TenantId, PlatformError> {
    deployment.metadata.tenant.clone().ok_or_else(|| {
        platform_error(
            PlatformErrorCode::InvalidArgument,
            "missing-deployment-tenant",
            "a standalone Phase 1 deployment must carry an explicit tenant scope",
            stable_fields([("deployment_id", deployment.id.0.clone())]),
        )
    })
}

fn deployment_route(deployment: &DeploymentManifest) -> Result<Option<String>, PlatformError> {
    match deployment.metadata.annotations.get(ROUTE_ANNOTATION_KEY) {
        Some(value) if value.trim().is_empty() => Err(platform_error(
            PlatformErrorCode::InvalidArgument,
            "invalid-route-name",
            "a named route annotation cannot be empty or whitespace",
            stable_fields([("deployment_id", deployment.id.0.clone())]),
        )),
        Some(value) => Ok(Some(value.trim().to_owned())),
        None => Ok(None),
    }
}

fn canonical_invocation_route(target: &InvocationTarget) -> Result<Option<String>, PlatformError> {
    match target.route.as_deref() {
        Some(value) => {
            let trimmed = value.trim();
            if trimmed.is_empty() {
                return Err(platform_error(
                    PlatformErrorCode::InvalidArgument,
                    "invalid-route-name",
                    "an invocation named route cannot be empty or whitespace",
                    stable_fields([
                        ("tenant", target.tenant.0.clone()),
                        ("service", target.service.0.clone()),
                    ]),
                ));
            }
            Ok(Some(trimmed.to_owned()))
        }
        None => Ok(None),
    }
}

fn validate_weight(deployment: &DeploymentManifest) -> Result<(), PlatformError> {
    if !(1..=10_000).contains(&deployment.route_weight) {
        return Err(platform_error(
            PlatformErrorCode::InvalidArgument,
            "invalid-route-weight",
            "a deployment route weight must be between 1 and 10000",
            stable_fields([
                ("deployment_id", deployment.id.0.clone()),
                ("weight", deployment.route_weight.to_string()),
            ]),
        ));
    }
    Ok(())
}

fn validate_service_route(route: &ServiceRoute) -> Result<(), PlatformError> {
    if route
        .route
        .as_deref()
        .is_some_and(|name| name.is_empty() || name.trim() != name)
    {
        return Err(platform_error(
            PlatformErrorCode::CorruptArtifact,
            "invalid-compiled-route-name",
            "a compiled named route must be non-empty and canonical",
            stable_fields([("route_id", route.id.0.clone())]),
        ));
    }
    if route.revisions.is_empty() {
        return Err(platform_error(
            PlatformErrorCode::CorruptArtifact,
            "empty-service-route",
            "a compiled service route must contain at least one revision",
            stable_fields([("route_id", route.id.0.clone())]),
        ));
    }
    let total: u32 = route
        .revisions
        .iter()
        .map(|revision| u32::from(revision.weight))
        .sum();
    if total == 0 || total > 10_000 || route.revisions.iter().any(|revision| revision.weight == 0) {
        return Err(platform_error(
            PlatformErrorCode::CorruptArtifact,
            "invalid-compiled-route-weights",
            "a compiled service route contains an invalid deterministic weight set",
            stable_fields([("route_id", route.id.0.clone())]),
        ));
    }
    let expected = &route.revisions[0].contracts;
    if expected.is_empty()
        || route
            .revisions
            .iter()
            .any(|revision| revision.contracts != *expected)
    {
        return Err(platform_error(
            PlatformErrorCode::CorruptArtifact,
            "invalid-compiled-contract-surface",
            "the revisions in a compiled weighted route do not share one callable contract surface",
            stable_fields([("route_id", route.id.0.clone())]),
        ));
    }
    Ok(())
}

fn compiled_service_namespace(route: &ServiceRoute) -> Result<Option<String>, PlatformError> {
    let mut namespace: Option<Option<String>> = None;
    for revision in &route.revisions {
        let candidate = revision.attributes.get(NAMESPACE_ATTRIBUTE_KEY).cloned();
        if let Some(existing) = namespace.as_ref() {
            if existing != &candidate {
                return Err(platform_error(
                    PlatformErrorCode::CorruptArtifact,
                    "mixed-compiled-route-namespaces",
                    "the revisions in one compiled route belong to different namespace identities",
                    stable_fields([("route_id", route.id.0.clone())]),
                ));
            }
        } else {
            namespace = Some(candidate);
        }
    }
    Ok(namespace.flatten())
}

fn route_supports(route: &ServiceRoute, contract: &ContractId, function: &FunctionId) -> bool {
    route.revisions.first().is_some_and(|revision| {
        revision.contracts.iter().any(|candidate| {
            candidate.contract == *contract && candidate.functions.contains(function)
        })
    })
}

fn select_revision<'a>(
    route: &'a ServiceRoute,
    target: &InvocationTarget,
    routing_key: Option<&str>,
) -> Result<&'a RevisionRoute, PlatformError> {
    let total: u64 = route
        .revisions
        .iter()
        .map(|revision| u64::from(revision.weight))
        .sum();
    if total == 0 {
        return Err(platform_error(
            PlatformErrorCode::CorruptArtifact,
            "empty-route-weight",
            "the compiled route has no selectable revision weight",
            stable_fields([("route_id", route.id.0.clone())]),
        ));
    }
    let mut hasher = blake3::Hasher::new();
    add_string(&mut hasher, &route.tenant.0);
    add_string(&mut hasher, &route.service.0);
    add_optional_string(&mut hasher, route.route.as_deref());
    add_string(&mut hasher, &target.contract.0);
    add_string(&mut hasher, &target.function.0);
    add_optional_string(&mut hasher, routing_key);
    let digest = hasher.finalize();
    let mut first_eight = [0_u8; 8];
    first_eight.copy_from_slice(&digest.as_bytes()[..8]);
    let bucket = u64::from_le_bytes(first_eight) % total;
    let mut cursor = 0_u64;
    for revision in &route.revisions {
        cursor += u64::from(revision.weight);
        if bucket < cursor {
            return Ok(revision);
        }
    }
    route.revisions.last().ok_or_else(|| {
        platform_error(
            PlatformErrorCode::CorruptArtifact,
            "empty-service-route",
            "the compiled route has no revision",
            stable_fields([("route_id", route.id.0.clone())]),
        )
    })
}

fn deterministic_revision_id(
    deployment: &DeploymentManifest,
    contracts: &[RouteContract],
) -> Result<RevisionId, PlatformError> {
    let mut hasher = blake3::Hasher::new();
    add_bytes(&mut hasher, &canonical_deployment_bytes(deployment)?);
    add_string(&mut hasher, &deployment.release.0);
    for contract in contracts {
        add_string(&mut hasher, &contract.contract.0);
        for function in &contract.functions {
            add_string(&mut hasher, &function.0);
        }
    }
    Ok(RevisionId(format!(
        "rev-blake3:{}",
        hasher.finalize().to_hex()
    )))
}

fn deterministic_route_id(key: &RouteKey) -> RouteId {
    let mut hasher = blake3::Hasher::new();
    add_string(&mut hasher, &key.tenant.0);
    add_string(&mut hasher, &key.service.0);
    add_optional_string(&mut hasher, key.route.as_deref());
    RouteId(format!("route-blake3:{}", hasher.finalize().to_hex()))
}

fn budget_within(requested: &ResourceBudget, ceiling: &ResourceBudget) -> bool {
    requested.cpu_fuel <= ceiling.cpu_fuel
        && requested.memory_bytes <= ceiling.memory_bytes
        && optional_limit_within(
            requested.wall_time_limit_millis,
            ceiling.wall_time_limit_millis,
        )
        && requested.child_calls <= ceiling.child_calls
        && requested.outbound_requests <= ceiling.outbound_requests
        && requested.state_read_bytes <= ceiling.state_read_bytes
        && requested.state_write_bytes <= ceiling.state_write_bytes
        && requested.blob_read_bytes <= ceiling.blob_read_bytes
        && requested.blob_write_bytes <= ceiling.blob_write_bytes
        && requested.log_bytes <= ceiling.log_bytes
        && requested.effect_count <= ceiling.effect_count
}

fn optional_limit_within(requested: Option<u64>, ceiling: Option<u64>) -> bool {
    match (requested, ceiling) {
        (Some(requested), Some(ceiling)) => requested <= ceiling,
        (Some(_), None) | (None, None) => true,
        (None, Some(_)) => false,
    }
}

fn missing_release(digest: &ReleaseDigest) -> PlatformError {
    platform_error(
        PlatformErrorCode::NotFound,
        "missing-release",
        "the deployment references a release that is not present in the local trusted catalog",
        stable_fields([("release_digest", digest.0.clone())]),
    )
}

fn namespace_label(namespace: Option<&str>) -> String {
    namespace.unwrap_or("unscoped").to_owned()
}

fn display_route(route: Option<&str>) -> String {
    route.unwrap_or("default").to_owned()
}

fn now_unix_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| {
            u64::try_from(duration.as_millis()).unwrap_or(u64::MAX)
        })
}

fn add_binding(hasher: &mut blake3::Hasher, binding: &BindingRoute) {
    add_string(hasher, &binding.id.0);
    add_string(hasher, &binding.consumer_tenant.0);
    add_string(hasher, &binding.consumer_service.0);
    add_string(hasher, &binding.imported_contract.0);
    add_string(hasher, &binding.provider_tenant.0);
    add_string(hasher, &binding.provider_service.0);
    add_string(hasher, &binding.provider_contract.0);
    add_string(
        hasher,
        match binding.mode {
            latent_manifest::BindingMode::Host => "host",
            latent_manifest::BindingMode::Inline => "inline",
            latent_manifest::BindingMode::IsolatedLocal => "isolated-local",
            latent_manifest::BindingMode::Remote => "remote",
            latent_manifest::BindingMode::Auto => "auto",
        },
    );
    add_string(hasher, &binding.policy_digest);
}

fn add_metadata(hasher: &mut blake3::Hasher, metadata: &Metadata) {
    add_u64(hasher, metadata.len() as u64);
    for (key, value) in metadata {
        add_string(hasher, key);
        add_string(hasher, value);
    }
}

fn add_optional_string(hasher: &mut blake3::Hasher, value: Option<&str>) {
    match value {
        Some(value) => {
            hasher.update(&[1]);
            add_string(hasher, value);
        }
        None => {
            hasher.update(&[0]);
        }
    }
}

fn add_string(hasher: &mut blake3::Hasher, value: &str) {
    add_bytes(hasher, value.as_bytes());
}

fn add_bytes(hasher: &mut blake3::Hasher, value: &[u8]) {
    add_u64(hasher, value.len() as u64);
    hasher.update(value);
}

fn add_u64(hasher: &mut blake3::Hasher, value: u64) {
    hasher.update(&value.to_le_bytes());
}
