//! Fresh policy intersection with the original captured namespace decision.
use latent_artifacts::ReleaseUseEligibility;
use latent_capabilities::namespace::{NamespaceAuthority, INTENT_CONTRACT, STATE_CONTRACT};
use latent_core::{ActivationBudget, InvocationPrincipal, PlatformError, PlatformErrorCode};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, GrantRestriction, PolicyStore,
    ResourceTarget,
};
use latent_state::namespace::catalog::NamespaceRead;
use std::{sync::Arc, time::Instant};

/// Descriptive installed binding constraints; the actual policy owner must
/// match every profile/configuration/revision before granting an operation.
pub struct PolicyCallBinding {
    pub policies: Vec<String>,
    pub binding: String,
    pub profile: String,
    pub configuration_digest: String,
    pub configuration_epoch: u64,
    pub operations: Vec<String>,
    pub deployment: GrantRestriction,
    pub provider_configuration: GrantRestriction,
}

/// Exact signed logical intent selection. Installed metadata narrows the
/// current caller's staging policy; it never creates a dispatch grant.
pub struct IntentPolicyBinding {
    pub call: PolicyCallBinding,
    pub binding: String,
    pub operation: String,
    pub maximum_intents: u32,
    pub payload_digest: String,
}

pub struct StateAuthorization {
    policy: Arc<PolicyStore>,
    pub(super) authority: Arc<NamespaceAuthority>,
    pub(super) namespace: Arc<NamespaceRead>,
    principal: InvocationPrincipal,
    service: String,
    publication: ReleaseUseEligibility,
    state: Arc<PolicyCallBinding>,
    intents: Option<Arc<IntentPolicyBinding>>,
    initial_intent: Option<Arc<latent_policy::capability::OwnedPolicyDecision>>,
    pub(super) budget: ActivationBudget,
}
impl StateAuthorization {
    pub(crate) fn authority_mode(&self) -> latent_capabilities::namespace::Mode {
        self.authority.mode()
    }
    #[must_use]
    pub fn activation_id(&self) -> &latent_core::ActivationId {
        self.authority.activation_id()
    }
    #[must_use]
    pub fn budget(&self) -> &ActivationBudget {
        &self.budget
    }
    #[must_use]
    pub(crate) fn cancellation(&self) -> latent_capabilities::namespace::CommitCancellation {
        self.authority.cancellation()
    }
    pub(super) fn publication(&self) -> &str {
        self.publication.publication().as_str()
    }
    #[allow(
        clippy::too_many_arguments,
        reason = "Trusted admission supplies each independent real owner"
    )]
    pub fn new(
        policy: Arc<PolicyStore>,
        authority: Arc<NamespaceAuthority>,
        namespace: NamespaceRead,
        principal: InvocationPrincipal,
        service: String,
        publication: ReleaseUseEligibility,
        state: PolicyCallBinding,
        intents: Option<IntentPolicyBinding>,
        budget: ActivationBudget,
    ) -> Result<Self, PlatformError> {
        let scope = authority.ownership();
        if principal.tenant.as_ref() != Some(&scope.tenant)
            || principal.subject != scope.caller.owner_subject
            || namespace.record().tenant != scope.tenant
            || namespace.record().id.0 != scope.namespace
            || namespace.record().version != authority.version()
            || publication.publication().as_str().is_empty()
            || budget.profile() != latent_core::BudgetProfile::Phase4
            || authority.requires_audit()
        {
            return Err(denied());
        }
        validate_bindings(&state, intents.as_ref(), &service)?;
        let mut admitted = Self {
            policy,
            authority,
            namespace: Arc::new(namespace),
            principal,
            service,
            publication,
            state: Arc::new(state),
            intents: intents.map(Arc::new),
            initial_intent: None,
            budget,
        };
        if admitted.authority_mode() == latent_capabilities::namespace::Mode::Command
            && admitted.intents.is_some()
        {
            admitted.initial_intent = Some(Arc::new(admitted.with_current_decision(
                "stage",
                0,
                0,
                |decision| admitted.policy.retain_decision(decision),
            )?));
        }
        Ok(admitted)
    }

    pub(super) fn authorize(
        &self,
        operation: &str,
        input_bytes: usize,
        output_bytes: usize,
        action: impl FnOnce() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.with_current_decision(operation, input_bytes, output_bytes, |decision| {
            let retained = if operation == "stage" {
                self.initial_intent
                    .as_deref()
                    .into_iter()
                    .collect::<Vec<_>>()
            } else {
                Vec::new()
            };
            self.authority.with_operation_retained(
                &self.policy,
                decision,
                &self.namespace,
                operation,
                &retained,
                action,
            )
        })
    }

    pub(super) fn check_intent_selection(
        &self,
        intent: &latent_executor::transaction::Intent,
        sequence: u32,
    ) -> Result<(), PlatformError> {
        let selected = self.intents.as_ref().ok_or_else(denied)?;
        if intent.binding != selected.binding
            || intent.operation != selected.operation
            || sequence >= selected.maximum_intents
            || intent.expires_at_unix_millis.is_some()
            || latent_effects::payload::payload_digest(&intent.payload).map_err(|_| denied())?
                != selected.payload_digest
        {
            return Err(denied());
        }
        Ok(())
    }

    pub(super) fn rebind_command_after_claim(
        &self,
        claim: &latent_commit::atomic::AdmittedCommand,
        namespace: NamespaceRead,
    ) -> Result<Self, PlatformError> {
        let authority = self.authority.rebind_command_after_claim(
            &self.policy,
            claim,
            &self.namespace,
            &namespace,
        )?;
        Ok(self.with_namespace(authority, namespace))
    }

    pub(super) fn rebind_result_read(
        &self,
        namespace: NamespaceRead,
    ) -> Result<Self, PlatformError> {
        let authority = self
            .authority
            .rebind_result_read(&self.policy, &namespace)?;
        Ok(self.with_namespace(authority, namespace))
    }

    pub(super) fn rebind_query_delivery(
        &self,
        namespace: NamespaceRead,
    ) -> Result<Self, PlatformError> {
        let authority =
            self.authority
                .rebind_query_delivery(&self.policy, &self.namespace, &namespace)?;
        Ok(self.with_namespace(authority, namespace))
    }

    fn with_namespace(&self, authority: NamespaceAuthority, namespace: NamespaceRead) -> Self {
        Self {
            policy: Arc::clone(&self.policy),
            authority: Arc::new(authority),
            namespace: Arc::new(namespace),
            principal: self.principal.clone(),
            service: self.service.clone(),
            publication: self.publication.clone(),
            state: Arc::clone(&self.state),
            intents: self.intents.clone(),
            initial_intent: self.initial_intent.clone(),
            budget: self.budget.clone(),
        }
    }

    pub(super) fn accepts_record(
        &self,
        record: &latent_commit::atomic::CommandRecord,
    ) -> Result<(), PlatformError> {
        let ownership = self.authority.ownership();
        if record.key().tenant != ownership.tenant.0
            || record.key().namespace != ownership.namespace
            || record.key().incarnation != ownership.incarnation.to_string()
            || record.key().entity != ownership.entity
            || record.key().recovery_scope != ownership.caller.scope
            || record.source().publication != self.publication()
            || record.source().state_schema != self.namespace.record().state_schema
            || record.result_read_policy() != ownership.result_policy
        {
            return Err(denied());
        }
        Ok(())
    }

    pub(super) fn accepts_envelope(
        &self,
        envelope: &latent_activation::ActivationEnvelope,
        budget: &ActivationBudget,
        input: &latent_commit::atomic::AdmissionInput,
    ) -> Result<(), PlatformError> {
        let revision = envelope.resolved_revision.as_ref().ok_or_else(denied)?;
        if envelope.activation_id != *self.activation_id()
            || envelope.principal != self.principal
            || !budget.is_same_instance(&self.budget)
            || revision
                .publication
                .as_ref()
                .map(latent_core::PublicationId::as_str)
                != Some(self.publication())
            || revision.revision.0 != input.source.revision
            || revision.release.0 != input.source.release_digest
            || revision.route_generation.0 != input.source.route_generation
        {
            return Err(denied());
        }
        // HTTP factories supply their reviewed canonical request fingerprint.
        // Ordinary typed commands bind the exact admitted application bytes.
        if input.source.input_format == "lsf-wit-values-v1"
            && (input.fingerprint.input.bytes != envelope.input
                || input.fingerprint.input.media_type != envelope.input_media_type)
        {
            return Err(denied());
        }
        Ok(())
    }

    pub(super) fn accept_commit(
        &self,
        envelope: &latent_commit::atomic::EnvelopeNamespaceExpectation,
        effects: Option<&latent_effects::authority::EffectAuthorityOwner>,
        authorities: &[latent_effects::authority::DurableEffectAuthority],
        time: latent_commit::atomic::CommandTime,
    ) -> Result<(), PlatformError> {
        use latent_state::namespace::NamespaceError;
        self.with_current_decision("commit", 0, 0, |decision| {
            let mut acceptance = self.authority.prepare_envelope_commit_io(
                &self.policy,
                decision,
                &self.namespace,
                envelope,
            )?;
            if !authorities.is_empty() {
                acceptance =
                    acceptance.retain_policy(self.initial_intent.as_deref().ok_or_else(denied)?)?;
            }
            acceptance
                .accept_with(|| {
                    if let Some(effects) = effects {
                        effects
                            .commit_fence(
                                authorities,
                                latent_effects::authority::EffectTime {
                                    unix_millis: time.unix_millis,
                                    continuity_proven: time.continuity_proven,
                                },
                            )
                            .map(Some)
                            .map_err(|_| NamespaceError::PermissionDenied)
                    } else if authorities.is_empty() {
                        Ok(None)
                    } else {
                        Err(NamespaceError::PermissionDenied)
                    }
                })
                .map_err(|_| denied())
        })
    }

    pub(super) fn accept_abort(
        &self,
        envelope: &latent_commit::atomic::EnvelopeNamespaceExpectation,
    ) -> Result<(), PlatformError> {
        self.with_current_decision("cancel-command", 0, 0, |decision| {
            self.authority
                .accept_terminal_abort(&self.policy, decision, &self.namespace, envelope)
        })
    }

    fn with_current_decision<R>(
        &self,
        operation: &str,
        input_bytes: usize,
        output_bytes: usize,
        action: impl FnOnce(
            &latent_policy::capability::SealedPolicyDecision<'_>,
        ) -> Result<R, PlatformError>,
    ) -> Result<R, PlatformError> {
        let intent = operation == "stage";
        let binding = if intent {
            &self.intents.as_ref().ok_or_else(denied)?.call
        } else {
            &self.state
        };
        let now = Instant::now();
        if self.budget.deadline().is_expired_at(now) || self.budget.descendant_is_cancelled() {
            return Err(denied());
        }
        // Current data permission also fences already-owned terminal buffers
        // after guest accounting freezes. This creates no execution allocation;
        // actual byte/call counters remain charged by the original host ledger.
        let remaining = self.budget.granted();
        let wall_time_millis = u64::try_from(
            self.budget
                .deadline()
                .remaining_at(now)
                .ok_or_else(denied)?
                .as_millis(),
        )
        .map_err(|_| denied())?
        .min(30_000);
        if wall_time_millis == 0 {
            return Err(denied());
        }
        let snapshot = self.policy.snapshot(
            &self.authority.ownership().tenant,
            &binding.policies,
            &binding.binding,
            now + std::time::Duration::from_millis(wall_time_millis),
        )?;
        let ownership = self.authority.ownership();
        let decision = snapshot.authorize(
            EvaluationInput {
                principal: &self.principal,
                service: &self.service,
                publication: self.publication.publication().as_str(),
                capability: if intent {
                    INTENT_CONTRACT
                } else {
                    STATE_CONTRACT
                },
                operation,
                resource: ResourceTarget::State {
                    namespace: &ownership.namespace,
                    incarnation: ownership.incarnation,
                    entity: ownership.entity.as_deref(),
                    recovery_kind: ownership.caller.kind,
                    recovery_scope: &ownership.caller.scope,
                    result_policy: &ownership.result_policy,
                },
            },
            &CallRestrictions {
                imported_operations: &binding.operations,
                deployment: &binding.deployment,
                provider_configuration: &binding.provider_configuration,
                provider_profile: &binding.profile,
                configuration_digest: &binding.configuration_digest,
                configuration_epoch: binding.configuration_epoch,
                remaining: CapabilityCeiling {
                    operations: 256,
                    input_bytes: remaining
                        .state_read_bytes
                        .max(remaining.state_write_bytes)
                        .min(2_097_152),
                    output_bytes: remaining.state_read_bytes.min(2_097_152),
                    wall_time_millis,
                },
                input_bytes: u64::try_from(input_bytes).map_err(|_| denied())?,
                output_bytes: u64::try_from(output_bytes).map_err(|_| denied())?,
            },
            &self.publication,
        )?;
        if decision.requires_audit() {
            // A descriptive flag cannot stand in for a durable audit receipt.
            // The audit-enabled runtime must install an actual reservation owner.
            return Err(denied());
        }
        action(&decision)
    }
}

fn validate_bindings(
    state: &PolicyCallBinding,
    intents: Option<&IntentPolicyBinding>,
    service: &str,
) -> Result<(), PlatformError> {
    if let Some(intent) = intents {
        latent_core::transaction_contract::identity(&intent.binding).map_err(|_| denied())?;
        latent_core::transaction_contract::identity(&intent.operation).map_err(|_| denied())?;
        if !(1..=128).contains(&intent.maximum_intents)
            || intent.payload_digest.len() != 71
            || !intent.payload_digest.starts_with("sha256:")
            || !intent.payload_digest[7..]
                .bytes()
                .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
        {
            return Err(denied());
        }
    }
    for binding in std::iter::once(state).chain(intents.map(|intent| &intent.call)) {
        if binding.policies.is_empty()
            || binding.policies.len() > 8
            || binding.operations.is_empty()
            || binding.operations.len() > 16
            || binding.configuration_epoch == 0
        {
            return Err(denied());
        }
        for text in binding
            .policies
            .iter()
            .chain(binding.operations.iter())
            .map(String::as_str)
            .chain([
                binding.binding.as_str(),
                binding.profile.as_str(),
                binding.configuration_digest.as_str(),
                service,
            ])
        {
            latent_core::transaction_contract::identity(text).map_err(|_| denied())?;
        }
    }
    Ok(())
}

pub(super) fn denied() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::PermissionDenied,
        message: "namespace-access-denied".into(),
        retryable: false,
        details: Vec::new(),
    }
}
