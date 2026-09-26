use super::{cookies, security_headers, MAX_COOKIE_BYTES};
use crate::http::{model::ResponseData, CanonicalTarget, Scheme};

pub(in crate::http) fn validate(response: &ResponseData, scheme: Scheme) -> bool {
    let mut location = None;
    let mut encoding = false;
    let mut cookies = Vec::new();
    let mut cookie_bytes = 0;
    for header in &response.headers.0 {
        let name = header.name.0.as_str();
        let value = header.value.0.as_slice();
        if security_headers(Scheme::Https).any(|owned| owned.name == name)
            || name.starts_with("access-control-")
            || matches!(
                name,
                "refresh"
                    | "content-location"
                    | "link"
                    | "clear-site-data"
                    | "report-to"
                    | "nel"
                    | "content-security-policy-report-only"
                    | "cross-origin-embedder-policy"
            )
        {
            return false;
        }
        if name == "content-encoding" {
            if encoding || !value.eq_ignore_ascii_case(b"identity") {
                return false;
            }
            encoding = true;
        }
        if name == "location" {
            if location.is_some() || !safe_location(value) {
                return false;
            }
            location = Some(value);
        }
        if name == "set-cookie" {
            cookie_bytes += value.len();
            if scheme != Scheme::Https
                || cookie_bytes > MAX_COOKIE_BYTES
                || !cookies::response(value, &mut cookies)
            {
                return false;
            }
        }
    }
    let redirect = matches!(response.status, 301 | 302 | 303 | 307 | 308);
    if redirect != location.is_some() && !(response.status == 201 && location.is_some()) {
        return false;
    }
    if let Some(media) = response.media_type.as_ref() {
        if media
            .0
            .split(';')
            .next()
            .is_some_and(|kind| kind.eq_ignore_ascii_case("text/html"))
            && (!media.0.eq_ignore_ascii_case("text/html; charset=utf-8")
                || std::str::from_utf8(&response.body.0).is_err())
        {
            return false;
        }
    }
    true
}

fn safe_location(value: &[u8]) -> bool {
    let Ok(value) = std::str::from_utf8(value) else {
        return false;
    };
    let Ok(target) = CanonicalTarget::parse(Scheme::Https, "redirect.invalid", value) else {
        return false;
    };
    let (path, query) = value
        .split_once('?')
        .map_or((value, None), |(path, query)| (path, Some(query)));
    target.path() == path && target.query() == query
}
