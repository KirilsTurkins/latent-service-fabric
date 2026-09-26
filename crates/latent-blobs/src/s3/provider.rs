mod handles;
mod recovery;
mod remote;
mod seal;
use super::{inventory, BlobError, Result, S3Inventory, S3_BLOB_PROFILE};
use latent_capabilities::broker::{
    blob::{BlobFuture, BlobInvoker, BlobReader, BlobReference, BlobWriter, BLOB_CAPABILITY},
    pools::{
        InstalledProvider, PoolAdmission, PoolCall, ProviderMetadata, ProviderPools, ProviderSetup,
    },
    secrets::ProviderCredential,
    AuditProviderOutcome, CapabilityCallCost, CapabilityRequestDigest, CapabilitySession,
    ProviderConfiguration, ProviderReference,
};
use latent_http::protocol::ProtocolTransport;
use latent_policy::capability::ResourceTarget;
pub use recovery::{S3Recovery, S3RecoveryMode};
use sha2::{Digest, Sha256};
use std::sync::Arc;

#[derive(Clone)]
pub struct S3BlobProvider {
    inner: Arc<Inner>,
}
struct Inner {
    inventory: Arc<S3Inventory>,
    pools: Arc<ProviderPools>,
    installed: InstalledProvider,
    transport: ProtocolTransport,
    credentials: Vec<Arc<dyn ProviderCredential>>,
    _metadata: ProviderMetadata,
}
impl S3BlobProvider {
    /// Trusted composition supplies one opaque, atomically rotated credential
    /// tuple per allowed tenant. No guest can substitute another account binding.
    pub fn install(
        pools: Arc<ProviderPools>,
        logical_id: &str,
        epoch: u64,
        expected_epoch: u64,
        inventory: Arc<S3Inventory>,
        credentials: Vec<Arc<dyn ProviderCredential>>,
    ) -> Result<Self> {
        if credentials.is_empty() || credentials.capacity() > 64 {
            return Err(BlobError::InvalidRange);
        }
        let config = inventory.config();
        let metadata = pools.reserve_protocol_metadata(65536)?;
        let mut hash = Sha256::new();
        hash.update(b"LSF S3 configured provider v1\0");
        hash.update(config.identity()?.as_bytes());
        for (i, credential) in credentials.iter().enumerate() {
            let scope = credential.scope();
            if scope.provider_id != logical_id
                || scope.origin != config.transport.destinations[0].origin
                || !super::text(&scope.tenant.0, 128)
                || !super::text(credential.reference(), 256)
                || credentials[..i]
                    .iter()
                    .any(|c| c.scope().tenant == scope.tenant)
            {
                return Err(BlobError::PermissionDenied);
            }
            for value in [&scope.tenant.0, credential.reference()] {
                hash.update((value.len() as u64).to_le_bytes());
                hash.update(value.as_bytes());
            }
        }
        let identity = format!("sha256:{:x}", hash.finalize());
        let restriction = serde_json::to_vec(&serde_json::json!({
            "operations": ["create", "write", "seal", "open", "read"],
            "resources": {"kind": "blob", "namespaces": [config.namespace]}
        }))
        .map_err(|_| BlobError::InvalidRange)?;
        let installed = pools.install(
            ProviderSetup {
                logical_id,
                credentials: &[],
                authority: ProviderConfiguration {
                    capability: BLOB_CAPABILITY,
                    profile: S3_BLOB_PROFILE,
                    configuration_digest: &identity,
                    configuration_epoch: epoch,
                    restriction_json: &restriction,
                    minimum_call_charges: &[],
                },
            },
            expected_epoch,
        )?;
        let transport = ProtocolTransport::new(pools.clone(), &installed, config.transport.clone())
            .map_err(super::http)?;
        Ok(Self {
            inner: Arc::new(Inner {
                inventory,
                pools,
                installed,
                transport,
                credentials,
                _metadata: metadata,
            }),
        })
    }
    #[must_use]
    pub fn reference(&self) -> ProviderReference {
        self.inner.installed.reference()
    }
    #[must_use]
    pub fn inventory(&self) -> &Arc<S3Inventory> {
        &self.inner.inventory
    }
}
impl Inner {
    fn credential(&self, tenant: &str) -> Result<&dyn ProviderCredential> {
        self.credentials
            .iter()
            .find(|c| c.scope().tenant.0 == tenant)
            .map(AsRef::as_ref)
            .ok_or(BlobError::PermissionDenied)
    }
    fn admit(&self, session: &CapabilitySession) -> Result<PoolAdmission> {
        if !session.uses_provider(&self.installed.reference())? {
            return Err(BlobError::PermissionDenied);
        }
        self.credential(&session.tenant().0)?;
        self.transport.admit(session).map_err(super::http)
    }
    async fn dispatch(
        &self,
        admission: PoolAdmission,
        operation: &str,
        cost: CapabilityCallCost,
    ) -> Result<PoolCall> {
        Ok(admission
            .wait()
            .await?
            .dispatch(
                BLOB_CAPABILITY,
                operation,
                ResourceTarget::Blob {
                    namespace: &self.inventory.config().namespace,
                },
                &[],
                cost,
            )
            .await?)
    }
}
async fn finish(call: &mut PoolCall, outcome: AuditProviderOutcome) -> Result<()> {
    call.io_mut().record_provider_outcome(outcome)?;
    call.io_mut().finish_audit().await;
    Ok(())
}
fn reference(reference: &BlobReference, maximum: usize) -> Result<()> {
    if reference.size > maximum as u64
        || reference.digest.capacity() > 71
        || reference.digest.len() != 71
        || !reference.digest.starts_with("sha256:")
        || !super::hex(&reference.digest[7..], 64)
        || !super::text(&reference.media_type, 128)
        || reference.media_type.capacity() > 128
    {
        return Err(BlobError::InvalidRange);
    }
    Ok(())
}
impl BlobInvoker for S3BlobProvider {
    fn create(
        &self,
        session: &CapabilitySession,
        media_type: String,
        expected_size: Option<u64>,
    ) -> Result<BlobFuture<'static, Box<dyn BlobWriter>>> {
        if !super::text(&media_type, 128)
            || media_type.capacity() > 128
            || expected_size.is_some_and(|v| {
                v > self.inner.inventory.config().limits.maximum_object_bytes as u64
            })
        {
            return Err(BlobError::InvalidRange);
        }
        let admission = self.inner.admit(session)?;
        let input = admission.reserve_input(media_type.capacity().max(1), 1024)?;
        let binding = session.reserve_resource_table(4096)?;
        let tenant = session.tenant().0.clone();
        let inner = self.inner.clone();
        let cost = CapabilityCallCost::new(8)
            .with_typed_input_bytes(media_type.len() + 9)
            .with_typed_request_digest(CapabilityRequestDigest::from_parts(&[
                b"s3-blob-create-v1",
                media_type.as_bytes(),
                &[u8::from(expected_size.is_some())],
                &expected_size.unwrap_or(0).to_le_bytes(),
            ])?);
        Ok(Box::pin(async move {
            let mut call = inner.dispatch(admission, "create", cost).await?;
            let _input = input;
            let stage = handles::Staging::new(&inner, tenant, media_type, expected_size)?;
            finish(&mut call, AuditProviderOutcome::HostCompleted).await?;
            Ok(Box::new(handles::Writer {
                data: Some(stage),
                inner,
                binding,
            }) as Box<dyn BlobWriter>)
        }))
    }
    fn open(
        &self,
        session: &CapabilitySession,
        reference: BlobReference,
    ) -> Result<BlobFuture<'static, Box<dyn BlobReader>>> {
        self::reference(
            &reference,
            self.inner.inventory.config().limits.maximum_object_bytes,
        )?;
        let admission = self.inner.admit(session)?;
        let memory = admission.reserve_input(
            reference.digest.capacity() + reference.media_type.capacity(),
            1024,
        )?;
        let binding = session.reserve_resource_table(4096)?;
        let tenant = session.tenant().0.clone();
        let inner = self.inner.clone();
        let cost = CapabilityCallCost::new(8)
            .with_typed_input_bytes(reference.digest.len() + reference.media_type.len() + 8)
            .with_typed_request_digest(CapabilityRequestDigest::from_parts(&[
                b"s3-blob-open-v1",
                reference.digest.as_bytes(),
                &reference.size.to_le_bytes(),
                reference.media_type.as_bytes(),
            ])?);
        Ok(Box::pin(async move {
            let mut call = inner.dispatch(admission, "open", cost).await?;
            let _memory = memory;
            let handle = inner.inventory.handle()?;
            let metadata = inner.pools.reserve_protocol_metadata(super::RECORD_BYTES)?;
            let record = inner.inventory.lookup(&tenant, &reference)?;
            finish(&mut call, AuditProviderOutcome::HostCompleted).await?;
            Ok(Box::new(handles::Reader {
                record: Some(record),
                inner,
                binding,
                _handle: handle,
                _metadata: metadata,
            }) as Box<dyn BlobReader>)
        }))
    }
}
