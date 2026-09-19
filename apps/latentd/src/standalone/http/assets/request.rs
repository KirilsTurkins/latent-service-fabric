use latent_artifacts::{web::IMMUTABLE_ASSET_PREFIX, LifecycleScope, PublicationRef};
use latent_core::TenantId;
use latent_ingress::http::MAX_HEADERS;

const MAX_CONDITION_BYTES: usize = 2048;
const MAX_TAGS: usize = 16;

pub(in crate::standalone::http) struct Request {
    pub reference: PublicationRef,
    pub path: String,
    pub head: bool,
    pub route: Option<latent_control_store::http_routes::AcceptedHttpRoute>,
    matching: Option<Tags>,
    none_matching: Option<Tags>,
}
impl Request {
    // Parse transport-validated bounded headers again only to capture this
    // profile's fields. Never decode the raw target: aliases are not asset URLs.
    pub(super) fn parse(bytes: &[u8], tenant: &TenantId) -> Result<Self, u16> {
        Self::parse_selected(bytes, tenant, None)
    }

    pub(super) fn parse_routed(
        bytes: &[u8],
        tenant: &TenantId,
        reference: PublicationRef,
        path: String,
    ) -> Result<Self, u16> {
        if reference.scope.tenant() != Some(tenant) {
            return Err(403);
        }
        Self::parse_selected(bytes, tenant, Some((reference, path)))
    }

    fn parse_selected(
        bytes: &[u8],
        tenant: &TenantId,
        selected: Option<(PublicationRef, String)>,
    ) -> Result<Self, u16> {
        let mut fields = [httparse::EMPTY_HEADER; MAX_HEADERS];
        let mut message = httparse::Request::new(&mut fields);
        if !matches!(message.parse(bytes), Ok(httparse::Status::Complete(n)) if n == bytes.len()) {
            return Err(400);
        }
        let head = match message.method {
            Some("GET") => false,
            Some("HEAD") => true,
            _ => return Err(405),
        };
        let target = message.path.ok_or(400u16)?;
        let (reference, path) = match selected {
            Some(selected) => selected,
            None => locator(target, tenant)?,
        };
        let matching = single(message.headers, "if-match")?
            .map(Tags::parse)
            .transpose()?;
        let none_matching = single(message.headers, "if-none-match")?
            .map(Tags::parse)
            .transpose()?;
        if !identity_allowed(single(message.headers, "accept-encoding")?)? {
            return Err(406);
        }
        Ok(Self {
            reference,
            path,
            head,
            route: None,
            matching,
            none_matching,
        })
    }

    pub(super) fn status(&self, etag: &str) -> Result<u16, u16> {
        // RFC 9110 precedence: If-Match is evaluated before If-None-Match.
        if self
            .matching
            .as_ref()
            .is_some_and(|tags| !tags.matches(etag, false))
        {
            return Err(412);
        }
        Ok(
            if self
                .none_matching
                .as_ref()
                .is_some_and(|tags| tags.matches(etag, true))
            {
                304
            } else {
                200
            },
        )
    }
}

fn locator(target: &str, tenant: &TenantId) -> Result<(PublicationRef, String), u16> {
    let suffix = target.strip_prefix(IMMUTABLE_ASSET_PREFIX).ok_or(400u16)?;
    let (id, path) = suffix.split_once('/').ok_or(400u16)?;
    let id = id.parse().map_err(|_| 400u16)?;
    // Signed paths use the package's closed ASCII grammar. No query aliases,
    // encoded unreserved characters, percent-decoding, directory indexes or fallback.
    if path.is_empty() || path.len() >= 240 || target.contains(['%', '?', '#', '\\']) {
        return Err(400);
    }
    latent_artifacts::package::validate_package_path(
        path,
        latent_artifacts::package::PackageLimits::default(),
    )
    .map_err(|_| 400u16)?;
    let scope = LifecycleScope::Tenant(tenant.clone());
    scope.validate().map_err(|_| 403u16)?;
    Ok((PublicationRef { id, scope }, format!("/{path}")))
}

fn single<'a>(headers: &'a [httparse::Header<'_>], name: &str) -> Result<Option<&'a str>, u16> {
    let mut values = headers
        .iter()
        .filter(|header| header.name.eq_ignore_ascii_case(name));
    let value = values.next();
    if values.next().is_some() {
        return Err(400);
    }
    value
        .map(|header| {
            if header.value.len() > MAX_CONDITION_BYTES {
                return Err(431);
            }
            std::str::from_utf8(header.value).map_err(|_| 400u16)
        })
        .transpose()
}

#[derive(Debug)]
enum Tags {
    Any,
    Values(Vec<(bool, String)>),
}
impl Tags {
    fn parse(value: &str) -> Result<Self, u16> {
        let mut remaining = value.trim_matches([' ', '\t']);
        if remaining == "*" {
            return Ok(Self::Any);
        }
        let mut tags = Vec::new();
        loop {
            if tags.len() == MAX_TAGS {
                return Err(431);
            }
            let weak = remaining.starts_with("W/");
            if weak {
                remaining = &remaining[2..];
            }
            let tail = remaining.strip_prefix('"').ok_or(400u16)?;
            let end = tail.find('"').ok_or(400u16)?;
            if end > 128
                || !tail[..end]
                    .bytes()
                    .all(|b| b == 0x21 || (0x23..=0x7e).contains(&b))
            {
                return Err(400);
            }
            tags.push((weak, remaining[..end + 2].to_owned()));
            remaining = tail[end + 1..].trim_matches([' ', '\t']);
            if remaining.is_empty() {
                break;
            }
            remaining = remaining
                .strip_prefix(',')
                .ok_or(400u16)?
                .trim_start_matches([' ', '\t']);
        }
        Ok(Self::Values(tags))
    }
    fn matches(&self, etag: &str, allow_weak: bool) -> bool {
        match self {
            Self::Any => true,
            Self::Values(tags) => tags
                .iter()
                .any(|(weak, value)| (allow_weak || !weak) && value == etag),
        }
    }
}

fn identity_allowed(value: Option<&str>) -> Result<bool, u16> {
    let Some(value) = value else {
        return Ok(true);
    };
    if value.trim().is_empty() {
        return Ok(true);
    }
    let mut identity = None;
    let mut wildcard = None;
    for (index, entry) in value.split(',').enumerate() {
        if index >= 16 {
            return Err(431);
        }
        let mut parts = entry.trim().split(';');
        let coding = parts.next().ok_or(400u16)?.trim();
        if coding.is_empty()
            || !coding
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&b))
        {
            return Err(400);
        }
        let quality = parts.next().map_or(Ok(1000), |part| {
            let (name, value) = part.trim().split_once('=').ok_or(400u16)?;
            if !name.trim().eq_ignore_ascii_case("q") {
                return Err(400);
            }
            qvalue(value.trim())
        })?;
        if parts.next().is_some() {
            return Err(400);
        }
        let slot = if coding.eq_ignore_ascii_case("identity") {
            Some(&mut identity)
        } else if coding == "*" {
            Some(&mut wildcard)
        } else {
            None
        };
        if let Some(slot) = slot {
            if slot.replace(quality).is_some() {
                return Err(400);
            }
        }
    }
    Ok(identity.map_or(wildcard != Some(0), |q| q != 0))
}
fn qvalue(value: &str) -> Result<u16, u16> {
    let (whole, fraction) = value.split_once('.').unwrap_or((value, ""));
    if !matches!(whole, "0" | "1")
        || fraction.len() > 3
        || !fraction.bytes().all(|b| b.is_ascii_digit())
    {
        return Err(400);
    }
    if whole == "1" {
        return if fraction.bytes().all(|b| b == b'0') {
            Ok(1000)
        } else {
            Err(400)
        };
    }
    let mut result = 0;
    for index in 0..3 {
        result =
            result * 10 + u16::from(fraction.as_bytes().get(index).copied().unwrap_or(b'0') - b'0');
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn immutable_locator_rejects_aliases_and_private_or_noncanonical_paths() {
        let tenant = TenantId("tests".into());
        let prefix = format!(
            "{IMMUTABLE_ASSET_PREFIX}publication:sha256:{}/",
            "ab".repeat(32)
        );
        assert!(locator(&format!("{prefix}main.js"), &tenant).is_ok());
        for suffix in [
            "",
            "../main.js",
            "a/../main.js",
            "a//main.js",
            "./main.js",
            "main.js?x=1",
            "%6dain.js",
            "%2fmain.js",
            "a\\main.js",
            "main.js#x",
        ] {
            assert!(
                locator(&format!("{prefix}{suffix}"), &tenant).is_err(),
                "{suffix}"
            );
        }
    }
    #[test]
    fn conditional_lists_support_weak_comparison_commas_and_strong_precedence() {
        let tags = Tags::parse("W/\"a,b\", \"second\"").unwrap();
        assert!(tags.matches("\"a,b\"", true));
        assert!(!tags.matches("\"a,b\"", false));
        assert!(tags.matches("\"second\"", false));
        assert!(Tags::parse("*").unwrap().matches("\"any\"", false));
        for invalid in [
            "",
            "*, \"x\"",
            "\"x\",",
            "w/\"x\"",
            "unquoted",
            "\"x\" garbage",
        ] {
            assert!(Tags::parse(invalid).is_err(), "{invalid}");
        }
    }
    #[test]
    fn identity_exclusion_is_honored_without_decompression_or_qvalue_guessing() {
        for value in [
            None,
            Some(""),
            Some("gzip, br"),
            Some("identity;q=0.001"),
            Some("*;q=0, identity;q=1"),
        ] {
            assert!(identity_allowed(value).unwrap());
        }
        for value in ["identity;q=0", "*;q=0", "gzip, identity;q=0.000"] {
            assert!(!identity_allowed(Some(value)).unwrap());
        }
        for value in [
            "identity;q=1.1",
            "identity;q=-1",
            "identity;q=0.0001",
            "identity;q=NaN",
            "identity;q=0, identity;q=1",
            "gzip,,br",
        ] {
            assert!(identity_allowed(Some(value)).is_err(), "{value}");
        }
    }
}
