//! Committed event delivery through the maintained NATS TLS transport and pools.
//! This profile is unordered and qualifies a finite stream duplicate window.

mod attempt;
mod qualification;
mod redrive;
pub use qualification::JetStreamQualification;

use crate::{network::Connection, request, EventError, NatsPublisher};
use latent_capabilities::broker::{
    events::Event,
    pools::{ProviderClient, ProviderMetadata},
};
use latent_core::BoxFuture;
use latent_effects::{
    authority::{
        AuthorityError, DispatchCeiling, DispatchGrant, DispatchProfile, EffectRule, EffectScope,
    },
    dispatch::{AttemptIdentity, RetryProof},
    payload::PayloadRecord,
    runtime::{
        AdapterOutcome, DeferredEffectAdapter, EffectTimeSource, ProviderReconciliationRequest,
    },
};
use sha2::{Digest, Sha256};
use std::{io, sync::Arc};

pub const NATS_DEFERRED_PROFILE: &str = "nats-jetstream-effect-v1";

/// One exact approved tenant/topic mapping on an already installed publisher.
/// No separate client, credential owner or application worker is created.
pub struct JetStreamEffectAdapter {
    publisher: NatsPublisher,
    row: usize,
    credential: usize,
    qualification: JetStreamQualification,
    profile: DispatchProfile,
    time: Arc<dyn EffectTimeSource>,
    client: Arc<ProviderClient<Connection>>,
    _metadata: ProviderMetadata,
}

impl NatsPublisher {
    pub fn deferred_adapter(
        &self,
        tenant: &str,
        topic: &str,
        qualification: JetStreamQualification,
        time: Arc<dyn EffectTimeSource>,
    ) -> Result<JetStreamEffectAdapter, AuthorityError> {
        let row = self
            .inner
            .config
            .topics
            .iter()
            .position(|mapping| mapping.tenant == tenant && mapping.topic == topic)
            .ok_or(AuthorityError::PolicyBlocked)?;
        qualification
            .validate(&self.inner.config.topics[row], &self.inner.config)
            .map_err(authority_error)?;
        let credential = self
            .inner
            .credentials
            .iter()
            .position(|credential| credential.secret.scope().tenant.0 == tenant)
            .ok_or(AuthorityError::PolicyBlocked)?;
        let metadata = self
            .inner
            .pools
            .reserve_protocol_metadata(4096)
            .map_err(|error| authority_error(error.into()))?;
        let client = self
            .inner
            .pools
            .client::<Connection>(
                &self.inner.installed,
                u16::try_from(credential).map_err(|_| AuthorityError::Invalid)?,
            )
            .map_err(|error| authority_error(error.into()))?;
        let mut hash = ProfileHash(Sha256::new());
        hash.0.update(b"lsf-jetstream-effect-profile-v1\0");
        serde_json::to_writer(&mut hash, &(&self.inner.config, row, &qualification))
            .map_err(|_| AuthorityError::Invalid)?;
        let profile = DispatchProfile {
            provider: self.inner.installed.logical_id().into(),
            destination: topic.into(),
            adapter: NATS_DEFERRED_PROFILE.into(),
            intent_format: 1,
            payload_format: "nats-event-value-v1".into(),
            idempotency_profile: format!(
                "js-window-v1:{:x}",
                latent_core::digest::HexDigest(hash.0.finalize())
            ),
        };
        Ok(JetStreamEffectAdapter {
            publisher: self.clone(),
            row,
            credential,
            qualification,
            profile,
            time,
            client,
            _metadata: metadata,
        })
    }
}

impl DeferredEffectAdapter for JetStreamEffectAdapter {
    fn profile(&self) -> &DispatchProfile {
        &self.profile
    }

    fn accept(
        &self,
        grant: DispatchGrant,
        payload: PayloadRecord,
        attempt: AttemptIdentity,
    ) -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError> {
        let horizon = self.check_grant(&grant, &payload, &attempt)?;
        let inner = &self.publisher.inner;
        let event = event(payload, &grant, &inner.config.topics[self.row].topic)?;
        let maximum = inner.config.maximum_payload_bytes.min(
            usize::try_from(grant.ceiling().maximum_payload_bytes)
                .map_err(|_| AuthorityError::Capacity)?,
        );
        let size = request::validate(&event, maximum).map_err(authority_error)?;
        let request = inner
            .pools
            .deferred(&self.client, grant, 2, size.retained + 128 * 1024 + 16_384)
            .map_err(|error| authority_error(error.into()))?;
        let accepted = attempt::AcceptedPublish {
            inner: Arc::clone(inner),
            client: Arc::clone(&self.client),
            qualification: self.qualification.clone(),
            row: self.row,
            credential: self.credential,
            time: Arc::clone(&self.time),
            event,
            request,
            attempt,
            horizon,
        };
        Ok(Box::pin(accepted.run()))
    }

    fn qualify_redrive(
        &self,
        request: &ProviderReconciliationRequest,
        time: latent_effects::authority::EffectTime,
    ) -> Result<RetryProof, AuthorityError> {
        self.redrive_qualification(request, time)
    }
}

impl JetStreamEffectAdapter {
    /// Constructs metadata for a trusted node policy binding. Publishing it into
    /// the current authority owner still requires the node's current-policy check.
    pub fn rule(
        &self,
        scope: EffectScope,
        policy_revision: u64,
        credential_epoch: u64,
        ceiling: DispatchCeiling,
    ) -> Result<EffectRule, AuthorityError> {
        if scope.tenant != self.publisher.inner.config.topics[self.row].tenant
            || scope.operation != "event"
            || ceiling.maximum_payload_bytes
                > self.publisher.inner.config.maximum_payload_bytes as u64
            || ceiling.maximum_response_bytes < 16_384
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        Ok(EffectRule {
            scope,
            profile: self.profile.clone(),
            policy_revision,
            credential_epoch,
            protected_credential_reference: self.publisher.inner.credentials[self.credential]
                .secret
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
        let inner = &self.publisher.inner;
        let mapping = &inner.config.topics[self.row];
        if grant.profile() != &self.profile
            || grant.scope().tenant != mapping.tenant
            || grant.effect() != attempt.effect()
            || grant.attempt() != attempt.attempt()
            || grant.protected_credential_reference()
                != inner.credentials[self.credential].secret.reference()
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        if grant.effect().len() != 64
            || !grant
                .effect()
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(AuthorityError::Invalid);
        }
        payload.verify_grant(grant)?;
        let horizon = grant
            .committed_at_millis()
            .checked_add(mapping.duplicate_window_millis)
            .ok_or(AuthorityError::Invalid)?
            .min(grant.expires_at_millis());
        // accept_with already owns the effect time/currentness fence. Calling
        // a role-owning clock here would reverse the Role -> Effect lock order.
        // The original clock/grant are rechecked on first poll and before send.
        if attempt
            .retry_horizon_millis()
            .is_some_and(|approved| approved > horizon)
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        // The qualification body and an unsupported header frame both require
        // prepaid response capacity even when the latter is rejected.
        if grant.ceiling().maximum_response_bytes < 16_384 {
            return Err(AuthorityError::Capacity);
        }
        Ok(horizon)
    }
}

fn event(
    payload: PayloadRecord,
    grant: &DispatchGrant,
    topic: &str,
) -> Result<Event, AuthorityError> {
    let value = payload.into_value();
    if value.metadata.iter().any(|(key, _)| {
        key.eq_ignore_ascii_case("ordering-key") || key.eq_ignore_ascii_case("lsf-ordering-key")
    }) {
        return Err(AuthorityError::UnsupportedFormat);
    }
    Ok(Event {
        topic: topic.into(),
        key: None,
        payload: value.bytes,
        media_type: value.media_type,
        attributes: value.metadata,
        idempotency_key: format!("lsf-effect-{}", grant.effect()),
    })
}

/// JSON hashing keeps bounded public configuration out of a second full buffer.
struct ProfileHash(Sha256);
impl io::Write for ProfileHash {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.0.update(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn authority_error(error: EventError) -> AuthorityError {
    match error {
        EventError::InvalidTopic | EventError::InvalidEvent => AuthorityError::Invalid,
        EventError::PermissionDenied => AuthorityError::PolicyBlocked,
        EventError::BudgetExhausted => AuthorityError::Capacity,
        EventError::DeadlineExceeded => AuthorityError::Expired,
        EventError::Cancelled | EventError::Unavailable | EventError::Uncertain => {
            AuthorityError::Unavailable
        }
    }
}
