//! Direct typed application routes over the existing HTTP exchange owner.
//! Installed scope descriptions are never namespace or result-read grants.

use std::collections::BTreeMap;

use base64::{
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
    Engine,
};
use latent_core::transaction_contract::{self as contract, ExpectedVersion, Precondition};
use serde_json::Value;

use super::{HttpError, Method};

pub const PROFILE: &str = "transaction-http-v1";
pub const VERSION_TOKEN_BYTES: usize = 67;

/// Closed configuration limits shared by persisted and wire route validation.
#[must_use]
pub fn configuration_limit(name: &str) -> Option<usize> {
    Some(match name {
        "profile" | "scheme" | "pathMatch" | "method" | "transactionMode" => 32,
        "host" => 255,
        "path" => super::MAX_TARGET_BYTES,
        "namespace" | "stateBinding" | "resultPolicy" | "entity" => contract::IDENTITY_BYTES,
        "incarnation" => 20,
        "stateSchema" | "companionDigest" => 71,
        "preconditionKey" => contract::KEY_BYTES.div_ceil(3) * 4,
        _ => return None,
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RouteMode {
    Command,
    Query,
    Result,
}

/// Exact installed route constraints. The runtime must compare the companion
/// digest and links with the same admitted publication before sealing access.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TransactionRoute {
    mode: RouteMode,
    namespace: String,
    incarnation: u64,
    state_schema: String,
    companion_digest: String,
    binding: String,
    result_policy: String,
    entity: Option<String>,
    precondition_key: Option<Vec<u8>>,
}

impl TransactionRoute {
    pub fn from_configuration(fields: &BTreeMap<String, Value>) -> Result<Self, HttpError> {
        for (name, value) in fields {
            let maximum = configuration_limit(name).ok_or(HttpError::InvalidTarget)?;
            let value = value.as_str().ok_or(HttpError::InvalidTarget)?;
            if name.capacity() > 32
                || value.is_empty()
                || value.len() > maximum
                || value.chars().any(char::is_control)
            {
                return Err(HttpError::InvalidTarget);
            }
        }
        let text = |name: &str| {
            fields
                .get(name)
                .and_then(Value::as_str)
                .ok_or(HttpError::InvalidTarget)
        };
        if text("profile")? != PROFILE || !(13..=15).contains(&fields.len()) {
            return Err(HttpError::InvalidTarget);
        }
        for name in ["scheme", "host", "path", "pathMatch", "method"] {
            text(name)?;
        }
        let mode = match text("transactionMode")? {
            "command" => RouteMode::Command,
            "query" => RouteMode::Query,
            "result" => RouteMode::Result,
            _ => return Err(HttpError::InvalidTarget),
        };
        let incarnation_text = text("incarnation")?;
        let incarnation = incarnation_text
            .parse::<u64>()
            .map_err(|_| HttpError::InvalidTarget)?;
        if incarnation == 0 || incarnation.to_string() != incarnation_text {
            return Err(HttpError::InvalidTarget);
        }
        let mut owned = [
            String::new(),
            String::new(),
            String::new(),
            String::new(),
            String::new(),
        ];
        for (index, name) in [
            "namespace",
            "stateBinding",
            "resultPolicy",
            "stateSchema",
            "companionDigest",
        ]
        .into_iter()
        .enumerate()
        {
            let value = text(name)?;
            if matches!(name, "stateSchema" | "companionDigest") {
                value
                    .parse::<latent_core::ArtifactBlobDigest>()
                    .map_err(|_| HttpError::InvalidTarget)?;
            } else {
                identifier(value)?;
            }
            value.clone_into(&mut owned[index]);
        }
        let entity = fields
            .get("entity")
            .map(|value| {
                let value = value.as_str().ok_or(HttpError::InvalidTarget)?;
                identifier(value)?;
                Ok(value.to_owned())
            })
            .transpose()?;
        let precondition_key = fields
            .get("preconditionKey")
            .map(|value| {
                if mode != RouteMode::Command {
                    return Err(HttpError::InvalidTarget);
                }
                let value = value.as_str().ok_or(HttpError::InvalidTarget)?;
                decode_canonical(value, contract::KEY_BYTES, None)
            })
            .transpose()?;
        let [namespace, binding, result_policy, state_schema, companion_digest] = owned;
        Ok(Self {
            mode,
            namespace,
            incarnation,
            state_schema,
            companion_digest,
            binding,
            result_policy,
            entity,
            precondition_key,
        })
    }

    pub fn require_method(&self, method: Method) -> Result<(), HttpError> {
        let permitted = match self.mode {
            RouteMode::Command => matches!(
                method,
                Method::Post | Method::Put | Method::Patch | Method::Delete
            ),
            RouteMode::Query => matches!(method, Method::Get | Method::Head),
            RouteMode::Result => method == Method::Get,
        };
        if permitted {
            Ok(())
        } else {
            Err(HttpError::UnsupportedMethod)
        }
    }

    #[must_use]
    pub const fn mode(&self) -> RouteMode {
        self.mode
    }
    #[must_use]
    pub fn namespace(&self) -> &str {
        &self.namespace
    }
    #[must_use]
    pub const fn incarnation(&self) -> u64 {
        self.incarnation
    }
    #[must_use]
    pub fn state_schema(&self) -> &str {
        &self.state_schema
    }
    #[must_use]
    pub fn companion_digest(&self) -> &str {
        &self.companion_digest
    }
    #[must_use]
    pub fn binding(&self) -> &str {
        &self.binding
    }
    #[must_use]
    pub fn result_policy(&self) -> &str {
        &self.result_policy
    }
    #[must_use]
    pub fn entity(&self) -> Option<&str> {
        self.entity.as_deref()
    }
    #[must_use]
    pub fn precondition_key(&self) -> Option<&[u8]> {
        self.precondition_key.as_deref()
    }
}

/// Bounded original request facts retained with the exchange. Input bytes must
/// subsequently use the prepared component's actual type-directed codec before
/// constructing a durable fingerprint; generic JSON rewriting is insufficient.
pub struct TransactionRequest {
    pub(super) client_key: Option<String>,
    pub(super) preconditions: Vec<Precondition>,
    pub(super) minimum_view: Option<Vec<u8>>,
    pub(super) business_path: String,
    pub(super) business_query: Option<String>,
    pub(super) method: Method,
}

impl TransactionRequest {
    #[must_use]
    pub fn client_key(&self) -> Option<&str> {
        self.client_key.as_deref()
    }
    #[must_use]
    pub fn preconditions(&self) -> &[Precondition] {
        &self.preconditions
    }
    #[must_use]
    pub fn minimum_view(&self) -> Option<&[u8]> {
        self.minimum_view.as_deref()
    }
    #[must_use]
    pub fn business_path(&self) -> &str {
        &self.business_path
    }
    #[must_use]
    pub fn business_query(&self) -> Option<&str> {
        self.business_query.as_deref()
    }
    #[must_use]
    pub const fn method(&self) -> Method {
        self.method
    }
}

pub(super) fn singleton<'a>(
    headers: &'a [super::model::Header],
    name: &str,
) -> Result<Option<&'a str>, HttpError> {
    let mut fields = headers.iter().filter(|header| header.name.0 == name);
    let value = fields
        .next()
        .map(|header| std::str::from_utf8(&header.value.0).map_err(|_| HttpError::InvalidHeaders))
        .transpose()?;
    if fields.next().is_some() {
        return Err(HttpError::InvalidHeaders);
    }
    Ok(value)
}

pub(super) fn query_input(query: Option<&str>) -> Result<Vec<u8>, HttpError> {
    let Some(query) = query else {
        return Ok(b"[]".to_vec());
    };
    let text = query
        .strip_prefix("input=")
        .ok_or(HttpError::InvalidTarget)?;
    if text.is_empty() || text.len() > super::MAX_TARGET_BYTES {
        return Err(HttpError::InvalidTarget);
    }
    let bytes = URL_SAFE_NO_PAD
        .decode(text)
        .map_err(|_| HttpError::InvalidTarget)?;
    if bytes.is_empty()
        || bytes.len() > super::MAX_REQUEST_BODY
        || URL_SAFE_NO_PAD.encode(&bytes) != text
    {
        return Err(HttpError::InvalidTarget);
    }
    Ok(bytes)
}

pub(super) fn identifier(value: &str) -> Result<(), HttpError> {
    contract::identity(value).map_err(|_| HttpError::InvalidTarget)?;
    if value.chars().any(char::is_control) || value.trim() != value {
        return Err(HttpError::InvalidTarget);
    }
    Ok(())
}

pub(super) fn decode_canonical(
    value: &str,
    maximum: usize,
    exact: Option<usize>,
) -> Result<Vec<u8>, HttpError> {
    if value.len() > maximum.div_ceil(3) * 4 {
        return Err(HttpError::InvalidHeaders);
    }
    let bytes = STANDARD
        .decode(value)
        .map_err(|_| HttpError::InvalidHeaders)?;
    if bytes.is_empty()
        || bytes.len() > maximum
        || exact.is_some_and(|length| bytes.len() != length)
        || STANDARD.encode(&bytes) != value
    {
        return Err(HttpError::InvalidHeaders);
    }
    Ok(bytes)
}

pub(super) fn original_precondition(value: &str, key: &[u8]) -> Result<Precondition, HttpError> {
    let token = value
        .strip_prefix('"')
        .and_then(|v| v.strip_suffix('"'))
        .ok_or(HttpError::InvalidHeaders)?;
    let expected = if token == "absent" {
        ExpectedVersion::Absent
    } else {
        let version = decode_canonical(token, VERSION_TOKEN_BYTES, Some(VERSION_TOKEN_BYTES))?;
        if !version.starts_with(b"SV\x02") {
            return Err(HttpError::InvalidHeaders);
        }
        ExpectedVersion::Present(version)
    };
    Ok(Precondition {
        key: key.to_vec(),
        expected,
    })
}
