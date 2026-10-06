use super::JetStreamEffectAdapter;
use latent_effects::{
    authority::{AuthorityError, EffectTime},
    dispatch::RetryProof,
    runtime::ProviderReconciliationRequest,
};

impl JetStreamEffectAdapter {
    /// Qualify only the original installed profile and its finite duplicate
    /// contract. The management writer separately fences current permissions,
    /// original history/version and actual prior physical retirement. This
    /// metadata callback reserves no permit and performs no clock observation
    /// or I/O. The later send must re-probe the actual stream incarnation.
    pub(super) fn redrive_qualification(
        &self,
        request: &ProviderReconciliationRequest,
        time: EffectTime,
    ) -> Result<RetryProof, AuthorityError> {
        let authority = request.authority();
        let attempt = request.attempt();
        let mapping = &self.publisher.inner.config.topics[self.row];
        if authority.profile() != &self.profile
            || authority.scope().tenant != mapping.tenant
            || authority.scope().operation != "event"
            || attempt.effect() != authority.link().effect
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        request.payload().verify(authority)?;
        if request.payload().value().metadata.iter().any(|(key, _)| {
            key.eq_ignore_ascii_case("ordering-key") || key.eq_ignore_ascii_case("lsf-ordering-key")
        }) {
            return Err(AuthorityError::UnsupportedFormat);
        }
        if authority.payload_bytes() > self.publisher.inner.config.maximum_payload_bytes as u64
            || attempt.attempt() >= authority.ceiling().maximum_attempts
        {
            return Err(AuthorityError::Capacity);
        }
        if !time.continuity_proven || time.unix_millis < authority.committed_at_millis() {
            return Err(AuthorityError::ClockDiscontinuity);
        }
        let horizon = authority
            .committed_at_millis()
            .checked_add(mapping.duplicate_window_millis)
            .ok_or(AuthorityError::Invalid)?
            .min(authority.expires_at_millis());
        let horizon = attempt
            .retry_horizon_millis()
            .map_or(horizon, |approved| approved.min(horizon));
        if time.unix_millis >= horizon {
            return Err(AuthorityError::PolicyBlocked);
        }
        Ok(RetryProof::QualifiedDeduplication {
            valid_until_millis: horizon,
            same_payload: true,
            same_provider_incarnation: true,
        })
    }
}
