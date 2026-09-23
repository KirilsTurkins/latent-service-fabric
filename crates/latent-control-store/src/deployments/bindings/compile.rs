use super::model::{BindingDefinition, BindingLimits, ConfiguredBindingProvider};
use super::{
    capacity, denied, error, invalid, model::StoredBinding, BindingCatalog, CompilerOwner,
};
use crate::deployments::compiler::{CompiledCatalog, RevisionRecord};
use latent_artifacts::{ArtifactRepository, ReleaseUseEligibility};
use latent_capabilities::broker::{
    CapabilityBindingSpec, InvocationBindingTarget, LOCAL_SERVICE_INVOCATION_PROFILE,
    SERVICE_INVOCATION_CAPABILITY,
};
use latent_core::{ContractId, FunctionId, Metadata, PlatformError, PlatformErrorCode};
use latent_manifest::BindingMode;
use latent_packaging::{PackageBundle, PackageComparisonLimits};
use latent_policy::capability::GrantRestriction;
use latent_routing::{InvocationTarget, ResolvedRevision};
use std::{
    collections::BTreeSet,
    sync::Arc,
    time::{Duration, Instant},
};
mod invocation;
mod web;

pub(super) async fn compile(
    catalog: &CompiledCatalog,
    data: Arc<[StoredBinding]>,
    owner: Option<Arc<CompilerOwner>>,
    artifacts: &dyn ArtifactRepository,
    strict: bool,
) -> Result<BindingCatalog, PlatformError> {
    let limits = owner
        .as_ref()
        .map_or_else(BindingLimits::default, |owner| owner.limits);
    let definitions = definitions(&data, limits)?;
    let Some(owner) = owner else {
        return Ok(BindingCatalog {
            data,
            owner: None,
            plans: Box::new([]),
            unavailable: catalog.records.len(),
        });
    };
    if catalog.records.len() > limits.maximum_deployments {
        return Err(capacity());
    }
    invocation::configured_graph(catalog, &definitions, &owner)?;
    let order_bytes = catalog
        .records
        .len()
        .checked_mul(std::mem::size_of::<&RevisionRecord>())
        .ok_or_else(capacity)?;
    if owner.retained_bytes()
        + order_bytes
        + data
            .iter()
            .map(StoredBinding::retained_bytes)
            .sum::<usize>()
        > limits.maximum_metadata_bytes
    {
        return Err(capacity());
    }
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(30))
        .ok_or_else(capacity)?;
    let mut plans = Vec::with_capacity(catalog.records.len());
    let mut unavailable = 0;
    // One transient consumer package, not one retained package per deployment.
    // Each plan still checks live eligibility and its own scoped grants. Sorting
    // the bounded pointer list groups only identical tenant/publication/source
    // identities; no cache or authority survives this compilation.
    let mut order = Vec::new();
    order
        .try_reserve_exact(catalog.records.len())
        .map_err(|_| capacity())?;
    order.extend(catalog.records.iter().map(Arc::as_ref));
    order.sort_unstable_by(|left, right| package_key(left).cmp(&package_key(right)));
    let mut consumer = None;
    for record in order {
        if matches!(
            catalog.selected_eligibility(&record.deployment.release, record.publication.as_ref()),
            Some(crate::deployments::admission_fence::SelectedEligibility::Inactive(_))
        ) {
            unavailable += 1;
            continue;
        }
        let result = plan(
            catalog,
            record,
            &definitions,
            &owner,
            artifacts,
            deadline,
            &mut consumer,
        )
        .await;
        match result {
            Ok(plan) => plans.push(plan),
            Err(failure)
                if !strict
                    && matches!(
                        failure.code,
                        PlatformErrorCode::PermissionDenied
                            | PlatformErrorCode::NotFound
                            | PlatformErrorCode::IncompatibleContract
                            | PlatformErrorCode::RouteUnavailable
                            | PlatformErrorCode::InvalidArgument
                    ) =>
            {
                unavailable += 1;
            }
            Err(failure) => return Err(failure),
        }
    }
    Ok(BindingCatalog {
        data,
        owner: Some(owner),
        plans: plans.into_boxed_slice(),
        unavailable,
    })
}

fn package_key(
    record: &RevisionRecord,
) -> (
    &Option<latent_core::TenantId>,
    &Option<latent_core::PublicationId>,
    &latent_core::ReleaseDigest,
) {
    (
        &record.deployment.metadata.tenant,
        &record.publication,
        &record.deployment.release,
    )
}

#[cfg(test)]
thread_local! {
    pub(in crate::deployments) static PACKAGE_READS: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}
fn definitions(
    data: &[StoredBinding],
    limits: BindingLimits,
) -> Result<Vec<BindingDefinition>, PlatformError> {
    if data.len() > limits.maximum_definitions {
        return Err(capacity());
    }
    let mut bytes = 0usize;
    let mut definitions = Vec::with_capacity(data.len());
    let mut names = BTreeSet::new();
    let mut imports = BTreeSet::new();
    for value in data {
        bytes = bytes
            .checked_add(value.retained_bytes())
            .ok_or_else(capacity)?;
        if bytes > limits.maximum_metadata_bytes {
            return Err(capacity());
        }
        let value = value.decode(limits)?;
        let m = &value.manifest;
        if !names.insert((m.metadata.tenant.clone(), m.id.clone()))
            || !imports.insert((
                m.metadata.tenant.clone(),
                m.consumer.service.clone(),
                m.consumer.route.clone(),
                m.consumer.contract.clone(),
            ))
        {
            return Err(invalid());
        }
        definitions.push(value);
    }
    graph(&definitions, limits.maximum_graph_depth)?;
    Ok(definitions)
}
fn graph(definitions: &[BindingDefinition], limit: usize) -> Result<(), PlatformError> {
    // Auto includes every allowed local edge. A later installation cannot turn
    // a previously accepted graph into an unexamined capacity cycle.
    fn walk<'a>(
        defs: &'a [BindingDefinition],
        tenant: Option<&latent_core::TenantId>,
        service: &'a latent_core::ServiceId,
        path: &mut Vec<&'a latent_core::ServiceId>,
        limit: usize,
        work: &mut usize,
    ) -> Result<(), PlatformError> {
        if path.contains(&service) || path.len() >= limit {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "binding-cycle-or-depth",
            ));
        }
        path.push(service);
        for d in defs {
            *work = work.checked_add(1).ok_or_else(capacity)?;
            if *work > 131_072 {
                return Err(capacity());
            }
            if d.manifest.metadata.tenant.as_ref() == tenant
                && &d.manifest.consumer.service == service
                && d.allowed_modes.contains(&BindingMode::IsolatedLocal)
                && d.manifest.consumer.contract.0 != SERVICE_INVOCATION_CAPABILITY
                && matches!(
                    d.manifest.mode,
                    BindingMode::Auto | BindingMode::IsolatedLocal
                )
            {
                walk(
                    defs,
                    tenant,
                    &d.manifest.provider.service,
                    path,
                    limit,
                    work,
                )?;
            }
        }
        path.pop();
        Ok(())
    }
    let mut work = 0;
    for d in definitions {
        walk(
            definitions,
            d.manifest.metadata.tenant.as_ref(),
            &d.manifest.consumer.service,
            &mut Vec::new(),
            limit,
            &mut work,
        )?;
    }
    Ok(())
}
fn selected<'a>(
    d: &BindingDefinition,
    owner: &'a CompilerOwner,
) -> Result<&'a ConfiguredBindingProvider, PlatformError> {
    let m = &d.manifest;
    let mut matches = owner.providers.iter().filter(|p| {
        Some(&p.tenant) == m.metadata.tenant.as_ref()
            && p.service == m.provider.service
            && (p.reference.capability() == m.provider.contract.0
                || (m.consumer.contract.0 == SERVICE_INVOCATION_CAPABILITY
                    && p.reference.capability() == SERVICE_INVOCATION_CAPABILITY
                    && p.reference.profile() == LOCAL_SERVICE_INVOCATION_PROFILE
                    && p.local_deployment.is_some()))
            && d.allowed_modes.contains(&p.mode())
            && (m.mode == BindingMode::Auto || m.mode == p.mode())
            && m.provider
                .route
                .as_ref()
                .is_none_or(|r| p.local_deployment.as_ref().is_some_and(|id| &id.0 == r))
    });
    let provider = matches.next().ok_or_else(denied)?;
    if matches.next().is_some() {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "binding-provider-ambiguous",
        ));
    }
    Ok(provider)
}
async fn bundle(
    record: &RevisionRecord,
    owner: &CompilerOwner,
    artifacts: &dyn ArtifactRepository,
) -> Result<PackageBundle, PlatformError> {
    #[cfg(test)]
    PACKAGE_READS.with(|reads| reads.set(reads.get() + 1));
    let tenant = record
        .deployment
        .metadata
        .tenant
        .as_ref()
        .ok_or_else(denied)?;
    let publication = record.publication.as_ref().ok_or_else(denied)?;
    let source = artifacts
        .retained_package_source_selected(
            tenant,
            &record.deployment.release,
            Some(publication),
            owner.limits.maximum_package_bytes,
        )
        .await?
        .ok_or_else(denied)?;
    if source.tenant() != tenant
        || source.publication() != publication
        || source.component() != &record.deployment.release
        || source.retained_bytes() > owner.limits.maximum_package_bytes
    {
        return Err(denied());
    }
    let package = source.package().clone();
    let (manifest, configuration, layers) = source.into_parts();
    let bundle = latent_packaging::inspect_bundle(
        latent_packaging::BundleInput {
            manifest,
            configuration,
            layers,
        },
        latent_packaging::PackagingLimits::default(),
    )?;
    if bundle.layout().digest() != &package
        || bundle
            .surface()
            .is_none_or(|s| s.component_digest().as_str() != record.deployment.release.0)
    {
        return Err(denied());
    }
    Ok(bundle)
}
fn eligibility(
    catalog: &CompiledCatalog,
    record: &RevisionRecord,
) -> Result<ReleaseUseEligibility, PlatformError> {
    let value = catalog
        .eligibility_for(&record.deployment.release, record.publication.as_ref())
        .ok_or_else(denied)?;
    value.authorize_tenant(
        record
            .deployment
            .metadata
            .tenant
            .as_ref()
            .ok_or_else(denied)?,
    )?;
    value.check_current()?;
    Ok(value.clone())
}
pub(super) fn revision(
    record: &RevisionRecord,
    generation: latent_core::RouteGeneration,
) -> ResolvedRevision {
    ResolvedRevision {
        target: InvocationTarget {
            tenant: record
                .deployment
                .metadata
                .tenant
                .clone()
                .expect("validated tenant"),
            service: record.deployment.service.clone(),
            contract: ContractId(String::new()),
            function: FunctionId(String::new()),
            route: None,
        },
        revision: record.revision.clone(),
        release: record.deployment.release.clone(),
        publication: record.publication.clone(),
        route_generation: generation,
        attributes: Metadata::new(),
    }
}
struct Import<'a> {
    definition_digest: latent_core::ArtifactBlobDigest,
    definition: &'a BindingDefinition,
    provider: &'a ConfiguredBindingProvider,
    operations: Vec<String>,
    policies: Vec<String>,
    restriction: Vec<u8>,
}
async fn plan<'a>(
    catalog: &CompiledCatalog,
    record: &'a RevisionRecord,
    definitions: &[BindingDefinition],
    owner: &Arc<CompilerOwner>,
    artifacts: &dyn ArtifactRepository,
    deadline: Instant,
    cached: &mut Option<(&'a RevisionRecord, PackageBundle)>,
) -> Result<Arc<latent_capabilities::broker::CompiledCapabilityPlan>, PlatformError> {
    if Instant::now() >= deadline {
        return Err(error(
            PlatformErrorCode::DeadlineExceeded,
            "binding-compile-deadline",
        ));
    }
    let publication = eligibility(catalog, record)?;
    if publication.web_projection().is_some() {
        return web::compile(catalog, record, definitions, owner, &publication, deadline);
    }
    let comparison = PackageComparisonLimits::default();
    if cached
        .as_ref()
        .is_none_or(|(previous, _)| package_key(previous) != package_key(record))
    {
        // Drop the preceding package before reading another bounded package.
        *cached = None;
        *cached = Some((record, bundle(record, owner, artifacts).await?));
    }
    let consumer = &cached.as_ref().expect("current checked consumer package").1;
    let surface = consumer.surface().ok_or_else(denied)?;
    let mut imports = Vec::new();
    let mut dependencies = Vec::new();
    let mut local = Vec::new();
    let mut local_targets = Vec::new();
    let mut invocation_targets = Vec::new();
    for interface in surface.imports() {
        let d = definition(record, definitions, interface)?;
        let provider = selected(d, owner)?;
        let is_invocation = interface.as_ref() == SERVICE_INVOCATION_CAPABILITY
            && provider.reference.profile() == LOCAL_SERVICE_INVOCATION_PROFILE;
        let proof = if let Some(id) = &provider.local_deployment {
            let target = catalog.record_by_id(id).ok_or_else(denied)?;
            if (!is_invocation
                && target.deployment.metadata.tenant != record.deployment.metadata.tenant)
                || target.deployment.service != provider.service
            {
                return Err(denied());
            }
            dependencies.push(eligibility(catalog, target)?);
            let provider_bundle = bundle(target, owner, artifacts).await?;
            local.push(super::source::LocalTarget::new(target));
            let mut resolved = revision(target, catalog.generation);
            resolved.target.contract = d.manifest.provider.contract.clone();
            resolved.target.route = Some(target.deployment.id.0.clone());
            if is_invocation {
                let target_proof = latent_packaging::check_invocation_target(
                    &provider_bundle,
                    &d.manifest.provider.contract.0,
                    comparison,
                )?;
                invocation_targets.push(InvocationBindingTarget::new(
                    resolved,
                    target_proof.functions(),
                )?);
                latent_packaging::compile_host_binding(consumer, interface, comparison)?
            } else {
                local_targets.push(resolved);
                latent_packaging::compile_local_binding(
                    consumer,
                    &provider_bundle,
                    interface,
                    &d.manifest.provider.contract.0,
                    comparison,
                )?
            }
        } else {
            latent_packaging::compile_host_binding(consumer, interface, comparison)?
        };
        let (policies, restriction) = grant(record, d, interface)?;
        imports.push(Import {
            definition_digest: definition_digest(d)?,
            definition: d,
            provider,
            operations: proof.operations().to_vec(),
            policies,
            restriction,
        });
    }
    let specs: Vec<_> = imports
        .iter()
        .map(|i| CapabilityBindingSpec {
            definition_digest: Some(&i.definition_digest),
            provider: &i.provider.reference,
            imported_operations: &i.operations,
            policy_ids: &i.policies,
            provider_binding_id: &i.definition.provider_binding_id,
            deployment_restriction_json: &i.restriction,
        })
        .collect();
    let fence = (!local.is_empty()).then(|| {
        Arc::new(super::source::LocalFence {
            current: owner.current.clone(),
            targets: local.into_boxed_slice(),
        }) as Arc<dyn latent_capabilities::broker::CapabilityRouteFence>
    });
    owner.broker.compile_invocation_plan(
        &revision(record, catalog.generation),
        Some(&record.deployment.id),
        &specs,
        &publication,
        &dependencies,
        &local_targets,
        &invocation_targets,
        fence,
        deadline,
    )
}

fn definition_digest(
    definition: &BindingDefinition,
) -> Result<latent_core::ArtifactBlobDigest, PlatformError> {
    use latent_manifest::{JsonManifestCodec, ManifestCodec};
    let manifest = JsonManifestCodec::default()
        .encode_binding(&definition.manifest)
        .map_err(|_| invalid())?;
    let bytes = latent_manifest::__serde_json::to_vec(&(
        "lsf-capability-binding-definition-v1",
        manifest,
        &definition.provider_binding_id,
        &definition.allowed_modes,
        &definition.restriction_json,
    ))
    .map_err(|_| invalid())?;
    Ok(latent_artifacts::package::artifact_blob_digest(&bytes))
}

fn grant(
    record: &RevisionRecord,
    d: &BindingDefinition,
    interface: &str,
) -> Result<(Vec<String>, Vec<u8>), PlatformError> {
    let mut grants = record
        .deployment
        .grants
        .iter()
        .filter(|g| g.capability.0 == interface);
    let grant = grants.next().ok_or_else(denied)?;
    if grants.next().is_some() || !grant.constraints.is_empty() {
        return Err(invalid());
    }
    let mut restriction = GrantRestriction::parse(&d.restriction_json, interface)?;
    // Empty input lists inherit scope. An empty intersection is denial, not
    // the language's empty-list inheritance spelling.
    if !grant.operations.is_empty() {
        if restriction.operations.is_empty() {
            restriction.operations.clone_from(&grant.operations);
        } else {
            restriction
                .operations
                .retain(|op| grant.operations.contains(op));
        }
        if restriction.operations.is_empty() {
            return Err(denied());
        }
    }
    restriction.validate(interface)?;
    Ok((
        vec![grant.policy.0.clone()],
        restriction.canonical_bytes(interface)?,
    ))
}

#[cfg(test)]
mod tests;

fn definition<'a>(
    record: &RevisionRecord,
    definitions: &'a [BindingDefinition],
    interface: &str,
) -> Result<&'a BindingDefinition, PlatformError> {
    let mut matches = definitions.iter().filter(|d| {
        let m = &d.manifest;
        m.metadata.tenant == record.deployment.metadata.tenant
            && m.consumer.service == record.deployment.service
            && m.consumer.contract.0 == interface
            && m.consumer
                .route
                .as_ref()
                .is_none_or(|r| r == &record.deployment.id.0)
    });
    let d = matches.next().ok_or_else(denied)?;
    if matches.next().is_some() {
        return Err(invalid());
    }
    Ok(d)
}
