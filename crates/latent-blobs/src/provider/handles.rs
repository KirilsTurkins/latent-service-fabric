use super::{
    checkpoint, execute, map, Arc, BlobError, BlobFuture, BlobReader, BlobReference, BlobWriter,
    BudgetDimension, CapabilityCallCost, CapabilityRequestDigest, Inner,
};
use latent_capabilities::broker::{
    blob::{BlobChunk, BlobSeal},
    SessionResourceTableReservation,
};

pub(super) struct Writer {
    // Close the physical FD before dropping the original session reservation.
    pub data: Option<crate::local::LocalBlobWriter>,
    pub inner: Arc<Inner>,
    pub binding: SessionResourceTableReservation,
}
pub(super) struct Reader {
    pub data: Option<crate::local::LocalBlobReader>,
    pub inner: Arc<Inner>,
    pub binding: SessionResourceTableReservation,
}
impl BlobWriter for Writer {
    fn write(&mut self, offset: u64, bytes: Vec<u8>) -> Result<BlobFuture<'_, u64>, BlobError> {
        let data = self.data.as_ref().ok_or(BlobError::InvalidState)?;
        if offset != data.written()
            || bytes.capacity() > self.inner.store.limits().maximum_chunk_bytes
            || offset
                .checked_add(bytes.len() as u64)
                .is_none_or(|n| n > data.maximum_size())
        {
            return Err(BlobError::InvalidRange);
        }
        let admission = self
            .binding
            .with_session(|session| self.inner.admit(session))?;
        let memory = admission.reserve_input(bytes.capacity().max(1), 512)?;
        let digest = CapabilityRequestDigest::from_parts(&[
            b"blob-write-v1",
            &offset.to_le_bytes(),
            &bytes,
        ])?;
        let mut cost = CapabilityCallCost::new(8)
            .with_typed_input_bytes(bytes.len() + 16)
            .with_typed_request_digest(digest);
        if !bytes.is_empty() {
            cost = cost.with_charge(BudgetDimension::BlobWriteBytes, bytes.len() as u64)?;
        }
        let mut data = self.data.take().expect("validated writer");
        Ok(Box::pin(async move {
            let call = execute::dispatch(&self.inner, admission, "write", cost).await?;
            let completion = execute::run(&self.inner, call, "write", move |call| {
                let _memory = memory;
                let count = data
                    .write(offset, &bytes, &|| checkpoint(call))
                    .map_err(map);
                drop(bytes);
                Ok((data, count?))
            })
            .await?;
            let (data, count) = completion.value?;
            self.data = Some(data);
            Ok(count)
        }))
    }
    fn seal(mut self: Box<Self>) -> Result<BlobFuture<'static, BlobSeal>, BlobError> {
        let data = self.data.take().ok_or(BlobError::InvalidState)?;
        let admission = self
            .binding
            .with_session(|session| self.inner.admit(session))?;
        let cost = CapabilityCallCost::new(512)
            .with_typed_input_bytes(8)
            .with_typed_request_digest(CapabilityRequestDigest::from_parts(&[
                b"blob-seal-v1",
                &data.written().to_le_bytes(),
            ])?);
        Ok(Box::pin(async move {
            let call = execute::dispatch(&self.inner, admission, "seal", cost).await?;
            let completion = execute::run(&self.inner, call, "seal", move |call| {
                data.seal(&|| checkpoint(call)).map_err(map)
            })
            .await?;
            let reference = completion.value?;
            Ok(BlobSeal {
                reference: BlobReference {
                    digest: reference.digest.0,
                    size: reference.size_bytes,
                    media_type: reference.media_type,
                },
                owner: completion.call,
            })
        }))
    }
}
impl BlobReader for Reader {
    fn read(&mut self, offset: u64, length: u32) -> Result<BlobFuture<'_, BlobChunk>, BlobError> {
        let data = self.data.as_ref().ok_or(BlobError::InvalidState)?;
        if length as usize > self.inner.store.limits().maximum_chunk_bytes
            || offset
                .checked_add(u64::from(length))
                .is_none_or(|n| n > data.reference().size_bytes)
        {
            return Err(BlobError::InvalidRange);
        }
        let admission = self
            .binding
            .with_session(|session| self.inner.admit(session))?;
        let mut cost = CapabilityCallCost::new((length as usize).max(1))
            .with_typed_input_bytes(20)
            .with_typed_request_digest(CapabilityRequestDigest::from_parts(&[
                b"blob-read-v1",
                data.reference().digest.0.as_bytes(),
                &offset.to_le_bytes(),
                &length.to_le_bytes(),
            ])?);
        if length != 0 {
            cost = cost.with_charge(BudgetDimension::BlobReadBytes, u64::from(length))?;
        }
        let data = self.data.take().expect("validated reader");
        Ok(Box::pin(async move {
            let call = execute::dispatch(&self.inner, admission, "read", cost).await?;
            let mut buffer = call.io().buffer((length as usize).max(1), 512)?;
            let copy = call.io().reserve_scratch((length as usize).max(1), 512)?;
            let completion = execute::run(&self.inner, call, "read", move |call| {
                let count = data
                    .read(
                        &crate::BlobRange {
                            offset,
                            length: u64::from(length),
                        },
                        &mut buffer.spare_mut()?[..length as usize],
                        &|| checkpoint(call),
                    )
                    .map_err(map)?;
                buffer.advance_written(count)?;
                Ok((data, buffer, copy))
            })
            .await?;
            let (data, buffer, copy) = completion.value?;
            self.data = Some(data);
            BlobChunk::new(buffer, copy, completion.call)
        }))
    }
}
