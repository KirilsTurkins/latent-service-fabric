mod decode;
mod links;

use super::{corrupt, exhausted, invalid, pull::metadata, transport, HttpOciRegistry, Result};
use crate::{OciDescriptor, OciReference};
pub(super) use decode::media_type;
use latent_artifacts::package::package_digest;
use latent_core::{PackageDigest, PlatformErrorCode};
use reqwest::{
    header::{HeaderMap, LINK},
    Method, StatusCode, Url,
};
use std::collections::{BTreeMap, BTreeSet};
use tokio::time::Instant;

impl HttpOciRegistry {
    pub(crate) async fn list_referrers_inner(
        &self,
        reference: &OciReference,
        artifact_type: Option<&str>,
    ) -> Result<Vec<OciDescriptor>> {
        self.transport.endpoint.check_reference(reference)?;
        let limits = self.transport.limits;
        if let Some(kind) = artifact_type {
            media_type(kind, limits.package.max_string_bytes)?;
        }
        let digest = reference.reference.parse::<PackageDigest>().ok();
        let reservation = limits
            .max_referrer_total_bytes
            .checked_add(if digest.is_none() {
                limits.package.max_document_bytes
            } else {
                0
            })
            .ok_or_else(|| exhausted("oci-referrer-byte-limit"))?;
        let operation = self.transport.begin(reservation)?;
        let digest = match digest {
            Some(digest) => digest,
            None => self
                .fetch_manifest(
                    reference,
                    limits.package.max_document_bytes,
                    operation.deadline,
                )
                .await?
                .ok_or_else(|| crate::error(PlatformErrorCode::NotFound, "oci-manifest-not-found"))?
                .bytes
                .digest()
                .clone(),
        };
        let mut url = self
            .transport
            .endpoint
            .url(&format!("referrers/{digest}"))?;
        if let Some(kind) = artifact_type {
            url.query_pairs_mut().append_pair("artifactType", kind);
        }
        let mut seen_urls = BTreeSet::new();
        let mut descriptors = BTreeMap::<String, OciDescriptor>::new();
        let mut bytes_read = 0;
        let mut entries_read = 0;
        loop {
            if seen_urls.len() >= limits.max_referrer_pages {
                return Err(exhausted("oci-referrer-page-limit"));
            }
            if !seen_urls.insert(url.as_str().to_owned()) {
                return Err(invalid("oci-referrer-pagination-cycle"));
            }
            let maximum = limits.package.max_document_bytes.min(
                limits
                    .max_referrer_total_bytes
                    .checked_sub(bytes_read)
                    .ok_or_else(|| exhausted("oci-referrer-byte-limit"))?,
            );
            if maximum == 0 {
                return Err(exhausted("oci-referrer-byte-limit"));
            }
            let (page, next, body_size) = self
                .fetch_referrer_page(
                    &url,
                    maximum,
                    limits.max_referrers - entries_read,
                    operation.deadline,
                )
                .await?;
            bytes_read += body_size;
            entries_read += page.len();
            for descriptor in page {
                if let Some(previous) = descriptors.get(&descriptor.digest) {
                    if previous != &descriptor {
                        return Err(corrupt("oci-referrer-descriptor-conflict"));
                    }
                } else {
                    descriptors.insert(descriptor.digest.clone(), descriptor);
                }
            }
            match next {
                Some(next) => url = next,
                None => break,
            }
        }
        // Apply the requested filter ourselves even if the registry claims it
        // did so. Every scanned entry/page has already consumed its full budget.
        Ok(descriptors
            .into_values()
            .filter(|value| {
                artifact_type.is_none_or(|kind| value.artifact_type.as_deref() == Some(kind))
            })
            .collect())
    }

    async fn fetch_referrer_page(
        &self,
        url: &Url,
        maximum: usize,
        remaining_entries: usize,
        deadline: Instant,
    ) -> Result<(Vec<OciDescriptor>, Option<Url>, usize)> {
        let response = self
            .transport
            .send(Method::GET, url.clone(), None, None, deadline)
            .await?;
        if response.status() == StatusCode::NOT_FOUND {
            return Err(crate::error(
                PlatformErrorCode::IncompatibleContract,
                "oci-native-referrers-unsupported",
            ));
        }
        transport::expect_status(&response, &[StatusCode::OK])?;
        metadata::content_type(response.headers(), decode::INDEX_MEDIA_TYPE)?;
        let next = self.next_referrer_page(url, response.headers())?;
        let headers = response.headers().clone();
        let body = self.transport.read_body(response, maximum, None).await?;
        transport::verify_digest_header(&headers, package_digest(&body).as_str())?;
        let page = decode::index(&body, self.transport.limits.package, remaining_entries)?;
        Ok((page, next, body.len()))
    }

    fn next_referrer_page(&self, current: &Url, headers: &HeaderMap) -> Result<Option<Url>> {
        let mut output = None;
        for value in headers.get_all(LINK) {
            let value = value
                .to_str()
                .map_err(|_| invalid("invalid-oci-pagination-link"))?;
            if let Some(raw) = links::next(value)? {
                if raw.len() > 4096 || output.is_some() {
                    return Err(invalid("invalid-oci-pagination-link"));
                }
                // Relative references (including query-only links) are resolved
                // against the current page, then checked against the exact subject.
                let target = current
                    .join(raw)
                    .map_err(|_| invalid("invalid-oci-pagination-link"))?;
                let target = self
                    .transport
                    .endpoint
                    .scoped_url(target.as_str(), current.path())?;
                if target.path() != current.path() {
                    return Err(invalid("oci-referrer-pagination-subject-mismatch"));
                }
                output = Some(target);
            }
        }
        Ok(output)
    }
}
