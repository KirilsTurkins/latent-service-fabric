use super::{
    finish, inventory, remote, seal, Arc, AuditProviderOutcome, BlobError, BlobFuture, BlobReader,
    BlobWriter, CapabilityCallCost, CapabilityRequestDigest, Digest, Inner, ProviderMetadata,
    Result, Sha256,
};
use latent_capabilities::broker::{
    blob::{BlobChunk, BlobSeal},
    SessionResourceTableReservation,
};
use latent_core::BudgetDimension;
use latent_http::protocol::{ProtocolPage, PROTOCOL_PAGE_BYTES};

pub(super) struct Staging {
    pub pages: Vec<Arc<ProtocolPage>>,
    pub written: usize,
    expected: Option<u64>,
    pub tenant: String,
    pub media_type: String,
    pub full_hash: Sha256,
    part_hash: Sha256,
    pub hashes: Vec<String>,
    stage: inventory::Stage,
    _metadata: ProviderMetadata,
}
impl Staging {
    pub fn new(
        inner: &Inner,
        tenant: String,
        media_type: String,
        expected: Option<u64>,
    ) -> Result<Self> {
        let stage = inner.inventory.stage(expected)?;
        let metadata = inner.pools.reserve_protocol_metadata(32768)?;
        let count = stage.maximum.div_ceil(PROTOCOL_PAGE_BYTES);
        let mut pages = Vec::with_capacity(count);
        for i in 0..count {
            pages.push(Arc::new(
                ProtocolPage::allocate(
                    &inner.pools,
                    (stage.maximum - i * PROTOCOL_PAGE_BYTES).min(PROTOCOL_PAGE_BYTES),
                )
                .map_err(crate::s3::http)?,
            ));
        }
        Ok(Self {
            pages,
            written: 0,
            expected,
            tenant,
            media_type,
            full_hash: Sha256::new(),
            part_hash: Sha256::new(),
            hashes: Vec::with_capacity(inner.inventory.config().limits.parts()),
            stage,
            _metadata: metadata,
        })
    }
    fn append(&mut self, bytes: &[u8]) -> Result<u64> {
        self.full_hash.update(bytes);
        for mut bytes in bytes.chunks(PROTOCOL_PAGE_BYTES) {
            while !bytes.is_empty() {
                let page = Arc::get_mut(&mut self.pages[self.written / PROTOCOL_PAGE_BYTES])
                    .ok_or(BlobError::InvalidState)?;
                let count = bytes.len().min(page.capacity() - page.bytes().len());
                page.append(&bytes[..count]).map_err(crate::s3::http)?;
                self.part_hash.update(&bytes[..count]);
                self.written += count;
                bytes = &bytes[count..];
                if self.written.is_multiple_of(crate::s3::PART_BYTES) {
                    self.hashes
                        .push(format!("{:x}", self.part_hash.finalize_reset()));
                }
            }
        }
        Ok(self.written as u64)
    }
    pub fn prepare(&mut self) -> Result<()> {
        if self.expected.is_some_and(|n| n != self.written as u64) {
            return Err(BlobError::InvalidRange);
        }
        if !self.written.is_multiple_of(crate::s3::PART_BYTES) {
            self.hashes
                .push(format!("{:x}", self.part_hash.finalize_reset()));
        }
        Ok(())
    }
}
pub(super) struct Writer {
    pub data: Option<Staging>,
    pub inner: Arc<Inner>,
    pub binding: SessionResourceTableReservation,
}
pub(super) struct Reader {
    pub record: Option<inventory::Record>,
    pub inner: Arc<Inner>,
    pub binding: SessionResourceTableReservation,
    pub _handle: inventory::Handle,
    pub _metadata: ProviderMetadata,
}
impl BlobWriter for Writer {
    fn write(&mut self, offset: u64, bytes: Vec<u8>) -> Result<BlobFuture<'_, u64>> {
        let data = self.data.as_ref().ok_or(BlobError::InvalidState)?;
        if offset != data.written as u64
            || bytes.capacity() > PROTOCOL_PAGE_BYTES
            || data
                .written
                .checked_add(bytes.len())
                .is_none_or(|n| n > data.stage.maximum)
        {
            return Err(BlobError::InvalidRange);
        }
        let admission = self.binding.with_session(|s| self.inner.admit(s))?;
        let memory = admission.reserve_input(bytes.capacity().max(1), 512)?;
        let mut cost = CapabilityCallCost::new(8)
            .with_typed_input_bytes(bytes.len() + 16)
            .with_typed_request_digest(CapabilityRequestDigest::from_parts(&[
                b"s3-blob-write-v1",
                &offset.to_le_bytes(),
                &bytes,
            ])?);
        if !bytes.is_empty() {
            cost = cost.with_charge(BudgetDimension::BlobWriteBytes, bytes.len() as u64)?;
        }
        let mut data = self.data.take().expect("validated writer");
        Ok(Box::pin(async move {
            let mut call = self.inner.dispatch(admission, "write", cost).await?;
            let _memory = memory;
            call.io().checkpoint()?;
            let count = data.append(&bytes)?;
            drop(bytes);
            finish(&mut call, AuditProviderOutcome::HostCompleted).await?;
            self.data = Some(data);
            Ok(count)
        }))
    }
    fn seal(mut self: Box<Self>) -> Result<BlobFuture<'static, BlobSeal>> {
        let mut data = self.data.take().ok_or(BlobError::InvalidState)?;
        data.prepare()?;
        let admission = self.binding.with_session(|s| self.inner.admit(s))?;
        let requests = if data.written == 0 {
            1
        } else {
            data.hashes.len() + 2
        };
        let digest = format!("sha256:{:x}", data.full_hash.clone().finalize());
        let cost = CapabilityCallCost::new(512)
            .with_typed_input_bytes(8)
            .with_typed_request_digest(CapabilityRequestDigest::from_parts(&[
                b"s3-blob-seal-v1",
                digest.as_bytes(),
                &(data.written as u64).to_le_bytes(),
            ])?)
            .with_charge(BudgetDimension::OutboundRequests, requests as u64)?;
        Ok(Box::pin(async move {
            let call = self.inner.dispatch(admission, "seal", cost).await?;
            seal::run(self.inner.clone(), call, data, digest).await
        }))
    }
}
impl BlobReader for Reader {
    fn read(&mut self, offset: u64, length: u32) -> Result<BlobFuture<'_, BlobChunk>> {
        let record = self.record.as_ref().ok_or(BlobError::InvalidState)?;
        if length as usize > PROTOCOL_PAGE_BYTES
            || offset
                .checked_add(u64::from(length))
                .is_none_or(|n| n > record.size)
        {
            return Err(BlobError::InvalidRange);
        }
        let admission = self.binding.with_session(|s| self.inner.admit(s))?;
        let part = crate::s3::PART_BYTES as u64;
        let requests = if length == 0 {
            0
        } else {
            (offset + u64::from(length) - 1) / part - offset / part + 1
        };
        let mut cost = CapabilityCallCost::new((length as usize).max(1))
            .with_typed_input_bytes(20)
            .with_typed_request_digest(CapabilityRequestDigest::from_parts(&[
                b"s3-blob-read-v1",
                record.digest.as_bytes(),
                &offset.to_le_bytes(),
                &length.to_le_bytes(),
            ])?);
        if requests > 0 {
            cost = cost
                .with_charge(BudgetDimension::OutboundRequests, requests)?
                .with_charge(BudgetDimension::BlobReadBytes, u64::from(length))?;
        }
        let record = self.record.take().expect("validated reader");
        Ok(Box::pin(async move {
            let mut call = self.inner.dispatch(admission, "read", cost).await?;
            let mut buffer = call.io().buffer((length as usize).max(1), 512)?;
            let copy = call.io().reserve_scratch((length as usize).max(1), 512)?;
            let value =
                remote::read(&self.inner, &call, &record, offset, length, &mut buffer).await;
            finish(
                &mut call,
                if value.is_ok() {
                    AuditProviderOutcome::HostCompleted
                } else {
                    AuditProviderOutcome::Rejected
                },
            )
            .await?;
            value?;
            self.record = Some(record);
            BlobChunk::new(buffer, copy, call)
        }))
    }
}
