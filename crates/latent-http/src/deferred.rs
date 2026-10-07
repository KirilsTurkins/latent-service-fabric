//! One explicitly qualified HTTP operation on the installed bounded provider.
//! The operator approves atomic idempotency and lookup semantics; arbitrary
//! HTTP APIs cannot acquire this profile through a header or guest URL.

mod attempt;
mod codec;
mod qualification;
mod request;
#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
mod tests;
pub use qualification::QualifiedHttpEndpoint;

use crate::{credentials::HashWriter, protocol::ProtocolTransport, HttpError, HttpProvider};
use latent_capabilities::broker::pools::ProviderMetadata;
use latent_core::BoxFuture;
use latent_effects::{
    authority::{
        AuthorityError, DispatchCeiling, DispatchGrant, DispatchProfile, DispatchPurpose,
        EffectRule, EffectScope,
    },
    dispatch::AttemptIdentity,
    payload::PayloadRecord,
    runtime::{
        AdapterOutcome, DeferredEffectAdapter, EffectTimeSource, ProviderReconciliationOutcome,
        ProviderReconciliationRequest,
    },
};
use sha2::{Digest, Sha256};
use std::sync::Arc;

pub const HTTP_DEFERRED_PROFILE: &str = "qualified-http-effect-v1";

/// Reuses the exact immediate provider, TLS configuration, opaque credential
/// binding and provider pools. It creates no activation, worker or new engine.
pub struct HttpEffectAdapter {
    provider: HttpProvider,
    transport: ProtocolTransport,
    endpoint: Arc<QualifiedHttpEndpoint>,
    tenant: String,
    profile: DispatchProfile,
    time: Arc<dyn EffectTimeSource>,
    _metadata: ProviderMetadata,
}

impl HttpProvider {
    pub fn deferred_adapter(
        &self,
        tenant: &str,
        endpoint: QualifiedHttpEndpoint,
        time: Arc<dyn EffectTimeSource>,
    ) -> Result<HttpEffectAdapter, AuthorityError> {
        endpoint
            .validate(&self.inner.config)
            .map_err(authority_error)?;
        if self.inner.streaming.is_some()
            || tenant.is_empty()
            || tenant.len() > 128
            || self.inner.credential_references.len() != 1
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        let credential = &self.inner.credential_references[0];
        if credential.destination != 0
            || !credential.name.eq_ignore_ascii_case("authorization")
            || credential.binding.scope().tenant.0 != tenant
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        let metadata = self
            .inner
            .pools
            .reserve_protocol_metadata(4096)
            .map_err(|error| authority_error(error.into()))?;
        let transport =
            ProtocolTransport::from_http_provider(&self.inner).map_err(authority_error)?;
        let mut hash = HashWriter(Sha256::new());
        hash.0.update(b"lsf-qualified-http-effect-v1\0");
        serde_json::to_writer(
            &mut hash,
            &(
                &self.inner.config,
                &endpoint,
                tenant,
                credential.binding.reference(),
            ),
        )
        .map_err(|_| AuthorityError::Invalid)?;
        let profile = DispatchProfile {
            provider: self.inner.installed.logical_id().into(),
            destination: format!(
                "https://{}:{}{}",
                endpoint.origin.host, endpoint.origin.port, endpoint.operation_path
            ),
            adapter: HTTP_DEFERRED_PROFILE.into(),
            intent_format: 1,
            payload_format: "http-body-value-v1".into(),
            idempotency_profile: format!(
                "qualified-http-v1:{:x}",
                latent_core::digest::HexDigest(hash.0.finalize())
            ),
        };
        Ok(HttpEffectAdapter {
            provider: self.clone(),
            transport,
            endpoint: Arc::new(endpoint),
            tenant: tenant.into(),
            profile,
            time,
            _metadata: metadata,
        })
    }
}

impl DeferredEffectAdapter for HttpEffectAdapter {
    fn profile(&self) -> &DispatchProfile {
        &self.profile
    }

    fn accept(
        &self,
        grant: DispatchGrant,
        payload: PayloadRecord,
        attempt: AttemptIdentity,
    ) -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError> {
        grant.require_execution()?;
        let lookup = attempt.attempt() > 1;
        let accepted = self.accept_operation(grant, payload, attempt, lookup, true)?;
        Ok(Box::pin(accepted.run()))
    }

    fn accept_reconciliation(
        &self,
        grant: DispatchGrant,
        request: ProviderReconciliationRequest,
    ) -> Result<BoxFuture<'static, ProviderReconciliationOutcome>, AuthorityError> {
        if grant.scope() != request.authority().scope()
            || grant.profile() != request.authority().profile()
            || grant.effect() != request.authority().link().effect
        {
            return Err(AuthorityError::Invalid);
        }
        let (payload, attempt, version) = request.into_parts();
        let accepted = self.accept_operation(grant, payload, attempt, true, false)?;
        Ok(Box::pin(accepted.reconcile(version)))
    }
}

impl HttpEffectAdapter {
    fn accept_operation(
        &self,
        grant: DispatchGrant,
        payload: PayloadRecord,
        attempt: AttemptIdentity,
        lookup: bool,
        retry_enabled: bool,
    ) -> Result<attempt::AcceptedOperation, AuthorityError> {
        if grant.purpose() == DispatchPurpose::ReconcileOnly && (!lookup || retry_enabled) {
            return Err(AuthorityError::PolicyBlocked);
        }
        let horizon = self.check_grant(&grant, &payload, &attempt)?;
        let value = payload.into_value();
        let response_bytes = usize::try_from(qualification::RESPONSE_RESERVATION_BYTES)
            .map_err(|_| AuthorityError::Capacity)?;
        let retained = value
            .bytes
            .capacity()
            .checked_add(value.media_type.capacity())
            .and_then(|bytes| bytes.checked_add(8192 + response_bytes))
            .ok_or(AuthorityError::Capacity)?;
        let request = self
            .transport
            .deferred(grant, retained)
            .map_err(authority_error)?;
        let body_digest = format!(
            "{:x}",
            latent_core::digest::HexDigest(Sha256::digest(&value.bytes))
        );
        Ok(attempt::AcceptedOperation {
            provider: self.provider.clone(),
            transport: self.transport.clone(),
            endpoint: Arc::clone(&self.endpoint),
            time: Arc::clone(&self.time),
            value,
            body_digest,
            request,
            attempt,
            horizon,
            lookup,
            retry_enabled,
        })
    }
    /// Current policy still decides whether to publish this trusted metadata.
    pub fn rule(
        &self,
        scope: EffectScope,
        policy_revision: u64,
        credential_epoch: u64,
        ceiling: DispatchCeiling,
    ) -> Result<EffectRule, AuthorityError> {
        if scope.tenant != self.tenant
            || scope.operation != "http"
            || ceiling.maximum_payload_bytes > self.endpoint.maximum_payload_bytes as u64
            || ceiling.maximum_response_bytes < qualification::RESPONSE_RESERVATION_BYTES
            || ceiling.maximum_age_millis > self.endpoint.retention_millis
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        Ok(EffectRule {
            scope,
            profile: self.profile.clone(),
            policy_revision,
            credential_epoch,
            protected_credential_reference: self.provider.inner.credential_references[0]
                .binding
                .reference()
                .into(),
            ceiling,
            enabled: true,
        })
    }

    fn check_grant(
        &self,
        grant: &DispatchGrant,
        payload: &PayloadRecord,
        attempt: &AttemptIdentity,
    ) -> Result<u64, AuthorityError> {
        if grant.profile() != &self.profile
            || grant.scope().tenant != self.tenant
            || grant.scope().operation != "http"
            || grant.effect() != attempt.effect()
            || grant.attempt() != attempt.attempt()
            || grant.protected_credential_reference()
                != self.provider.inner.credential_references[0]
                    .binding
                    .reference()
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        payload.verify_grant(grant)?;
        let value = payload.value();
        if !value.metadata.is_empty()
            || value.media_type != self.endpoint.media_type
            || value.bytes.capacity() > self.endpoint.maximum_payload_bytes
        {
            return Err(AuthorityError::Invalid);
        }
        if grant.ceiling().maximum_response_bytes < qualification::RESPONSE_RESERVATION_BYTES {
            return Err(AuthorityError::Capacity);
        }
        let retained_until = grant
            .committed_at_millis()
            .checked_add(self.endpoint.retention_millis)
            .ok_or(AuthorityError::Invalid)?;
        let horizon = match grant.purpose() {
            DispatchPurpose::Execute => retained_until.min(grant.expires_at_millis()),
            DispatchPurpose::ReconcileOnly => retained_until,
        };
        // accept_with holds the effect time fence. Observing a role-owning
        // clock here would reverse Role -> Effect lock order. Polling and
        // prewrite recheck that same clock outside this acceptance fence.
        if grant.purpose() == DispatchPurpose::Execute
            && attempt
                .retry_horizon_millis()
                .is_some_and(|original| original > horizon)
        {
            return Err(AuthorityError::Expired);
        }
        Ok(horizon)
    }
}

fn authority_error(error: HttpError) -> AuthorityError {
    match error {
        HttpError::InvalidRequest | HttpError::InvalidUrl | HttpError::RequestTooLarge => {
            AuthorityError::Invalid
        }
        HttpError::PermissionDenied => AuthorityError::PolicyBlocked,
        HttpError::BudgetExhausted | HttpError::ResponseTooLarge => AuthorityError::Capacity,
        HttpError::DeadlineExceeded => AuthorityError::Expired,
        _ => AuthorityError::Unavailable,
    }
}
