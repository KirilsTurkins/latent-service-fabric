use super::{super::DeliveryCause, Delivery, PublicCachePolicy};

/// A deliberately closed subset, not a permissive Cache-Control parser. No
/// heuristic freshness, revalidation, errors, stale reuse or negative caching.
pub(super) fn ttl(delivery: &Delivery, policy: &PublicCachePolicy) -> Option<u64> {
    if delivery.status() != 200 || delivery.cause() != DeliveryCause::Application {
        return None;
    }
    let mut control = None;
    let mut vary = [false; 3];
    // Inspect original guest metadata, before the outward no-store override.
    for header in &delivery.response.headers.0 {
        let name = header.name.0.as_str();
        let value = std::str::from_utf8(&header.value.0).ok()?;
        match name {
            "cache-control" if control.is_none() => control = Some(value),
            "vary" => {
                for name in value.split(',').map(str::trim) {
                    let index = policy.vary.iter().position(|v| v.name.eq_ignore_ascii_case(name))?;
                    if vary[index] {
                        return None;
                    }
                    vary[index] = true;
                }
            }
            "content-language" | "etag" | "last-modified" | "content-security-policy"
            | "x-content-type-options" | "referrer-policy" => {}
            // Includes Set-Cookie, credentials, Age, Expires, cache extensions,
            // duplicate Cache-Control and unknown/unbounded Vary fields.
            _ => return None,
        }
    }
    let mut public = false;
    let mut maximum_age = None;
    let mut shared_age = None;
    for directive in control?.split(',').map(str::trim) {
        if directive.eq_ignore_ascii_case("public") && !public {
            public = true;
        } else if let Some((name, value)) = directive.split_once('=') {
            if value.is_empty() || !value.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            let age: u64 = value.parse().ok()?;
            if name.eq_ignore_ascii_case("max-age") && maximum_age.is_none() {
                maximum_age = Some(age);
            } else if name.eq_ignore_ascii_case("s-maxage") && shared_age.is_none() {
                shared_age = Some(age);
            } else {
                return None;
            }
        } else {
            return None;
        }
    }
    let ttl = maximum_age?.min(shared_age.unwrap_or(u64::MAX)).min(policy.maximum_age_seconds);
    (public && ttl > 0).then_some(ttl)
}
