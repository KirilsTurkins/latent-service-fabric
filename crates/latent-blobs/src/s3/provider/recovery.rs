//! Explicit finite operator reconciliation. Never recreates an upload or
//! automatically repeats a `CompleteMultipartUpload` after an uncertain response.
use super::{remote, Arc, BlobError, Digest, Inner, Result, S3BlobProvider, Sha256};
use crate::s3::{
    inventory::{Activity, Phase, Record},
    PART_BYTES,
};
use latent_capabilities::broker::pools::ProviderMaintenance;
use latent_http::protocol::ProtocolScope;
use std::time::Instant;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum S3Recovery {
    Retired,
    Sealed,
    Unresolved,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum S3RecoveryMode {
    /// Ordinary bounded reconciliation. A missing upload does not prove a lost
    /// part request stopped running on the remote service.
    Observe,
    /// Trusted operator assertion that all remote part work for this exact
    /// inventory ID has ended, established through the selected server's own
    /// administration. Never infer this from elapsed time or one empty listing.
    /// Abort/ListParts verification is still required before local retirement.
    AfterOperatorConfirmedQuiescence,
}
struct Work {
    record: Record,
    activity: Activity,
    permit: ProviderMaintenance,
}
impl S3BlobProvider {
    pub async fn reconcile(
        &self,
        id: &str,
        deadline: Instant,
        attempts: usize,
        mode: S3RecoveryMode,
    ) -> Result<S3Recovery> {
        if !crate::s3::hex(id, 64) || !(1..=4).contains(&attempts) {
            return Err(BlobError::InvalidRange);
        }
        let (record, activity) = self.inner.inventory.acquire(id)?;
        if record.phase == Phase::Sealed {
            return Ok(S3Recovery::Sealed);
        }
        let permit = self
            .inner
            .transport
            .maintenance(deadline, 2 * attempts + 10)
            .map_err(crate::s3::http)?;
        let mut work = Work {
            record,
            activity,
            permit,
        };
        if work.record.phase == Phase::Ready
            || (work.record.phase == Phase::Aborted && work.record.quiescent)
        {
            return retire(&self.inner, work).await;
        }
        if work.record.phase == Phase::Completing {
            let version = verify_completed(&self.inner, &work).await;
            if let Ok(version) = version {
                work.record.phase = Phase::Sealed;
                work.record.version = Some(version);
                work.record.quiescent = true;
                save(&self.inner, work).await?;
                return Ok(S3Recovery::Sealed);
            }
            return Ok(S3Recovery::Unresolved);
        }
        let key = work.record.object_key(self.inner.inventory.config());
        if work.record.upload_id.is_none() {
            let found = discover(&self.inner, &work, &key).await;
            let Ok(id) = found else {
                return Ok(S3Recovery::Unresolved);
            };
            // No part could pass its local fence without a durable upload ID.
            // A positive exact-key listing establishes the one upload to abort.
            work.record.upload_id = Some(id);
            work.record.phase = Phase::Uploading;
            work.record.quiescent = true;
            work = save(&self.inner, work).await?;
        }
        let upload_id = work.record.upload_id.clone().ok_or(BlobError::Uncertain)?;
        for _ in 0..attempts {
            let attempt = abort_and_verify(&self.inner, &work, &key, &upload_id).await;
            if matches!(attempt, Ok(true))
                && (work.record.quiescent
                    || mode == S3RecoveryMode::AfterOperatorConfirmedQuiescence)
            {
                return retire(&self.inner, work).await;
            }
        }
        Ok(S3Recovery::Unresolved)
    }
}
async fn save(inner: &Arc<Inner>, work: Work) -> Result<Work> {
    let inventory = inner.inventory.clone();
    inner
        .pools
        .control_blocking(move || {
            inventory.update(&work.record, &work.activity)?;
            Ok(work)
        })?
        .wait()
        .await?
}
async fn retire(inner: &Arc<Inner>, mut work: Work) -> Result<S3Recovery> {
    work.record.phase = Phase::Aborted;
    work.record.quiescent = true;
    let inventory = inner.inventory.clone();
    inner
        .pools
        .control_blocking(move || {
            inventory.remove_aborted(&work.record, &work.activity)?;
            Ok(S3Recovery::Retired)
        })?
        .wait()
        .await?
}
async fn discover(inner: &Inner, work: &Work, key: &str) -> Result<String> {
    let request = work.permit.begin_request()?;
    let response = remote::small(
        inner,
        &work.record.tenant,
        ProtocolScope::Maintenance(&request),
        remote::Spec {
            method: "GET",
            key: None,
            query: &[("uploads", ""), ("prefix", key), ("max-uploads", "2")],
            extra: &[],
            payload_sha: &crate::s3::sha(b""),
            body: remote::body(inner, b"")?,
        },
    )
    .await?;
    response.success(200)?;
    let doc = response.document()?;
    doc.expect("ListMultipartUploadsResult")?;
    if doc.field("Bucket")? != inner.inventory.config().bucket
        || doc.field("IsTruncated")? != "false"
    {
        return Err(BlobError::Uncertain);
    }
    let keys: Vec<_> = doc.fields.iter().filter(|f| f.0 == "Upload/Key").collect();
    let ids: Vec<_> = doc
        .fields
        .iter()
        .filter(|f| f.0 == "Upload/UploadId")
        .collect();
    if keys.len() != 1 || ids.len() != 1 || keys[0].1 != key || !crate::s3::text(&ids[0].1, 1024) {
        return Err(BlobError::Uncertain);
    }
    Ok(ids[0].1.clone())
}
async fn abort_and_verify(inner: &Inner, work: &Work, key: &str, id: &str) -> Result<bool> {
    let request = work.permit.begin_request()?;
    let response = remote::small(
        inner,
        &work.record.tenant,
        ProtocolScope::Maintenance(&request),
        remote::Spec {
            method: "DELETE",
            key: Some(key),
            query: &[("uploadId", id)],
            extra: &[],
            payload_sha: &crate::s3::sha(b""),
            body: remote::body(inner, b"")?,
        },
    )
    .await?;
    if response.response.status != 204 && !(response.response.status == 404 && no_upload(&response))
    {
        return Err(BlobError::Uncertain);
    }
    drop((request, response));
    let request = work.permit.begin_request()?;
    let response = remote::small(
        inner,
        &work.record.tenant,
        ProtocolScope::Maintenance(&request),
        remote::Spec {
            method: "GET",
            key: Some(key),
            query: &[("uploadId", id), ("max-parts", "1")],
            extra: &[],
            payload_sha: &crate::s3::sha(b""),
            body: remote::body(inner, b"")?,
        },
    )
    .await?;
    Ok(response.response.status == 404 && no_upload(&response))
}
fn no_upload(response: &remote::Small) -> bool {
    response
        .document()
        .is_ok_and(|d| d.root == "Error" && d.field("Code").is_ok_and(|v| v == "NoSuchUpload"))
}
async fn verify_completed(inner: &Inner, work: &Work) -> Result<String> {
    let key = work.record.object_key(inner.inventory.config());
    let request = work.permit.begin_request()?;
    let response = remote::small(
        inner,
        &work.record.tenant,
        ProtocolScope::Maintenance(&request),
        remote::Spec {
            method: "HEAD",
            key: Some(&key),
            query: &[],
            extra: &[],
            payload_sha: &crate::s3::sha(b""),
            body: remote::body(inner, b"")?,
        },
    )
    .await?;
    response.success(200)?;
    if remote::header(&response.response, "content-length")? != work.record.size.to_string() {
        return Err(BlobError::ChecksumMismatch);
    }
    let version = remote::header(&response.response, "x-amz-version-id")?.to_owned();
    if version == "null" {
        return Err(BlobError::Uncertain);
    }
    drop((request, response));
    let _metadata = inner.pools.reserve_protocol_metadata(131_072)?;
    let mut full = Sha256::new();
    for (index, expected) in work.record.parts.iter().enumerate() {
        let low = index * PART_BYTES;
        let high = (low + PART_BYTES)
            .min(usize::try_from(work.record.size).map_err(|_| BlobError::InvalidRange)?);
        let range = format!("bytes={low}-{}", high - 1);
        let request = work.permit.begin_request()?;
        let input = remote::request(
            inner,
            &work.record.tenant,
            remote::Spec {
                method: "GET",
                key: Some(&key),
                query: &[("versionId", &version)],
                extra: &[("range", &range)],
                payload_sha: &crate::s3::sha(b""),
                body: remote::body(inner, b"")?,
            },
        )?;
        let mut part = Sha256::new();
        let response = inner
            .transport
            .exchange(
                ProtocolScope::Maintenance(&request),
                input,
                high - low,
                &mut |bytes| {
                    full.update(bytes);
                    part.update(bytes);
                    Ok(())
                },
            )
            .await
            .map_err(|_| BlobError::Uncertain)?;
        if response.status != 206
            || response.body_bytes != high - low
            || remote::header(&response, "x-amz-version-id")? != version
            || remote::header(&response, "content-range")?
                != format!("bytes {low}-{}/{}", high - 1, work.record.size)
            || response.headers.iter().any(|h| h.0 == "content-encoding")
            || format!("{:x}", part.finalize()) != *expected
        {
            return Err(BlobError::ChecksumMismatch);
        }
    }
    if format!("sha256:{:x}", full.finalize()) != work.record.digest {
        return Err(BlobError::ChecksumMismatch);
    }
    Ok(version)
}
