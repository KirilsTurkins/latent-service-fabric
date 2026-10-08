use super::{AuthorityError, DispatchProfile, MAXIMUM_EFFECT_BODY_BYTES};
use crate::{HttpProviderConfig, HttpResolution};
use latent_capabilities::broker::secrets::ProviderCredential;
use latent_core::{digest::HexDigest, TenantId};
use latent_policy::capability::HttpOrigin;
use sha2::{Digest, Sha256};

pub const HTTP_EFFECT_ADAPTER: &str = "qualified-http-put-once-v1";
pub const HTTP_EFFECT_OPERATION: &str = "put-once";
pub(super) const WIRE_CONTRACT: &str = "latent.http-effect.put-once.v1";
pub(super) const PAYLOAD_FORMAT: &str = "http-put-once-bytes-v1";
pub(super) const IDEMPOTENCY_PROFILE: &str = "retained-put-once-v1";
pub(super) const PATH_PREFIX: &str = "/latent-effects/v1/";

/// Trusted native installation, not a guest-supplied URL or a declarative grant.
/// The operator must qualify this exact endpoint's reservation, conflict,
/// deadline, lookup and provider-incarnation behavior before installing it.
#[derive(Clone)]
pub struct PutOnceContract {
    pub tenant: TenantId,
    pub provider_id: String,
    pub origin: HttpOrigin,
    /// Lowercase SHA-256-shaped opaque identity. Restoring deduplication history
    /// or replacing the endpoint establishes another incarnation.
    pub provider_incarnation: String,
    pub retention_horizon_millis: u64,
    pub maximum_body_bytes: usize,
    pub retry_delay_millis: u64,
}

impl PutOnceContract {
    pub(super) fn validate(&self, http: &HttpProviderConfig) -> Result<(), AuthorityError> {
        http.validate().map_err(|_| AuthorityError::Invalid)?;
        if !identity(&self.tenant.0, 128)
            || self.tenant.0.capacity() > 128
            || !identity(&self.provider_id, 128)
            || self.provider_id.capacity() > 128
            || !hex_identity(&self.provider_incarnation)
            || self.provider_incarnation.capacity() > 64
            || !(1..=604_800_000).contains(&self.retention_horizon_millis)
            || !(1..=MAXIMUM_EFFECT_BODY_BYTES).contains(&self.maximum_body_bytes)
            || !(1..=60_000).contains(&self.retry_delay_millis)
            || http.destinations.len() != 1
            || http.destinations[0].origin != self.origin
            || self.origin.scheme != "https"
            || !matches!(
                http.destinations[0].resolution,
                HttpResolution::Static { .. }
            )
            || !http.destinations[0].allowed_request_headers.is_empty()
            || !http.destinations[0].redirect_destinations.is_empty()
            || http.limits.maximum_redirects != 0
            || http.limits.maximum_request_body_bytes < self.maximum_body_bytes
            || http.limits.maximum_response_body_bytes < super::MAXIMUM_EFFECT_RECEIPT_BYTES
        {
            return Err(AuthorityError::UnsupportedFormat);
        }
        Ok(())
    }

    pub(super) fn check_credential(
        &self,
        epoch: u64,
        credential: &dyn ProviderCredential,
    ) -> Result<(), AuthorityError> {
        let scope = credential.scope();
        if epoch == 0
            || scope.tenant != self.tenant
            || scope.provider_id != self.provider_id
            || scope.origin != self.origin
            || !identity(credential.reference(), 256)
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        Ok(())
    }

    pub(super) fn profile(&self, configuration_digest: &str) -> DispatchProfile {
        let mut digest = Sha256::new();
        digest.update(b"lsf-qualified-http-put-once-v1\0");
        for value in [
            configuration_digest,
            &self.tenant.0,
            &self.provider_id,
            &self.provider_incarnation,
        ] {
            digest.update((value.len() as u64).to_le_bytes());
            digest.update(value.as_bytes());
        }
        digest.update(self.retention_horizon_millis.to_le_bytes());
        digest.update((self.maximum_body_bytes as u64).to_le_bytes());
        digest.update(self.retry_delay_millis.to_le_bytes());
        DispatchProfile {
            provider: self.provider_id.clone(),
            destination: format!("put-once:sha256:{:x}", HexDigest(digest.finalize())),
            adapter: HTTP_EFFECT_ADAPTER.into(),
            intent_format: 1,
            payload_format: PAYLOAD_FORMAT.into(),
            idempotency_profile: IDEMPOTENCY_PROFILE.into(),
        }
    }
}

pub(super) fn identity(value: &str, maximum: usize) -> bool {
    !value.is_empty() && value.len() <= maximum && !value.chars().any(char::is_control)
}

pub(super) fn hex_identity(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn configured() -> (PutOnceContract, HttpProviderConfig) {
        let mut http = crate::tests::config(12345);
        http.destinations[0].origin.scheme = "https".into();
        http.destinations[0].allowed_request_headers.clear();
        http.destinations[0].redirect_destinations.clear();
        http.limits.maximum_redirects = 0;
        let contract = PutOnceContract {
            tenant: TenantId("a".into()),
            provider_id: "http".into(),
            origin: http.destinations[0].origin.clone(),
            provider_incarnation: "a".repeat(64),
            retention_horizon_millis: 1000,
            maximum_body_bytes: 1024,
            retry_delay_millis: 10,
        };
        (contract, http)
    }

    #[test]
    fn closed_profile_refuses_generic_http_dynamic_dns_redirects_and_unsafe_peers() {
        let (contract, http) = configured();
        assert_eq!(contract.validate(&http), Ok(()));
        for index in 0..5 {
            let mut altered = http.clone();
            match index {
                0 => altered.destinations[0].origin.scheme = "http".into(),
                1 => {
                    altered.destinations[0].resolution = HttpResolution::Dns {
                        server: "127.0.0.1:5353".parse().unwrap(),
                        maximum_ttl_seconds: 30,
                    }
                }
                2 => altered.destinations[0].redirect_destinations.push(0),
                3 => altered.destinations[0]
                    .allowed_request_headers
                    .push("x-guest".into()),
                4 => {
                    altered.destinations[0].resolution = HttpResolution::Static {
                        addresses: vec!["169.254.169.254".parse().unwrap()],
                    }
                }
                _ => unreachable!(),
            }
            assert!(contract.validate(&altered).is_err());
        }
    }

    #[test]
    fn finite_contract_and_provider_incarnation_changes_never_reinterpret_retained_profiles() {
        let (contract, http) = configured();
        let profile = contract.profile("sha256:original-public-config");
        for index in 0..6 {
            let mut altered = contract.clone();
            match index {
                0 => altered.retention_horizon_millis = 0,
                1 => altered.retention_horizon_millis = 604_800_001,
                2 => altered.maximum_body_bytes = 0,
                3 => altered.maximum_body_bytes = 65_537,
                4 => altered.retry_delay_millis = 60_001,
                5 => altered.provider_incarnation = "A".repeat(64),
                _ => unreachable!(),
            }
            assert!(altered.validate(&http).is_err());
        }
        let mut replacement = contract;
        replacement.provider_incarnation = "b".repeat(64);
        assert_eq!(replacement.validate(&http), Ok(()));
        assert_ne!(
            profile,
            replacement.profile("sha256:original-public-config")
        );
        assert_ne!(profile, replacement.profile("sha256:another-public-config"));
    }
}
