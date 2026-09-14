use super::{auth, cache, tick, Arc, Inner, Result, SecretError};
use latent_capabilities::broker::pools::PoolCall;
use latent_http::protocol::{ProtocolBody, ProtocolRequest, ProtocolScope};
use std::time::Duration;
use zeroize::Zeroizing;

pub(super) async fn fetch(
    inner: &Inner,
    call: &PoolCall,
    index: usize,
    sequence: u64,
    auth: auth::Auth,
) -> Result<Arc<cache::Value>> {
    let limits = inner.config.limits;
    // Raw body, bounded decoder scratch/key copies and selected value coexist.
    // Both reservations precede allocating any response plaintext.
    let _parser = inner
        .plaintext
        .reserve(&inner.pools, 3 * limits.maximum_response_bytes + 65536)?;
    let value_charge = inner
        .plaintext
        .reserve(&inner.pools, limits.maximum_value_bytes)?;
    let reference = &inner.config.references[index];
    let mut path = format!("/v1/{}/data/{}", reference.mount, reference.path);
    if let Some(version) = reference.version {
        use std::fmt::Write;
        let _ = write!(path, "?version={version}");
    }
    let (headers, stamp) = auth.headers(inner);
    let request = ProtocolRequest {
        method: "GET".into(),
        path_and_query: path,
        headers,
        body: ProtocolBody::empty(&inner.pools).map_err(|_| SecretError::Unavailable)?,
    };
    let mut body = Zeroizing::new(Vec::with_capacity(limits.maximum_response_bytes));
    call.io().checkpoint()?;
    tick(&inner.requests);
    let response = inner
        .transport
        .exchange(
            ProtocolScope::Invocation(call),
            request,
            limits.maximum_response_bytes,
            &mut |bytes| {
                if body.len() + bytes.len() > limits.maximum_response_bytes {
                    return Err(latent_capabilities::broker::http::HttpError::ResponseTooLarge);
                }
                body.extend_from_slice(bytes);
                Ok(())
            },
        )
        .await
        .map_err(|_| SecretError::Unavailable)?;
    match response.status {
        200 => (),
        401 | 403 => return Err(SecretError::PermissionDenied),
        404 => return Err(SecretError::NotFound),
        _ => return Err(SecretError::Unavailable),
    }
    let mut content_types = response.headers.iter().filter(|h| h.0 == "content-type");
    if !content_types.next().is_some_and(|h| {
        h.1.split(';')
            .next()
            .is_some_and(|v| v.trim().eq_ignore_ascii_case("application/json"))
    }) || content_types.next().is_some()
        || response.headers.iter().any(|h| h.0 == "content-encoding")
    {
        return Err(SecretError::Unavailable);
    }
    drop(response);
    let value = crate::vault::json::decode(&body, reference, limits.maximum_value_bytes)?;
    call.io().checkpoint()?;
    let now = inner.clock.sample();
    inner.expiry[index].check(now)?;
    let expiration = match (reference.expires_at_unix_millis, value.deletion_millis) {
        (Some(a), Some(b)) => Some(a.min(b)),
        (a, b) => a.or(b),
    };
    let expiry = cache::Expiry::new(expiration, now)?;
    // A scheduled KV deletion is a storage expiry, never a renewable lease.
    expiry.check(now)?;
    let fresh_until = if limits.cache_ttl_millis == 0 {
        None
    } else {
        Some(
            now.monotonic()
                .checked_add(Duration::from_millis(limits.cache_ttl_millis))
                .ok_or(SecretError::Unavailable)?,
        )
    };
    let value = Arc::new(cache::Value {
        bytes: value.bytes,
        version: value.version,
        version_text: value.version.to_string(),
        expiry,
        fresh_until,
        token: stamp,
        sequence,
        _plaintext: value_charge,
    });
    inner.check()?;
    auth::with_current(inner, index, &value.token, &mut || {
        call.io().checkpoint().map_err(Into::into)
    })?;
    inner
        .cache
        .try_lock()
        .map_err(|_| SecretError::Unavailable)?
        .install(index, &value, limits)?;
    Ok(value)
}
