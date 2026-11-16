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
    pages: Vec<PageEntry>,
    index: usize,
    offset: usize,
    remaining: usize,
    _metadata: ProviderMetadata,
}
// One possible frame per page. Its original node guard is admitted before the
// infallible Body poll and moved to Bytes only if that page is emitted.
struct PageEntry {
    page: Arc<ProtocolPage>,
    retirement: Option<ProviderMetadata>,
}

// Reproduce the previous body fields and their drop glue without constructing
// this type; reject changes to its value, Option or Result layout.
#[allow(dead_code)]
struct OriginalProtocolBodyLayout {
    pages: Vec<Arc<ProtocolPage>>,
    index: usize,
    offset: usize,
    remaining: usize,
    _metadata: ProviderMetadata,
}
const _: () = {
    assert!(
        std::mem::size_of::<ProtocolBody>() == std::mem::size_of::<OriginalProtocolBodyLayout>()
    );
    assert!(
        std::mem::align_of::<ProtocolBody>() == std::mem::align_of::<OriginalProtocolBodyLayout>()
    );
    assert!(
        std::mem::size_of::<Option<ProtocolBody>>()
            == std::mem::size_of::<Option<OriginalProtocolBodyLayout>>()
    );
    assert!(
        std::mem::size_of::<Result<ProtocolBody, HttpError>>()
            == std::mem::size_of::<Result<OriginalProtocolBodyLayout, HttpError>>()
    );
};
struct Slice {
    page: Arc<ProtocolPage>,
    range: Range<usize>,
}

fn frame_allocation_bytes() -> Result<usize, HttpError> {
    bytes::Bytes::owner_with_retirement_allocation_size::<Slice, ProviderMetadata>()
        .checked_add(64)
        .ok_or(HttpError::RequestTooLarge)
}

#[cfg(test)]
pub(crate) fn protocol_accounting_layout() -> (usize, usize) {
    (
        std::mem::size_of::<PageEntry>(),
        frame_allocation_bytes().unwrap(),
    )
}

#[cfg(test)]
type SliceDropHook = Box<dyn FnOnce() + Send>;
#[cfg(test)]
static SLICE_DROP_HOOK: std::sync::Mutex<Option<(usize, SliceDropHook)>> =
    std::sync::Mutex::new(None);

#[cfg(test)]
pub(crate) fn observe_slice_drop(page: &Arc<ProtocolPage>, hook: SliceDropHook) {
    let mut slot = SLICE_DROP_HOOK.lock().unwrap();
    assert!(slot.is_none());
    *slot = Some((Arc::as_ptr(page) as usize, hook));
}

#[cfg(test)]
impl Drop for Slice {
    fn drop(&mut self) {
        let hook = {
            let mut slot = SLICE_DROP_HOOK.lock().unwrap();
            if slot
                .as_ref()
                .is_some_and(|(page, _)| *page == Arc::as_ptr(&self.page) as usize)
            {
                slot.take()
            } else {
                None
            }
        };
        if let Some((_, hook)) = hook {
            hook();
        }
    }
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
        let mut index = 0;
        let mut offset = range.start;
        while index < pages.len() && offset >= pages[index].bytes().len() {
            offset -= pages[index].bytes().len();
            index += 1;
        }
        // Mirror poll_frame exactly: even an empty page between nonempty pages
        // produces a frame, while an empty range produces no frame at all.
        let mut end = index;
        let mut pending = range.len();
        let mut first_offset = offset;
        while pending != 0 {
            let page = pages.get(end).ok_or(HttpError::InvalidRequest)?;
            let length = (page.bytes().len() - first_offset).min(pending);
            pending -= length;
            first_offset = 0;
            end += 1;
        }
        // The old body prepaid 32 bytes per page plus 1 KiB. Increase this
        // only where the actual typed vector entry needs more than 32 bytes.
        let entry_bytes = std::mem::size_of::<PageEntry>().max(32);
        let metadata_bytes = pages
            .len()
            .checked_mul(entry_bytes)
            .and_then(|n| n.checked_add(1024))
            .ok_or(HttpError::RequestTooLarge)?;
        let metadata = pools.reserve_protocol_metadata(metadata_bytes)?;
        let frame_bytes = frame_allocation_bytes()?;
        let mut entries = Vec::new();
        // The pinned Rust 1.97.1 Global allocator and grow_exact request the
        // exact typed layout prepaid above; reject a different reported capacity.
        // https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/library/alloc/src/raw_vec/mod.rs#L725-L750
        // https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/library/alloc/src/alloc.rs#L188-L199
        entries
            .try_reserve_exact(pages.len())
            .map_err(|_| HttpError::BudgetExhausted)?;
        if entries.capacity() != pages.len() {
            return Err(HttpError::Unavailable);
        }
        for (position, page) in pages.iter().enumerate() {
            let retirement = if (index..end).contains(&position) {
                Some(pools.reserve_protocol_metadata(frame_bytes)?)
            } else {
                None
            };
            entries.push(PageEntry {
                page: Arc::clone(page),
                retirement,
            });
        }
        Ok(Self {
            pages: entries,
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
        let entry = &mut this.pages[this.index];
        let page = Arc::clone(&entry.page);
        let retirement = entry
            .retirement
            .take()
            .expect("each emitted page is prepaid");
        let length = (page.bytes().len() - this.offset).min(this.remaining);
        let range = this.offset..this.offset + length;
        this.index += 1;
        this.offset = 0;
        this.remaining -= length;
        Poll::Ready(Some(Ok(Frame::data(Bytes::from_owner_with_retirement(
            Slice { page, range },
            retirement,
            |_| {},
        )))))
    }
    fn is_end_stream(&self) -> bool {
        self.remaining == 0
    }
    fn size_hint(&self) -> SizeHint {
        SizeHint::with_exact(self.remaining as u64)
    }
}
