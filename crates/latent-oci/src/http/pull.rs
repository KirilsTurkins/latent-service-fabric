mod envelope;
pub(super) mod metadata;
mod package;

use super::{corrupt, invalid, transport, HttpOciRegistry, Result};
use crate::{OciDescriptor, OciManifestBytes, OciReference};
use envelope::Envelope;
use latent_artifacts::package::{artifact_blob_digest, OCI_MANIFEST_MEDIA_TYPE};
use latent_core::{PackageDigest, PlatformErrorCode};
use reqwest::{Method, StatusCode};
use tokio::time::Instant;

pub use package::OciPulledPackage;

pub(crate) struct FetchedManifest {
    pub(crate) bytes: OciManifestBytes,
    envelope: Envelope,
}

impl HttpOciRegistry {
    pub(crate) async fn resolve_inner(
        &self,
        reference: &OciReference,
    ) -> Result<Option<OciDescriptor>> {
        self.transport.endpoint.check_reference(reference)?;
        let maximum = self.transport.limits.package.max_document_bytes;
        let operation = self.transport.begin(maximum)?;
        let fetched = self
            .fetch_manifest(reference, maximum, operation.deadline)
            .await?;
        Ok(fetched.map(|value| value.envelope.descriptor(&value.bytes)))
    }

    pub(crate) async fn pull_manifest_inner(
        &self,
        reference: &OciReference,
        maximum: usize,
    ) -> Result<OciManifestBytes> {
        self.transport.endpoint.check_reference(reference)?;
        if maximum == 0 || maximum > self.transport.limits.package.max_document_bytes {
            return Err(invalid("invalid-oci-manifest-limit"));
        }
        let operation = self.transport.begin(maximum)?;
        self.fetch_manifest(reference, maximum, operation.deadline)
            .await?
            .map(|value| value.bytes)
            .ok_or_else(|| crate::error(PlatformErrorCode::NotFound, "oci-manifest-not-found"))
    }

    pub(crate) async fn pull_blob_inner(
        &self,
        reference: &OciReference,
        descriptor: &OciDescriptor,
        maximum: u64,
    ) -> Result<Vec<u8>> {
        self.transport.endpoint.check_reference(reference)?;
        metadata::descriptor(descriptor, maximum, self.transport.limits.package)?;
        let size = usize::try_from(descriptor.size_bytes)
            .map_err(|_| invalid("oci-size-not-addressable"))?;
        let operation = self.transport.begin(size)?;
        self.fetch_blob(descriptor, operation.deadline).await
    }

    pub(crate) async fn fetch_manifest(
        &self,
        reference: &OciReference,
        maximum: usize,
        deadline: Instant,
    ) -> Result<Option<FetchedManifest>> {
        let url = self
            .transport
            .endpoint
            .url(&format!("manifests/{}", reference.reference))?;
        let response = self
            .transport
            .send(Method::GET, url, None, None, deadline)
            .await?;
        if response.status() == StatusCode::NOT_FOUND {
            return Ok(None);
        }
        transport::expect_status(&response, &[StatusCode::OK])?;
        metadata::content_type(response.headers(), OCI_MANIFEST_MEDIA_TYPE)?;
        let headers = response.headers().clone();
        let bytes = self.transport.read_body(response, maximum, None).await?;
        let bytes = OciManifestBytes::new(bytes, maximum)?;
        transport::verify_digest_header(&headers, bytes.digest().as_str())?;
        if let Ok(expected) = reference.reference.parse::<PackageDigest>() {
            if expected != *bytes.digest() {
                return Err(corrupt("oci-manifest-digest-mismatch"));
            }
        }
        let envelope = Envelope::decode(bytes.as_bytes(), self.transport.limits.package)?;
        Ok(Some(FetchedManifest { bytes, envelope }))
    }

    pub(super) async fn fetch_blob(
        &self,
        descriptor: &OciDescriptor,
        deadline: Instant,
    ) -> Result<Vec<u8>> {
        let maximum = usize::try_from(descriptor.size_bytes)
            .map_err(|_| invalid("oci-size-not-addressable"))?;
        let url = self
            .transport
            .endpoint
            .url(&format!("blobs/{}", descriptor.digest))?;
        let response = self
            .transport
            .send(Method::GET, url, None, None, deadline)
            .await?;
        transport::expect_status(&response, &[StatusCode::OK])?;
        transport::verify_digest_header(response.headers(), &descriptor.digest)?;
        // Blob HTTP Content-Type is commonly application/octet-stream. The
        // checked package descriptor determines the artifact's application type.
        let bytes = self
            .transport
            .read_body(response, maximum, Some(descriptor.size_bytes))
            .await?;
        if artifact_blob_digest(&bytes).as_str() != descriptor.digest {
            return Err(corrupt("oci-blob-digest-mismatch"));
        }
        Ok(bytes)
    }
}
