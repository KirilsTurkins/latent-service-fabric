use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use latent_artifacts::{
    content_digest, ArtifactRepository, ContractDescriptor, FieldDescriptor, ValueType,
};
use latent_core::{
    DeploymentId, Metadata, PlatformError, PlatformErrorCode, RouteGeneration, RouteId,
};
use latent_manifest::{
    __serde_json as json, DeploymentManifest, JsonManifestCodec, ManifestCodec, ManifestValidator,
    Phase1ManifestValidator,
};
use latent_routing::{InvocationTarget, ResolvedRevision, RevisionRoute, RouteSnapshot, ServiceRoute};

use super::{deployment_revision_id, error, manifest_error, DirectoryDeploymentRepositoryConfig};

type RouteKey = (String, String, String);
type EndpointKey = (RouteKey, String, String);

struct WeightedSet {
    total: u64,
    revisions: Vec<(u64, Arc<RevisionRoute>)>,
}

pub(super) struct CompiledCatalog {
    pub deployments: BTreeMap<DeploymentId, DeploymentManifest>,
    pub snapshot: RouteSnapshot,
    routes: BTreeSet<RouteKey>,
    endpoints: BTreeMap<EndpointKey, WeightedSet>,
}

impl CompiledCatalog {
    pub(super) fn resolve(
        &self,
        target: &InvocationTarget,
        routing_key: Option<&str>,
        config: DirectoryDeploymentRepositoryConfig,
    ) -> Result<ResolvedRevision, PlatformError> {
        let route = target.route.as_deref().unwrap_or("default");
        let key = routing_key.unwrap_or("");
        let identifiers = [&target.tenant.0, &target.service.0, &target.contract.0, &target.function.0];
        if identifiers.iter().any(|id| id.is_empty() || id.len() > config.max_identifier_bytes || id.chars().any(char::is_control))
            || route.is_empty()
            || route.len() > config.max_identifier_bytes
            || route.chars().any(char::is_control)
            || key.len() > config.max_routing_key_bytes
        {
            return Err(error(PlatformErrorCode::InvalidArgument, "invalid-invocation-target"));
        }
        let route_key = (target.tenant.0.clone(), target.service.0.clone(), route.to_owned());
        if !self.routes.contains(&route_key) {
            return Err(error(PlatformErrorCode::RouteUnavailable, "route-not-found"));
        }
        let endpoint_key = (route_key, target.contract.0.clone(), target.function.0.clone());
        let candidates = self.endpoints.get(&endpoint_key).ok_or_else(|| {
            error(PlatformErrorCode::IncompatibleContract, "contract-or-function-not-exported")
        })?;
        let mut framed = b"lsf-route-selection-v1\0".to_vec();
        for part in [target.tenant.0.as_str(), target.service.0.as_str(), route, target.contract.0.as_str(), target.function.0.as_str(), key] {
            framed.extend_from_slice(&(part.len() as u64).to_be_bytes());
            framed.extend_from_slice(part.as_bytes());
        }
        let digest = content_digest(&framed);
        let hash = u64::from_str_radix(&digest.0[7..23], 16)
            .expect("content_digest returns canonical SHA-256 hexadecimal");
        let bucket = hash % candidates.total;
        let index = candidates.revisions.partition_point(|(end, _)| *end <= bucket);
        let revision = &candidates.revisions[index].1;
        Ok(ResolvedRevision {
            target: target.clone(),
            revision: revision.revision.clone(),
            release: revision.release.clone(),
            route_generation: self.snapshot.generation,
            attributes: revision.attributes.clone(),
        })
    }
}

pub(super) async fn compile(
    deployments: BTreeMap<DeploymentId, DeploymentManifest>,
    generation: RouteGeneration,
    generated_at_unix_millis: u64,
    artifacts: &dyn ArtifactRepository,
    config: DirectoryDeploymentRepositoryConfig,
) -> Result<CompiledCatalog, PlatformError> {
    if deployments.len() > config.max_deployments {
        return Err(error(PlatformErrorCode::ResourceExhausted, "deployment-count-limit"));
    }
    let codec = JsonManifestCodec::default();
    let mut releases = BTreeMap::new();
    let mut scopes = BTreeMap::new();
    let mut contracts = BTreeMap::new();
    let mut services: BTreeMap<RouteKey, ServiceRoute> = BTreeMap::new();
    let mut endpoints: BTreeMap<EndpointKey, Vec<Arc<RevisionRoute>>> = BTreeMap::new();
    let mut route_entries = 0_usize;
    let mut policy_digests = BTreeSet::new();

    for deployment in deployments.values() {
        Phase1ManifestValidator.validate_deployment(deployment).map_err(manifest_error)?;
        if deployment.id.0 == "default" {
            return Err(error(PlatformErrorCode::AlreadyExists, "reserved-default-route"));
        }
        let tenant = deployment.metadata.tenant.as_ref().ok_or_else(|| {
            error(PlatformErrorCode::InvalidArgument, "missing-tenant")
        })?;
        let scope_key = (tenant.clone(), deployment.service.clone());
        if let Some(namespace) = scopes.insert(scope_key.clone(), deployment.metadata.namespace.clone()) {
            if namespace != deployment.metadata.namespace {
                return Err(error(PlatformErrorCode::PermissionDenied, "namespace-route-conflict"));
            }
        }
        if !releases.contains_key(&deployment.release) {
            let mut artifact = artifacts.fetch(&deployment.release).await?;
            if !artifact.descriptor.release_digest.0.eq_ignore_ascii_case(&deployment.release.0)
                || !artifact.manifest.component_digest.0.eq_ignore_ascii_case(&deployment.release.0)
            {
                return Err(error(PlatformErrorCode::CorruptArtifact, "release-digest-mismatch"));
            }
            // Never retain component bytes in the route catalog, or prepare/instantiate them.
            drop(std::mem::take(&mut artifact.component_bytes));
            releases.insert(deployment.release.clone(), artifact);
        }
        let artifact = &releases[&deployment.release];
        Phase1ManifestValidator.validate_deployment_against_capsule(deployment, &artifact.manifest)
            .map_err(manifest_error)?;
        let mut descriptors = BTreeMap::new();
        for descriptor in &artifact.contracts {
            if descriptors.insert(&descriptor.id, descriptor).is_some() {
                return Err(error(PlatformErrorCode::AlreadyExists, "duplicate-contract-id"));
            }
        }
        let mut callable = BTreeSet::new();
        let mut exported = BTreeMap::new();
        for export in &artifact.manifest.exports {
            let descriptor = descriptors.get(&export.contract).ok_or_else(|| {
                error(PlatformErrorCode::IncompatibleContract, "missing-export-contract-metadata")
            })?;
            let contract_key = (scope_key.clone(), export.contract.clone());
            let canonical = contract_value(descriptor);
            if let Some(previous) = contracts.insert(contract_key, canonical.clone()) {
                if previous != canonical {
                    return Err(error(PlatformErrorCode::IncompatibleContract, "conflicting-contract-metadata"));
                }
            }
            let mut interface_ids = BTreeSet::new();
            let mut functions = BTreeSet::new();
            for interface in &descriptor.interfaces {
                if !interface_ids.insert(&interface.id) {
                    return Err(error(PlatformErrorCode::AlreadyExists, "duplicate-interface-id"));
                }
                for function in &interface.functions {
                    if function.id.0.is_empty() || function.id.0.len() > config.max_identifier_bytes {
                        return Err(error(PlatformErrorCode::IncompatibleContract, "invalid-function-id"));
                    }
                    if !functions.insert(function.id.0.clone()) {
                        return Err(error(PlatformErrorCode::AlreadyExists, "duplicate-function-id"));
                    }
                    callable.insert((export.contract.0.clone(), function.id.0.clone()));
                }
            }
            if functions.is_empty() {
                return Err(error(PlatformErrorCode::IncompatibleContract, "export-has-no-functions"));
            }
            let bytes = json::to_vec(&canonical).map_err(|_| {
                error(PlatformErrorCode::Internal, "contract-encoding-failed")
            })?;
            exported.insert(export.contract.0.clone(), json::json!({
                "schema": content_digest(&bytes).0,
                "functions": functions,
            }));
        }
        let encoded = codec.encode_deployment(deployment).map_err(manifest_error)?;
        let deployment_json = String::from_utf8(encoded).map_err(|_| {
            error(PlatformErrorCode::Internal, "deployment-encoding-failed")
        })?;
        let exports_json = json::to_string(&exported).map_err(|_| {
            error(PlatformErrorCode::Internal, "contract-encoding-failed")
        })?;
        let revision = Arc::new(RevisionRoute {
            revision: deployment_revision_id(deployment)?,
            release: deployment.release.clone(),
            weight: deployment.route_weight,
            attributes: Metadata::from([
                ("lsf.deployment".to_owned(), deployment_json),
                ("lsf.exports".to_owned(), exports_json),
            ]),
        });
        for grant in &deployment.grants {
            // References, not evaluated policy digests: kept inside the pinned deployment only.
            let _ = grant;
        }
        for route in ["default", deployment.id.0.as_str()] {
            let route_key = (tenant.0.clone(), deployment.service.0.clone(), route.to_owned());
            services.entry(route_key.clone()).or_insert_with(|| ServiceRoute {
                id: RouteId(route.to_owned()),
                tenant: tenant.clone(),
                service: deployment.service.clone(),
                revisions: Vec::new(),
            }).revisions.push((*revision).clone());
            for (contract, function) in &callable {
                route_entries = route_entries.checked_add(1).ok_or_else(|| {
                    error(PlatformErrorCode::ResourceExhausted, "route-index-limit")
                })?;
                if route_entries > config.max_route_entries {
                    return Err(error(PlatformErrorCode::ResourceExhausted, "route-index-limit"));
                }
                endpoints.entry((route_key.clone(), contract.clone(), function.clone()))
                    .or_default().push(Arc::clone(&revision));
            }
        }
    }
    let routes = services.keys().cloned().collect();
    let services = services.into_values().map(|mut service| {
        service.revisions.sort_by(|left, right| left.revision.cmp(&right.revision));
        service
    }).collect();
    let mut weighted = BTreeMap::new();
    for (key, mut revisions) in endpoints {
        revisions.sort_by(|left, right| left.revision.cmp(&right.revision));
        let mut total = 0_u64;
        let mut cumulative = Vec::with_capacity(revisions.len());
        for revision in revisions {
            total = total.checked_add(u64::from(revision.weight)).ok_or_else(|| {
                error(PlatformErrorCode::ResourceExhausted, "route-weight-overflow")
            })?;
            cumulative.push((total, revision));
        }
        weighted.insert(key, WeightedSet { total, revisions: cumulative });
    }
    // Binding/policy evaluation is intentionally outside this deployment-only compiler.
    policy_digests.clear();
    let catalog = CompiledCatalog {
        deployments,
        snapshot: RouteSnapshot {
            generation,
            generated_at_unix_millis,
            services,
            bindings: Vec::new(),
            policy_digests: policy_digests.into_iter().collect(),
        },
        routes,
        endpoints: weighted,
    };
    // Bound persisted snapshots (and their duplicated metadata) before publication.
    super::persistence::encode(&catalog, config)?;
    Ok(catalog)
}

fn contract_value(contract: &ContractDescriptor) -> json::Value {
    let mut interfaces = contract.interfaces.iter().map(|interface| {
        let mut functions = interface.functions.iter().map(|function| json::json!({
            "id": function.id.0,
            "name": function.name,
            "asynchronous": function.asynchronous,
            "parameters": function.parameters.iter().map(field_value).collect::<Vec<_>>(),
            "results": function.results.iter().map(field_value).collect::<Vec<_>>(),
            "documentation": function.documentation,
            "attributes": function.attributes,
        })).collect::<Vec<_>>();
        functions.sort_by(|left, right| left["id"].as_str().cmp(&right["id"].as_str()));
        json::json!({
            "id": interface.id.0,
            "digest": interface.digest,
            "documentation": interface.documentation,
            "functions": functions,
        })
    }).collect::<Vec<_>>();
    interfaces.sort_by(|left, right| left["id"].as_str().cmp(&right["id"].as_str()));
    let mut dependencies = contract.dependencies.iter().map(|id| id.0.as_str()).collect::<Vec<_>>();
    dependencies.sort_unstable();
    json::json!({
        "id": contract.id.0,
        "package": contract.package_name,
        "version": contract.semantic_version,
        "digest": contract.digest,
        "dependencies": dependencies,
        "interfaces": interfaces,
    })
}

fn field_value(field: &FieldDescriptor) -> json::Value {
    json::json!({
        "name": field.name,
        "type": type_value(&field.value_type),
        "documentation": field.documentation,
    })
}

fn type_value(value: &ValueType) -> json::Value {
    use ValueType::{List, Option, Result, Tuple};
    match value {
        List(inner) => json::json!(["list", type_value(inner)]),
        Option(inner) => json::json!(["option", type_value(inner)]),
        Result { ok, error } => json::json!([
            "result", ok.as_deref().map(type_value), error.as_deref().map(type_value),
        ]),
        Tuple(values) => json::json!(["tuple", values.iter().map(type_value).collect::<Vec<_>>()]),
        ValueType::Record(name) => json::json!(["record", name]),
        ValueType::Variant(name) => json::json!(["variant", name]),
        ValueType::Resource(name) => json::json!(["resource", name]),
        ValueType::Future(inner) => json::json!(["future", type_value(inner)]),
        ValueType::Stream(inner) => json::json!(["stream", type_value(inner)]),
        ValueType::Bool => json::json!("bool"),
        ValueType::U8 => json::json!("u8"),
        ValueType::U16 => json::json!("u16"),
        ValueType::U32 => json::json!("u32"),
        ValueType::U64 => json::json!("u64"),
        ValueType::S8 => json::json!("s8"),
        ValueType::S16 => json::json!("s16"),
        ValueType::S32 => json::json!("s32"),
        ValueType::S64 => json::json!("s64"),
        ValueType::F32 => json::json!("f32"),
        ValueType::F64 => json::json!("f64"),
        ValueType::Char => json::json!("char"),
        ValueType::String => json::json!("string"),
        ValueType::Bytes => json::json!("bytes"),
    }
}
