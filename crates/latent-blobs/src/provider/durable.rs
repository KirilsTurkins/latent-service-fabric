//! Only the installed local immutable profile can capture this affine payload.
//! The coordinator still supplies its final current policy/publication fence.
use super::{
    checkpoint, execute, map, reference_digest, validate_reference, Arc, BlobError, BlobFuture,
    BlobReference, CapabilityCallCost, CapabilitySession, Inner, LocalBlobProvider,
};
use latent_capabilities::broker::SessionResourceTableReservation;
use latent_state::payload_references::LocalPayloadIdentity;

pub struct CapturedLocalPayload {
    // Physical FD/pending pin retires before original binding-table ownership.
    pin: crate::local::LocalDurablePin,
    inner: Arc<Inner>,
    binding: SessionResourceTableReservation,
    identity: LocalPayloadIdentity,
}
impl CapturedLocalPayload {
    /// Compare the actual original session owner without reconstructing it from
    /// tenant, principal or publication strings supplied in a reference.
    #[must_use]
    pub fn uses_session(&self, session: &CapabilitySession) -> bool {
        self.binding
            .with_session(|original| original.is_same_session(session))
    }
    /// An attached inline value must describe these exact verified bytes. This
    /// does not reinterpret a serialized descriptor as provider request bytes.
    pub fn verify_inline_value(
        &self,
        value: &latent_core::transaction_contract::Value,
    ) -> Result<(), BlobError> {
        use sha2::{Digest, Sha256};
        value.validate().map_err(|_| BlobError::InvalidRange)?;
        let digest: [u8; 32] = Sha256::digest(&value.bytes).into();
        if self.identity.size != value.bytes.len() as u64
            || self.identity.digest != digest
            || self.identity.media_type != value.media_type
        {
            return Err(BlobError::ChecksumMismatch);
        }
        Ok(())
    }
    #[must_use]
    pub fn identity(&self) -> &LocalPayloadIdentity {
        &self.identity
    }
    #[must_use]
    pub fn store_identity(&self) -> &str {
        self.pin.store_identity()
    }
    #[must_use]
    pub fn native_reader(&self) -> &crate::local::LocalBlobReader {
        self.pin.reader()
    }
    /// Borrow the same captured caller/binding owner for the complete host's
    /// current acceptance fence. This never reconstructs a grant from the DTO.
    pub fn with_session<T>(&self, fence: impl FnOnce(&CapabilitySession) -> T) -> T {
        self.binding.with_session(fence)
    }
    /// Descriptive installed identity; this check does not authorize a commit.
    pub fn matches_provider(&self, session: &CapabilitySession) -> Result<bool, BlobError> {
        Ok(session.uses_provider(&self.inner.installed.reference())?)
    }
}
impl LocalBlobProvider {
    /// The existing open operation authorizes and audits exact caller/binding,
    /// provider configuration and tenant before native bytes are verified. The
    /// original shared worker and session resource reservation retain the pin.
    /// S3 and other external retention classes have no constructor for this type.
    pub fn capture_reference(
        &self,
        session: &CapabilitySession,
        reference: BlobReference,
    ) -> Result<BlobFuture<'static, CapturedLocalPayload>, BlobError> {
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
            .with_typed_request_digest(reference_digest(b"blob-durable-reference-v1", &reference)?);
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
                root.capture_durable_reference(&reference.tenant, &reference, &|| checkpoint(call))
                    .map_err(map)
            })
            .await?;
            let pin = completed.value?;
            let identity = pin
                .identity(
                    &inner.logical_id,
                    inner.installed.reference().configuration_epoch(),
                )
                .map_err(map)?;
            Ok(CapturedLocalPayload {
                pin,
                inner,
                binding,
                identity,
            })
        }))
    }
}
