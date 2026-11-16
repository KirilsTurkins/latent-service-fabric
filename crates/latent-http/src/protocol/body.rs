//! Prepaid fixed pages shared with a protocol request without a whole-part copy.
use crate::HttpError;
use bytes::Bytes;
use http_body::{Body, Frame, SizeHint};
use latent_capabilities::broker::pools::{ProviderMetadata, ProviderPools};
use std::{
    alloc::Layout,
    convert::Infallible,
    ops::Range,
    pin::Pin,
    sync::{atomic::AtomicUsize, Arc},
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

#[cfg(test)]
type PageDropHook = Box<dyn FnOnce() + Send>;
#[cfg(test)]
static PAGE_DROP_HOOK: std::sync::Mutex<Option<(usize, PageDropHook)>> =
    std::sync::Mutex::new(None);

#[cfg(test)]
pub(crate) fn observe_shared_page_drop(page: &SharedProtocolPage, hook: PageDropHook) {
    let mut slot = PAGE_DROP_HOOK.lock().unwrap();
    assert!(slot.is_none());
    *slot = Some((page.page().data.as_ptr() as usize, hook));
}

#[cfg(test)]
impl Drop for ProtocolPage {
    fn drop(&mut self) {
        let hook = {
            let mut slot = PAGE_DROP_HOOK.lock().unwrap();
            if slot
                .as_ref()
                .is_some_and(|(page, _)| *page == self.data.as_ptr() as usize)
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

/// A protocol page whose private Arc is retired before its original pool charge.
/// Only the handle is cloneable; its Arc and Weak handles never escape.
///
/// ```compile_fail
/// use latent_http::protocol::SharedProtocolPage;
/// fn cannot_downgrade(page: &SharedProtocolPage) {
///     let _ = std::sync::Arc::downgrade(page);
/// }
/// ```
///
/// ```compile_fail
/// use latent_http::protocol::{ProtocolPage, SharedProtocolPage};
/// fn cannot_replace(page: &mut SharedProtocolPage, other: ProtocolPage) {
///     let _ = std::mem::replace(page.get_mut().unwrap(), other);
/// }
/// ```
pub struct SharedProtocolPage(Option<Arc<ProtocolPage>>);

impl SharedProtocolPage {
    pub fn allocate(pools: &ProviderPools, capacity: usize) -> Result<Self, HttpError> {
        // The existing capacity + 512 reservation must cover BOTH the actual
        // page Arc and the Vec, including one 64-byte allowance for each.
        // Pinned Rust 1.97.1 uses this repr(C) ArcInner field order:
        // https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/library/alloc/src/sync.rs#L365-L386
        let arc = Layout::new::<[AtomicUsize; 2]>()
            .extend(Layout::new::<ProtocolPage>())
            .map_err(|_| HttpError::RequestTooLarge)?
            .0
            .pad_to_align()
            .size();
        if arc.checked_add(128).is_none_or(|bytes| bytes > 512) {
            return Err(HttpError::BudgetExhausted);
        }
        let page = ProtocolPage::allocate(pools, capacity)?;
        Ok(Self(Some(Arc::new(page))))
    }

    fn page(&self) -> &ProtocolPage {
        self.0.as_deref().expect("live protocol page")
    }

    #[must_use]
    pub fn capacity(&self) -> usize {
        self.page().capacity()
    }

    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        self.page().bytes()
    }

    /// Return None if another handle currently owns this page; no mutable
    /// page reference is exposed or allowed to replace the prepaid owner.
    pub fn try_append(&mut self, bytes: &[u8]) -> Option<Result<(), HttpError>> {
        Arc::get_mut(self.0.as_mut()?).map(|page| page.append(bytes))
    }
}

impl Clone for SharedProtocolPage {
    fn clone(&self) -> Self {
        Self(Some(Arc::clone(
            self.0.as_ref().expect("live protocol page"),
        )))
    }
}

impl Drop for SharedProtocolPage {
    fn drop(&mut self) {
        if let Some(page) = self.0.take() {
            // Every managed strong handle uses into_inner, and no Weak can be
            // created. On the last handle the Arc allocation is freed before
            // the returned page drops its Vec and original metadata charge.
            // https://github.com/rust-lang/rust/blob/8bab26f4f68e0e26f0bb7960be334d5b520ea452/library/alloc/src/sync.rs#L1176-L1199
            drop(Arc::into_inner(page));
        }
    }
}

const _: () = {
    assert!(std::mem::size_of::<SharedProtocolPage>() == std::mem::size_of::<Arc<ProtocolPage>>());
    assert!(
        std::mem::align_of::<SharedProtocolPage>() == std::mem::align_of::<Arc<ProtocolPage>>()
    );
};

// Only these two source forms are accepted. The raw-Arc form remains supported
// for existing callers, but its external Weak references are not covered by
// the managed handle's retirement guarantee.
trait PageSource {
    fn page(&self) -> &ProtocolPage;
    fn retained(&self) -> SharedProtocolPage;
}
impl PageSource for Arc<ProtocolPage> {
    fn page(&self) -> &ProtocolPage {
        self.as_ref()
    }
    fn retained(&self) -> SharedProtocolPage {
        SharedProtocolPage(Some(Arc::clone(self)))
    }
}
impl PageSource for SharedProtocolPage {
    fn page(&self) -> &ProtocolPage {
        SharedProtocolPage::page(self)
    }
    fn retained(&self) -> SharedProtocolPage {
        self.clone()
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
    page: SharedProtocolPage,
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
    page: SharedProtocolPage,
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
mod shared_page_layout_tests {
    use super::*;

    struct OriginalSlice {
        page: Arc<ProtocolPage>,
        range: Range<usize>,
    }
    impl AsRef<[u8]> for OriginalSlice {
        fn as_ref(&self) -> &[u8] {
            &self.page.bytes()[self.range.clone()]
        }
    }
    impl Drop for OriginalSlice {
        fn drop(&mut self) {}
    }

    #[test]
    fn shared_page_preserves_original_handle_and_frame_layouts() {
        let arc = Layout::new::<[AtomicUsize; 2]>()
            .extend(Layout::new::<ProtocolPage>())
            .unwrap()
            .0
            .pad_to_align()
            .size();
        assert!(arc + 128 <= 512);
        assert_eq!(
            std::mem::size_of::<SharedProtocolPage>(),
            std::mem::size_of::<Arc<ProtocolPage>>()
        );
        assert_eq!(
            std::mem::align_of::<SharedProtocolPage>(),
            std::mem::align_of::<Arc<ProtocolPage>>()
        );
        assert_eq!(
            std::mem::size_of::<Slice>(),
            std::mem::size_of::<OriginalSlice>()
        );
        assert_eq!(
            std::mem::align_of::<Slice>(),
            std::mem::align_of::<OriginalSlice>()
        );
        assert_eq!(
            bytes::Bytes::owner_with_retirement_allocation_size::<Slice, ProviderMetadata>(),
            bytes::Bytes::owner_with_retirement_allocation_size::<OriginalSlice, ProviderMetadata>(
            )
        );
        eprintln!(
            "ProtocolPage={}, Arc backing={arc}, handle={}, Slice={}, frame charge={}",
            std::mem::size_of::<ProtocolPage>(),
            std::mem::size_of::<SharedProtocolPage>(),
            std::mem::size_of::<Slice>(),
            frame_allocation_bytes().unwrap()
        );
    }
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
            if slot.as_ref().is_some_and(|(page, _)| {
                *page == Arc::as_ptr(self.page.0.as_ref().unwrap()) as usize
            }) {
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
        Self::from_page_source(pools, pages, range)
    }

    /// Build from pages whose private Arc headers retire before their charges.
    pub fn from_shared_pages(
        pools: &ProviderPools,
        pages: &[SharedProtocolPage],
        range: Range<usize>,
    ) -> Result<Self, HttpError> {
        Self::from_page_source(pools, pages, range)
    }

    fn from_page_source<T: PageSource>(
        pools: &ProviderPools,
        pages: &[T],
        range: Range<usize>,
    ) -> Result<Self, HttpError> {
        if pages.len() > 512 || range.end < range.start || range.end > MAXIMUM_PROTOCOL_BODY_BYTES {
            return Err(HttpError::InvalidRequest);
        }
        let total: usize = pages.iter().map(|p| p.page().bytes().len()).sum();
        if range.end > total {
            return Err(HttpError::InvalidRequest);
        }
        let mut index = 0;
        let mut offset = range.start;
        while index < pages.len() && offset >= pages[index].page().bytes().len() {
            offset -= pages[index].page().bytes().len();
            index += 1;
        }
        // Mirror poll_frame exactly: even an empty page between nonempty pages
        // produces a frame, while an empty range produces no frame at all.
        let mut end = index;
        let mut pending = range.len();
        let mut first_offset = offset;
        while pending != 0 {
            let page = pages.get(end).ok_or(HttpError::InvalidRequest)?;
            let length = (page.page().bytes().len() - first_offset).min(pending);
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
                page: page.retained(),
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
        let page = entry.page.clone();
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
