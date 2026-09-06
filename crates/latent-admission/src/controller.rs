use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use latent_core::{
    BoxFuture, BudgetError, ClockSample, EffectiveActivationBudget, PlatformError,
    PlatformErrorCode, PrincipalKind,
};
use latent_routing::revision_policy::{ExecutionBackendKind, StateModel};
use latent_routing::{RevisionAdmissionPolicy, RevisionPolicySource};

use crate::policy::cell_rank;
use crate::{
    rejection, valid_identifier, AdmissionController, AdmissionObligations, AdmissionPermit,
    AdmissionRequest, LocalQuotaProvider, NodeAdmissionPolicy, TenantAdmissionPolicy,
};

/// Trusted node-wide observation, never accepted from invocation metadata.
/// `queue_delay_millis` is a scheduler-observed estimate; admission uses the
/// greater of this value and its own atomically reserved class backlog estimate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NodeLoadSnapshot {
    pub accepting: bool,
    pub cpu_pressure_milli: u16,
    pub memory_pressure_milli: u16,
    pub queue_delay_millis: u64,
    pub observed_at: Instant,
}

pub trait NodeLoadSource: Send + Sync {
    fn snapshot(&self) -> Result<NodeLoadSnapshot, PlatformError>;
}

/// An externally updated, shared load observation. It owns no monitoring task.
/// A stale, malformed, out-of-order, or unavailable sample fails closed.
#[derive(Clone)]
pub struct NodeLoadState {
    inner: Arc<Mutex<NodeLoadSnapshot>>,
}

impl NodeLoadState {
    pub fn new(snapshot: NodeLoadSnapshot) -> Result<Self, PlatformError> {
        validate_load_values(snapshot)?;
        Ok(Self { inner: Arc::new(Mutex::new(snapshot)) })
    }

    pub fn publish(&self, snapshot: NodeLoadSnapshot) -> Result<(), PlatformError> {
        validate_load_values(snapshot)?;
        let mut current = self.inner.lock().map_err(|_| unavailable_load())?;
        if snapshot.observed_at < current.observed_at {
            return Err(rejection(PlatformErrorCode::InvalidArgument, "node", "load", "out-of-order-load-sample"));
        }
        *current = snapshot;
        Ok(())
    }
}

impl NodeLoadSource for NodeLoadState {
    fn snapshot(&self) -> Result<NodeLoadSnapshot, PlatformError> {
        Ok(*self.inner.lock().map_err(|_| unavailable_load())?)
    }
}

/// Admission against an immutable catalog view and a shared node-owned ledger.
#[derive(Clone)]
pub struct LocalAdmissionController {
    source: Arc<dyn RevisionPolicySource>,
    quotas: LocalQuotaProvider,
    load: Arc<dyn NodeLoadSource>,
}

impl LocalAdmissionController {
    #[must_use]
    pub fn new(
        source: Arc<dyn RevisionPolicySource>,
        quotas: LocalQuotaProvider,
        load: Arc<dyn NodeLoadSource>,
    ) -> Self {
        Self { source, quotas, load }
    }

    /// Change the pinned policy view without resetting any node/tenant quotas.
    #[must_use]
    pub fn with_policy_source(&self, source: Arc<dyn RevisionPolicySource>) -> Self {
        Self::new(source, self.quotas.clone(), Arc::clone(&self.load))
    }

    #[must_use]
    pub fn quotas(&self) -> LocalQuotaProvider { self.quotas.clone() }

    pub fn admit_now(&self, request: AdmissionRequest) -> Result<AdmissionPermit, PlatformError> {
        let load = self.load.snapshot().map_err(|_| unavailable_load())?;
        self.admit_observed_at(request, load, ClockSample::system_now())
    }

    /// Deterministic clock seam for trusted embedding code and boundary tests.
    /// The sample must describe the actual admission instant, not caller data.
    pub fn admit_at(&self, request: AdmissionRequest, sample: ClockSample) -> Result<AdmissionPermit, PlatformError> {
        let load = self.load.snapshot().map_err(|_| unavailable_load())?;
        self.admit_observed_at(request, load, sample)
    }

    fn admit_observed_at(
        &self,
        request: AdmissionRequest,
        load: NodeLoadSnapshot,
        sample: ClockSample,
    ) -> Result<AdmissionPermit, PlatformError> {
        let node = self.quotas.policy();
        let tenant = validate_request(&request, node)?;
        validate_load(load, node, sample.monotonic())?;
        let policy = self.source.admission_policy(&request.revision).map_err(|error| {
            let code = if error.code == PlatformErrorCode::Unavailable {
                PlatformErrorCode::Unavailable
            } else {
                PlatformErrorCode::AdmissionRejected
            };
            rejection(code, "revision", "revision", "revision-not-available")
        })?;
        validate_revision_policy(&policy, node)?;
        let trust = node.trust_classes.get(&policy.placement.trust_class)
            .filter(|_| tenant.allowed_trust_classes.contains(&policy.placement.trust_class))
            .ok_or_else(|| rejection(PlatformErrorCode::PermissionDenied, "tenant", "trust-class", "trust-class-not-authorized"))?;
        let deployment_ceiling = policy.deployment_ceiling.intersect(&policy.execution.resource_budget_ceiling);
        let grant = EffectiveActivationBudget::admit_at(
            &request.requested_budget,
            &deployment_ceiling,
            &node.budget_ceiling,
            request.deadline_unix_millis,
            sample,
        ).map_err(budget_rejection)?;
        grant.require_executable_capacity().map_err(budget_rejection)?;
        let class = select_class(&policy, node, tenant, &trust.allowed_cell_classes, grant.budget.memory_bytes)?;
        let queue = node.queue_classes.iter()
            .find(|(_, queue)| (queue.minimum_priority..=queue.maximum_priority).contains(&request.priority))
            .map(|(name, _)| name.clone())
            .expect("validated priority has exactly one queue class");
        let obligations = AdmissionObligations {
            cell_class: class,
            queue_class: queue,
            trust_class: policy.placement.trust_class,
            priority: request.priority,
            required_features: policy.placement.required_features,
            host_call_depth_maximum: policy.execution.host_call_depth_maximum,
            component_call_depth_maximum: policy.execution.component_call_depth_maximum,
        };
        AdmissionPermit::reserve(
            self.quotas.clone(), request.activation_id, request.revision, grant, obligations,
            load.queue_delay_millis, sample.monotonic(),
        )
    }
}

impl AdmissionController for LocalAdmissionController {
    fn admit<'a>(&'a self, request: AdmissionRequest) -> BoxFuture<'a, Result<AdmissionPermit, PlatformError>> {
        Box::pin(async move { self.admit_now(request) })
    }
}

fn validate_request<'a>(request: &AdmissionRequest, node: &'a NodeAdmissionPolicy) -> Result<&'a TenantAdmissionPolicy, PlatformError> {
    let principal = &request.principal;
    if principal.tenant.as_ref() != Some(&request.revision.target.tenant)
        || principal.kind == PrincipalKind::Anonymous
        || !valid_identifier(&principal.subject, node.maximum_identifier_bytes)
        || (principal.kind == PrincipalKind::Service && principal.service.is_none())
        || principal.service.as_ref().is_some_and(|service| !valid_identifier(&service.0, node.maximum_identifier_bytes))
    {
        return Err(rejection(PlatformErrorCode::PermissionDenied, "request", "principal", "principal-not-authorized"));
    }
    let tenant = node.tenants.get(&request.revision.target.tenant)
        .filter(|tenant| tenant.allowed_subjects.contains(&principal.subject) && tenant.allowed_principal_kinds.contains(&principal.kind))
        .ok_or_else(|| rejection(PlatformErrorCode::PermissionDenied, "tenant", "principal", "principal-not-authorized"))?;
    let target = &request.revision.target;
    for id in [
        request.activation_id.0.as_str(), target.tenant.0.as_str(), target.service.0.as_str(),
        target.contract.0.as_str(), target.function.0.as_str(), request.revision.revision.0.as_str(),
        request.revision.release.0.as_str(), target.route.as_deref().unwrap_or("default"),
    ] {
        if !valid_identifier(id, node.maximum_identifier_bytes) {
            return Err(rejection(PlatformErrorCode::InvalidArgument, "request", "identifier", "invalid-identifier"));
        }
    }
    if request.revision.route_generation.0 == 0 {
        return Err(rejection(PlatformErrorCode::AdmissionRejected, "revision", "revision", "revision-not-available"));
    }
    if request.priority > node.maximum_priority || request.priority > tenant.maximum_priority {
        return Err(rejection(PlatformErrorCode::PermissionDenied, "tenant", "priority", "priority-not-authorized"));
    }
    for (limit, scope) in [(node.maximum_payload_bytes, "node"), (tenant.maximum_payload_bytes, "tenant")] {
        if request.payload_bytes > limit {
            return Err(rejection(PlatformErrorCode::ResourceExhausted, scope, "payload-bytes", "payload-too-large"));
        }
    }
    let mut entries = 0_usize;
    let mut bytes = 0_usize;
    for metadata in [&principal.claims, &request.attributes, &request.revision.attributes] {
        entries = entries.checked_add(metadata.len()).ok_or_else(metadata_rejection)?;
        if entries > node.maximum_metadata_entries {
            return Err(metadata_rejection());
        }
        for (key, value) in metadata {
            if !valid_identifier(key, node.maximum_identifier_bytes) {
                return Err(metadata_rejection());
            }
            bytes = bytes.checked_add(key.len()).and_then(|size| size.checked_add(value.len()))
                .filter(|size| *size <= node.maximum_metadata_bytes).ok_or_else(metadata_rejection)?;
        }
    }
    Ok(tenant)
}

fn validate_revision_policy(policy: &RevisionAdmissionPolicy, node: &NodeAdmissionPolicy) -> Result<(), PlatformError> {
    for (supported, dimension) in [
        (policy.execution.backend == ExecutionBackendKind::WasmComponent, "backend"),
        (policy.execution.state_model == StateModel::Stateless, "state-model"),
        (policy.execution.host_call_depth_maximum > 0 && policy.execution.component_call_depth_maximum > 0, "call-depth"),
    ] {
        if !supported {
            return Err(rejection(PlatformErrorCode::AdmissionRejected, "revision", dimension, "unsupported-execution-requirement"));
        }
    }
    for (allowed, value, dimension) in [
        (&policy.placement.architectures, Some(node.architecture.as_str()), "architecture"),
        (&policy.placement.regions, node.region.as_deref(), "region"),
        (&policy.placement.zones, node.zone.as_deref(), "zone"),
    ] {
        if !allowed.is_empty() && !value.is_some_and(|value| allowed.iter().any(|allowed| allowed == value)) {
            return Err(rejection(PlatformErrorCode::AdmissionRejected, "node", dimension, "placement-not-compatible"));
        }
    }
    Ok(())
}

fn select_class(
    policy: &RevisionAdmissionPolicy,
    node: &NodeAdmissionPolicy,
    tenant: &TenantAdmissionPolicy,
    trust_cells: &std::collections::BTreeSet<String>,
    memory: u64,
) -> Result<String, PlatformError> {
    let mut memory_supported = false;
    let mut threading_supported = false;
    let mut features_supported = false;
    let mut candidates = Vec::with_capacity(5);
    for (name, class) in &node.cell_classes {
        if class.maximum_memory_bytes < memory { continue; }
        memory_supported = true;
        if !class.threading_models.contains(&policy.execution.threading) { continue; }
        threading_supported = true;
        if !policy.placement.required_features.iter().all(|feature| class.features.contains(feature)) { continue; }
        features_supported = true;
        if tenant.allowed_cell_classes.contains(name) && trust_cells.contains(name) {
            candidates.push((class.maximum_memory_bytes, cell_rank(name), name));
        }
    }
    if let Some((_, _, name)) = candidates.into_iter().min() {
        return Ok(name.clone());
    }
    let (code, dimension, reason) = if !memory_supported {
        (PlatformErrorCode::ResourceExhausted, "memory-bytes", "no-compatible-cell")
    } else if !threading_supported {
        (PlatformErrorCode::AdmissionRejected, "threading", "no-compatible-cell")
    } else if !features_supported {
        (PlatformErrorCode::AdmissionRejected, "required-features", "no-compatible-cell")
    } else {
        (PlatformErrorCode::PermissionDenied, "cell-class", "cell-class-not-authorized")
    };
    Err(rejection(code, "node", dimension, reason))
}

fn validate_load(load: NodeLoadSnapshot, node: &NodeAdmissionPolicy, now: Instant) -> Result<(), PlatformError> {
    validate_load_values(load).map_err(|_| unavailable_load())?;
    if !load.accepting {
        return Err(rejection(PlatformErrorCode::Unavailable, "node", "overload", "node-not-accepting"));
    }
    if now.checked_duration_since(load.observed_at)
        .is_none_or(|age| age > Duration::from_millis(node.overload.maximum_sample_age_millis))
    {
        return Err(rejection(PlatformErrorCode::Unavailable, "node", "load", "load-sample-not-current"));
    }
    for (value, maximum, dimension) in [
        (load.cpu_pressure_milli, node.overload.maximum_cpu_pressure_milli, "cpu-pressure"),
        (load.memory_pressure_milli, node.overload.maximum_memory_pressure_milli, "memory-pressure"),
    ] {
        if value >= maximum {
            return Err(rejection(PlatformErrorCode::ResourceExhausted, "node", dimension, "node-overloaded"));
        }
    }
    Ok(())
}

fn validate_load_values(snapshot: NodeLoadSnapshot) -> Result<(), PlatformError> {
    if snapshot.cpu_pressure_milli > 1000 || snapshot.memory_pressure_milli > 1000 {
        Err(rejection(PlatformErrorCode::InvalidArgument, "node", "load", "invalid-load-sample"))
    } else {
        Ok(())
    }
}

fn unavailable_load() -> PlatformError {
    rejection(PlatformErrorCode::Unavailable, "node", "load", "load-source-unavailable")
}

fn metadata_rejection() -> PlatformError {
    rejection(PlatformErrorCode::InvalidArgument, "request", "metadata", "metadata-limit")
}

fn budget_rejection(error: BudgetError) -> PlatformError {
    let (code, dimension, reason) = match error {
        BudgetError::UnsupportedRequestDimension { dimension, .. } =>
            (PlatformErrorCode::InvalidArgument, dimension.wire_name(), "unsupported-budget-dimension"),
        BudgetError::Exhausted { dimension, .. } =>
            (PlatformErrorCode::ResourceExhausted, dimension.wire_name(), "no-executable-capacity"),
        BudgetError::DeadlineExceeded { .. } =>
            (PlatformErrorCode::DeadlineExceeded, "deadline", "deadline-exceeded"),
        BudgetError::DeadlineOutOfRange { .. } =>
            (PlatformErrorCode::InvalidArgument, "deadline", "deadline-out-of-range"),
        _ => (PlatformErrorCode::InvalidArgument, "budget", "invalid-budget"),
    };
    rejection(code, "request", dimension, reason)
}
