use crate::{HttpError, HttpProviderConfig};
pub(crate) use latent_network::canonical;
use latent_policy::capability::HttpOrigin;
use url::{Host, Url};

pub(crate) struct Destination {
    pub url: Url,
    pub origin: HttpOrigin,
    pub index: usize,
}
pub(crate) fn parse(raw: &str, config: &HttpProviderConfig) -> Result<Destination, HttpError> {
    if raw.is_empty()
        || raw.len() > 2048
        || !raw.is_ascii()
        || raw.bytes().any(|b| b <= 32 || b == 127 || b == b'\\')
    {
        return Err(HttpError::InvalidUrl);
    }
    let authority = raw
        .split_once("://")
        .ok_or(HttpError::InvalidUrl)?
        .1
        .split(['/', '?', '#'])
        .next()
        .ok_or(HttpError::InvalidUrl)?;
    if authority.contains('@') {
        return Err(HttpError::InvalidUrl);
    }
    let url = Url::parse(raw).map_err(|_| HttpError::InvalidUrl)?;
    if !matches!(url.scheme(), "http" | "https")
        || url.fragment().is_some()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err(HttpError::InvalidUrl);
    }
    let host = match url.host().ok_or(HttpError::InvalidUrl)? {
        Host::Domain(host) => host.to_owned(),
        Host::Ipv4(ip) => ip.to_string(),
        Host::Ipv6(ip) => ip.to_string(),
    };
    let origin = HttpOrigin {
        scheme: url.scheme().into(),
        host,
        port: url.port_or_known_default().ok_or(HttpError::InvalidUrl)?,
    };
    let index = config
        .destinations
        .iter()
        .position(|d| d.origin == origin)
        .ok_or(HttpError::PermissionDenied)?;
    // This is the same normalized path sent on the wire. The closed policy's
    // initial profile rejects encoded separators/dot ambiguity and '%' paths.
    let target =
        serde_json::json!({"kind":"http","origin":origin,"method":"GET","path":url.path()});
    latent_policy::capability::ResourceRequest::parse(
        &serde_json::to_vec(&target).map_err(|_| HttpError::InvalidUrl)?,
    )
    .map_err(|_| HttpError::InvalidUrl)?;
    Ok(Destination { url, origin, index })
}
