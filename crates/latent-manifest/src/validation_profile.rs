//! Host-selected compatibility checks. A profile supplies no execution grant.

use latent_core::{BudgetProfile, HostAbiProfile, PHASE4_HOST_ABI_V1};

use crate::{
    finish_violations, phase4_host_abi_digest, BindingManifest, CapsuleManifest,
    DeploymentManifest, ManifestResult, ManifestValidator, ManifestViolation,
    Phase1ManifestValidator, PolicyManifest, ThreadingModel, TriggerManifest,
};

/// Explicit supported accounting/preparation selection, never decoded from a
/// manifest or companion asset. The default retains the stateless validator.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ManifestValidationProfile {
    transactional: bool,
}

impl ManifestValidationProfile {
    /// Called by a trusted host only after selecting its actual preparation ABI
    /// and accounting profile. Compatibility does not prove provider availability
    /// or confer namespace, result-read, execution or dispatch authority.
    pub fn phase4(
        accounting: BudgetProfile,
        preparation_abi: HostAbiProfile,
        host_abi_digest: &str,
    ) -> ManifestResult<Self> {
        if accounting != BudgetProfile::Phase4
            || preparation_abi != PHASE4_HOST_ABI_V1
            || host_abi_digest != phase4_host_abi_digest()
        {
            return Err(vec![violation(
                "$.compatibility",
                "unsupported-transaction-preparation-profile",
            )]);
        }
        Ok(Self {
            transactional: true,
        })
    }

    #[must_use]
    pub const fn transactional(self) -> bool {
        self.transactional
    }

    /// Web execution never inherits transaction state from a catalog selection.
    pub fn validate_web_execution_projection(
        &self,
        deployment: &DeploymentManifest,
        capsule: &CapsuleManifest,
    ) -> ManifestResult<()> {
        Phase1ManifestValidator.validate_web_execution_projection(deployment, capsule)
    }

    fn capsule_profile(self, capsule: &CapsuleManifest) -> ManifestResult<()> {
        let budget = &capsule.execution.resource_budget_ceiling;
        let state_requested = budget.state_read_bytes != 0 || budget.state_write_bytes != 0;
        let transaction_import = capsule.imports.iter().any(|import| {
            import.contract.0.starts_with("latent:state/")
                || import.contract.0.starts_with("latent:intents/")
        });
        if !self.transactional || (!state_requested && !transaction_import) {
            return Phase1ManifestValidator.validate_capsule(capsule);
        }
        let mut violations = Vec::new();
        let required_state = capsule
            .imports
            .iter()
            .any(|import| import.contract.0 == "latent:state/key-value@0.2.0" && !import.optional);
        if !required_state {
            violations.push(violation("$.imports", "transaction-state-import-required"));
        }
        for (index, import) in capsule.imports.iter().enumerate() {
            // This supported HTTP ABI remains available for signature and value
            // preparation. Its presence never authorizes an immediate send.
            let recognized = PHASE4_HOST_ABI_V1.interface(&import.contract.0).is_some()
                || import.contract.0 == "latent:http/client@0.2.0";
            if import.optional || !recognized {
                violations.push(violation(
                    &format!("$.imports[{index}]"),
                    "unsupported-transaction-host-import",
                ));
            }
        }
        if capsule.execution.threading != ThreadingModel::SingleThreaded
            || capsule.execution.snapshot_eligible
            || capsule.execution.fusion_eligible
            || capsule.runtime_requirements.renderer.is_some()
        {
            violations.push(violation(
                "$.execution",
                "unsupported-transaction-execution-profile",
            ));
        }
        // Immediate application effects and synchronous descendants cannot be
        // admitted merely because another supported stateless world uses them.
        if budget.child_calls != 0
            || budget.outbound_requests != 0
            || budget.blob_read_bytes != 0
            || budget.blob_write_bytes != 0
            || budget.cpu_fuel == 0
            || budget.memory_bytes == 0
            || budget
                .wall_time_limit_millis
                .is_none_or(|millis| millis == 0)
        {
            violations.push(violation(
                "$.execution.limits",
                "invalid-transaction-budget",
            ));
        }
        append_state_profile(
            &mut violations,
            Phase1ManifestValidator.validate_capsule(capsule),
        );
        finish_violations(violations)
    }
}

impl ManifestValidator for ManifestValidationProfile {
    fn validate_capsule(&self, manifest: &CapsuleManifest) -> ManifestResult<()> {
        self.capsule_profile(manifest)
    }

    fn validate_deployment(&self, manifest: &DeploymentManifest) -> ManifestResult<()> {
        let result = Phase1ManifestValidator.validate_deployment(manifest);
        if !self.transactional {
            return result;
        }
        let mut violations = Vec::new();
        append_state_profile(&mut violations, result);
        finish_violations(violations)
    }

    fn validate_binding(&self, manifest: &BindingManifest) -> ManifestResult<()> {
        Phase1ManifestValidator.validate_binding(manifest)
    }
    fn validate_trigger(&self, manifest: &TriggerManifest) -> ManifestResult<()> {
        Phase1ManifestValidator.validate_trigger(manifest)
    }
    fn validate_policy(&self, manifest: &PolicyManifest) -> ManifestResult<()> {
        Phase1ManifestValidator.validate_policy(manifest)
    }

    fn validate_deployment_against_capsule(
        &self,
        deployment: &DeploymentManifest,
        capsule: &CapsuleManifest,
    ) -> ManifestResult<()> {
        if !self.transactional {
            return Phase1ManifestValidator
                .validate_deployment_against_capsule(deployment, capsule);
        }
        let mut violations = Vec::new();
        if let Err(mut rejected) = self.capsule_profile(capsule) {
            violations.append(&mut rejected);
        }
        append_state_profile(
            &mut violations,
            Phase1ManifestValidator.validate_deployment_against_capsule(deployment, capsule),
        );
        finish_violations(violations)
    }
}

fn append_state_profile(violations: &mut Vec<ManifestViolation>, result: ManifestResult<()>) {
    if let Err(rejected) = result {
        violations.extend(rejected.into_iter().filter(|violation| {
            !(violation.code == "invalid-stateless-budget"
                && matches!(
                    violation.path.as_str(),
                    "$.execution.limits.stateReadBytes"
                        | "$.execution.limits.stateWriteBytes"
                        | "$.spec.resources.stateReadBytes"
                        | "$.spec.resources.stateWriteBytes"
                ))
        }));
    }
}

fn violation(path: &str, code: &str) -> ManifestViolation {
    ManifestViolation::new(
        path,
        code,
        "the selected host transaction profile is incompatible",
    )
}

#[cfg(test)]
mod tests;
