use super::{
    finish, handles, remote, Arc, AuditProviderOutcome, BlobError, BlobReference, Inner, PoolCall,
    Result,
};
use crate::s3::{
    inventory::{Activity, Phase, Record},
    PART_BYTES,
};
use latent_capabilities::broker::blob::BlobSeal;
use latent_http::protocol::{ProtocolBody, ProtocolScope};

struct Upload {
    record: Record,
    activity: Activity,
}
/// The physical filesystem job owns both the original call and inventory lease.
/// Dropping this future cannot release either while fsync is still executing.
async fn save(inner: &Arc<Inner>, call: PoolCall, upload: Upload) -> Result<(PoolCall, Upload)> {
    let inventory = inner.inventory.clone();
    inner
        .pools
        .control_blocking(move || {
            inventory.update(&upload.record, &upload.activity)?;
            Ok((call, upload))
        })?
        .wait()
        .await?
}
pub(super) async fn run(
    inner: Arc<Inner>,
    mut call: PoolCall,
    data: handles::Staging,
    digest: String,
) -> Result<BlobSeal> {
    let reference = BlobReference {
        digest: digest.clone(),
        size: data.written as u64,
        media_type: data.media_type.clone(),
    };
    if inner.inventory.lookup(&data.tenant, &reference).is_ok() {
        finish(&mut call, AuditProviderOutcome::BlobSealed).await?;
        return Ok(BlobSeal {
            reference,
            owner: call,
        });
    }
    let mut nonce = [0; 16];
    getrandom::fill(&mut nonce).map_err(|_| BlobError::Unavailable)?;
    let record = Record {
        format: 1,
        namespace: inner.inventory.config().namespace.clone(),
        tenant: data.tenant.clone(),
        digest,
        size: data.written as u64,
        media_type: data.media_type.clone(),
        nonce: crate::s3::hex_bytes(&nonce),
        parts: data.hashes.clone(),
        phase: Phase::Ready,
        upload_id: None,
        version: None,
        quiescent: true,
    };
    let inventory = inner.inventory.clone();
    let (next_call, result) = inner
        .pools
        .control_blocking(move || {
            let value = inventory.insert(record);
            (call, value)
        })?
        .wait()
        .await?;
    call = next_call;
    let (record, activity) = result?;
    let upload = Upload { record, activity };
    // The next helper returns the owner even for a protocol failure, so the
    // original audit can preserve uncertainty without fabricating acceptance.
    let (mut call, result) = transfer(&inner, call, upload, &data).await?;
    let outcome = if result.is_ok() {
        AuditProviderOutcome::BlobSealed
    } else {
        AuditProviderOutcome::Unknown
    };
    finish(&mut call, outcome).await?;
    result?;
    Ok(BlobSeal {
        reference,
        owner: call,
    })
}
async fn transfer(
    inner: &Arc<Inner>,
    mut call: PoolCall,
    mut upload: Upload,
    data: &handles::Staging,
) -> Result<(PoolCall, Result<()>)> {
    let key = upload.record.object_key(inner.inventory.config());
    if data.written == 0 {
        return empty(inner, call, upload, &key).await;
    }
    let (next, result) = initiate(inner, call, upload, &key).await?;
    call = next;
    upload = match result {
        Ok(value) => value,
        Err(error) => return Ok((call, Err(error))),
    };
    let id = upload
        .record
        .upload_id
        .clone()
        .ok_or(BlobError::Uncertain)?;
    let mut etags = Vec::with_capacity(data.hashes.len());
    for (index, hash) in data.hashes.iter().enumerate() {
        upload.record.quiescent = false;
        (call, upload) = save(inner, call, upload).await?;
        let low = index * PART_BYTES;
        let high = (low + PART_BYTES).min(data.written);
        let part = (index + 1).to_string();
        let result = remote::small(
            inner,
            &upload.record.tenant,
            ProtocolScope::Invocation(&call),
            remote::Spec {
                method: "PUT",
                key: Some(&key),
                query: &[("partNumber", &part), ("uploadId", &id)],
                extra: &[],
                payload_sha: hash,
                body: ProtocolBody::from_pages(&inner.pools, &data.pages, low..high)
                    .map_err(crate::s3::http)?,
            },
        )
        .await
        .and_then(|r| {
            r.success(200)?;
            let etag = remote::header(&r.response, "etag")?;
            if etag.len() != 34
                || !etag.starts_with('"')
                || !etag.ends_with('"')
                || !crate::s3::hex(&etag[1..33], 32)
            {
                return Err(BlobError::Uncertain);
            }
            Ok(etag.to_owned())
        });
        let etag = match result {
            Ok(value) => value,
            Err(error) => return Ok((call, Err(error))),
        };
        etags.push(etag);
        upload.record.quiescent = true;
        (call, upload) = save(inner, call, upload).await?;
    }
    let mut complete = String::from("<CompleteMultipartUpload>");
    for (index, etag) in etags.iter().enumerate() {
        use std::fmt::Write;
        let _ = write!(
            complete,
            "<Part><PartNumber>{}</PartNumber><ETag>{etag}</ETag></Part>",
            index + 1
        );
    }
    complete.push_str("</CompleteMultipartUpload>");
    upload.record.phase = Phase::Completing;
    upload.record.quiescent = false;
    (call, upload) = save(inner, call, upload).await?;
    let result = remote::small(
        inner,
        &upload.record.tenant,
        ProtocolScope::Invocation(&call),
        remote::Spec {
            method: "POST",
            key: Some(&key),
            query: &[("uploadId", &id)],
            extra: &[("if-none-match", "*")],
            payload_sha: &crate::s3::sha(complete.as_bytes()),
            body: remote::body(inner, complete.as_bytes())?,
        },
    )
    .await
    .and_then(|r| {
        r.success(200)?;
        let doc = r.document()?;
        doc.expect("CompleteMultipartUploadResult")?;
        if doc.field("Bucket")? != inner.inventory.config().bucket || doc.field("Key")? != key {
            return Err(BlobError::Uncertain);
        }
        version(&r.response)
    });
    completed(inner, call, upload, result).await
}
fn version(response: &latent_http::protocol::ProtocolResponse) -> Result<String> {
    let version = remote::header(response, "x-amz-version-id")?;
    if version == "null" {
        return Err(BlobError::Uncertain);
    }
    Ok(version.to_owned())
}
async fn completed(
    inner: &Arc<Inner>,
    call: PoolCall,
    mut upload: Upload,
    version: Result<String>,
) -> Result<(PoolCall, Result<()>)> {
    let version = match version {
        Ok(value) => value,
        Err(error) => return rejected(inner, call, upload, error).await,
    };
    upload.record.phase = Phase::Sealed;
    upload.record.version = Some(version);
    upload.record.quiescent = true;
    let (call, _upload) = save(inner, call, upload).await?;
    Ok((call, Ok(())))
}

async fn empty(
    inner: &Arc<Inner>,
    mut call: PoolCall,
    mut upload: Upload,
    key: &str,
) -> Result<(PoolCall, Result<()>)> {
    upload.record.phase = Phase::Completing;
    upload.record.quiescent = false;
    (call, upload) = save(inner, call, upload).await?;
    let result = remote::small(
        inner,
        &upload.record.tenant,
        ProtocolScope::Invocation(&call),
        remote::Spec {
            method: "PUT",
            key: Some(key),
            query: &[],
            extra: &[("if-none-match", "*")],
            payload_sha: &crate::s3::sha(b""),
            body: remote::body(inner, b"")?,
        },
    )
    .await;
    let version = result.and_then(|r| {
        r.success(200)?;
        version(&r.response)
    });
    completed(inner, call, upload, version).await
}

async fn initiate(
    inner: &Arc<Inner>,
    mut call: PoolCall,
    mut upload: Upload,
    key: &str,
) -> Result<(PoolCall, Result<Upload>)> {
    upload.record.phase = Phase::Creating;
    upload.record.quiescent = false;
    (call, upload) = save(inner, call, upload).await?;
    let created = remote::small(
        inner,
        &upload.record.tenant,
        ProtocolScope::Invocation(&call),
        remote::Spec {
            method: "POST",
            key: Some(key),
            query: &[("uploads", "")],
            extra: &[],
            payload_sha: &crate::s3::sha(b""),
            body: remote::body(inner, b"")?,
        },
    )
    .await
    .and_then(|r| {
        r.success(200)?;
        let doc = r.document()?;
        doc.expect("InitiateMultipartUploadResult")?;
        if doc.field("Bucket")? != inner.inventory.config().bucket || doc.field("Key")? != key {
            return Err(BlobError::Uncertain);
        }
        let id = doc.field("UploadId")?;
        if !crate::s3::text(id, 1024) {
            return Err(BlobError::Uncertain);
        }
        Ok(id.to_owned())
    });
    let id = match created {
        Ok(id) => id,
        Err(error) => return rejected(inner, call, upload, error).await,
    };
    upload.record.upload_id = Some(id);
    upload.record.phase = Phase::Uploading;
    upload.record.quiescent = true;
    (call, upload) = save(inner, call, upload).await?;
    Ok((call, Ok(upload)))
}

async fn rejected<T>(
    inner: &Arc<Inner>,
    call: PoolCall,
    mut upload: Upload,
    error: BlobError,
) -> Result<(PoolCall, Result<T>)> {
    // A known authentication/not-found rejection of initial creation has no
    // multipart parts to reclaim. Do not fill the finite inventory with failed
    // credential attempts. Later multipart failures retain their cleanup owner.
    if upload.record.upload_id.is_none()
        && matches!(error, BlobError::PermissionDenied | BlobError::NotFound)
    {
        upload.record.phase = Phase::Aborted;
        upload.record.quiescent = true;
        let inventory = inner.inventory.clone();
        let call = inner
            .pools
            .control_blocking(move || {
                inventory.remove_aborted(&upload.record, &upload.activity)?;
                Ok::<_, BlobError>(call)
            })?
            .wait()
            .await??;
        return Ok((call, Err(error)));
    }
    Ok((call, Err(error)))
}
