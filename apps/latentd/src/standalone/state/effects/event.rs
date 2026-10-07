//! One existing qualified publisher under independent current native policies.
use super::*;
use latent_nats::deferred::JetStreamEffectAdapter;

pub(super) struct AuthorizedEvent {
    inner: JetStreamEffectAdapter,
    pub policies: Vec<DispatchPolicy>,
}

/// Capture the same actual adapter/reference for both startup inspection and
/// installation. This path creates no rule or dispatch permission by itself.
pub(super) fn prepare(
    settings: &NodeSettings,
    operation: &Arc<InstalledTransactionOperation>,
    providers: &ProviderRuntime,
    policy: &Arc<PolicyStore>,
    time: &Arc<dyn EffectTimeSource>,
) -> Result<
    (
        JetStreamEffectAdapter,
        latent_capabilities::broker::ProviderReference,
        DispatchPolicy,
    ),
    PlatformError,
> {
    let (selected, _) = operation
        .deferred_event
        .as_ref()
        .ok_or_else(super::super::denied)?;
    let installation = settings
        .providers
        .as_ref()
        .and_then(|p| p.events.as_ref())
        .ok_or_else(super::super::denied)?;
    if installation.identity.tenant != operation.target.tenant.0 {
        return Err(super::super::denied());
    }
    let (adapter, reference) =
        providers.captured_deferred_event(installation, &selected.topic, Arc::clone(time))?;
    let dispatch = DispatchPolicy::new_event(
        Arc::clone(operation),
        Arc::clone(policy),
        &adapter,
        &reference,
    )?;
    Ok((adapter, reference, dispatch))
}

pub(super) fn install(
    settings: &NodeSettings,
    operation: &Arc<InstalledTransactionOperation>,
    providers: &ProviderRuntime,
    policy: &Arc<PolicyStore>,
    authority: &EffectAuthorityOwner,
    time: &Arc<dyn EffectTimeSource>,
    deadline: Instant,
) -> Result<(AuthorizedEvent, InstalledIntent), PlatformError> {
    let (adapter, reference, dispatch) = prepare(settings, operation, providers, policy, time)?;
    let (selected, requirements) = operation
        .deferred_event
        .as_ref()
        .ok_or_else(super::super::denied)?;
    let staging = policy.snapshot(
        &operation.target.tenant,
        &selected.staging_policies,
        &selected.staging_binding,
        deadline,
    )?;
    staging.check_provider_configuration(
        latent_capabilities::namespace::INTENT_CONTRACT,
        &adapter.profile().adapter,
        reference.configuration_digest(),
        reference.configuration_epoch(),
    )?;
    let payload = IntentPayloadConstraint::bounded_event(
        reference.clone(),
        requirements.maximum_value_bytes,
        requirements.media_type.clone(),
    )?;
    dispatch.with_current(
        deadline,
        requirements.ceiling.maximum_payload_bytes,
        |generation| {
            let rule = adapter
                .rule(
                    dispatch.scope.clone(),
                    generation,
                    reference.configuration_epoch(),
                    requirements.ceiling,
                )
                .map_err(|_| super::super::denied())?;
            authority.publish(rule).map_err(|_| super::super::denied())
        },
    )?;
    let intent = InstalledIntent {
        operation: Arc::clone(operation),
        digest: reference.configuration_digest().into(),
        profile: adapter.profile().adapter.clone(),
        epoch: reference.configuration_epoch(),
        event_payload: Some(payload),
    };
    Ok((
        AuthorizedEvent {
            inner: adapter,
            policies: vec![dispatch],
        },
        intent,
    ))
}

impl DeferredEffectAdapter for AuthorizedEvent {
    fn profile(&self) -> &DispatchProfile {
        self.inner.profile()
    }
    fn with_current_dispatch(
        &self,
        authority: &DurableEffectAuthority,
        deadline: Instant,
        accept: &mut dyn FnMut() -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError>,
    ) -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError> {
        let policy = self
            .policies
            .iter()
            .find(|policy| &policy.scope == authority.scope())
            .ok_or(AuthorityError::PolicyBlocked)?;
        if authority.profile() != self.profile()
            || authority.payload_bytes() > policy.ceiling.maximum_payload_bytes
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        let mut accepted = None;
        policy
            .with_current(deadline, authority.payload_bytes(), |_| {
                accepted = Some(accept());
                Ok(())
            })
            .map_err(|_| AuthorityError::PolicyBlocked)?;
        accepted.ok_or(AuthorityError::PolicyBlocked)?
    }
    fn accept(
        &self,
        grant: DispatchGrant,
        payload: PayloadRecord,
        attempt: AttemptIdentity,
    ) -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError> {
        self.inner.accept(grant, payload, attempt)
    }
    fn qualify_redrive(
        &self,
        request: &latent_effects::runtime::ProviderReconciliationRequest,
        time: latent_effects::authority::EffectTime,
    ) -> Result<latent_effects::dispatch::RetryProof, AuthorityError> {
        self.inner.qualify_redrive(request, time)
    }
}
