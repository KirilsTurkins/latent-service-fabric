//! Bounded tenant-authorized target observations over the existing catalog owner.
//! Descriptors, supplied routing keys and observed preconditions grant no authority.
use super::{admission_fence, compiler::CompiledCatalog, error, DirectoryDeploymentRepository};
use crate::deployment_operations::DeploymentReadLease;
use latent_core::{
    DeploymentId, PackageDigest, PlatformError, PlatformErrorCode, PublicationId, ReleaseDigest,
    RevisionId, RouteGeneration,
};
use latent_routing::InvocationTarget;
use sha2::{Digest, Sha256};
use std::{fmt::Write as _, sync::Arc};

pub const MAXIMUM_CANDIDATES: usize = 32;
pub const MAXIMUM_DEPENDENCIES: usize = 32;
pub const MAXIMUM_BYTES: usize = 64 * 1024;
pub const MAXIMUM_ID_BYTES: usize = 512;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TargetInspectionRequest {
    pub target: InvocationTarget,
    pub revision: Option<RevisionId>,
    pub publication: Option<PublicationId>,
    /// Selects deterministically for THIS hypothetical key, never the next HTTP request.
    pub routing_key: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TargetObservationState {
    Coherent,
    Stale,
    Unavailable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TargetReason {
    Current,
    ExportAbsent,
    ZeroRoutingWeight,
    PublicationUnavailable,
    BindingPlanUnavailable,
    PolicyChanged,
    ProviderUnavailable,
    InspectionUnavailable,
    UnmanagedPublication,
    HttpIncompatible,
}
impl TargetReason {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::Current => "current",
            Self::ExportAbsent => "export-absent",
            Self::ZeroRoutingWeight => "zero-routing-weight",
            Self::PublicationUnavailable => "publication-unavailable",
            Self::BindingPlanUnavailable => "binding-plan-unavailable",
            Self::PolicyChanged => "policy-changed-or-revoked",
            Self::ProviderUnavailable => "provider-unavailable",
            Self::InspectionUnavailable => "inspection-unavailable",
            Self::UnmanagedPublication => "unmanaged-publication",
            Self::HttpIncompatible => "http-incompatible",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TargetDependency {
    pub capability: String,
    pub state: String,
    pub policy_identity_digest: String,
    pub provider_configuration_epoch: u64,
    pub binding: TargetDependencyRevision,
    pub policies: Vec<TargetDependencyRevision>,
    pub provider_profile: String,
    pub configuration_digest: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TargetDependencyRevision {
    pub id: String,
    pub digest: String,
    pub revision: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TargetCandidate {
    pub deployment: DeploymentId,
    pub deployment_generation: u64,
    pub revision: RevisionId,
    pub component: ReleaseDigest,
    pub publication: Option<PublicationId>,
    /// Original manifest selector; absence is preserved despite a captured publication.
    pub requested_publication: Option<PublicationId>,
    pub package: Option<PackageDigest>,
    pub publication_generation: Option<u64>,
    pub weight: u16,
    pub export_compatible: bool,
    pub http_compatible: bool,
    pub eligible: bool,
    pub reasons: Vec<TargetReason>,
    pub dependencies: Vec<TargetDependency>,
    pub http_bindings: Vec<TargetHttpBinding>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TargetHttpBinding {
    pub id: latent_core::TriggerId,
    pub generation: u64,
    pub selected_deployment_generation: u64,
    pub current: bool,
}

/// The existing read lease bounds response/scratch lifetime and concurrent pins.
/// There is no query map, worker, authority token or synthesized activation receipt.
pub struct TargetInspection {
    pub request: TargetInspectionRequest,
    pub catalog_transaction: u64,
    pub route_generation: RouteGeneration,
    /// Capability plans are compiled in the same route generation.
    pub binding_generation: RouteGeneration,
    pub candidates: Vec<TargetCandidate>,
    pub selected_revision: Option<RevisionId>,
    pub state: TargetObservationState,
    catalog: Arc<CompiledCatalog>,
    lease: DeploymentReadLease,
}
impl TargetInspection {
    #[must_use]
    pub fn lease(&self) -> &DeploymentReadLease {
        &self.lease
    }
}

impl DirectoryDeploymentRepository {
    pub fn inspect_target(
        &self,
        request: TargetInspectionRequest,
    ) -> Result<TargetInspection, PlatformError> {
        validate(&request)?;
        let lease = self
            .operation_budget
            .read_with_scratch(MAXIMUM_BYTES, 16 * 1024)?;
        let current = self.invocation_catalog()?;
        if !current.confirmed {
            return Err(error(
                PlatformErrorCode::Unavailable,
                "target-catalog-unconfirmed",
            ));
        }
        let catalog = &current.routes;
        let members = catalog.inspection_members(&request.target, MAXIMUM_CANDIDATES)?;
        let mut candidates = Vec::with_capacity(members.len());
        let mut bytes = 1024_usize;
        for (index, exported) in members {
            let record = catalog.record(index);
            if request
                .revision
                .as_ref()
                .is_some_and(|id| id != &record.revision)
                || request
                    .publication
                    .as_ref()
                    .is_some_and(|id| record.publication.as_ref() != Some(id))
            {
                continue;
            }
            for id in [
                &record.deployment.id.0,
                &record.revision.0,
                &record.deployment.release.0,
            ] {
                if id.len() > MAXIMUM_ID_BYTES {
                    return Err(limit());
                }
                bytes = bytes.checked_add(id.len()).ok_or_else(limit)?;
            }
            let mut candidate = describe(
                catalog,
                index,
                exported,
                &request.target,
                MAXIMUM_BYTES.saturating_sub(bytes),
            )?;
            candidate.http_bindings = current.http.inspection_bindings(
                &request.target.tenant,
                &candidate,
                MAXIMUM_CANDIDATES,
            )?;
            bytes = bytes
                .checked_add(
                    2048 + candidate
                        .dependencies
                        .iter()
                        .map(|v| {
                            512 + v.capability.len()
                                + v.provider_profile.len()
                                + v.configuration_digest.len()
                                + v.binding.id.len()
                                + v.binding.digest.len()
                                + v.policies
                                    .iter()
                                    .map(|p| 128 + p.id.len() + p.digest.len())
                                    .sum::<usize>()
                        })
                        .sum::<usize>(),
                )
                .ok_or_else(limit)?;
            bytes = bytes
                .checked_add(
                    candidate
                        .http_bindings
                        .iter()
                        .map(|binding| 128 + binding.id.0.len())
                        .sum::<usize>(),
                )
                .ok_or_else(limit)?;
            if bytes > MAXIMUM_BYTES {
                return Err(limit());
            }
            candidates.push(candidate);
        }
        // No omitted key is replaced with an invented empty routing context.
        let selected_revision = match &request.routing_key {
            Some(key) => catalog
                .resolve(&request.target, Some(key), self.config)
                .ok()
                .filter(|selected| {
                    candidates
                        .iter()
                        .any(|candidate| candidate.revision == selected.revision)
                })
                .map(|selected| selected.revision),
            None => None,
        };
        self.binding_generations.retain(catalog)?;
        let state = if catalog.with_current_admission(&mut |_| Ok(())).is_ok() {
            TargetObservationState::Coherent
        } else {
            TargetObservationState::Stale
        };
        Ok(TargetInspection {
            request,
            catalog_transaction: current.transaction,
            route_generation: catalog.generation,
            binding_generation: catalog.generation,
            candidates,
            selected_revision,
            state,
            catalog: Arc::clone(catalog),
            lease,
        })
    }

    /// Recheck the SAME pinned state after bounded asynchronous preparation.
    /// A stale result supplies no positive eligibility or write precondition claim.
    pub fn finish_target_inspection(
        &self,
        value: &TargetInspection,
    ) -> Result<TargetObservationState, PlatformError> {
        let current = self.invocation_catalog()?;
        if !current.confirmed
            || current.transaction != value.catalog_transaction
            || !Arc::ptr_eq(&current.routes, &value.catalog)
        {
            return Ok(TargetObservationState::Stale);
        }
        if current
            .routes
            .with_current_admission(&mut |_| Ok(()))
            .is_err()
        {
            return Ok(TargetObservationState::Stale);
        }
        for (index, exported) in current
            .routes
            .inspection_members(&value.request.target, MAXIMUM_CANDIDATES)?
        {
            let record = current.routes.record(index);
            if let Some(before) = value
                .candidates
                .iter()
                .find(|candidate| candidate.revision == record.revision)
            {
                let mut after = describe(
                    &current.routes,
                    index,
                    exported,
                    &value.request.target,
                    MAXIMUM_BYTES,
                )?;
                after.http_bindings = current.http.inspection_bindings(
                    &value.request.target.tenant,
                    &after,
                    MAXIMUM_CANDIDATES,
                )?;
                if after != *before {
                    return Ok(TargetObservationState::Stale);
                }
            }
        }
        Ok(value.state)
    }
}

fn describe(
    catalog: &CompiledCatalog,
    index: super::compiler::RecordIndex,
    exported: bool,
    target: &InvocationTarget,
    maximum_bytes: usize,
) -> Result<TargetCandidate, PlatformError> {
    let record = catalog.record(index);
    let mut reasons = Vec::new();
    if !exported {
        reasons.push(TargetReason::ExportAbsent);
    }
    if record.deployment.route_weight == 0 {
        reasons.push(TargetReason::ZeroRoutingWeight);
    }
    let eligibility =
        catalog.selected_eligibility(&record.deployment.release, record.publication.as_ref());
    let (package, publication_generation) = match &eligibility {
        Some(admission_fence::SelectedEligibility::Eligible(token)) => {
            (token.package().cloned(), Some(token.generation()))
        }
        _ => (None, None),
    };
    if record.publication.is_none() || package.is_none() {
        reasons.push(TargetReason::UnmanagedPublication);
    }
    if let Err(failure) = admission_fence::check_selected(eligibility.as_ref(), &target.tenant) {
        reasons.push(if failure.code == PlatformErrorCode::Unavailable {
            TargetReason::InspectionUnavailable
        } else {
            TargetReason::PublicationUnavailable
        });
    }
    let mut dependencies = Vec::new();
    match catalog
        .bindings
        .inspection_plan(&target.tenant, &record.deployment.id, &record.revision)
    {
        Some(plan) => {
            let bindings = plan.inspect_bindings_bounded(
                &target.tenant,
                MAXIMUM_DEPENDENCIES,
                MAXIMUM_DEPENDENCIES,
                maximum_bytes,
            )?;
            if bindings.len() > MAXIMUM_DEPENDENCIES {
                return Err(limit());
            }
            for binding in bindings {
                if binding.policies.len() > MAXIMUM_DEPENDENCIES {
                    return Err(limit());
                }
                for text in [
                    &binding.capability,
                    &binding.provider_profile,
                    &binding.configuration_digest,
                ]
                .into_iter()
                .chain(
                    std::iter::once(&binding.binding)
                        .chain(&binding.policies)
                        .flat_map(|revision| [&revision.id, &revision.digest]),
                ) {
                    if text.is_empty()
                        || text.len() > MAXIMUM_ID_BYTES
                        || text.chars().any(char::is_control)
                    {
                        return Err(limit());
                    }
                }
                use latent_capabilities::broker::diagnostics::BindingState as B;
                let reason = match binding.state {
                    B::Current => None,
                    B::PolicyChanged => Some(TargetReason::PolicyChanged),
                    B::ProviderUnavailable => Some(TargetReason::ProviderUnavailable),
                    B::PublicationUnavailable => Some(TargetReason::PublicationUnavailable),
                    B::RouteChanged | B::Indeterminate => Some(TargetReason::InspectionUnavailable),
                };
                if let Some(reason) = reason {
                    if !reasons.contains(&reason) {
                        reasons.push(reason);
                    }
                }
                let mut digest = Sha256::new();
                digest.update(b"lsf-target-dependency-v1\0");
                for revision in std::iter::once(&binding.binding).chain(&binding.policies) {
                    for part in [&revision.id, &revision.digest] {
                        digest.update((part.len() as u64).to_le_bytes());
                        digest.update(part.as_bytes());
                    }
                    digest.update(revision.revision.to_le_bytes());
                }
                for part in [&binding.provider_profile, &binding.configuration_digest] {
                    digest.update((part.len() as u64).to_le_bytes());
                    digest.update(part.as_bytes());
                }
                let mut identity = String::with_capacity(64);
                for byte in digest.finalize() {
                    let _ = write!(identity, "{byte:02x}");
                }
                let revision = |value: latent_capabilities::broker::diagnostics::Revision| {
                    TargetDependencyRevision {
                        id: value.id,
                        digest: value.digest,
                        revision: value.revision,
                    }
                };
                dependencies.push(TargetDependency {
                    capability: binding.capability,
                    state: binding.state.code().into(),
                    policy_identity_digest: identity,
                    provider_configuration_epoch: binding.configuration_epoch,
                    binding: revision(binding.binding),
                    policies: binding.policies.into_iter().map(revision).collect(),
                    provider_profile: binding.provider_profile,
                    configuration_digest: binding.configuration_digest,
                });
            }
        }
        None => reasons.push(TargetReason::BindingPlanUnavailable),
    }
    // ABI compatibility is independent of route/publication/grant currentness.
    let http_compatible = exported
        && target.contract.0 == "latent:web/application@0.1.0"
        && target.function.0 == "handle";
    let eligible = reasons.is_empty();
    if eligible {
        reasons.push(TargetReason::Current);
    }
    Ok(TargetCandidate {
        deployment: record.deployment.id.clone(),
        deployment_generation: *catalog.versions.get(&record.deployment.id).ok_or_else(|| {
            error(
                PlatformErrorCode::Internal,
                "target-deployment-version-missing",
            )
        })?,
        revision: record.revision.clone(),
        component: record.deployment.release.clone(),
        publication: record.publication.clone(),
        requested_publication: record.deployment.publication.clone(),
        package,
        publication_generation,
        weight: record.deployment.route_weight,
        export_compatible: exported,
        http_compatible,
        eligible,
        reasons,
        dependencies,
        http_bindings: Vec::new(),
    })
}

fn validate(request: &TargetInspectionRequest) -> Result<(), PlatformError> {
    let target = &request.target;
    for value in [
        &target.tenant.0,
        &target.service.0,
        &target.contract.0,
        &target.function.0,
    ]
    .into_iter()
    .chain(target.route.as_ref())
    .chain(request.revision.as_ref().map(|id| &id.0))
    {
        if value.is_empty() || value.len() > MAXIMUM_ID_BYTES || value.chars().any(char::is_control)
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-target-inspection",
            ));
        }
    }
    if request.routing_key.as_ref().is_some_and(|key| {
        key.is_empty() || key.len() > MAXIMUM_ID_BYTES || key.chars().any(char::is_control)
    }) {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "invalid-routing-context",
        ));
    }
    Ok(())
}
fn limit() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "target-inspection-limit",
    )
}
