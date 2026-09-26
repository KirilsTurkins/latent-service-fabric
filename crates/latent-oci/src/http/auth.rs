mod cache;
mod lifecycle;
#[cfg(test)]
pub(super) mod security_tests;
mod token;

use super::{
    exhausted, invalid, BearerIdentity, RegistryActions, RegistryConfig, RegistryCredentials,
    Result,
};
pub use cache::BearerUsage;
pub(super) use cache::Token;
use latent_core::PlatformErrorCode;
use reqwest::{
    header::{HeaderMap, HeaderValue, ACCEPT, AUTHORIZATION, WWW_AUTHENTICATE},
    Method, Response, StatusCode, Url,
};
use std::{
    net::IpAddr,
    sync::{Arc, Mutex},
};
use tokio::time::Instant;

const MAX_CHALLENGE_BYTES: usize = 4096;
pub(super) const MAX_TOKEN_RESPONSE_BYTES: usize = 16 * 1024;
const MAX_TOKEN_BYTES: usize = 8192;
const MAX_REALM_BYTES: usize = 2048;
const MAX_SERVICE_BYTES: usize = 512;
const MAX_SCOPE_BYTES: usize = 512;
const MAX_AUTH_ADDRESSES: usize = 16;

pub(super) struct ConfiguredBearer {
    realm: Url,
    service: Box<str>,
    scope: Box<str>,
    repository: Box<str>,
    actions: RegistryActions,
    cache: cache::Cache,
    accounting: Arc<cache::Accounting>,
    acquisition: tokio::sync::Mutex<()>,
    waiters: tokio::sync::Semaphore,
    client: Option<reqwest::Client>,
    owned: Option<Arc<super::network::OwnedClient>>,
}

impl ConfiguredBearer {
    pub(super) fn new(config: &RegistryConfig) -> Result<Option<Self>> {
        Self::with_network(config, None)
    }

    pub(super) fn with_network(
        config: &RegistryConfig,
        network: Option<&super::network::Network>,
    ) -> Result<Option<Self>> {
        let RegistryCredentials::BearerChallenge {
            realm: configured_realm,
            service,
            identity,
            actions,
            username,
            password,
            addresses,
        } = &config.credentials
        else {
            return Ok(None);
        };
        if configured_realm.len() > MAX_REALM_BYTES
            || service.is_empty()
            || service.len() > MAX_SERVICE_BYTES
            || service.bytes().any(|byte| !byte.is_ascii_graphic())
        {
            return Err(invalid("invalid-oci-bearer-authority"));
        }
        let realm =
            Url::parse(configured_realm).map_err(|_| invalid("invalid-oci-bearer-authority"))?;
        if realm.scheme() != "https"
            || realm.host().is_none()
            || !realm.username().is_empty()
            || realm.password().is_some()
            || realm.query().is_some()
            || realm.fragment().is_some()
        {
            return Err(invalid("invalid-oci-bearer-authority"));
        }
        let port = realm
            .port_or_known_default()
            .ok_or_else(|| invalid("invalid-oci-bearer-authority"))?;
        let numeric = realm
            .host_str()
            .and_then(|host| host.trim_matches(['[', ']']).parse::<IpAddr>().ok());
        if addresses.len() > MAX_AUTH_ADDRESSES
            || (network.is_none() && numeric.is_none() && addresses.is_empty())
            || addresses
                .iter()
                .any(|address| address.port() != port || address.ip().is_unspecified())
        {
            return Err(invalid("invalid-oci-bearer-address"));
        }
        identity.validate()?;
        let scope = format!("repository:{}:{}", config.repository, actions.scope());
        if scope.len() > MAX_SCOPE_BYTES {
            return Err(invalid("invalid-oci-bearer-scope"));
        }
        let authorization = super::transport::client::basic_authorization(username, password)?;
        let owned = network.map(|network| network.client(&realm)).transpose()?;
        let client = if owned.is_some() {
            None
        } else {
            Some(super::transport::client::build_authority(
                config,
                realm.host_str().expect("checked bearer host"),
                addresses,
            )?)
        };
        Ok(Some(Self {
            realm,
            service: service.clone().into_boxed_str(),
            scope: scope.into_boxed_str(),
            repository: config.repository.clone().into_boxed_str(),
            actions: *actions,
            cache: cache::Cache(Mutex::new(cache::State {
                identity: identity.clone(),
                authorization: Some(authorization),
                cached: None,
                failed: None,
                closed: false,
            })),
            accounting: Arc::new(cache::Accounting {
                active: 0.into(),
                waiting: 0.into(),
                bytes: 0.into(),
                maximum: (MAX_TOKEN_BYTES + 7) * (config.limits.max_in_flight + 2),
            }),
            acquisition: tokio::sync::Mutex::new(()),
            waiters: tokio::sync::Semaphore::new(config.limits.max_in_flight),
            client,
            owned,
        }))
    }

    pub(super) fn validate_challenge(&self, headers: &HeaderMap) -> Result<()> {
        let mut values = headers.get_all(WWW_AUTHENTICATE).iter();
        let value = values
            .next()
            .ok_or_else(|| unauthenticated("oci-bearer-challenge-missing"))?;
        if values.next().is_some() || value.as_bytes().len() > MAX_CHALLENGE_BYTES {
            return Err(unauthenticated("oci-bearer-challenge-ambiguous"));
        }
        let value = value
            .to_str()
            .map_err(|_| unauthenticated("oci-bearer-challenge-invalid"))?;
        let parameters = parse_challenge(value)?;
        if parameters.realm != self.realm.as_str()
            || parameters.service != self.service.as_ref()
            || parameters
                .scope
                .is_some_and(|scope| !self.permits_scope(scope))
        {
            return Err(unauthenticated("oci-bearer-challenge-outside-profile"));
        }
        Ok(())
    }

    fn permits_scope(&self, scope: &str) -> bool {
        let Some((repository, actions)) = scope
            .strip_prefix("repository:")
            .and_then(|scope| scope.rsplit_once(':'))
        else {
            return false;
        };
        repository == self.repository.as_ref()
            && (actions == "pull"
                || (self.actions == RegistryActions::PullPush
                    && matches!(actions, "push" | "pull,push")))
    }

    pub(super) async fn exchange(
        &self,
        deadline: Instant,
        request_timeout: std::time::Duration,
        authorization: HeaderValue,
    ) -> Result<Response> {
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .filter(|time| !time.is_zero())
            .ok_or_else(|| {
                crate::error(
                    PlatformErrorCode::DeadlineExceeded,
                    "oci-operation-deadline",
                )
            })?;
        let mut request_url = self.realm.clone();
        {
            let mut query = request_url.query_pairs_mut();
            query.append_pair("service", self.service.as_ref());
            query.append_pair("scope", self.scope.as_ref());
        }
        if let Some(client) = &self.owned {
            let mut headers = HeaderMap::new();
            headers.insert(ACCEPT, HeaderValue::from_static("application/json"));
            headers.insert(AUTHORIZATION, authorization);
            let response = client
                .send(Method::GET, request_url, headers, None, deadline)
                .await?;
            super::transport::expect_status(&response, &[StatusCode::OK])?;
            return Ok(response);
        }
        let response = self
            .client
            .as_ref()
            .ok_or_else(|| invalid("oci-token-client-unavailable"))?
            .get(request_url)
            .header(ACCEPT, HeaderValue::from_static("application/json"))
            .header(AUTHORIZATION, authorization)
            .timeout(remaining.min(request_timeout))
            .send()
            .await
            .map_err(|error| super::transport::network_error(&error))?;
        super::body::headers(&response)?;
        super::transport::expect_status(&response, &[StatusCode::OK])?;
        Ok(response)
    }

    #[cfg(test)]
    fn token_header(&self, body: &[u8]) -> Result<HeaderValue> {
        token::parse(
            body,
            &self.scope,
            Instant::now(),
            std::time::SystemTime::now(),
        )
        .map(|(header, _)| header)
    }
}

pub(super) fn read_continuation_allowed(method: &Method, body_present: bool) -> bool {
    !body_present && (method == Method::GET || method == Method::HEAD)
}

struct Challenge<'a> {
    realm: &'a str,
    service: &'a str,
    scope: Option<&'a str>,
}

fn parse_challenge(value: &str) -> Result<Challenge<'_>> {
    let trimmed = value.trim();
    let split = trimmed
        .find(char::is_whitespace)
        .ok_or_else(|| unauthenticated("oci-bearer-challenge-invalid"))?;
    let (scheme, parameters) = trimmed.split_at(split);
    if !scheme.eq_ignore_ascii_case("bearer") {
        return Err(unauthenticated("oci-bearer-challenge-invalid"));
    }
    let mut realm = None;
    let mut service = None;
    let mut scope = None;
    let mut parameters = parameters.trim_start();
    if parameters.is_empty() {
        return Err(unauthenticated("oci-bearer-challenge-invalid"));
    }
    while !parameters.is_empty() {
        let (name, value) = parameters
            .split_once('=')
            .ok_or_else(|| unauthenticated("oci-bearer-challenge-invalid"))?;
        let name = name.trim();
        let quoted = value
            .trim_start()
            .strip_prefix('"')
            .ok_or_else(|| unauthenticated("oci-bearer-challenge-invalid"))?;
        let end = quoted
            .find('"')
            .ok_or_else(|| unauthenticated("oci-bearer-challenge-invalid"))?;
        let value = &quoted[..end];
        if value
            .bytes()
            .any(|byte| byte == b'\\' || byte.is_ascii_control())
        {
            return Err(unauthenticated("oci-bearer-challenge-invalid"));
        }
        match name {
            name if name.eq_ignore_ascii_case("realm") && realm.is_none() => realm = Some(value),
            name if name.eq_ignore_ascii_case("service") && service.is_none() => {
                service = Some(value);
            }
            name if name.eq_ignore_ascii_case("scope") && scope.is_none() => scope = Some(value),
            _ => return Err(unauthenticated("oci-bearer-challenge-invalid")),
        }
        let remaining = quoted[end + 1..].trim();
        parameters = if remaining.is_empty() {
            ""
        } else {
            remaining
                .strip_prefix(',')
                .map(str::trim_start)
                .filter(|rest| !rest.is_empty())
                .ok_or_else(|| unauthenticated("oci-bearer-challenge-invalid"))?
        };
    }
    Ok(Challenge {
        realm: realm.ok_or_else(|| unauthenticated("oci-bearer-challenge-invalid"))?,
        service: service.ok_or_else(|| unauthenticated("oci-bearer-challenge-invalid"))?,
        scope,
    })
}

fn unauthenticated(reason: &'static str) -> latent_core::PlatformError {
    crate::error(PlatformErrorCode::Unauthenticated, reason)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::http::RegistryLimits;

    fn config() -> RegistryConfig {
        RegistryConfig {
            origin: "https://127.0.0.1".to_owned(),
            repository: "tenant/site".to_owned(),
            credentials: RegistryCredentials::BearerChallenge {
                realm: "https://127.0.0.1/token".to_owned(),
                service: "registry.example".to_owned(),
                identity: BearerIdentity {
                    tenant: latent_core::TenantId("tenant".into()),
                    principal: "operator".into(),
                    credential_epoch: 1,
                },
                actions: RegistryActions::Pull,
                username: "robot".to_owned(),
                password: "secret".to_owned(),
                addresses: Vec::new(),
            },
            addresses: Vec::new(),
            additional_root_certificates: Vec::new(),
            allow_insecure_loopback: false,
            limits: RegistryLimits::default(),
        }
    }

    fn challenge(value: &'static str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(WWW_AUTHENTICATE, HeaderValue::from_static(value));
        headers
    }

    #[test]
    fn exact_approved_challenge_is_accepted() {
        let configured = ConfiguredBearer::new(&config()).unwrap().unwrap();
        configured
            .validate_challenge(&challenge(
                "Bearer realm=\"https://127.0.0.1/token\",service=\"registry.example\",scope=\"repository:tenant/site:pull\"",
            ))
            .unwrap();
    }

    #[test]
    fn realm_service_scope_and_duplicate_fields_fail_closed() {
        let configured = ConfiguredBearer::new(&config()).unwrap().unwrap();
        for value in [
            "Bearer realm=\"https://evil.invalid/token\",service=\"registry.example\",scope=\"repository:tenant/site:pull\"",
            "Bearer realm=\"https://127.0.0.1/token\",service=\"other\",scope=\"repository:tenant/site:pull\"",
            "Bearer realm=\"https://127.0.0.1/token\",service=\"registry.example\",scope=\"repository:tenant/site:pull,push\"",
            "Bearer realm=\"https://127.0.0.1/token\",realm=\"https://127.0.0.1/token\",service=\"registry.example\",scope=\"repository:tenant/site:pull\"",
            "Basic realm=\"https://127.0.0.1/token\"",
        ] {
            assert!(configured.validate_challenge(&challenge(value)).is_err());
        }
    }

    #[test]
    fn token_body_is_bounded_unambiguous_and_scope_bound() {
        let configured = ConfiguredBearer::new(&config()).unwrap().unwrap();
        let header = configured
            .token_header(
                br#"{"token":"abc.def","expires_in":60,"scope":"repository:tenant/site:pull"}"#,
            )
            .unwrap();
        assert!(header.is_sensitive());
        assert_eq!(header.as_bytes(), b"Bearer abc.def");
        for body in [
            b"{}".as_slice(),
            br#"{"token":"one","access_token":"two"}"#.as_slice(),
            br#"{"token":"one","expires_in":0}"#.as_slice(),
            br#"{"token":"one","scope":"repository:tenant/site:pull,push"}"#.as_slice(),
        ] {
            assert!(configured.token_header(body).is_err());
        }
        assert!(configured
            .token_header(&vec![b'x'; MAX_TOKEN_RESPONSE_BYTES + 1])
            .is_err());
    }

    #[test]
    fn bearer_authority_requires_https_and_bounded_explicit_resolution() {
        let mut value = config();
        let RegistryCredentials::BearerChallenge { realm, .. } = &mut value.credentials else {
            unreachable!();
        };
        *realm = "http://127.0.0.1/token".to_owned();
        assert!(ConfiguredBearer::new(&value).is_err());

        let mut value = config();
        let RegistryCredentials::BearerChallenge { realm, .. } = &mut value.credentials else {
            unreachable!();
        };
        *realm = "https://auth.example/token".to_owned();
        assert!(ConfiguredBearer::new(&value).is_err());

        let mut value = config();
        let RegistryCredentials::BearerChallenge {
            realm, addresses, ..
        } = &mut value.credentials
        else {
            unreachable!();
        };
        *realm = "https://auth.example/token".to_owned();
        *addresses = vec!["127.0.0.1:443".parse().unwrap()];
        assert!(ConfiguredBearer::new(&value).is_ok());
    }

    #[test]
    fn only_bodyless_get_and_head_can_authenticate_by_replay() {
        assert!(read_continuation_allowed(&Method::GET, false));
        assert!(read_continuation_allowed(&Method::HEAD, false));
        assert!(!read_continuation_allowed(&Method::GET, true));
        assert!(!read_continuation_allowed(&Method::POST, false));
        assert!(!read_continuation_allowed(&Method::PUT, false));
        assert!(!read_continuation_allowed(&Method::PATCH, false));
        assert!(!read_continuation_allowed(&Method::DELETE, false));
    }
}
