use std::cmp::Ordering;
use std::collections::BTreeSet;

use latent_core::ResourceBudget;

use crate::schema::is_sha256_digest;
use crate::{
    finish_violations, BindingManifest, CapsuleManifest, DeploymentManifest, ManifestResult,
    ManifestValidator, ManifestViolation, ObjectMetadata, PolicyManifest, StateModel,
    TriggerManifest,
};

pub const MANIFEST_API_VERSION: &str = "latent.dev/v1alpha1";
pub const PHASE1_FABRIC_VERSION: &str = "0.1.0";

const MAX_IDENTIFIER_BYTES: usize = 253;
const MAX_TOKEN_BYTES: usize = 128;
const MAX_METADATA_VALUE_BYTES: usize = 4096;

/// Stateless standalone Phase 1 semantic validator.
#[derive(Debug, Clone, Copy, Default)]
pub struct Phase1ManifestValidator;

impl Phase1ManifestValidator {
    #[must_use]
    pub const fn new() -> Self {
        Self
    }
}

impl ManifestValidator for Phase1ManifestValidator {
    fn validate_capsule(&self, manifest: &CapsuleManifest) -> ManifestResult<()> {
        let mut violations = Vec::new();
        validate_api_version(&manifest.api_version, &mut violations);
        validate_metadata(&manifest.metadata, &mut violations);
        validate_resource_identifier(
            &manifest.metadata.name,
            "$.metadata.name",
            "capsule name",
            &mut violations,
        );
        validate_digest(
            &manifest.component_digest.0,
            "$.component.digest",
            &mut violations,
        );
        validate_semantic_version(
            &manifest.semantic_version,
            "$.component.version",
            &mut violations,
        );
        validate_contract_id(&manifest.world.0, "$.component.world", &mut violations);

        if manifest.exports.is_empty() {
            violations.push(ManifestViolation::new(
                "$.exports",
                "missing-export",
                "a capsule must export at least one callable contract",
            ));
        }
        let mut exports = BTreeSet::new();
        for (index, export) in manifest.exports.iter().enumerate() {
            let path = format!("$.exports[{index}]");
            validate_contract_id(&export.contract.0, &path, &mut violations);
            if !exports.insert(export.contract.0.as_str()) {
                violations.push(ManifestViolation::new(
                    path,
                    "duplicate-export",
                    "a contract may be exported only once",
                ));
            }
        }

        let mut imports = BTreeSet::new();
        for (index, import) in manifest.imports.iter().enumerate() {
            let path = format!("$.imports[{index}].contract");
            validate_contract_id(&import.contract.0, &path, &mut violations);
            if !imports.insert(import.contract.0.as_str()) {
                violations.push(ManifestViolation::new(
                    path,
                    "duplicate-import",
                    "a contract may be imported only once",
                ));
            }
        }

        if manifest.execution.backend != crate::ExecutionBackendKind::WasmComponent {
            violations.push(ManifestViolation::new(
                "$.execution.backend",
                "unsupported-execution-backend",
                "standalone Phase 1 admits only the wasm-component backend",
            ));
        }
        if manifest.execution.state_model != StateModel::Stateless {
            violations.push(ManifestViolation::new(
                "$.execution.stateModel",
                "unsupported-state-model",
                "standalone Phase 1 admits only stateless capsules",
            ));
        }
        if manifest.execution.host_call_depth_maximum == 0 {
            violations.push(ManifestViolation::new(
                "$.execution.hostCallDepthMaximum",
                "out-of-range",
                "host call depth must be at least one",
            ));
        }
        if manifest.execution.component_call_depth_maximum == 0 {
            violations.push(ManifestViolation::new(
                "$.execution.componentCallDepthMaximum",
                "out-of-range",
                "component call depth must be at least one",
            ));
        }
        validate_stateless_budget(
            &manifest.execution.resource_budget_ceiling,
            "$.execution.limits",
            &mut violations,
        );
        validate_minimum_fabric_version(&manifest.minimum_fabric_version, &mut violations);
        validate_capsule_scope(manifest, &mut violations);

        finish_violations(violations)
    }

    fn validate_deployment(&self, manifest: &DeploymentManifest) -> ManifestResult<()> {
        let mut violations = Vec::new();
        validate_api_version(&manifest.api_version, &mut violations);
        validate_metadata(&manifest.metadata, &mut violations);
        validate_wire_identity(&manifest.id.0, &manifest.metadata.name, &mut violations);
        validate_resource_identifier(
            &manifest.id.0,
            "$.metadata.name",
            "deployment name",
            &mut violations,
        );
        validate_resource_identifier(
            &manifest.service.0,
            "$.spec.service",
            "service ID",
            &mut violations,
        );
        validate_digest(&manifest.release.0, "$.spec.release", &mut violations);

        if !(1..=10_000).contains(&manifest.route_weight) {
            violations.push(ManifestViolation::new(
                "$.spec.route.weight",
                "invalid-route-weight",
                "a Phase 1 deployment route weight must be between 1 and 10000",
            ));
        }

        let mut grants = BTreeSet::new();
        for (index, grant) in manifest.grants.iter().enumerate() {
            validate_contract_id(
                &grant.capability.0,
                &format!("$.spec.grants[{index}].capability"),
                &mut violations,
            );
            validate_resource_identifier(
                &grant.policy.0,
                &format!("$.spec.grants[{index}].policy"),
                "policy ID",
                &mut violations,
            );
            let key = (&grant.capability.0, &grant.policy.0);
            if !grants.insert(key) {
                violations.push(ManifestViolation::new(
                    format!("$.spec.grants[{index}]"),
                    "duplicate-grant",
                    "the same capability and policy pair may be granted only once",
                ));
            }

            let mut operations = BTreeSet::new();
            for (operation_index, operation) in grant.operations.iter().enumerate() {
                validate_token(
                    operation,
                    &format!("$.spec.grants[{index}].operations[{operation_index}]"),
                    "operation",
                    &mut violations,
                );
                if !operations.insert(operation.as_str()) {
                    violations.push(ManifestViolation::new(
                        format!("$.spec.grants[{index}].operations[{operation_index}]"),
                        "duplicate-operation",
                        "grant operations must be unique",
                    ));
                }
            }
            validate_metadata_map(
                &grant.constraints,
                &format!("$.spec.grants[{index}].constraints"),
                &mut violations,
            );
        }

        validate_stateless_budget(&manifest.resources, "$.spec.resources", &mut violations);
        if manifest.availability.minimum_zones > manifest.availability.minimum_cached_copies {
            violations.push(ManifestViolation::new(
                "$.spec.availability.minimumZones",
                "invalid-availability",
                "minimumZones cannot exceed minimumCachedCopies",
            ));
        }
        validate_token(
            &manifest.placement.trust_class,
            "$.spec.placement.trustClass",
            "trust class",
            &mut violations,
        );
        validate_unique_tokens(
            &manifest.placement.architectures,
            "$.spec.placement.architectures",
            "architecture",
            &mut violations,
        );
        validate_unique_tokens(
            &manifest.placement.regions,
            "$.spec.placement.regions",
            "region",
            &mut violations,
        );
        validate_unique_tokens(
            &manifest.placement.zones,
            "$.spec.placement.zones",
            "zone",
            &mut violations,
        );
        validate_unique_tokens(
            &manifest.placement.required_features,
            "$.spec.placement.requiredFeatures",
            "required feature",
            &mut violations,
        );
        validate_required_tenant(&manifest.metadata, &mut violations);
        validate_scoped_value(
            &manifest.service.0,
            manifest
                .metadata
                .tenant
                .as_ref()
                .map(|tenant| tenant.0.as_str()),
            "$.spec.service",
            &mut violations,
        );

        finish_violations(violations)
    }

    fn validate_binding(&self, manifest: &BindingManifest) -> ManifestResult<()> {
        let mut violations = Vec::new();
        validate_api_version(&manifest.api_version, &mut violations);
        validate_metadata(&manifest.metadata, &mut violations);
        validate_wire_identity(&manifest.id.0, &manifest.metadata.name, &mut violations);
        validate_resource_identifier(
            &manifest.id.0,
            "$.metadata.name",
            "binding name",
            &mut violations,
        );
        validate_required_tenant(&manifest.metadata, &mut violations);
        let tenant = manifest
            .metadata
            .tenant
            .as_ref()
            .map(|value| value.0.as_str());

        validate_resource_identifier(
            &manifest.consumer.service.0,
            "$.spec.consumer.service",
            "consumer service ID",
            &mut violations,
        );
        validate_scoped_value(
            &manifest.consumer.service.0,
            tenant,
            "$.spec.consumer.service",
            &mut violations,
        );
        validate_contract_id(
            &manifest.consumer.contract.0,
            "$.spec.consumer.contract",
            &mut violations,
        );
        validate_optional_route(
            manifest.consumer.route.as_deref(),
            "$.spec.consumer.route",
            &mut violations,
        );

        validate_resource_identifier(
            &manifest.provider.service.0,
            "$.spec.provider.service",
            "provider service ID",
            &mut violations,
        );
        validate_scoped_value(
            &manifest.provider.service.0,
            tenant,
            "$.spec.provider.service",
            &mut violations,
        );
        validate_contract_id(
            &manifest.provider.contract.0,
            "$.spec.provider.contract",
            &mut violations,
        );
        validate_optional_route(
            manifest.provider.route.as_deref(),
            "$.spec.provider.route",
            &mut violations,
        );

        finish_violations(violations)
    }

    fn validate_trigger(&self, manifest: &TriggerManifest) -> ManifestResult<()> {
        let mut violations = Vec::new();
        validate_api_version(&manifest.api_version, &mut violations);
        validate_metadata(&manifest.metadata, &mut violations);
        validate_wire_identity(&manifest.id.0, &manifest.metadata.name, &mut violations);
        validate_resource_identifier(
            &manifest.id.0,
            "$.metadata.name",
            "trigger name",
            &mut violations,
        );
        validate_required_tenant(&manifest.metadata, &mut violations);
        validate_resource_identifier(
            &manifest.target.service.0,
            "$.spec.target.service",
            "target service ID",
            &mut violations,
        );
        validate_scoped_value(
            &manifest.target.service.0,
            manifest
                .metadata
                .tenant
                .as_ref()
                .map(|tenant| tenant.0.as_str()),
            "$.spec.target.service",
            &mut violations,
        );
        validate_contract_id(
            &manifest.target.contract.0,
            "$.spec.target.contract",
            &mut violations,
        );
        validate_token(
            &manifest.target.function,
            "$.spec.target.function",
            "target function",
            &mut violations,
        );
        validate_optional_route(
            manifest.target.route.as_deref(),
            "$.spec.target.route",
            &mut violations,
        );

        finish_violations(violations)
    }

    fn validate_policy(&self, manifest: &PolicyManifest) -> ManifestResult<()> {
        let mut violations = Vec::new();
        validate_api_version(&manifest.api_version, &mut violations);
        validate_metadata(&manifest.metadata, &mut violations);
        validate_wire_identity(&manifest.id.0, &manifest.metadata.name, &mut violations);
        validate_resource_identifier(
            &manifest.id.0,
            "$.metadata.name",
            "policy name",
            &mut violations,
        );
        validate_required_tenant(&manifest.metadata, &mut violations);
        validate_resource_identifier(
            &manifest.language,
            "$.spec.language",
            "policy language",
            &mut violations,
        );
        if manifest.document.trim().is_empty() {
            violations.push(ManifestViolation::new(
                "$.spec.document",
                "empty-value",
                "policy document must not be empty or whitespace-only",
            ));
        }

        finish_violations(violations)
    }

    fn validate_deployment_against_capsule(
        &self,
        deployment: &DeploymentManifest,
        capsule: &CapsuleManifest,
    ) -> ManifestResult<()> {
        let mut violations = Vec::new();
        if let Err(mut invalid) = self.validate_deployment(deployment) {
            violations.append(&mut invalid);
        }
        if let Err(mut invalid) = self.validate_capsule(capsule) {
            violations.append(&mut invalid);
        }

        if deployment.service.0 != capsule.metadata.name {
            violations.push(ManifestViolation::new(
                "$.spec.service",
                "service-mismatch",
                "deployment service must equal the referenced capsule name",
            ));
        }
        if !deployment
            .release
            .0
            .eq_ignore_ascii_case(&capsule.component_digest.0)
        {
            violations.push(ManifestViolation::new(
                "$.spec.release",
                "release-mismatch",
                "deployment release digest must equal the capsule component digest",
            ));
        }

        if let Some(capsule_tenant) = capsule.metadata.tenant.as_ref() {
            if deployment.metadata.tenant.as_ref() != Some(capsule_tenant) {
                violations.push(ManifestViolation::new(
                    "$.metadata.tenant",
                    "tenant-scope-mismatch",
                    "deployment tenant must match the scoped capsule tenant",
                ));
            }
        }
        if let Some(capsule_namespace) = capsule.metadata.namespace.as_ref() {
            if deployment.metadata.namespace.as_ref() != Some(capsule_namespace) {
                violations.push(ManifestViolation::new(
                    "$.metadata.namespace",
                    "namespace-scope-mismatch",
                    "deployment namespace must match the scoped capsule namespace",
                ));
            }
        }

        validate_budget_ceiling(
            &deployment.resources,
            &capsule.execution.resource_budget_ceiling,
            &mut violations,
        );

        let imports: BTreeSet<&str> = capsule
            .imports
            .iter()
            .map(|import| import.contract.0.as_str())
            .collect();
        for (index, grant) in deployment.grants.iter().enumerate() {
            if !imports.contains(grant.capability.0.as_str()) {
                violations.push(ManifestViolation::new(
                    format!("$.spec.grants[{index}].capability"),
                    "capability-not-imported",
                    "deployment grants may reference only contracts imported by the capsule",
                ));
            }
        }

        finish_violations(violations)
    }
}

fn validate_api_version(value: &str, violations: &mut Vec<ManifestViolation>) {
    if value != MANIFEST_API_VERSION {
        violations.push(ManifestViolation::new(
            "$.apiVersion",
            "unsupported-api-version",
            format!("supported manifest API version is `{MANIFEST_API_VERSION}`"),
        ));
    }
}

fn validate_metadata(metadata: &ObjectMetadata, violations: &mut Vec<ManifestViolation>) {
    validate_resource_identifier(
        &metadata.name,
        "$.metadata.name",
        "resource name",
        violations,
    );
    if let Some(tenant) = metadata.tenant.as_ref() {
        validate_scope_component(&tenant.0, "$.metadata.tenant", "tenant", violations);
    }
    if let Some(namespace) = metadata.namespace.as_ref() {
        validate_scope_component(namespace, "$.metadata.namespace", "namespace", violations);
        if metadata.tenant.is_none() {
            violations.push(ManifestViolation::new(
                "$.metadata.namespace",
                "namespace-requires-tenant",
                "a namespace cannot be declared without an explicit tenant",
            ));
        }
    }
    validate_metadata_map(&metadata.labels, "$.metadata.labels", violations);
    validate_metadata_map(&metadata.annotations, "$.metadata.annotations", violations);
}

fn validate_required_tenant(metadata: &ObjectMetadata, violations: &mut Vec<ManifestViolation>) {
    if metadata.tenant.is_none() {
        violations.push(ManifestViolation::new(
            "$.metadata.tenant",
            "missing-tenant",
            "standalone Phase 1 resources require an explicit tenant",
        ));
    }
}

fn validate_capsule_scope(manifest: &CapsuleManifest, violations: &mut Vec<ManifestViolation>) {
    let tenant = manifest
        .metadata
        .tenant
        .as_ref()
        .map(|tenant| tenant.0.as_str());
    validate_scoped_value(
        &manifest.metadata.name,
        tenant,
        "$.metadata.name",
        violations,
    );
    if let Some(tenant) = tenant {
        validate_contract_namespace(&manifest.world.0, tenant, "$.component.world", violations);
        for (index, export) in manifest.exports.iter().enumerate() {
            validate_contract_namespace(
                &export.contract.0,
                tenant,
                &format!("$.exports[{index}]"),
                violations,
            );
        }
    }
}

fn validate_wire_identity(id: &str, name: &str, violations: &mut Vec<ManifestViolation>) {
    if id != name {
        violations.push(ManifestViolation::new(
            "$.metadata.name",
            "identity-mismatch",
            "the domain ID must equal metadata.name because the JSON resource has one identity field",
        ));
    }
}

fn validate_digest(value: &str, path: &str, violations: &mut Vec<ManifestViolation>) {
    if !is_sha256_digest(value) {
        violations.push(ManifestViolation::new(
            path,
            "invalid-digest",
            "digest must use sha256: followed by exactly 64 hexadecimal characters",
        ));
    }
}

fn validate_semantic_version(value: &str, path: &str, violations: &mut Vec<ManifestViolation>) {
    if SemanticVersion::parse(value).is_none() {
        violations.push(ManifestViolation::new(
            path,
            "invalid-semantic-version",
            "value must be a valid Semantic Version 2.0.0 string",
        ));
    }
}

fn validate_minimum_fabric_version(value: &str, violations: &mut Vec<ManifestViolation>) {
    let Some(required) = SemanticVersion::parse(value) else {
        violations.push(ManifestViolation::new(
            "$.compatibility.minimumFabricVersion",
            "invalid-semantic-version",
            "minimumFabricVersion must be a valid Semantic Version 2.0.0 string",
        ));
        return;
    };
    let supported = SemanticVersion::parse(PHASE1_FABRIC_VERSION)
        .expect("the built-in Phase 1 fabric version is valid SemVer");
    if required > supported {
        violations.push(ManifestViolation::new(
            "$.compatibility.minimumFabricVersion",
            "unsupported-minimum-fabric-version",
            format!(
                "capsule requires fabric version `{value}`, but this contract supports `{PHASE1_FABRIC_VERSION}`"
            ),
        ));
    }
}

fn validate_stateless_budget(
    budget: &ResourceBudget,
    path: &str,
    violations: &mut Vec<ManifestViolation>,
) {
    if budget.state_read_bytes != 0 {
        violations.push(ManifestViolation::new(
            format!("{path}.stateReadBytes"),
            "invalid-stateless-budget",
            "stateless Phase 1 resources cannot grant state reads",
        ));
    }
    if budget.state_write_bytes != 0 {
        violations.push(ManifestViolation::new(
            format!("{path}.stateWriteBytes"),
            "invalid-stateless-budget",
            "stateless Phase 1 resources cannot grant state writes",
        ));
    }
}

fn validate_budget_ceiling(
    requested: &ResourceBudget,
    ceiling: &ResourceBudget,
    violations: &mut Vec<ManifestViolation>,
) {
    macro_rules! check_numeric {
        ($field:ident, $wire:literal) => {
            if requested.$field > ceiling.$field {
                violations.push(ManifestViolation::new(
                    concat!("$.spec.resources.", $wire),
                    "budget-exceeds-capsule",
                    concat!(
                        "deployment ",
                        $wire,
                        " ceiling exceeds the capsule-declared ceiling"
                    ),
                ));
            }
        };
    }

    check_numeric!(cpu_fuel, "cpuFuel");
    check_numeric!(memory_bytes, "memoryBytes");
    check_numeric!(child_calls, "childCalls");
    check_numeric!(outbound_requests, "outboundRequests");
    check_numeric!(state_read_bytes, "stateReadBytes");
    check_numeric!(state_write_bytes, "stateWriteBytes");
    check_numeric!(blob_read_bytes, "blobReadBytes");
    check_numeric!(blob_write_bytes, "blobWriteBytes");
    check_numeric!(log_bytes, "logBytes");
    check_numeric!(effect_count, "effectCount");

    if let Some(capsule_limit) = ceiling.wall_time_limit_millis {
        let exceeds = requested
            .wall_time_limit_millis
            .is_none_or(|deployment_limit| deployment_limit > capsule_limit);
        if exceeds {
            violations.push(ManifestViolation::new(
                "$.spec.resources.wallTimeLimitMillis",
                "budget-exceeds-capsule",
                "an absent or larger deployment wall-time ceiling cannot widen a finite capsule ceiling",
            ));
        }
    }
}

fn validate_contract_id(value: &str, path: &str, violations: &mut Vec<ManifestViolation>) {
    validate_resource_identifier(value, path, "contract ID", violations);
    let Some((base, version)) = value.rsplit_once('@') else {
        violations.push(ManifestViolation::new(
            path,
            "invalid-identifier",
            "contract ID must end with `@<semantic-version>`",
        ));
        return;
    };
    let Some((namespace, contract_path)) = base.split_once(':') else {
        violations.push(ManifestViolation::new(
            path,
            "invalid-identifier",
            "contract ID must contain a namespace followed by `:`",
        ));
        return;
    };
    validate_scope_component(namespace, path, "contract namespace", violations);
    if !contract_path.contains('/')
        || contract_path
            .split('/')
            .any(|segment| segment.is_empty() || segment == "." || segment == "..")
    {
        violations.push(ManifestViolation::new(
            path,
            "invalid-identifier",
            "contract ID path must contain non-empty package and interface segments",
        ));
    }
    validate_semantic_version(version, path, violations);
}

fn validate_contract_namespace(
    value: &str,
    expected: &str,
    path: &str,
    violations: &mut Vec<ManifestViolation>,
) {
    if value
        .split_once(':')
        .is_some_and(|(namespace, _)| namespace != expected)
    {
        violations.push(ManifestViolation::new(
            path,
            "tenant-scope-mismatch",
            "capsule-owned world and export contract namespaces must match metadata.tenant",
        ));
    }
}

fn validate_scoped_value(
    value: &str,
    expected_tenant: Option<&str>,
    path: &str,
    violations: &mut Vec<ManifestViolation>,
) {
    let explicit_scope = value.split_once('/').and_then(|(scope, remainder)| {
        (!scope.is_empty() && !remainder.is_empty()).then_some(scope)
    });
    match (explicit_scope, expected_tenant) {
        (Some(actual), Some(expected)) if actual != expected => {
            violations.push(ManifestViolation::new(
                path,
                "tenant-scope-mismatch",
                "identifier tenant prefix does not match metadata.tenant",
            ));
        }
        (Some(_), None) => violations.push(ManifestViolation::new(
            path,
            "tenant-scope-mismatch",
            "a tenant-qualified identifier requires metadata.tenant",
        )),
        _ => {}
    }
}

fn validate_optional_route(
    value: Option<&str>,
    path: &str,
    violations: &mut Vec<ManifestViolation>,
) {
    if let Some(value) = value {
        validate_token(value, path, "route", violations);
    }
}

fn validate_unique_tokens(
    values: &[String],
    path: &str,
    label: &str,
    violations: &mut Vec<ManifestViolation>,
) {
    let mut unique = BTreeSet::new();
    for (index, value) in values.iter().enumerate() {
        let item_path = format!("{path}[{index}]");
        validate_token(value, &item_path, label, violations);
        if !unique.insert(value.as_str()) {
            violations.push(ManifestViolation::new(
                item_path,
                "duplicate-item",
                format!("{label} values must be unique"),
            ));
        }
    }
}

fn validate_scope_component(
    value: &str,
    path: &str,
    label: &str,
    violations: &mut Vec<ManifestViolation>,
) {
    if value.is_empty()
        || value.len() > MAX_TOKEN_BYTES
        || value.trim() != value
        || !value.is_ascii()
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
        || !value
            .bytes()
            .next()
            .is_some_and(|byte| byte.is_ascii_alphanumeric())
        || !value
            .bytes()
            .last()
            .is_some_and(|byte| byte.is_ascii_alphanumeric())
    {
        violations.push(ManifestViolation::new(
            path,
            "invalid-identifier",
            format!(
                "{label} must be an ASCII token of at most {MAX_TOKEN_BYTES} bytes and may use internal '-', '_', or '.' characters"
            ),
        ));
    }
}

fn validate_token(value: &str, path: &str, label: &str, violations: &mut Vec<ManifestViolation>) {
    if value.is_empty()
        || value.len() > MAX_TOKEN_BYTES
        || value.trim() != value
        || !value.is_ascii()
        || value
            .bytes()
            .any(|byte| byte.is_ascii_control() || byte.is_ascii_whitespace())
    {
        violations.push(ManifestViolation::new(
            path,
            "invalid-identifier",
            format!(
                "{label} must be non-empty, ASCII, whitespace-free, and at most {MAX_TOKEN_BYTES} bytes"
            ),
        ));
    }
}

fn validate_resource_identifier(
    value: &str,
    path: &str,
    label: &str,
    violations: &mut Vec<ManifestViolation>,
) {
    let allowed = value.bytes().all(|byte| {
        byte.is_ascii_alphanumeric()
            || matches!(byte, b'-' | b'_' | b'.' | b'/' | b':' | b'@' | b'+')
    });
    let bad_segments = value
        .split('/')
        .any(|segment| segment.is_empty() || segment == "." || segment == "..");
    if value.is_empty()
        || value.len() > MAX_IDENTIFIER_BYTES
        || value.trim() != value
        || !value.is_ascii()
        || !allowed
        || bad_segments
    {
        violations.push(ManifestViolation::new(
            path,
            "invalid-identifier",
            format!(
                "{label} must be a canonical ASCII identifier of at most {MAX_IDENTIFIER_BYTES} bytes without whitespace or empty/path-traversal segments"
            ),
        ));
    }
}

fn validate_metadata_map(
    values: &std::collections::BTreeMap<String, String>,
    path: &str,
    violations: &mut Vec<ManifestViolation>,
) {
    for (key, value) in values {
        validate_resource_identifier(
            key,
            &format!("{path}[{}]", json_string(key)),
            "metadata key",
            violations,
        );
        if value.len() > MAX_METADATA_VALUE_BYTES || value.contains('\0') {
            violations.push(ManifestViolation::new(
                format!("{path}[{}]", json_string(key)),
                "invalid-metadata-value",
                format!(
                    "metadata values may not contain NUL and may use at most {MAX_METADATA_VALUE_BYTES} bytes"
                ),
            ));
        }
    }
}

fn json_string(value: &str) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "\"?\"".to_owned())
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct SemanticVersion {
    major: u64,
    minor: u64,
    patch: u64,
    prerelease: Vec<PrereleaseIdentifier>,
}

impl SemanticVersion {
    fn parse(value: &str) -> Option<Self> {
        if value.is_empty() || value.trim() != value || !value.is_ascii() {
            return None;
        }

        let mut build_split = value.split('+');
        let core_and_pre = build_split.next()?;
        if let Some(build) = build_split.next() {
            if build_split.next().is_some() || !valid_dot_identifiers(build, false) {
                return None;
            }
        }

        let (core, prerelease) = core_and_pre
            .split_once('-')
            .map_or((core_and_pre, None), |(core, prerelease)| {
                (core, Some(prerelease))
            });
        let mut core_parts = core.split('.');
        let major = parse_core_number(core_parts.next()?)?;
        let minor = parse_core_number(core_parts.next()?)?;
        let patch = parse_core_number(core_parts.next()?)?;
        if core_parts.next().is_some() {
            return None;
        }

        let prerelease = match prerelease {
            Some(value) => parse_prerelease(value)?,
            None => Vec::new(),
        };
        Some(Self {
            major,
            minor,
            patch,
            prerelease,
        })
    }
}

impl Ord for SemanticVersion {
    fn cmp(&self, other: &Self) -> Ordering {
        self.major
            .cmp(&other.major)
            .then_with(|| self.minor.cmp(&other.minor))
            .then_with(|| self.patch.cmp(&other.patch))
            .then_with(
                || match (self.prerelease.is_empty(), other.prerelease.is_empty()) {
                    (true, true) | (false, false) => self.prerelease.cmp(&other.prerelease),
                    (true, false) => Ordering::Greater,
                    (false, true) => Ordering::Less,
                },
            )
    }
}

impl PartialOrd for SemanticVersion {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum PrereleaseIdentifier {
    Numeric(u64),
    AlphaNumeric(String),
}

impl Ord for PrereleaseIdentifier {
    fn cmp(&self, other: &Self) -> Ordering {
        match (self, other) {
            (Self::Numeric(left), Self::Numeric(right)) => left.cmp(right),
            (Self::Numeric(_), Self::AlphaNumeric(_)) => Ordering::Less,
            (Self::AlphaNumeric(_), Self::Numeric(_)) => Ordering::Greater,
            (Self::AlphaNumeric(left), Self::AlphaNumeric(right)) => left.cmp(right),
        }
    }
}

impl PartialOrd for PrereleaseIdentifier {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

fn parse_core_number(value: &str) -> Option<u64> {
    if value.is_empty()
        || !value.bytes().all(|byte| byte.is_ascii_digit())
        || (value.len() > 1 && value.starts_with('0'))
    {
        return None;
    }
    value.parse().ok()
}

fn parse_prerelease(value: &str) -> Option<Vec<PrereleaseIdentifier>> {
    if !valid_dot_identifiers(value, true) {
        return None;
    }
    value
        .split('.')
        .map(|identifier| {
            if identifier.bytes().all(|byte| byte.is_ascii_digit()) {
                parse_core_number(identifier).map(PrereleaseIdentifier::Numeric)
            } else {
                Some(PrereleaseIdentifier::AlphaNumeric(identifier.to_owned()))
            }
        })
        .collect()
}

fn valid_dot_identifiers(value: &str, reject_numeric_leading_zero: bool) -> bool {
    !value.is_empty()
        && value.split('.').all(|identifier| {
            !identifier.is_empty()
                && identifier
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
                && (!reject_numeric_leading_zero
                    || !identifier.bytes().all(|byte| byte.is_ascii_digit())
                    || identifier.len() == 1
                    || !identifier.starts_with('0'))
        })
}
