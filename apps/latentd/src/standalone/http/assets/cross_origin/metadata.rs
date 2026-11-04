//! Provisional browser admission; only exact publication selection can finish it.
use crate::config::http::{CrossOriginAssetGrant, CrossOriginCredentials};
use latent_ingress::http::{CanonicalTarget, HeaderView, Method, Scheme};

#[derive(Debug)]
pub(in crate::standalone::http) struct Candidate {
    pub(super) origin: String,
    pub(super) method: Method,
    pub(super) preflight: Option<String>,
    pub(super) cookie: bool,
}

pub(in crate::standalone::http) fn admit(
    grants: &[CrossOriginAssetGrant],
    target: &CanonicalTarget,
    tenant: &str,
    method: Method,
    headers: &[HeaderView<'_>],
) -> Result<Option<Candidate>, u16> {
    if grants.is_empty() {
        return Ok(None);
    }
    let origin = singleton(headers, "origin")?;
    // Preserve the original profile for same-origin and non-browser callers.
    let Some(origin) = origin else {
        return Ok(None);
    };
    if origin.strip_prefix(b"https://") == Some(target.authority().as_bytes()) {
        return Ok(None);
    }
    if target.scheme() != Scheme::Https || origin.len() > 512 {
        return Err(403);
    }
    let origin = std::str::from_utf8(origin).map_err(|_| 403u16)?;
    let approved = grants
        .iter()
        .find_map(|grant| grant.caller(target.authority(), tenant, origin))
        .ok_or(403u16)?;
    if singleton(headers, "sec-fetch-mode")? != Some(b"cors")
        || !matches!(
            singleton(headers, "sec-fetch-site")?,
            Some(b"same-site" | b"cross-site")
        )
        || !matches!(
            singleton(headers, "sec-fetch-dest")?,
            Some(b"empty" | b"script" | b"style" | b"font" | b"image" | b"manifest")
        )
        || singleton(headers, "sec-fetch-user")?.is_some()
        || headers.iter().any(|header| {
            [
                "authorization",
                "proxy-authorization",
                "x-tenant",
                "x-lsf-tenant",
            ]
            .iter()
            .any(|name| header.name.eq_ignore_ascii_case(name))
        })
    {
        return Err(403);
    }
    let cookie = singleton(headers, "cookie")?.is_some();
    let requested_method = singleton(headers, "access-control-request-method")?;
    let requested_headers = singleton(headers, "access-control-request-headers")?;
    let (method, preflight) = if method == Method::Options {
        if cookie || singleton(headers, "sec-fetch-dest")? != Some(b"empty") {
            return Err(403);
        }
        let requested = match requested_method {
            Some(b"GET") => Method::Get,
            Some(b"HEAD") => Method::Head,
            _ => return Err(403),
        };
        (requested, Some(conditional_headers(requested_headers)?))
    } else {
        if !matches!(method, Method::Get | Method::Head)
            || requested_method.is_some()
            || requested_headers.is_some()
        {
            return Err(403);
        }
        (method, None)
    };
    Ok(Some(Candidate {
        // Copy approved configuration, never arbitrary caller-provided bytes.
        origin: approved.to_owned(),
        method,
        preflight,
        cookie,
    }))
}

impl Candidate {
    pub(super) fn grant<'a>(
        &self,
        grants: &'a [CrossOriginAssetGrant],
        authority: &str,
        tenant: &str,
        publication: &str,
    ) -> Result<&'a CrossOriginAssetGrant, u16> {
        let grant = grants
            .iter()
            .find(|grant| {
                grant.publication == publication
                    && grant.caller(authority, tenant, &self.origin).is_some()
            })
            .ok_or(403u16)?;
        if self.cookie && grant.credentials == CrossOriginCredentials::Omit {
            return Err(403);
        }
        Ok(grant)
    }
}

fn conditional_headers(value: Option<&[u8]>) -> Result<String, u16> {
    let Some(value) = value else {
        return Ok(String::new());
    };
    if value.is_empty() || value.len() > 64 {
        return Err(403);
    }
    let value = std::str::from_utf8(value).map_err(|_| 403u16)?;
    let mut names = [false; 2];
    for (index, name) in value.split(',').enumerate() {
        let slot = match name.trim_matches([' ', '\t']) {
            "if-none-match" => 0,
            "if-modified-since" => 1,
            _ => return Err(403),
        };
        if index >= 2 || names[slot] {
            return Err(403);
        }
        names[slot] = true;
    }
    Ok(match names {
        [true, true] => "if-none-match, if-modified-since",
        [true, false] => "if-none-match",
        [false, true] => "if-modified-since",
        [false, false] => return Err(403),
    }
    .to_owned())
}

fn singleton<'a>(headers: &[HeaderView<'a>], name: &str) -> Result<Option<&'a [u8]>, u16> {
    let mut values = headers
        .iter()
        .filter(|header| header.name.eq_ignore_ascii_case(name));
    let result = values.next().map(|header| header.value);
    if values.next().is_some() {
        return Err(400);
    }
    Ok(result)
}

#[cfg(test)]
mod tests;
