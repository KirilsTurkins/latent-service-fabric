mod cookies;
mod response;
#[cfg(test)]
mod tests;

use super::{CanonicalTarget, HeaderView, Method, Scheme};
pub(super) use response::validate as validate_response;

pub const PROFILE: &str = "same-origin-v1";
pub const CSP: &str = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; worker-src 'none'; manifest-src 'self'";
pub const MAX_COOKIE_BYTES: usize = 4096;
pub const MAX_COOKIES: usize = 16;

pub fn security_headers<'value>(scheme: Scheme) -> impl Iterator<Item = HeaderView<'value>> {
    [
        ("content-security-policy", CSP),
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "same-origin"),
        ("cross-origin-opener-policy", "same-origin"),
        ("cross-origin-resource-policy", "same-origin"),
        (
            "permissions-policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        ),
    ]
    .into_iter()
    .chain((scheme == Scheme::Https).then_some(("strict-transport-security", "max-age=31536000")))
    .map(|(name, value)| HeaderView {
        name,
        value: value.as_bytes(),
    })
}

pub fn validate_input(headers: &[HeaderView<'_>]) -> Result<(), u16> {
    cookies::request(headers)?;
    let encoding = singleton(headers, "content-encoding")?;
    if encoding.is_some_and(|value| !value.eq_ignore_ascii_case(b"identity")) {
        return Err(415);
    }
    Ok(())
}

pub fn admit(
    target: &CanonicalTarget,
    method: Method,
    headers: &[HeaderView<'_>],
    approved_origin: bool,
    bearer: bool,
) -> Result<(), u16> {
    let origin = singleton(headers, "origin")?;
    let site = singleton(headers, "sec-fetch-site")?;
    let mode = singleton(headers, "sec-fetch-mode")?;
    let destination = singleton(headers, "sec-fetch-dest")?;
    let user = singleton(headers, "sec-fetch-user")?;
    let browser = origin.is_some()
        || headers.iter().any(|header| {
            header
                .name
                .get(..10)
                .is_some_and(|name| name.eq_ignore_ascii_case("sec-fetch-"))
        });
    if browser && !approved_origin {
        return Err(403);
    }
    if let Some(origin) = origin {
        let prefix = if target.scheme() == Scheme::Https {
            "https://"
        } else {
            "http://"
        };
        if origin.strip_prefix(prefix.as_bytes()) != Some(target.authority().as_bytes()) {
            return Err(403);
        }
    }
    if site.is_some_and(|value| !matches!(value, b"same-origin" | b"none")) {
        return Err(403);
    }
    if mode
        .is_some_and(|value| !matches!(value, b"navigate" | b"same-origin" | b"cors" | b"no-cors"))
        || destination.is_some_and(|value| {
            !matches!(
                value,
                b"document" | b"empty" | b"script" | b"style" | b"image" | b"font" | b"manifest"
            )
        })
        || user.is_some_and(|value| value != b"?1")
        || headers.iter().any(|header| {
            header
                .name
                .eq_ignore_ascii_case("access-control-request-method")
                || header
                    .name
                    .eq_ignore_ascii_case("access-control-request-headers")
        })
    {
        return Err(403);
    }
    if !matches!(method, Method::Get | Method::Head | Method::Options)
        && (origin.is_none() && (browser || !bearer) || site == Some(b"none"))
    {
        return Err(403);
    }
    Ok(())
}

fn singleton<'value>(
    headers: &[HeaderView<'value>],
    name: &str,
) -> Result<Option<&'value [u8]>, u16> {
    let mut values = headers
        .iter()
        .filter(|header| header.name.eq_ignore_ascii_case(name));
    let result = values.next().map(|header| header.value);
    if values.next().is_some() {
        return Err(400);
    }
    Ok(result)
}
