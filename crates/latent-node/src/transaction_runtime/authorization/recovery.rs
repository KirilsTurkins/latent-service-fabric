//! Fresh metadata authority consumes retirement; it never publishes a guest host.
use super::*;
use latent_capabilities::namespace::{NamespaceAdmission, RecoverySelection};
use latent_state::namespace::catalog::NamespaceCatalog;

impl StateAuthorization {
    pub(crate) fn fresh_abort_authority(
        &self,
        namespace: NamespaceRead,
        namespaces: &NamespaceCatalog,
        recovery: &RecoverySelection,
    ) -> Result<Arc<Self>, PlatformError> {
        let now = Instant::now();
        let deadline = self
            .budget
            .deadline()
            .monotonic()
            .ok_or_else(denied)?
            .min(self.authority.deadline());
        let ownership = self.authority.ownership();
        if self.budget.retained_authority_is_cancelled_at(now)
            || now >= deadline
            || namespace.record().tenant != ownership.tenant
            || namespace.record().id.0 != ownership.namespace
            || namespace.record().version.incarnation != ownership.incarnation
            || namespace.record().state_schema != self.namespace.record().state_schema
        {
            return Err(denied());
        }
        let retained = self.retention.as_ref().ok_or_else(denied)?;
        retained.check_current()?;
        let snapshot = self.policy.snapshot(
            &ownership.tenant,
            &self.state.policies,
            &self.state.binding,
            deadline,
        )?;
        let decision = snapshot.authorize(
            EvaluationInput {
                principal: &self.principal,
                service: &self.service,
                publication: self.publication.publication().as_str(),
                capability: STATE_CONTRACT,
                operation: "acquire-command",
                resource: ResourceTarget::State {
                    namespace: &ownership.namespace,
                    incarnation: ownership.incarnation,
                    entity: ownership.entity.as_deref(),
                    recovery_kind: ownership.caller.kind,
                    recovery_scope: &ownership.caller.scope,
                    result_policy: &ownership.result_policy,
                },
            },
            &self.abort_restrictions(now, deadline)?,
            &self.publication,
        )?;
        if decision.requires_audit() {
            return Err(denied());
        }
        // Preserve the exact originally captured permission as well as its
        // numeric ceilings. A later broader grant cannot renew this attempt.
        self.authority.with_operation(
            &self.policy,
            &decision,
            &self.namespace,
            "acquire-command",
            || Ok(()),
        )?;
        self.seal_abort_authority(namespace, namespaces, recovery, deadline, &decision)
    }

    fn seal_abort_authority(
        &self,
        namespace: NamespaceRead,
        namespaces: &NamespaceCatalog,
        recovery: &RecoverySelection,
        deadline: Instant,
        decision: &SealedPolicyDecision<'_>,
    ) -> Result<Arc<Self>, PlatformError> {
        let lifecycle = namespaces
            .lifecycle()
            .pin(&namespace)
            .map_err(|_| denied())?;
        let authority = NamespaceAuthority::seal(
            &self.policy,
            decision,
            &namespace,
            NamespaceAdmission {
                activation: self.authority.activation_id().clone(),
                deadline,
                recovery,
                state_schema: &namespace.record().state_schema,
            },
            lifecycle,
        )?;
        let authorization = Self::new(
            Arc::clone(&self.policy),
            Arc::new(authority),
            namespace,
            self.principal.clone(),
            self.service.clone(),
            self.publication.clone(),
            Arc::clone(&self.state),
            self.intents.clone(),
            self.budget.clone(),
        )?
        .with_retention(Arc::clone(self.retention.as_ref().ok_or_else(denied)?))
        .with_entity(self.entity.clone());
        // Frozen original accounting remains frozen. This authority stays
        // private to the metadata writer and the original result response.
        Ok(Arc::new(authorization))
    }

    fn abort_restrictions(
        &self,
        now: Instant,
        deadline: Instant,
    ) -> Result<CallRestrictions<'_>, PlatformError> {
        let remaining = self.budget.granted();
        let original = self.authority.ceiling();
        Ok(CallRestrictions {
            imported_operations: &self.state.operations,
            deployment: &self.state.deployment,
            provider_configuration: &self.state.provider_configuration,
            provider_profile: &self.state.profile,
            configuration_digest: &self.state.configuration_digest,
            configuration_epoch: self.state.configuration_epoch,
            remaining: CapabilityCeiling {
                operations: original.operations.min(256),
                input_bytes: remaining
                    .state_read_bytes
                    .max(remaining.state_write_bytes)
                    .min(original.input_bytes)
                    .min(2_097_152),
                output_bytes: remaining
                    .state_read_bytes
                    .min(original.output_bytes)
                    .min(2_097_152),
                wall_time_millis: u64::try_from(
                    deadline.saturating_duration_since(now).as_millis(),
                )
                .map_err(|_| denied())?
                .min(original.wall_time_millis)
                .min(30_000),
            },
            input_bytes: 0,
            output_bytes: 0,
        })
    }
}
