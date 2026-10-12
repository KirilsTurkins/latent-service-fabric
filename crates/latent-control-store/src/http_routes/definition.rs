use super::{capacity, invalid, MAX_DEFINITION_BYTES, MAX_IDENTIFIER_BYTES};
use latent_core::PlatformError;
use latent_ingress::http::{CanonicalTarget, Method, Scheme, CONTRACT, FUNCTION, PROFILE};
use latent_manifest::{
    __serde_json as json, JsonManifestCodec, ManifestCodec, TriggerKind, TriggerManifest,
    TriggerTarget,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum PathMatch {
    Exact,
    Prefix,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct Matcher {
    pub scheme: Scheme,
    pub authority: String,
    pub path: String,
    pub path_match: PathMatch,
    pub method: Method,
}
impl Matcher {
    pub fn matches(&self, target: &CanonicalTarget, method: Method) -> bool {
        self.scheme == target.scheme()
            && self.authority == target.authority()
            && self.method == method
            && match self.path_match {
                PathMatch::Exact => self.path == target.path(),
                PathMatch::Prefix => {
                    self.path == "/"
                        || self.path == target.path()
                        || target
                            .path()
                            .strip_prefix(&self.path)
                            .is_some_and(|suffix| suffix.starts_with('/'))
                }
            }
    }
    pub fn precedence(&self) -> (usize, bool) {
        (self.path.len(), self.path_match == PathMatch::Exact)
    }

    /// Derives a canonical site-local path from the already-canonical external
    /// request. No second URL parser or normalization pass participates.
    pub fn site_path(&self, target: &CanonicalTarget) -> Option<String> {
        if self.path == "/" {
            return Some(target.path().to_owned());
        }
        if target.path() == self.path {
            return Some("/".into());
        }
        target
            .path()
            .strip_prefix(&self.path)
            .filter(|suffix| suffix.starts_with('/'))
            .map(str::to_owned)
    }
}

pub(crate) fn reserved_node_path(path: &str) -> bool {
    path == "/_lsf" || path.starts_with("/_lsf/")
}

/// Bound every field before the generic manifest codec can traverse or copy it.
/// Each supported profile has a closed string configuration, with no arbitrary
/// JSON children or request-controlled scope selectors.
pub(crate) fn normalize(
    mut value: TriggerManifest,
) -> Result<(TriggerManifest, Matcher), PlatformError> {
    bounded(&value)?;
    if value.kind != TriggerKind::Http {
        return Err(invalid());
    }
    let field = |key: &str| {
        value
            .configuration
            .get(key)
            .and_then(json::Value::as_str)
            .ok_or_else(invalid)
    };
    let profile = field("profile")?;
    match &value.target {
        TriggerTarget::Application(target) => {
            let transaction = profile == latent_ingress::http::transaction::PROFILE;
            if (!transaction
                && (profile != PROFILE
                    || target.contract.0 != CONTRACT
                    || target.function != FUNCTION))
                || target
                    .route
                    .as_deref()
                    .is_none_or(|route| route == "default")
                || target.publication.is_none()
                || target
                    .deployment_generation
                    .is_none_or(|generation| generation == 0)
                || !target.revision.as_ref().is_some_and(|revision| {
                    revision.strip_prefix("revision-v1:").is_some_and(|digest| {
                        digest.parse::<latent_core::ArtifactBlobDigest>().is_ok()
                    })
                })
            {
                return Err(invalid());
            }
        }
        TriggerTarget::StaticWeb(_) if profile == latent_artifacts::web::STATIC_SITE_PROFILE => {}
        TriggerTarget::StaticWeb(_) => return Err(invalid()),
    }
    let scheme = match field("scheme")? {
        "http" => Scheme::Http,
        "https" => Scheme::Https,
        _ => return Err(invalid()),
    };
    let method = Method::parse(field("method")?).map_err(|_| invalid())?;
    if profile == latent_ingress::http::transaction::PROFILE {
        latent_ingress::http::transaction::TransactionRoute::from_configuration(
            &value.configuration,
        )
        .and_then(|route| route.require_method(method))
        .map_err(|_| invalid())?;
    }
    if matches!(&value.target, TriggerTarget::StaticWeb(_))
        && !matches!(method, Method::Get | Method::Head)
    {
        return Err(invalid());
    }
    let path_match = match field("pathMatch")? {
        "exact" => PathMatch::Exact,
        "prefix" => PathMatch::Prefix,
        _ => return Err(invalid()),
    };
    let target =
        CanonicalTarget::parse(scheme, field("host")?, field("path")?).map_err(|_| invalid())?;
    if target.query().is_some()
        || (path_match == PathMatch::Prefix && target.path() != "/" && target.path().ends_with('/'))
    {
        return Err(invalid());
    }
    let matcher = Matcher {
        scheme,
        authority: target.authority().into(),
        path: target.path().into(),
        path_match,
        method,
    };
    value.configuration.insert(
        "host".into(),
        json::Value::String(matcher.authority.clone()),
    );
    value
        .configuration
        .insert("path".into(), json::Value::String(matcher.path.clone()));
    let bytes = JsonManifestCodec::default()
        .encode_trigger(&value)
        .map_err(|_| invalid())?;
    if bytes.len() > MAX_DEFINITION_BYTES {
        return Err(capacity());
    }
    Ok((value, matcher))
}
pub(crate) fn token(value: &str, maximum: usize) -> bool {
    !value.is_empty() && value.len() <= maximum && !value.chars().any(char::is_control)
}
fn text(value: &String, maximum: usize) -> bool {
    token(value, maximum) && value.capacity() <= maximum
}

pub(crate) fn bounded(value: &TriggerManifest) -> Result<(), PlatformError> {
    if value.api_version != latent_manifest::MANIFEST_API_VERSION
        || value.api_version.capacity() > 32
        || value.id.0 != value.metadata.name
        || value.metadata.tenant.is_none()
        || ![&value.id.0, &value.metadata.name]
            .into_iter()
            .all(|s| text(s, MAX_IDENTIFIER_BYTES))
        || value
            .metadata
            .tenant
            .as_ref()
            .is_some_and(|t| !text(&t.0, MAX_IDENTIFIER_BYTES))
        || value
            .metadata
            .namespace
            .as_ref()
            .is_some_and(|s| !text(s, MAX_IDENTIFIER_BYTES))
        || !configuration_count(value)
    {
        return Err(invalid());
    }
    match &value.target {
        TriggerTarget::Application(target) => {
            if !text(&target.service.0, MAX_IDENTIFIER_BYTES)
                || !text(&target.contract.0, 256)
                || !text(&target.function, 128)
                || target
                    .route
                    .as_ref()
                    .is_some_and(|s| !text(s, MAX_IDENTIFIER_BYTES))
                || target.revision.as_ref().is_some_and(|s| !text(s, 128))
            {
                return Err(invalid());
            }
        }
        TriggerTarget::StaticWeb(target) => {
            if target.publication.as_str().len() > 83 {
                return Err(invalid());
            }
        }
    }
    for fields in [&value.metadata.labels, &value.metadata.annotations] {
        if fields.len() > 16
            || fields.iter().any(|(k, v)| {
                !text(k, 128) || v.capacity() > 256 || v.chars().any(char::is_control)
            })
        {
            return Err(invalid());
        }
    }
    let transaction = value
        .configuration
        .get("profile")
        .and_then(json::Value::as_str)
        == Some(latent_ingress::http::transaction::PROFILE);
    for (key, value) in &value.configuration {
        if key.capacity() > 32 {
            return Err(invalid());
        }
        let json::Value::String(value) = value else {
            return Err(invalid());
        };
        let maximum = configuration_maximum(key, transaction).ok_or_else(invalid)?;
        if !text(value, maximum) {
            return Err(invalid());
        }
    }
    Ok(())
}

fn configuration_count(value: &TriggerManifest) -> bool {
    let transaction = value
        .configuration
        .get("profile")
        .and_then(json::Value::as_str)
        == Some(latent_ingress::http::transaction::PROFILE);
    if transaction {
        (13..=15).contains(&value.configuration.len())
    } else {
        value.configuration.len() == 6
    }
}

fn configuration_maximum(key: &str, transaction: bool) -> Option<usize> {
    if transaction {
        return latent_ingress::http::transaction::configuration_limit(key);
    }
    match key {
        "path" => Some(8192),
        "host" => Some(255),
        "profile" | "scheme" | "pathMatch" | "method" => Some(32),
        _ => None,
    }
}
