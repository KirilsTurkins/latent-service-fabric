use super::{
    envelope::{blob_descriptor, Envelope},
    HttpOciRegistry, Result,
};
use crate::{OciPushRequest, OciReference};
use latent_artifacts::package::inspect_package;
use latent_core::PlatformErrorCode;
use std::fmt;
use tokio::sync::OwnedSemaphorePermit;

/// A complete format/integrity-checked package or detached evidence envelope.
/// Raw-byte and package-slot leases remain held until this value is dropped.
/// No publisher trust, guest semantics, runtime admission or cache residency is implied.
pub struct OciPulledPackage {
    request: OciPushRequest,
    _slot: OwnedSemaphorePermit,
    _manifest_bytes: OwnedSemaphorePermit,
    _blob_bytes: OwnedSemaphorePermit,
}

impl OciPulledPackage {
    #[must_use]
    pub fn request(&self) -> &OciPushRequest {
        &self.request
    }
}

impl fmt::Debug for OciPulledPackage {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("OciPulledPackage")
            .field("request", &self.request)
            .finish_non_exhaustive()
    }
}

impl HttpOciRegistry {
    /// Retrieves one immutable package, including capsule/browser/SSR or detached
    /// evidence. A mutable tag is read once; every subsequent blob uses a digest.
    /// Returned ownership remains charged to the adapter until Drop.
    pub async fn pull_package(&self, reference: &OciReference) -> Result<OciPulledPackage> {
        self.transport.endpoint.check_reference(reference)?;
        let operation = self.transport.begin(0)?;
        let slot = self.transport.lease_package()?;
        let limits = self.transport.limits.package;
        let mut manifest_lease = self.transport.lease_bytes(limits.max_document_bytes)?;
        let fetched = self
            .fetch_manifest(reference, limits.max_document_bytes, operation.deadline)
            .await?
            .ok_or_else(|| crate::error(PlatformErrorCode::NotFound, "oci-manifest-not-found"))?;
        let unused = limits.max_document_bytes - fetched.bytes.as_bytes().len();
        if unused != 0 {
            drop(
                manifest_lease
                    .split(unused)
                    .expect("reserved manifest ceiling"),
            );
        }
        // Reserve the complete retained graph before fetching any blob. Admission
        // is nonblocking, so partial packages cannot deadlock waiting for quota.
        let blob_lease = self.transport.lease_bytes(fetched.envelope.blob_bytes()?)?;
        let config = self
            .fetch_blob(
                &blob_descriptor(fetched.envelope.config()),
                operation.deadline,
            )
            .await?;
        match &fetched.envelope {
            Envelope::Package(_) => {
                inspect_package(fetched.bytes.as_bytes(), &config, limits)?;
            }
            Envelope::Evidence(_) if config != b"{}" => {
                return Err(super::super::corrupt("oci-referrer-config-mismatch"));
            }
            Envelope::Evidence(_) => (),
        }
        let mut layers = Vec::with_capacity(fetched.envelope.layers().len());
        for descriptor in fetched.envelope.layers() {
            let bytes = self
                .fetch_blob(&blob_descriptor(descriptor), operation.deadline)
                .await?;
            layers.push((descriptor.clone(), bytes));
        }
        let pinned = OciReference {
            registry: self.transport.endpoint.authority.clone(),
            repository: self.transport.endpoint.repository.clone(),
            reference: fetched.bytes.digest().as_str().to_owned(),
        };
        let request = fetched
            .envelope
            .finish(pinned, fetched.bytes, config, layers, limits)?;
        Ok(OciPulledPackage {
            request,
            _slot: slot,
            _manifest_bytes: manifest_lease,
            _blob_bytes: blob_lease,
        })
    }
}
