//! One explicitly scoped OCI endpoint with bounded transfer and retention owners.
mod body;
mod config;
mod pull;
mod push;
mod reference;
mod referrers;
mod transport;
mod upload_worker;

use crate::{OciDescriptor, OciManifestBytes, OciPushRequest, OciReference, OciRegistry};
pub use config::{RegistryConfig, RegistryCredentials, RegistryLimits};
use latent_core::{BoxFuture, PackageDigest, PlatformError, PlatformErrorCode};
pub use pull::OciPulledPackage;
use std::sync::Arc;
use tokio::time::Instant;
pub use transport::RegistryUsage;
pub(crate) use transport::{Operation, Transport};

pub(crate) type Result<T> = std::result::Result<T, PlatformError>;
pub(crate) fn invalid(reason: &'static str) -> PlatformError {
    crate::error(PlatformErrorCode::InvalidArgument, reason)
}
pub(crate) fn exhausted(reason: &'static str) -> PlatformError {
    crate::error(PlatformErrorCode::ResourceExhausted, reason)
}
pub(crate) fn corrupt(reason: &'static str) -> PlatformError {
    crate::error(PlatformErrorCode::CorruptArtifact, reason)
}

/// One shared client/worker for one configured origin and repository. Construction
/// requires a Tokio runtime; no DNS lookup, token flow or guest network authority.
#[derive(Clone)]
pub struct HttpOciRegistry {
    pub(crate) transport: Arc<Transport>,
    pub(crate) uploads: upload_worker::UploadWorker,
}

impl HttpOciRegistry {
    pub fn new(config: RegistryConfig) -> Result<Self> {
        let handle = tokio::runtime::Handle::try_current()
            .map_err(|_| invalid("oci-tokio-runtime-required"))?;
        let transport = Arc::new(Transport::new(config)?);
        let uploads = upload_worker::UploadWorker::new(transport.clone(), &handle);
        Ok(Self { transport, uploads })
    }
    #[must_use]
    pub fn usage(&self) -> RegistryUsage {
        self.transport.usage()
    }

    /// Stops new operations, waits for owned transfers/cleanup and closes the worker.
    /// A deadline failure does not claim remote upload cleanup has completed.
    pub async fn shutdown(&self, deadline: Instant) -> Result<()> {
        self.transport.close_and_wait(deadline).await?;
        self.uploads.shutdown(deadline).await
    }
}

impl OciRegistry for HttpOciRegistry {
    fn resolve<'a>(
        &'a self,
        reference: &'a OciReference,
    ) -> BoxFuture<'a, Result<Option<OciDescriptor>>> {
        Box::pin(self.resolve_inner(reference))
    }
    fn pull_manifest<'a>(
        &'a self,
        reference: &'a OciReference,
        max_document_bytes: usize,
    ) -> BoxFuture<'a, Result<OciManifestBytes>> {
        Box::pin(self.pull_manifest_inner(reference, max_document_bytes))
    }
    fn pull_blob<'a>(
        &'a self,
        reference: &'a OciReference,
        descriptor: &'a OciDescriptor,
        max_blob_bytes: u64,
    ) -> BoxFuture<'a, Result<Vec<u8>>> {
        Box::pin(self.pull_blob_inner(reference, descriptor, max_blob_bytes))
    }
    fn push(&self, request: OciPushRequest) -> BoxFuture<'_, Result<PackageDigest>> {
        Box::pin(self.push_inner(request))
    }
    fn list_referrers<'a>(
        &'a self,
        reference: &'a OciReference,
        artifact_type: Option<&'a str>,
    ) -> BoxFuture<'a, Result<Vec<OciDescriptor>>> {
        Box::pin(self.list_referrers_inner(reference, artifact_type))
    }
}
