use super::{inventory, Arc, BlobError, Digest, Inner, PoolCall, ProviderMetadata, Result, Sha256};
use crate::s3::{signing, xml::Document, PART_BYTES, XML_BYTES};
use latent_capabilities::broker::{http::HttpError, io::IoBuffer};
use latent_http::protocol::{
    ProtocolBody, ProtocolPage, ProtocolRequest, ProtocolResponse, ProtocolScope,
};

pub(super) struct Spec<'a> {
    pub method: &'a str,
    pub key: Option<&'a str>,
    pub query: &'a [(&'a str, &'a str)],
    pub extra: &'a [(&'a str, &'a str)],
    pub payload_sha: &'a str,
    pub body: ProtocolBody,
}
pub(super) struct Small {
    pub response: ProtocolResponse,
    pub bytes: Vec<u8>,
    _metadata: ProviderMetadata,
}
impl Small {
    pub fn document(&self) -> Result<Document> {
        Document::parse(&self.bytes)
    }
    pub fn success(&self, expected: u16) -> Result<()> {
        if self.response.status == expected {
            return Ok(());
        }
        Err(match self.response.status {
            401 | 403 => BlobError::PermissionDenied,
            404 => BlobError::NotFound,
            _ => BlobError::Uncertain,
        })
    }
}
pub(super) fn header<'a>(response: &'a ProtocolResponse, name: &str) -> Result<&'a str> {
    let mut values = response.headers.iter().filter(|v| v.0 == name);
    let value = values.next().ok_or(BlobError::Uncertain)?;
    if values.next().is_some() || !crate::s3::text(&value.1, 1024) {
        return Err(BlobError::Uncertain);
    }
    Ok(&value.1)
}
pub(super) fn request(inner: &Inner, tenant: &str, spec: Spec<'_>) -> Result<ProtocolRequest> {
    let config = inner.inventory.config();
    let path = if let Some(key) = spec.key {
        if !key.starts_with(&config.prefix) || key.len() > 256 {
            return Err(BlobError::PermissionDenied);
        }
        format!("/{}/{}", config.bucket, signing::encode(key, true))
    } else {
        format!("/{}", config.bucket)
    };
    if spec.query.len() > 8
        || spec
            .query
            .iter()
            .any(|(k, v)| k.len() > 64 || v.len() > 1024)
    {
        return Err(BlobError::InvalidRange);
    }
    let query = signing::query(spec.query);
    let headers = signing::headers(
        inner.credential(tenant)?,
        signing::Input {
            method: spec.method,
            path: &path,
            query: &query,
            host: &config.host(),
            region: &config.region,
            time: &signing::timestamp()?,
            payload_sha: spec.payload_sha,
        },
        spec.extra,
    )?;
    let path_and_query = if query.is_empty() {
        path
    } else {
        format!("{path}?{query}")
    };
    Ok(ProtocolRequest {
        method: spec.method.into(),
        path_and_query,
        headers,
        body: spec.body,
    })
}
pub(super) async fn small(
    inner: &Inner,
    tenant: &str,
    scope: ProtocolScope<'_>,
    spec: Spec<'_>,
) -> Result<Small> {
    let metadata = inner
        .pools
        .reserve_protocol_metadata(XML_BYTES * 4 + 65536)?;
    let request = request(inner, tenant, spec)?;
    let mut bytes = Vec::with_capacity(XML_BYTES);
    let response = inner
        .transport
        .exchange(scope, request, XML_BYTES, &mut |data| {
            if bytes.len() + data.len() > XML_BYTES {
                return Err(HttpError::ResponseTooLarge);
            }
            bytes.extend_from_slice(data);
            Ok(())
        })
        .await
        .map_err(|failure| {
            if failure.request_started {
                BlobError::Uncertain
            } else {
                crate::s3::http(failure.error)
            }
        })?;
    if response.headers.iter().any(|h| h.0 == "content-encoding") {
        return Err(BlobError::Uncertain);
    }
    Ok(Small {
        response,
        bytes,
        _metadata: metadata,
    })
}
pub(super) fn body(inner: &Inner, bytes: &[u8]) -> Result<ProtocolBody> {
    if bytes.len() > XML_BYTES {
        return Err(BlobError::BudgetExhausted);
    }
    if bytes.is_empty() {
        return ProtocolBody::empty(&inner.pools).map_err(crate::s3::http);
    }
    let mut page = ProtocolPage::allocate(&inner.pools, bytes.len()).map_err(crate::s3::http)?;
    page.append(bytes).map_err(crate::s3::http)?;
    ProtocolBody::from_pages(&inner.pools, &[Arc::new(page)], 0..bytes.len())
        .map_err(crate::s3::http)
}
pub(super) async fn read(
    inner: &Inner,
    call: &PoolCall,
    record: &inventory::Record,
    offset: u64,
    length: u32,
    buffer: &mut IoBuffer,
) -> Result<()> {
    if length == 0 {
        call.io().checkpoint()?;
        return Ok(());
    }
    let _memory = inner.pools.reserve_protocol_metadata(131_072)?;
    let start = usize::try_from(offset).map_err(|_| BlobError::InvalidRange)?;
    let end = start + length as usize;
    let key = record.object_key(inner.inventory.config());
    let version = record.version.as_deref().ok_or(BlobError::Uncertain)?;
    for part in start / PART_BYTES..=(end - 1) / PART_BYTES {
        let low = part * PART_BYTES;
        let high = (low + PART_BYTES)
            .min(usize::try_from(record.size).map_err(|_| BlobError::InvalidRange)?);
        let range = format!("bytes={low}-{}", high - 1);
        let request = request(
            inner,
            &record.tenant,
            Spec {
                method: "GET",
                key: Some(&key),
                query: &[("versionId", version)],
                extra: &[("range", &range)],
                payload_sha: &crate::s3::sha(b""),
                body: body(inner, b"")?,
            },
        )?;
        let mut digest = Sha256::new();
        let mut position = low;
        let response = inner
            .transport
            .exchange(
                ProtocolScope::Invocation(call),
                request,
                high - low,
                &mut |bytes| {
                    digest.update(bytes);
                    let next = position + bytes.len();
                    let copy_start = position.max(start);
                    let copy_end = next.min(end);
                    if copy_end > copy_start {
                        let count = copy_end - copy_start;
                        buffer.spare_mut().map_err(HttpError::from)?[..count]
                            .copy_from_slice(&bytes[copy_start - position..copy_end - position]);
                        buffer.advance_written(count).map_err(HttpError::from)?;
                    }
                    position = next;
                    Ok(())
                },
            )
            .await
            .map_err(|e| crate::s3::http(e.error))?;
        if response.status == 404 {
            return Err(BlobError::NotFound);
        }
        if response.status == 403 {
            return Err(BlobError::PermissionDenied);
        }
        if response.status != 206
            || response.body_bytes != high - low
            || header(&response, "x-amz-version-id")? != version
            || header(&response, "content-range")?
                != format!("bytes {low}-{}/{}", high - 1, record.size)
            || response.headers.iter().any(|h| h.0 == "content-encoding")
            || format!("{:x}", digest.finalize()) != record.parts[part]
        {
            return Err(BlobError::ChecksumMismatch);
        }
        call.io().checkpoint()?;
    }
    Ok(())
}
