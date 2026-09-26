//! Prepaid fixed pages shared with a protocol request without a whole-part copy.
use crate::HttpError;
use bytes::Bytes;
use http_body::{Body, Frame, SizeHint};
use latent_capabilities::broker::pools::{ProviderMetadata, ProviderPools};
use std::{
    convert::Infallible,
    ops::Range,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};
use zeroize::Zeroizing;

pub const PROTOCOL_PAGE_BYTES: usize = 65536;
pub const MAXIMUM_PROTOCOL_BODY_BYTES: usize = 32 * 1024 * 1024;

pub struct ProtocolPage {
    data: Zeroizing<Vec<u8>>,
    length: usize,
    _memory: ProviderMetadata,
}
impl ProtocolPage {
    pub fn allocate(pools: &ProviderPools, capacity: usize) -> Result<Self, HttpError> {
        if capacity == 0 || capacity > PROTOCOL_PAGE_BYTES {
            return Err(HttpError::InvalidRequest);
        }
        let memory = pools.reserve_protocol_metadata(capacity + 512)?;
        let data = Zeroizing::new(vec![0; capacity]);
        if data.capacity() != capacity {
            return Err(HttpError::Unavailable);
        }
        Ok(Self {
            data,
            length: 0,
            _memory: memory,
        })
    }
    #[must_use]
    pub fn capacity(&self) -> usize {
        self.data.len()
    }
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.data[..self.length]
    }
    pub fn append(&mut self, bytes: &[u8]) -> Result<(), HttpError> {
        let end = self
            .length
            .checked_add(bytes.len())
            .filter(|n| *n <= self.data.len())
            .ok_or(HttpError::RequestTooLarge)?;
        self.data[self.length..end].copy_from_slice(bytes);
        self.length = end;
        Ok(())
    }
}
pub struct ProtocolBody {
    pages: Vec<Arc<ProtocolPage>>,
    index: usize,
    offset: usize,
    remaining: usize,
    _metadata: ProviderMetadata,
}
struct Slice {
    page: Arc<ProtocolPage>,
    range: Range<usize>,
}
impl AsRef<[u8]> for Slice {
    fn as_ref(&self) -> &[u8] {
        &self.page.bytes()[self.range.clone()]
    }
}
impl ProtocolBody {
    pub fn from_pages(
        pools: &ProviderPools,
        pages: &[Arc<ProtocolPage>],
        range: Range<usize>,
    ) -> Result<Self, HttpError> {
        if pages.len() > 512 || range.end < range.start || range.end > MAXIMUM_PROTOCOL_BODY_BYTES {
            return Err(HttpError::InvalidRequest);
        }
        let total: usize = pages.iter().map(|p| p.bytes().len()).sum();
        if range.end > total {
            return Err(HttpError::InvalidRequest);
        }
        let metadata = pools.reserve_protocol_metadata(1024 + pages.len() * 32)?;
        let mut index = 0;
        let mut offset = range.start;
        while index < pages.len() && offset >= pages[index].bytes().len() {
            offset -= pages[index].bytes().len();
            index += 1;
        }
        Ok(Self {
            pages: pages.to_vec(),
            index,
            offset,
            remaining: range.len(),
            _metadata: metadata,
        })
    }
    pub fn empty(pools: &ProviderPools) -> Result<Self, HttpError> {
        Self::from_pages(pools, &[], 0..0)
    }
    #[must_use]
    pub fn length(&self) -> usize {
        self.remaining
    }
}
impl Body for ProtocolBody {
    type Data = Bytes;
    type Error = Infallible;
    fn poll_frame(
        self: Pin<&mut Self>,
        _: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, Infallible>>> {
        let this = self.get_mut();
        if this.remaining == 0 {
            return Poll::Ready(None);
        }
        let page = this.pages[this.index].clone();
        let length = (page.bytes().len() - this.offset).min(this.remaining);
        let range = this.offset..this.offset + length;
        this.index += 1;
        this.offset = 0;
        this.remaining -= length;
        Poll::Ready(Some(Ok(Frame::data(Bytes::from_owner(Slice {
            page,
            range,
        })))))
    }
    fn is_end_stream(&self) -> bool {
        self.remaining == 0
    }
    fn size_hint(&self) -> SizeHint {
        SizeHint::with_exact(self.remaining as u64)
    }
}
