mod location;
#[cfg(test)]
mod tests;

use super::{
    corrupt, exhausted, invalid,
    transport::{expect_status, verify_digest_header},
    HttpOciRegistry, Operation, Result,
};
use crate::{upload::PushParts, OciPushRequest};
use bytes::Bytes;
use latent_artifacts::package::{
    decode_referrer, inspect_package, ArtifactDescriptor, OCI_MANIFEST_MEDIA_TYPE,
};
use latent_core::PackageDigest;
use reqwest::{header::CONTENT_LENGTH, Method, StatusCode};

impl HttpOciRegistry {
    pub(crate) async fn push_inner(&self, request: OciPushRequest) -> Result<PackageDigest> {
        self.transport
            .endpoint
            .check_reference(request.reference())?;
        if request.reference().reference.starts_with("sha256:")
            && request.reference().reference != request.manifest().digest().as_str()
        {
            return Err(invalid("oci-push-reference-digest-mismatch"));
        }
        // Requests may have been created with wider package-profile limits.
        // Reapply this endpoint's lowered metadata/individual/aggregate ceilings.
        let limits = self.transport.limits.package;
        if request.layout().is_some() {
            inspect_package(
                request.manifest().as_bytes(),
                request.config_bytes(),
                limits,
            )?;
        } else {
            decode_referrer(request.manifest().as_bytes(), limits)?;
        }
        let total = request.layers().try_fold(
            request
                .manifest()
                .as_bytes()
                .len()
                .checked_add(request.config_bytes().len())
                .ok_or_else(|| exhausted("oci-push-byte-limit"))?,
            |total, (_, bytes)| {
                total
                    .checked_add(bytes.len())
                    .ok_or_else(|| exhausted("oci-push-byte-limit"))
            },
        )?;
        let mut operation = self.transport.begin(total)?;
        let PushParts {
            reference,
            manifest,
            digest,
            subject,
            config,
            layers,
        } = request.into_parts();
        for (descriptor, bytes) in std::iter::once(config).chain(layers) {
            operation = self.push_blob(descriptor, bytes, operation).await?;
        }
        // Publish only after all exact associated blobs have succeeded. There
        // are deliberately no automatic retries, including POST initiation.
        let response = self
            .transport
            .send(
                Method::PUT,
                self.transport
                    .endpoint
                    .url(&format!("manifests/{}", reference.reference))?,
                Some(manifest),
                Some(OCI_MANIFEST_MEDIA_TYPE),
                operation.deadline,
            )
            .await?;
        expect_status(&response, &[StatusCode::CREATED])?;
        if !response.headers().contains_key("docker-content-digest") {
            return Err(corrupt("oci-push-response-digest-missing"));
        }
        verify_digest_header(response.headers(), digest.as_str())?;
        if let Some(subject) = subject {
            // This profile requires native OCI 1.1 referrers. The manifest may
            // already be stored when the server fails this discovery handshake.
            let acknowledged = response
                .headers()
                .get("oci-subject")
                .and_then(|value| value.to_str().ok());
            if acknowledged != Some(subject.as_str()) {
                return Err(invalid("oci-native-referrers-not-acknowledged"));
            }
        }
        Ok(digest)
    }

    async fn push_blob(
        &self,
        descriptor: ArtifactDescriptor,
        bytes: Bytes,
        operation: Operation,
    ) -> Result<Operation> {
        let response = self
            .transport
            .send(
                Method::HEAD,
                self.transport
                    .endpoint
                    .url(&format!("blobs/{}", descriptor.digest.as_str()))?,
                None,
                None,
                operation.deadline,
            )
            .await?;
        expect_status(&response, &[StatusCode::OK, StatusCode::NOT_FOUND])?;
        if response.status() == StatusCode::OK {
            verify_digest_header(response.headers(), descriptor.digest.as_str())?;
            if let Some(length) = response.headers().get(CONTENT_LENGTH) {
                let length = length
                    .to_str()
                    .ok()
                    .and_then(|value| value.parse::<u64>().ok())
                    .ok_or_else(|| corrupt("oci-blob-head-length-invalid"))?;
                if length != descriptor.size {
                    return Err(corrupt("oci-blob-head-length-mismatch"));
                }
            }
            return Ok(operation);
        }
        drop(response);
        let session = self.uploads.start(operation).await?;
        let target = location::with_digest(session.location(), &descriptor.digest, 4096)?;
        let response = self
            .transport
            .send(
                Method::PUT,
                target,
                Some(bytes),
                Some("application/octet-stream"),
                session.deadline(),
            )
            .await?;
        expect_status(&response, &[StatusCode::CREATED])?;
        verify_digest_header(response.headers(), descriptor.digest.as_str())?;
        Ok(session.complete())
    }
}
