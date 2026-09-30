//! One bounded read on the existing catalog/preparation owners. No synthetic
//! invocation, provider call, trigger write, or new resident inspection worker.
use super::{
    bounds, errors, identifier, proto, ManagementOperation, ManagementServiceAdapter, RequestBudget,
};
use latent_artifacts::{LifecycleScope, PublicationRef};
use latent_control_store::target_inspection as domain;
use latent_core::{ContractId, FunctionId, PlatformError, PlatformErrorCode, ServiceId, TenantId};
use latent_executor::PreparationInspection;
use latent_routing::InvocationTarget;
use prost::Message;
use std::time::{Duration, Instant};
use tonic::{Request, Response, Status};

const MAXIMUM_REQUEST_BYTES: usize = 8 * 1024;
const MAXIMUM_WAIT_MILLIS: u64 = 30_000;

pub(super) async fn inspect(
    adapter: &ManagementServiceAdapter,
    mut request: Request<proto::InspectHttpTargetRequest>,
) -> Result<Response<proto::InspectHttpTargetResponse>, Status> {
    let expires = deadline(&request)?;
    let principal = adapter.authenticate(&mut request, ManagementOperation::Tenant)?;
    let tenant = crate::invocation::authenticated_tenant(&principal, &adapter.limits.auth)
        .map_err(|failure| errors::platform_status(failure, &adapter.limits))?;
    let mut limits = adapter.limits.clone();
    limits.max_request_bytes = limits.max_request_bytes.min(MAXIMUM_REQUEST_BYTES);
    limits.max_response_bytes = limits.max_response_bytes.min(domain::MAXIMUM_BYTES);
    let mut budget = RequestBudget::new::<proto::InspectHttpTargetRequest>(&limits)?;
    let query = request.get_ref();
    for text in [&query.service, &query.contract, &query.function]
        .into_iter()
        .chain(
            [&query.route, &query.revision_id, &query.routing_key]
                .into_iter()
                .flatten(),
        )
    {
        budget.string(text, domain::MAXIMUM_ID_BYTES)?;
        identifier(text, domain::MAXIMUM_ID_BYTES)?;
    }
    let publication = query
        .publication
        .as_ref()
        .map(|value| {
            budget.allocation::<proto::PublicationRef>(1)?;
            budget.string(&value.id, latent_core::PublicationId::TEXT_BYTES)?;
            budget.string(&value.tenant, domain::MAXIMUM_ID_BYTES)?;
            if value.tenant != tenant.0 {
                return Err(Status::invalid_argument(
                    "target publication tenant mismatch",
                ));
            }
            value
                .id
                .parse()
                .map_err(|_| Status::invalid_argument("invalid target publication"))
        })
        .transpose()?;
    if query.encoded_len() > limits.max_request_bytes {
        return Err(bounds::exhausted());
    }
    let repository = adapter
        .http
        .as_ref()
        .ok_or_else(|| Status::unimplemented("target inspection unavailable"))?;
    let policy_before = policy_generation(adapter)?;
    let observed = repository
        .inspect_target(domain::TargetInspectionRequest {
            target: InvocationTarget {
                tenant: tenant.clone(),
                service: ServiceId(query.service.clone()),
                contract: ContractId(query.contract.clone()),
                function: FunctionId(query.function.clone()),
                route: query.route.clone(),
            },
            revision: query
                .revision_id
                .as_ref()
                .map(|id| latent_core::RevisionId(id.clone())),
            publication,
            routing_key: query.routing_key.clone(),
        })
        .map_err(|failure| errors::platform_status(failure, &limits))?;
    let mut budget = RequestBudget::for_response::<proto::InspectHttpTargetResponse>(&limits)?;
    for text in [&tenant.0, &query.service, &query.contract, &query.function] {
        budget.string(text, domain::MAXIMUM_ID_BYTES)?;
    }
    budget.optional_string(query.route.as_ref(), domain::MAXIMUM_ID_BYTES)?;
    budget.allocation::<proto::TargetCandidate>(observed.candidates.len())?;
    let mut candidates = Vec::with_capacity(observed.candidates.len());
    for candidate in &observed.candidates {
        let mut output = candidate_to_proto(candidate, tenant, &mut budget)?;
        // Metadata-only fixed-size identity lookup, not a full metadata clone.
        if let (Some(catalog), Some(id)) = (&adapter.web, &candidate.publication) {
            let selector = PublicationRef {
                id: id.clone(),
                scope: LifecycleScope::Tenant(tenant.clone()),
            };
            if let Some(identity) = catalog
                .inspect_publication_identity(&selector)
                .map_err(|failure| errors::platform_status(failure, &limits))?
            {
                if identity.component != candidate.component
                    || candidate
                        .package
                        .as_ref()
                        .is_some_and(|package| identity.package.as_ref() != Some(package))
                {
                    return Err(Status::internal("target publication identity changed"));
                }
                output.package_digest = identity.package.map(|digest| digest.as_str().to_owned());
                output.publication_kind = identity.kind.map(|kind| {
                    match kind {
                        latent_artifacts::package::PackageKind::Capsule => "capsule",
                        latent_artifacts::package::PackageKind::BrowserAssets => "browser-assets",
                        latent_artifacts::package::PackageKind::SsrPackage => "ssr-package",
                    }
                    .into()
                });
                budget.optional_string(output.package_digest.as_ref(), 71)?;
                budget.optional_string(output.publication_kind.as_ref(), 32)?;
            }
        }
        output.preparation = Some(if query.include_preparation {
            let prepared = preparation(adapter, candidate, expires).await;
            if prepared.state != proto::TargetPreparationState::Ready as i32 {
                output.eligible = false;
                output
                    .reasons
                    .retain(|reason| *reason != proto::TargetReason::Current as i32);
                if !output
                    .reasons
                    .contains(&(proto::TargetReason::InspectionUnavailable as i32))
                {
                    output
                        .reasons
                        .push(proto::TargetReason::InspectionUnavailable as i32);
                }
            } else if !prepared.exports.iter().any(|export| {
                export.contract == query.contract && export.function == query.function
            }) {
                output.export_compatible = false;
                output.http_compatible = false;
                output.eligible = false;
                output
                    .reasons
                    .retain(|reason| *reason != proto::TargetReason::Current as i32);
                if !output
                    .reasons
                    .contains(&(proto::TargetReason::ExportAbsent as i32))
                {
                    output
                        .reasons
                        .push(proto::TargetReason::ExportAbsent as i32);
                }
            }
            charge_preparation(&prepared, &mut budget)?;
            prepared
        } else {
            proto::TargetPreparation {
                state: proto::TargetPreparationState::NotRequested as i32,
                ..proto::TargetPreparation::default()
            }
        });
        candidates.push(output);
    }
    let policy_after = policy_generation(adapter)?;
    let mut state = repository
        .finish_target_inspection(&observed)
        .map_err(|failure| errors::platform_status(failure, &limits))?;
    if policy_before != policy_after || Instant::now() >= expires {
        state = domain::TargetObservationState::Stale;
    }
    if state != domain::TargetObservationState::Coherent {
        for candidate in &mut candidates {
            candidate.eligible = false;
        }
    }
    let output = proto::InspectHttpTargetResponse {
        schema_version: 1,
        tenant: tenant.0.clone(),
        service: query.service.clone(),
        contract: query.contract.clone(),
        function: query.function.clone(),
        route: query.route.clone().unwrap_or_else(|| "default".into()),
        state: match state {
            domain::TargetObservationState::Coherent => proto::TargetObservationState::Coherent,
            domain::TargetObservationState::Stale => proto::TargetObservationState::Stale,
            domain::TargetObservationState::Unavailable => {
                proto::TargetObservationState::Unavailable
            }
        } as i32,
        catalog_transaction: observed.catalog_transaction,
        route_generation: observed.route_generation.0,
        binding_generation: observed.binding_generation.0,
        policy_store_generation: policy_before,
        candidates,
        selected_revision_id: observed.selected_revision.as_ref().map(|id| id.0.clone()),
        live_grants_checked: false,
    };
    if output.encoded_len() > limits.max_response_bytes {
        return Err(bounds::exhausted());
    }
    let mut response = adapter.response(output)?;
    response.extensions_mut().insert(observed.lease().clone());
    Ok(response)
}

fn policy_generation(adapter: &ManagementServiceAdapter) -> Result<Option<u64>, Status> {
    adapter
        .policies
        .as_ref()
        .map(|owner| {
            owner
                .store()
                .inspection_generation()
                .map_err(|failure| errors::platform_status(failure, &adapter.limits))
        })
        .transpose()
}

fn candidate_to_proto(
    value: &domain::TargetCandidate,
    tenant: &TenantId,
    budget: &mut RequestBudget,
) -> Result<proto::TargetCandidate, Status> {
    for text in [&value.deployment.0, &value.revision.0, &value.component.0] {
        budget.string(text, domain::MAXIMUM_ID_BYTES)?;
    }
    for id in [&value.publication, &value.requested_publication]
        .into_iter()
        .flatten()
    {
        budget.allocation::<proto::PublicationRef>(1)?;
        budget.allocation::<u8>(id.as_str().len() + tenant.0.len())?;
    }
    budget.allocation::<proto::TargetDependency>(value.dependencies.len())?;
    budget.allocation::<proto::InspectedHttpBinding>(value.http_bindings.len())?;
    for binding in &value.http_bindings {
        budget.string(&binding.id.0, domain::MAXIMUM_ID_BYTES)?;
        budget.allocation::<u8>(32)?;
    }
    if let Some(package) = &value.package {
        budget.allocation::<u8>(package.as_str().len())?;
    }
    let mut dependencies = Vec::with_capacity(value.dependencies.len());
    for dependency in &value.dependencies {
        for text in [
            &dependency.capability,
            &dependency.state,
            &dependency.policy_identity_digest,
            &dependency.provider_profile,
            &dependency.configuration_digest,
        ] {
            budget.string(text, domain::MAXIMUM_ID_BYTES)?;
        }
        budget.allocation::<proto::TargetDependencyRevision>(1 + dependency.policies.len())?;
        for revision in std::iter::once(&dependency.binding).chain(&dependency.policies) {
            budget.string(&revision.id, domain::MAXIMUM_ID_BYTES)?;
            budget.string(&revision.digest, domain::MAXIMUM_ID_BYTES)?;
        }
        let revision = |value: &domain::TargetDependencyRevision| proto::TargetDependencyRevision {
            id: value.id.clone(),
            digest: value.digest.clone(),
            revision: value.revision,
        };
        dependencies.push(proto::TargetDependency {
            capability: dependency.capability.clone(),
            state: dependency.state.clone(),
            policy_identity_digest: dependency.policy_identity_digest.clone(),
            provider_configuration_epoch: dependency.provider_configuration_epoch,
            binding: Some(revision(&dependency.binding)),
            policies: dependency.policies.iter().map(revision).collect(),
            provider_profile: dependency.provider_profile.clone(),
            configuration_digest: dependency.configuration_digest.clone(),
        });
    }
    let publication = |id: &latent_core::PublicationId| proto::PublicationRef {
        id: id.as_str().into(),
        tenant: tenant.0.clone(),
    };
    Ok(proto::TargetCandidate {
        deployment_id: value.deployment.0.clone(),
        deployment_generation: value.deployment_generation,
        revision_id: value.revision.0.clone(),
        component_digest: value.component.0.clone(),
        publication: value.publication.as_ref().map(publication),
        requested_publication: value.requested_publication.as_ref().map(publication),
        package_digest: value.package.as_ref().map(|id| id.as_str().into()),
        publication_generation: value.publication_generation,
        routing_weight: u32::from(value.weight),
        export_compatible: value.export_compatible,
        http_compatible: value.http_compatible,
        eligible: value.eligible,
        reasons: value
            .reasons
            .iter()
            .map(|reason| match reason {
                domain::TargetReason::Current => proto::TargetReason::Current,
                domain::TargetReason::ExportAbsent => proto::TargetReason::ExportAbsent,
                domain::TargetReason::ZeroRoutingWeight => proto::TargetReason::ZeroRoutingWeight,
                domain::TargetReason::PublicationUnavailable => {
                    proto::TargetReason::PublicationUnavailable
                }
                domain::TargetReason::BindingPlanUnavailable => {
                    proto::TargetReason::BindingPlanUnavailable
                }
                domain::TargetReason::PolicyChanged => proto::TargetReason::PolicyChanged,
                domain::TargetReason::ProviderUnavailable => {
                    proto::TargetReason::ProviderUnavailable
                }
                domain::TargetReason::InspectionUnavailable => {
                    proto::TargetReason::InspectionUnavailable
                }
                domain::TargetReason::UnmanagedPublication => {
                    proto::TargetReason::UnmanagedPublication
                }
                domain::TargetReason::HttpIncompatible => proto::TargetReason::HttpIncompatible,
            } as i32)
            .collect(),
        dependencies,
        preparation: None,
        publication_kind: None,
        http_bindings: value
            .http_bindings
            .iter()
            .map(|binding| proto::InspectedHttpBinding {
                id: binding.id.0.clone(),
                generation: binding.generation,
                selected_deployment_generation: binding.selected_deployment_generation,
                state: if binding.current {
                    "configured-current"
                } else {
                    "deployment-changed"
                }
                .into(),
            })
            .collect(),
    })
}

async fn preparation(
    adapter: &ManagementServiceAdapter,
    candidate: &domain::TargetCandidate,
    expires: Instant,
) -> proto::TargetPreparation {
    let result = async {
        let backend = adapter
            .web_backend
            .as_ref()
            .ok_or_else(|| platform(PlatformErrorCode::Unavailable))?;
        if !candidate.eligible || candidate.publication.is_none() {
            return Err(platform(PlatformErrorCode::Unavailable));
        }
        let mut key = backend.preparation_key(&candidate.component)?;
        key.publication = candidate.publication.clone();
        let ready = backend
            .prepare_ready_from_repository(adapter.services.artifacts.clone(), key.clone())
            .await?;
        if ready.descriptor().key != key || ready.descriptor().backend != backend.backend_id() {
            return Err(platform(PlatformErrorCode::Internal));
        }
        backend.inspect_ready(ready)
    };
    match tokio::time::timeout_at(expires.into(), result).await {
        Ok(Ok(value)) => prepared_to_proto(value),
        Ok(Err(failure)) => {
            let diagnostic = latent_core::diagnostic::ActivationDiagnostic::from_error(&failure);
            let rejected = matches!(
                failure.code,
                PlatformErrorCode::IncompatibleContract
                    | PlatformErrorCode::CorruptArtifact
                    | PlatformErrorCode::InvalidArgument
                    | PlatformErrorCode::PermissionDenied
            ) || diagnostic.as_ref().is_some_and(|value| {
                value.stage == latent_core::diagnostic::DiagnosticStage::Preparation
            });
            proto::TargetPreparation {
                state: (if rejected {
                    proto::TargetPreparationState::Rejected
                } else {
                    proto::TargetPreparationState::Unavailable
                }) as i32,
                diagnostic: diagnostic.as_ref().map(super::activations::diagnostic),
                ..proto::TargetPreparation::default()
            }
        }
        Err(_) => proto::TargetPreparation {
            state: proto::TargetPreparationState::Unavailable as i32,
            diagnostic: Some(super::activations::diagnostic(
                &latent_core::diagnostic::ActivationDiagnostic::new(
                    latent_core::diagnostic::DiagnosticStage::Preparation,
                    latent_core::diagnostic::DiagnosticReason::DeadlineExceeded,
                ),
            )),
            ..proto::TargetPreparation::default()
        },
    }
}

fn prepared_to_proto(value: PreparationInspection) -> proto::TargetPreparation {
    proto::TargetPreparation {
        state: proto::TargetPreparationState::Ready as i32,
        diagnostic: None,
        profile: Some(value.profile as i32),
        engine_version: Some(value.key.engine_version),
        engine_configuration_digest: Some(value.key.engine_configuration_digest),
        target_triple: Some(value.key.target_triple),
        cpu_feature_set: Some(value.key.cpu_feature_set),
        sealed_metadata_fingerprint: value
            .sealed_metadata_fingerprint
            .map(|digest| format!("{:x}", latent_core::digest::HexDigest(&digest))),
        import_count: Some(value.import_count),
        function_count: Some(value.function_count),
        hostcall_fuel: Some(value.hostcall_fuel),
        maximum_lifted_bytes: Some(value.maximum_lifted_bytes),
        maximum_type_nodes: Some(value.maximum_type_nodes),
        declared_budget: Some(super::control_budget_to_proto(&value.declared_budget)),
        imports: value.imports.into_iter().map(|id| id.0).collect(),
        exports: value
            .exports
            .into_iter()
            .map(|(contract, function)| proto::PreparedTargetExport {
                contract: contract.0,
                function: function.0,
            })
            .collect(),
    }
}

fn charge_preparation(
    value: &proto::TargetPreparation,
    budget: &mut RequestBudget,
) -> Result<(), Status> {
    budget.allocation::<proto::TargetPreparation>(1)?;
    for text in [
        &value.engine_version,
        &value.engine_configuration_digest,
        &value.target_triple,
        &value.cpu_feature_set,
        &value.sealed_metadata_fingerprint,
    ]
    .into_iter()
    .flatten()
    {
        budget.string(text, domain::MAXIMUM_ID_BYTES)?;
        if text.is_empty() || text.chars().any(char::is_control) {
            return Err(Status::internal("invalid preparation observation"));
        }
    }
    budget.sequence(&value.imports, 64)?;
    for import in &value.imports {
        budget.string(import, domain::MAXIMUM_ID_BYTES)?;
        identifier(import, domain::MAXIMUM_ID_BYTES)?;
    }
    budget.sequence(&value.exports, 128)?;
    for export in &value.exports {
        budget.string(&export.contract, domain::MAXIMUM_ID_BYTES)?;
        budget.string(&export.function, domain::MAXIMUM_ID_BYTES)?;
        identifier(&export.contract, domain::MAXIMUM_ID_BYTES)?;
        identifier(&export.function, domain::MAXIMUM_ID_BYTES)?;
    }
    if value.declared_budget.is_some() {
        budget.allocation::<proto::ResourceBudget>(1)?;
    }
    if let Some(diagnostic) = &value.diagnostic {
        budget.allocation::<proto::ActivationDiagnostic>(1)?;
        budget.optional_string(diagnostic.profile_digest.as_ref(), 64)?;
    }
    Ok(())
}

fn deadline(request: &Request<proto::InspectHttpTargetRequest>) -> Result<Instant, Status> {
    let millis = request.get_ref().maximum_wait_millis;
    if millis > MAXIMUM_WAIT_MILLIS {
        return Err(Status::invalid_argument(
            "target inspection wait exceeds finite limit",
        ));
    }
    let maximum = Instant::now() + Duration::from_millis(if millis == 0 { 10_000 } else { millis });
    Ok(request
        .extensions()
        .get::<crate::invocation::AuthenticatedInvocationContext>()
        .and_then(crate::invocation::AuthenticatedInvocationContext::transport_expires_at)
        .map_or(maximum, |expires| expires.min(maximum)))
}
fn platform(code: PlatformErrorCode) -> PlatformError {
    PlatformError {
        code,
        message: "target-preparation-unavailable".into(),
        retryable: false,
        details: Vec::new(),
    }
}
