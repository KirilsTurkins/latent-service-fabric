//! Linux immutable blobs on shared policy/audit/I/O owners. Installation is an
//! explicit trusted composition step; no dormant deployment creates a root/pool.
mod execute;
mod handles;
use crate::local::{LocalBlobError, LocalBlobStore};
use latent_capabilities::broker::{
    blob::{
        BlobError, BlobFuture, BlobInvoker, BlobReader, BlobReference, BlobWriter, BLOB_CAPABILITY,
    },
    pools::{
        InstalledProvider, PoolAdmission, ProviderClient, ProviderMetadata, ProviderPools,
        ProviderSetup,
    },
    CapabilityCallCost, CapabilityRequestDigest, CapabilitySession, ProviderConfiguration,
    ProviderReference,
};
use latent_core::{BudgetDimension, PlatformError};
use std::sync::Arc;

pub const LOCAL_BLOB_PROFILE: &str = "linux-immutable-blobs-v1";
#[derive(Clone)]
pub struct LocalBlobProvider {
    inner: Arc<Inner>,
}
struct Inner {
    store: Arc<LocalBlobStore>,
    pools: Arc<ProviderPools>,
    installed: InstalledProvider,
    client: Arc<ProviderClient<()>>,
    _metadata: ProviderMetadata,
}
impl LocalBlobProvider {
    pub fn install(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        store: Arc<LocalBlobStore>,
    ) -> Result<Self, BlobError> {
        let metadata = pools.reserve_protocol_metadata(8192)?;
        let identity = store.configuration_digest().map_err(map)?;
        let restriction = serde_json::to_vec(&serde_json::json!({
            "operations": ["create", "open", "write", "read", "seal"],
            "resources": {"kind": "blob", "namespaces": [store.namespace()]}
        }))
        .map_err(|_| BlobError::Unavailable)?;
        let installed = pools.install(
            ProviderSetup {
                logical_id,
                credentials: &[],
                authority: ProviderConfiguration {
                    capability: BLOB_CAPABILITY,
                    profile: LOCAL_BLOB_PROFILE,
                    configuration_digest: &identity,
                    configuration_epoch: epoch,
                    restriction_json: &restriction,
                    minimum_call_charges: &[],
                },
            },
            expected_epoch,
        )?;
        let client = pools.client(&installed, 0)?;
        Ok(Self {
            inner: Arc::new(Inner {
                store,
                pools,
                installed,
                client,
                _metadata: metadata,
            }),
        })
    }
    #[must_use]
    pub fn reference(&self) -> ProviderReference {
        self.inner.installed.reference()
    }
    #[must_use]
    pub fn store(&self) -> &Arc<LocalBlobStore> {
        &self.inner.store
    }
}
impl Inner {
    fn admit(&self, session: &CapabilitySession) -> Result<PoolAdmission, BlobError> {
        if !session.uses_provider(&self.installed.reference())? {
            return Err(BlobError::PermissionDenied);
        }
        Ok(self.pools.admit(&self.client, session)?)
    }
}
impl BlobInvoker for LocalBlobProvider {
    fn create(
        &self,
        session: &CapabilitySession,
        media_type: String,
        expected_size: Option<u64>,
    ) -> Result<BlobFuture<'static, Box<dyn BlobWriter>>, BlobError> {
        text(&media_type)?;
        if expected_size.is_some_and(|n| n > self.inner.store.limits().maximum_object_bytes) {
            return Err(BlobError::BudgetExhausted);
        }
        let admission = self.inner.admit(session)?;
        let memory = admission.reserve_input(media_type.capacity().max(1), 1024)?;
        let binding = session.reserve_resource_table(4096)?;
        let tenant = session.tenant().clone();
        let inner = self.inner.clone();
        let digest = CapabilityRequestDigest::from_parts(&[
            b"blob-create-v1",
            media_type.as_bytes(),
            &[u8::from(expected_size.is_some())],
            &expected_size.unwrap_or(0).to_le_bytes(),
        ])?;
        let cost = CapabilityCallCost::new(8)
            .with_typed_input_bytes(media_type.len() + 9)
            .with_typed_request_digest(digest);
        Ok(Box::pin(async move {
            let call = execute::dispatch(&inner, admission, "create", cost).await?;
            let root = inner.store.clone();
            let completed = execute::run(&inner, call, "create", move |call| {
                let _memory = memory;
                let result = root
                    .create(&tenant, &media_type, expected_size, &|| checkpoint(call))
                    .map_err(map);
                drop(media_type);
                result
            })
            .await?;
            let data = completed.value?;
            Ok(Box::new(handles::Writer {
                data: Some(data),
                inner,
                binding,
            }) as Box<dyn BlobWriter>)
        }))
    }
    fn open(
        &self,
        session: &CapabilitySession,
        reference: BlobReference,
    ) -> Result<BlobFuture<'static, Box<dyn BlobReader>>, BlobError> {
        validate_reference(&reference, self.inner.store.limits().maximum_object_bytes)?;
        let admission = self.inner.admit(session)?;
        let memory = admission.reserve_input(
            reference.digest.capacity() + reference.media_type.capacity(),
            1024,
        )?;
        let binding = session.reserve_resource_table(4096)?;
        let tenant = session.tenant().clone();
        let inner = self.inner.clone();
        let cost = CapabilityCallCost::new(8)
            .with_typed_input_bytes(reference.digest.len() + reference.media_type.len() + 8)
            .with_typed_request_digest(reference_digest(b"blob-open-v1", &reference)?);
        Ok(Box::pin(async move {
            let call = execute::dispatch(&inner, admission, "open", cost).await?;
            let root = inner.store.clone();
            let completed = execute::run(&inner, call, "open", move |call| {
                let _memory = memory;
                let reference = crate::BlobReference {
                    digest: latent_core::BlobDigest(reference.digest),
                    size_bytes: reference.size,
                    media_type: reference.media_type,
                    tenant,
                    metadata: latent_core::Metadata::new(),
                };
                let result = root
                    .open_read(&reference.tenant, &reference, &|| checkpoint(call))
                    .map_err(map);
                drop(reference);
                result
            })
            .await?;
            let data = completed.value?;
            Ok(Box::new(handles::Reader {
                data: Some(data),
                inner,
                binding,
            }) as Box<dyn BlobReader>)
        }))
    }
}
fn text(value: &str) -> Result<(), BlobError> {
    if value.is_empty() || value.len() > 128 || value.chars().any(char::is_control) {
        return Err(BlobError::InvalidRange);
    }
    Ok(())
}
fn validate_reference(reference: &BlobReference, maximum: u64) -> Result<(), BlobError> {
    text(&reference.media_type)?;
    if reference.size > maximum
        || reference.digest.len() != 71
        || !reference.digest.starts_with("sha256:")
        || !reference.digest.as_bytes()[7..]
            .iter()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(b))
    {
        return Err(BlobError::InvalidRange);
    }
    Ok(())
}
fn reference_digest(
    domain: &[u8],
    reference: &BlobReference,
) -> Result<CapabilityRequestDigest, PlatformError> {
    CapabilityRequestDigest::from_parts(&[
        domain,
        reference.digest.as_bytes(),
        &reference.size.to_le_bytes(),
        reference.media_type.as_bytes(),
    ])
}
fn map(error: LocalBlobError) -> BlobError {
    match error {
        LocalBlobError::Invalid => BlobError::InvalidRange,
        LocalBlobError::PermissionDenied => BlobError::PermissionDenied,
        LocalBlobError::NotFound => BlobError::NotFound,
        LocalBlobError::Corrupt => BlobError::ChecksumMismatch,
        LocalBlobError::Capacity => BlobError::BudgetExhausted,
        LocalBlobError::Busy | LocalBlobError::Unavailable | LocalBlobError::Closed => {
            BlobError::Unavailable
        }
        LocalBlobError::Uncertain => BlobError::Uncertain,
        LocalBlobError::Cancelled => BlobError::Cancelled,
        LocalBlobError::DeadlineExceeded => BlobError::DeadlineExceeded,
    }
}
fn checkpoint(call: &latent_capabilities::broker::pools::PoolCall) -> Result<(), LocalBlobError> {
    call.io().checkpoint().map_err(|e| match e.code {
        latent_core::PlatformErrorCode::Cancelled => LocalBlobError::Cancelled,
        latent_core::PlatformErrorCode::DeadlineExceeded => LocalBlobError::DeadlineExceeded,
        _ => LocalBlobError::Closed,
    })
}
