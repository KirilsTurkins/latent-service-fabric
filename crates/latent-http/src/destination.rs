use crate::{HttpAddressPolicy, HttpError, HttpProviderConfig};
use latent_policy::capability::HttpOrigin;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
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
impl HttpAddressPolicy {
    #[must_use]
    pub fn permits(&self, address: IpAddr) -> bool {
        let ip = canonical(address);
        let in_network = self.networks.iter().any(|network| network.contains(&ip));
        in_network && (!special(ip) || self.special_addresses.iter().any(|a| canonical(*a) == ip))
    }
}
pub(crate) fn canonical(ip: IpAddr) -> IpAddr {
    match ip {
        IpAddr::V6(ip) => ip.to_ipv4_mapped().map_or(IpAddr::V6(ip), IpAddr::V4),
        ip @ IpAddr::V4(_) => ip,
    }
}
fn special(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip) => special4(ip),
        IpAddr::V6(ip) => special6(ip),
    }
}
fn special4(ip: Ipv4Addr) -> bool {
    let [a, b, c, _] = ip.octets();
    ip == Ipv4Addr::new(168, 63, 129, 16)
        || a == 0
        || a == 10
        || a == 127
        || a >= 224
        || (a == 100 && (64..=127).contains(&b))
        || (a == 169 && b == 254)
        || (a == 172 && (16..=31).contains(&b))
        || (a == 192 && ((b == 0 && (c == 0 || c == 2)) || (b == 88 && c == 99) || b == 168))
        || (a == 198 && ((b == 18 || b == 19) || (b == 51 && c == 100)))
        || (a == 203 && b == 0 && c == 113)
}
fn special6(ip: Ipv6Addr) -> bool {
    let [a, b, _, _, _, _, _, _] = ip.segments();
    // Only global unicast 2000::/3 is ordinary, excluding embedded-v4,
    // protocol-assignment, benchmark, documentation and transition spaces.
    a & 0xe000 != 0x2000 || a == 0x2002 || (a == 0x2001 && (b < 0x200 || b == 0xdb8)) || a == 0x3fff
}
