use super::{exhausted, invalid, RegistryConfig, RegistryCredentials, Result};
use latent_core::PlatformErrorCode;
use reqwest::{
    header::{HeaderMap, HeaderValue, ACCEPT, AUTHORIZATION, WWW_AUTHENTICATE},
    Method, Response, StatusCode, Url,
};
use serde::Deserialize;
use std::net::IpAddr;
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
    authorization: HeaderValue,
    client: reqwest::Client,
}

impl ConfiguredBearer {
    pub(super) fn new(config: &RegistryConfig) -> Result<Option<Self>> {
        let RegistryCredentials::BearerChallenge(credentials) = &config.credentials else {
            return Ok(None);
        };
        if credentials.realm.len() > MAX_REALM_BYTES
            || credentials.service.is_empty()
            || credentials.service.len() > MAX_SERVICE_BYTES
            || credentials
                .service
                .bytes()
                .any(|byte| !byte.is_ascii_graphic())
        {
            return Err(invalid("invalid-oci-bearer-authority"));
        }
        let realm = Url::parse(&credentials.realm)
            .map_err(|_| invalid("invalid-oci-bearer-authority"))?;
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
        if credentials.addresses.len() > MAX_AUTH_ADDRESSES
            || (numeric.is_none() && credentials.addresses.is_empty())
            || credentials
                .addresses
                .iter()
                .any(|address| address.port() != port || address.ip().is_unspecified())
        {
            return Err(invalid("invalid-oci-bearer-address"));
        }
        let scope = format!("repository:{}:pull", config.repository);
        if scope.len() > MAX_SCOPE_BYTES {
            return Err(invalid("invalid-oci-bearer-scope"));
        }
        let authorization = super::transport::client::basic_authorization(
            &credentials.username,
            &credentials.password,
        )?;
        let client = super::transport::client::build_authority(
            config,
            realm.host_str().expect("checked bearer host"),
            &credentials.addresses,
        )?;
        Ok(Some(Self {
            realm,
            service: credentials.service.clone().into_boxed_str(),
            scope: scope.into_boxed_str(),
            authorization,
            client,
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
            || parameters.scope != self.scope.as_ref()
        {
            return Err(unauthenticated("oci-bearer-challenge-outside-profile"));
        }
        Ok(())
    }

    pub(super) async fn exchange(
        &self,
        deadline: Instant,
        request_timeout: std::time::Duration,
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
        let response = self
            .client
            .get(self.realm.clone())
            .header(ACCEPT, HeaderValue::from_static("application/json"))
            .header(AUTHORIZATION, self.authorization.clone())
            .query(&[
                ("service", self.service.as_ref()),
                ("scope", self.scope.as_ref()),
            ])
            .timeout(remaining.min(request_timeout))
            .send()
            .await
            .map_err(|error| super::transport::network_error(&error))?;
        super::body::headers(&response)?;
        super::transport::expect_status(&response, &[StatusCode::OK])?;
        Ok(response)
    }

    pub(super) fn token_header(&self, body: &[u8]) -> Result<HeaderValue> {
        if body.len() > MAX_TOKEN_RESPONSE_BYTES {
            return Err(exhausted("oci-token-response-byte-limit"));
        }
        let document: TokenDocument = serde_json::from_slice(body)
            .map_err(|_| unauthenticated("oci-token-response-invalid"))?;
        let token = match (document.token, document.access_token) {
            (Some(token), None) | (None, Some(token)) => token,
            (Some(token), Some(alias)) if token == alias => token,
            _ => return Err(unauthenticated("oci-token-response-ambiguous")),
        };
        if token.is_empty()
            || token.len() > MAX_TOKEN_BYTES
            || !token.bytes().all(|byte| byte.is_ascii_graphic())
            || document.expires_in == Some(0)
            || document
                .scope
                .as_deref()
                .is_some_and(|scope| scope != self.scope.as_ref())
        {
            return Err(unauthenticated("oci-token-response-outside-profile"));
        }
        super::transport::client::bearer_authorization(&token)
    }
}

pub(super) fn read_continuation_allowed(method: &Method, body_present: bool) -> bool {
    !body_present && matches!(*method, Method::GET | Method::HEAD)
}

struct Challenge<'a> {
    realm: &'a str,
    service: &'a str,
    scope: &'a str,
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
    let parameters = parameters.trim_start();
    if parameters.is_empty() {
        return Err(unauthenticated("oci-bearer-challenge-invalid"));
    }
    for field in parameters.split(',') {
        let (name, value) = field
            .trim()
            .split_once('=')
            .ok_or_else(|| unauthenticated("oci-bearer-challenge-invalid"))?;
        let name = name.trim();
        let value = value.trim();
        if value.len() < 2
            || !value.starts_with('"')
            || !value.ends_with('"')
            || value[1..value.len() - 1]
                .bytes()
                .any(|byte| byte == b'"' || byte == b'\\' || byte.is_ascii_control())
        {
            return Err(unauthenticated("oci-bearer-challenge-invalid"));
        }
        let value = &value[1..value.len() - 1];
        match name {
            name if name.eq_ignore_ascii_case("realm") && realm.is_none() => {
                realm = Some(value)
            }
            name if name.eq_ignore_ascii_case("service") && service.is_none() => {
                service = Some(value)
            }
            name if name.eq_ignore_ascii_case("scope") && scope.is_none() => scope = Some(value),
            _ => return Err(unauthenticated("oci-bearer-challenge-invalid")),
        }
    }
    Ok(Challenge {
        realm: realm.ok_or_else(|| unauthenticated("oci-bearer-challenge-invalid"))?,
        service: service.ok_or_else(|| unauthenticated("oci-bearer-challenge-invalid"))?,
        scope: scope.ok_or_else(|| unauthenticated("oci-bearer-challenge-invalid"))?,
    })
}

#[derive(Deserialize)]
struct TokenDocument {
    token: Option<String>,
    access_token: Option<String>,
    expires_in: Option<u64>,
    scope: Option<String>,
}

fn unauthenticated(reason: &'static str) -> latent_core::PlatformError {
    crate::error(PlatformErrorCode::Unauthenticated, reason)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::http::{RegistryBearerChallenge, RegistryLimits};

    fn config() -> RegistryConfig {
        RegistryConfig {
            origin: "https://127.0.0.1".to_owned(),
            repository: "tenant/site".to_owned(),
            credentials: RegistryCredentials::BearerChallenge(RegistryBearerChallenge {
                realm: "https://127.0.0.1/token".to_owned(),
                service: "registry.example".to_owned(),
                username: "robot".to_owned(),
                password: "secret".to_owned(),
                addresses: Vec::new(),
            }),
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
            .token_header(br#"{"token":"abc.def","expires_in":60,"scope":"repository:tenant/site:pull"}"#)
            .unwrap();
        assert!(header.is_sensitive());
        assert_eq!(header.as_bytes(), b"Bearer abc.def");
        for body in [
            br#"{}"#.as_slice(),
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
        let RegistryCredentials::BearerChallenge(credentials) = &mut value.credentials else {
            unreachable!();
        };
        credentials.realm = "http://127.0.0.1/token".to_owned();
        assert!(ConfiguredBearer::new(&value).is_err());

        let mut value = config();
        let RegistryCredentials::BearerChallenge(credentials) = &mut value.credentials else {
            unreachable!();
        };
        credentials.realm = "https://auth.example/token".to_owned();
        assert!(ConfiguredBearer::new(&value).is_err());

        let mut value = config();
        let RegistryCredentials::BearerChallenge(credentials) = &mut value.credentials else {
            unreachable!();
        };
        credentials.realm = "https://auth.example/token".to_owned();
        credentials.addresses = vec!["127.0.0.1:443".parse().unwrap()];
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
