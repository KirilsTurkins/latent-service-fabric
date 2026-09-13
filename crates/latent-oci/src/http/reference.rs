use super::{invalid, RegistryConfig, Result};
use crate::OciReference;
use latent_core::PackageDigest;
use reqwest::Url;
use std::net::IpAddr;

pub(crate) struct Endpoint {
    pub(crate) authority: String,
    pub(crate) repository: String,
    origin: Url,
    prefix: String,
}

impl Endpoint {
    pub(crate) fn new(config: &RegistryConfig) -> Result<Self> {
        if config.origin.len() > 512 || !repository(&config.repository) {
            return Err(invalid("invalid-oci-endpoint"));
        }
        let origin = Url::parse(&config.origin).map_err(|_| invalid("invalid-oci-origin"))?;
        if !origin.username().is_empty()
            || origin.password().is_some()
            || origin.query().is_some()
            || origin.fragment().is_some()
            || origin.path() != "/"
            || origin.host().is_none()
        {
            return Err(invalid("invalid-oci-origin"));
        }
        let numeric = origin
            .host_str()
            .and_then(|host| host.trim_matches(['[', ']']).parse::<IpAddr>().ok());
        let loopback = numeric.is_some_and(|ip| ip.is_loopback());
        if origin.scheme() != "https"
            && !(origin.scheme() == "http" && config.allow_insecure_loopback && loopback)
        {
            return Err(invalid("oci-tls-required"));
        }
        if config.addresses.len() > 16 || (numeric.is_none() && config.addresses.is_empty()) {
            return Err(invalid("oci-bounded-addresses-required"));
        }
        let port = origin
            .port_or_known_default()
            .ok_or_else(|| invalid("invalid-oci-port"))?;
        if config.addresses.iter().any(|address| {
            address.port() != port
                || address.ip().is_unspecified()
                || (origin.scheme() == "http" && !address.ip().is_loopback())
        }) {
            return Err(invalid("invalid-oci-address"));
        }
        let authority = origin
            .origin()
            .ascii_serialization()
            .split_once("://")
            .expect("checked scheme")
            .1
            .to_owned();
        if authority.len() + 1 + config.repository.len() > 255 {
            return Err(invalid("oci-reference-too-long"));
        }
        Ok(Self {
            authority,
            repository: config.repository.clone(),
            origin,
            prefix: format!("/v2/{}/", config.repository),
        })
    }
    pub(crate) fn host(&self) -> &str {
        self.origin.host_str().expect("checked host")
    }
    pub(crate) fn check_reference(&self, reference: &OciReference) -> Result<()> {
        if reference.registry.len() > 512 {
            return Err(invalid("oci-reference-outside-configured-scope"));
        }
        let origin = Url::parse(&format!(
            "{}://{}",
            self.origin.scheme(),
            reference.registry
        ))
        .map_err(|_| invalid("oci-reference-outside-configured-scope"))?;
        if origin.origin() != self.origin.origin()
            || origin.path() != "/"
            || !origin.username().is_empty()
            || origin.password().is_some()
            || origin.query().is_some()
            || origin.fragment().is_some()
            || reference.repository != self.repository
            || !tag_or_digest(&reference.reference)
        {
            return Err(invalid("oci-reference-outside-configured-scope"));
        }
        Ok(())
    }
    pub(crate) fn url(&self, suffix: &str) -> Result<Url> {
        if suffix.len() > 512
            || suffix.starts_with('/')
            || suffix.contains(['?', '#', '%', '\\'])
            || suffix.split('/').any(|part| matches!(part, "." | ".."))
        {
            return Err(invalid("invalid-oci-path"));
        }
        let mut url = self.origin.clone();
        url.set_path(&format!("{}{suffix}", self.prefix));
        Ok(url)
    }
    /// Resolves a registry Location/Link against this origin. Prefix is an
    /// absolute path, or a suffix relative to this configured repository.
    pub(crate) fn scoped_url(&self, raw: &str, path_prefix: &str) -> Result<Url> {
        if raw.len() > 4096 || raw.contains('\\') {
            return Err(invalid("invalid-oci-location"));
        }
        let prefix = if path_prefix.starts_with('/') {
            path_prefix.to_owned()
        } else {
            format!("{}{path_prefix}", self.prefix)
        };
        let mut base = self.origin.clone();
        base.set_path(&prefix);
        let url = base
            .join(raw)
            .map_err(|_| invalid("invalid-oci-location"))?;
        self.check_url(&url)?;
        if !url.path().starts_with(&prefix) {
            return Err(invalid("oci-location-outside-operation"));
        }
        Ok(url)
    }
    pub(crate) fn check_url(&self, url: &Url) -> Result<()> {
        if url.as_str().len() > 4096
            || url.origin() != self.origin.origin()
            || !url.username().is_empty()
            || url.password().is_some()
            || url.fragment().is_some()
            || !url.path().starts_with(&self.prefix)
            || url.path().contains(['%', '\\'])
        {
            return Err(invalid("oci-location-outside-configured-scope"));
        }
        Ok(())
    }
}

pub(crate) fn tag_or_digest(value: &str) -> bool {
    if value.starts_with("sha256:") {
        return value.parse::<PackageDigest>().is_ok();
    }
    let bytes = value.as_bytes();
    !bytes.is_empty()
        && bytes.len() <= 128
        && (bytes[0].is_ascii_alphanumeric() || bytes[0] == b'_')
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'.' | b'-'))
}
fn repository(value: &str) -> bool {
    !value.is_empty() && value.len() <= 255 && value.split('/').all(repository_part)
}
fn repository_part(value: &str) -> bool {
    let bytes = value.as_bytes();
    let alnum = |byte: u8| byte.is_ascii_lowercase() || byte.is_ascii_digit();
    let mut cursor = 0;
    loop {
        let start = cursor;
        while cursor < bytes.len() && alnum(bytes[cursor]) {
            cursor += 1;
        }
        if cursor == start {
            return false;
        }
        if cursor == bytes.len() {
            return true;
        }
        match bytes[cursor] {
            b'.' => cursor += 1,
            b'_' => {
                cursor += 1;
                if bytes.get(cursor) == Some(&b'_') {
                    cursor += 1;
                }
            }
            b'-' => {
                while bytes.get(cursor) == Some(&b'-') {
                    cursor += 1;
                }
            }
            _ => return false,
        }
    }
}
