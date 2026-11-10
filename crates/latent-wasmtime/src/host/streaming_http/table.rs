//! Fixed Store-local resources; no number can create or extend authority.
use latent_capabilities::broker::{
    http::HttpError,
    io::{IoOutputChunk, IoOutputCopy},
    streaming_http::{HttpBody, HttpUpload, StreamingHttpError as Error},
    CapabilitySession, SessionResourceTableReservation,
};
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
mod shared;
use latent_core::HostMemoryReservation;
use shared::Shared;

const CAPACITY: usize = 64;
static NEXT_REP: AtomicU32 = AtomicU32::new(1);
#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Kind {
    Upload,
    Body,
    Chunk,
}
pub(super) enum Value {
    Upload(Box<dyn HttpUpload>),
    Body {
        value: Box<dyn HttpBody>,
        trailers_delivered: bool,
    },
    Chunk {
        value: IoOutputChunk,
        delivered: bool,
    },
}
struct Entry {
    // Bit 0 marks an empty slot; bit 1 remains set once its value is published,
    // including while borrowed. A guard can erase only its unpublished slot.
    state: Shared<AtomicU64>,
    kind: Kind,
    value: Option<Value>,
}
#[derive(Default)]
pub(crate) struct Table {
    entries: Vec<Entry>,
    memory: Option<Shared<SessionResourceTableReservation>>,
    // The actual Vec and every retained entry die before this capacity refunds.
    native: Option<HostMemoryReservation>,
}

pub(super) struct Reservation {
    state: Shared<AtomicU64>,
    rep: u32,
    // Metadata that survives Store destruction remains charged until this
    // affine guard actually disappears; the fixed table's slack covers it.
    _memory: Option<Shared<SessionResourceTableReservation>>,
}

impl Reservation {
    pub(super) fn rep(&self) -> u32 {
        self.rep
    }
}

impl Drop for Reservation {
    fn drop(&mut self) {
        let _ = self.state.compare_exchange(
            (u64::from(self.rep) << 2) | 1,
            0,
            Ordering::AcqRel,
            Ordering::Acquire,
        );
    }
}

// Rust drops fields in declaration order. The real future/transport value is
// destroyed before the empty, unpublished slot becomes reusable.
pub(super) struct Reserved<T> {
    pub(super) value: T,
    pub(super) reservation: Reservation,
}

impl Table {
    pub(super) fn initialize(&mut self, session: &CapabilitySession) -> Result<(), Error> {
        if !self.entries.is_empty() {
            return Ok(());
        }
        let memory =
            session.reserve_resource_table(CAPACITY * std::mem::size_of::<Entry>() + 4096)?;
        let quota_memory = memory.reserve_native_backing(Shared::<
            SessionResourceTableReservation,
        >::allocation_bytes()?)?;
        let table_bytes = std::alloc::Layout::array::<Entry>(CAPACITY)
            .map_err(|_| HttpError::BudgetExhausted)?
            .size()
            .checked_add(shared::ALLOCATION_BOOKKEEPING)
            .and_then(|bytes| u64::try_from(bytes).ok())
            .ok_or(HttpError::BudgetExhausted)?;
        let native = memory.reserve_native_backing(table_bytes)?;
        // The sealed broker table owner is installed before creating any state
        // Arc or table buffer. Failed partial construction never publishes rows.
        let memory = Shared::new(memory, quota_memory)?;
        let mut candidate = Self {
            entries: Vec::with_capacity(CAPACITY),
            memory: Some(memory),
            native,
        };
        if candidate.entries.capacity() != CAPACITY {
            return Err(HttpError::BudgetExhausted.into());
        }
        if let Some(native) = &mut candidate.native {
            native.confirm();
        }
        for _ in 0..CAPACITY {
            let native = candidate
                .memory
                .as_ref()
                .unwrap()
                .reserve_native_backing(Shared::<AtomicU64>::allocation_bytes()?)?;
            candidate.entries.push(Entry {
                state: Shared::new(AtomicU64::new(0), native)?,
                kind: Kind::Upload,
                value: None,
            });
        }
        *self = candidate;
        Ok(())
    }
    pub(super) fn reserve(&mut self, kind: Kind) -> Result<u32, Error> {
        let slot = self
            .entries
            .iter_mut()
            .find(|e| e.state.load(Ordering::Acquire) == 0 && e.value.is_none())
            .ok_or(HttpError::BudgetExhausted)?;
        let rep = NEXT_REP
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| n.checked_add(1))
            .map_err(|_| HttpError::BudgetExhausted)?;
        slot.state
            .store((u64::from(rep) << 2) | 1, Ordering::Release);
        slot.kind = kind;
        Ok(rep)
    }
    pub(super) fn reserve_guarded(&mut self, kind: Kind) -> Result<Reservation, Error> {
        let rep = self.reserve(kind)?;
        let entry = self.entry(rep, kind)?;
        let state = entry.state.clone();
        Ok(Reservation {
            state,
            rep,
            _memory: self.memory.clone(),
        })
    }
    fn entry(&mut self, rep: u32, kind: Kind) -> Result<&mut Entry, Error> {
        self.entries
            .iter_mut()
            .find(|e| {
                e.state.load(Ordering::Acquire) >> 2 == u64::from(rep) && rep != 0 && e.kind == kind
            })
            .ok_or(Error::InvalidState)
    }
    pub(super) fn put(&mut self, rep: u32, kind: Kind, value: Value) -> Result<(), Error> {
        if !matches!(
            (&value, kind),
            (Value::Upload(_), Kind::Upload)
                | (Value::Body { .. }, Kind::Body)
                | (Value::Chunk { .. }, Kind::Chunk)
        ) {
            return Err(Error::InvalidState);
        }
        let entry = self.entry(rep, kind)?;
        if entry.value.is_some() {
            return Err(Error::InvalidState);
        }
        entry.value = Some(value);
        entry
            .state
            .store((u64::from(rep) << 2) | 2, Ordering::Release);
        Ok(())
    }
    // A completed write must retain the same upload if its row was
    // concurrently removed, until the surrounding Store callback returns.
    pub(super) fn put_upload_recoverable(
        &mut self,
        rep: u32,
        upload: Box<dyn HttpUpload>,
    ) -> Result<(), (Error, Box<dyn HttpUpload>)> {
        let entry = match self.entry(rep, Kind::Upload) {
            Ok(entry) => entry,
            Err(error) => return Err((error, upload)),
        };
        if entry.value.is_some() {
            return Err((Error::InvalidState, upload));
        }
        entry.value = Some(Value::Upload(upload));
        entry
            .state
            .store((u64::from(rep) << 2) | 2, Ordering::Release);
        Ok(())
    }
    // A refused finish publication returns the actual body to its caller so
    // the provider's destructor runs after Store access ends.
    pub(super) fn put_body_recoverable(
        &mut self,
        rep: u32,
        body: Box<dyn HttpBody>,
    ) -> Result<(), (Error, Box<dyn HttpBody>)> {
        let entry = match self.entry(rep, Kind::Body) {
            Ok(entry) => entry,
            Err(error) => return Err((error, body)),
        };
        if entry.value.is_some() {
            return Err((Error::InvalidState, body));
        }
        entry.value = Some(Value::Body {
            value: body,
            trailers_delivered: false,
        });
        entry
            .state
            .store((u64::from(rep) << 2) | 2, Ordering::Release);
        Ok(())
    }
    pub(super) fn take(&mut self, rep: u32, kind: Kind, consume: bool) -> Result<Value, Error> {
        let entry = self.entry(rep, kind)?;
        let value = entry.value.take().ok_or(Error::InvalidState)?;
        if consume {
            entry.state.store(0, Ordering::Release);
        } else {
            entry
                .state
                .store((u64::from(rep) << 2) | 3, Ordering::Release);
        }
        Ok(value)
    }
    pub(super) fn remove(&mut self, rep: u32, kind: Kind) -> Result<(), Error> {
        let entry = self.entry(rep, kind)?;
        entry.value = None;
        entry.state.store(0, Ordering::Release);
        Ok(())
    }
    // Preserve an existing value for retirement after the Store callback.
    // A busy row still removes successfully without taking its in-flight owner.
    pub(super) fn remove_recoverable(
        &mut self,
        rep: u32,
        kind: Kind,
    ) -> Result<Option<Value>, Error> {
        let entry = self.entry(rep, kind)?;
        let value = entry.value.take();
        entry.state.store(0, Ordering::Release);
        Ok(value)
    }
    pub(super) fn chunk_bytes(&mut self, rep: u32) -> Result<IoOutputCopy, Error> {
        let Some(Value::Chunk { value, delivered }) = &mut self.entry(rep, Kind::Chunk)?.value
        else {
            return Err(Error::InvalidState);
        };
        if *delivered {
            return Err(Error::InvalidState);
        }
        let bytes = value.copy_bytes()?;
        *delivered = true;
        Ok(bytes)
    }
    pub(super) fn trailers(&mut self, rep: u32) -> Result<Vec<super::wit::Header>, Error> {
        let Some(Value::Body {
            value,
            trailers_delivered,
        }) = &mut self.entry(rep, Kind::Body)?.value
        else {
            return Err(Error::InvalidState);
        };
        if *trailers_delivered {
            return Err(Error::InvalidState);
        }
        let trailers = value.trailers()?;
        *trailers_delivered = true;
        Ok(trailers
            .iter()
            .map(|(name, value)| super::wit::Header {
                name: name.into(),
                value: value.into(),
            })
            .collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_capabilities::broker::io::IoFuture;
    use std::sync::{atomic::AtomicUsize, Arc};
    struct Upload(Arc<AtomicUsize>);
    impl Drop for Upload {
        fn drop(&mut self) {
            self.0.fetch_add(1, Ordering::AcqRel);
        }
    }
    impl HttpUpload for Upload {
        fn write(&mut self, _: Vec<u8>) -> IoFuture<'_, Result<(), Error>> {
            IoFuture::failed(Error::InvalidState)
        }
        fn finish(self: Box<Self>) -> IoFuture<'static, Result<Box<dyn HttpBody>, Error>> {
            IoFuture::failed(Error::InvalidState)
        }
    }

    struct ReentrantOpenUpload {
        access: wasmtime::component::Accessor<crate::host::HostState>,
        observed: Arc<AtomicUsize>,
    }
    impl Drop for ReentrantOpenUpload {
        fn drop(&mut self) {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                self.access.with(|_| ());
            }));
            // 1 means the same Store was available; 2 means the upload was
            // destroyed while an Accessor::with callback still held it.
            self.observed
                .store(if result.is_ok() { 1 } else { 2 }, Ordering::SeqCst);
        }
    }
    impl HttpUpload for ReentrantOpenUpload {
        fn write(&mut self, _: Vec<u8>) -> IoFuture<'_, Result<(), Error>> {
            IoFuture::failed(Error::InvalidState)
        }
        fn finish(self: Box<Self>) -> IoFuture<'static, Result<Box<dyn HttpBody>, Error>> {
            IoFuture::failed(Error::InvalidState)
        }
    }

    #[tokio::test]
    async fn abort_upload_drops_original_after_store_access() {
        use crate::host::native_context_reply_tests::{engine, ledger, store};
        use latent_core::BudgetProfile;
        use wasmtime::AsContextMut;

        let mut drop_orders = Vec::new();
        for fail_checkpoint in [false, true] {
            let engine = engine();
            let budget = ledger(BudgetProfile::Phase1);
            let mut store = store(&engine, &budget, true);
            let mut resources = table();
            let rep = resources.reserve(Kind::Upload).unwrap();
            store.data_mut().capabilities.streams = resources;
            if fail_checkpoint {
                store.set_fuel(u64::MAX).unwrap();
            }
            let observed = Arc::new(AtomicUsize::new(0));
            let witness = observed.clone();
            store
                .run_concurrent(async |access| {
                    let upload = ReentrantOpenUpload {
                        access: access.with_getter(|state: &mut crate::host::HostState| state),
                        observed: witness.clone(),
                    };
                    access.with(|mut access| {
                        access
                            .as_context_mut()
                            .data_mut()
                            .capabilities
                            .streams
                            .put(rep, Kind::Upload, Value::Upload(Box::new(upload)))
                            .unwrap();
                    });
                    let result = super::super::upload::complete_abort_upload(access, rep);
                    if fail_checkpoint {
                        assert!(result.is_err());
                    } else {
                        assert!(result.unwrap().0.is_ok());
                    }
                    access.with(|mut access| {
                        assert!(access
                            .as_context_mut()
                            .data_mut()
                            .capabilities
                            .streams
                            .entry(rep, Kind::Upload)
                            .is_err());
                    });
                })
                .await
                .unwrap();
            drop_orders.push(observed.load(Ordering::SeqCst));
        }
        assert_eq!(drop_orders, [1, 1]);
    }

    #[tokio::test]
    async fn abort_upload_busy_and_missing_rows_keep_original_semantics() {
        use crate::host::native_context_reply_tests::{engine, ledger, store};
        use latent_core::BudgetProfile;
        use wasmtime::AsContextMut;

        let engine = engine();
        let budget = ledger(BudgetProfile::Phase1);
        let mut store = store(&engine, &budget, true);
        let mut resources = table();
        let rep = resources.reserve(Kind::Upload).unwrap();
        store.data_mut().capabilities.streams = resources;
        let observed = Arc::new(AtomicUsize::new(0));
        let witness = observed.clone();
        store
            .run_concurrent(async |access| {
                let held = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    let table = &mut store.data_mut().capabilities.streams;
                    table
                        .put(
                            rep,
                            Kind::Upload,
                            Value::Upload(Box::new(Upload(witness.clone()))),
                        )
                        .unwrap();
                    table.take(rep, Kind::Upload, false).unwrap()
                });
                assert!(super::super::upload::complete_abort_upload(access, rep)
                    .unwrap()
                    .0
                    .is_ok());
                assert_eq!(witness.load(Ordering::SeqCst), 0);
                assert!(matches!(
                    super::super::upload::complete_abort_upload(access, rep)
                        .unwrap()
                        .0,
                    Err(super::super::wit::HttpError::InvalidState)
                ));
                drop(held);
                assert_eq!(witness.load(Ordering::SeqCst), 1);
            })
            .await
            .unwrap();
    }

    struct ReentrantFinishBody {
        access: wasmtime::component::Accessor<crate::host::HostState>,
        observed: Arc<AtomicUsize>,
    }
    impl Drop for ReentrantFinishBody {
        fn drop(&mut self) {
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                self.access.with(|_| ());
            }));
            self.observed
                .store(if result.is_ok() { 1 } else { 2 }, Ordering::SeqCst);
        }
    }
    impl HttpBody for ReentrantFinishBody {
        fn head(&self) -> &latent_capabilities::broker::http::HttpResponseHead {
            panic!("the refusal paths must not inspect the response")
        }
        fn read(&mut self, _: usize) -> IoFuture<'_, Result<Option<IoOutputChunk>, Error>> {
            IoFuture::failed(Error::InvalidState)
        }
        fn trailers(&self) -> Result<&latent_capabilities::broker::http::HttpHeaderBlock, Error> {
            Err(Error::InvalidState)
        }
    }

    #[tokio::test]
    async fn finish_completion_refusals_drop_body_after_store_access() {
        use crate::host::native_context_reply_tests::{engine, ledger, store};
        use latent_core::BudgetProfile;

        let mut drop_orders = Vec::new();
        for fail_checkpoint in [true, false] {
            let engine = engine();
            let budget = ledger(BudgetProfile::Phase1);
            let mut store = store(&engine, &budget, true);
            let mut resources = table();
            if fail_checkpoint {
                store.set_fuel(u64::MAX).unwrap();
            } else {
                // Force body publication to refuse without destroying an
                // unrelated live resource or inspecting this response.
                for _ in 0..CAPACITY {
                    resources.reserve(Kind::Upload).unwrap();
                }
            }
            store.data_mut().capabilities.streams = resources;
            let observed = Arc::new(AtomicUsize::new(0));
            let witness = observed.clone();
            store
                .run_concurrent(async |access| {
                    let body = ReentrantFinishBody {
                        access: access.with_getter(|state: &mut crate::host::HostState| state),
                        observed: witness.clone(),
                    };
                    let result = super::super::upload::complete_finish(
                        access,
                        Ok(Box::new(body)),
                        std::time::Instant::now(),
                    );
                    if fail_checkpoint {
                        assert!(result.is_err());
                    } else {
                        assert!(matches!(
                            result.unwrap().0,
                            Err(super::super::wit::HttpError::BudgetExhausted)
                        ));
                    }
                })
                .await
                .unwrap();
            drop_orders.push(observed.load(Ordering::SeqCst));
        }
        assert_eq!(drop_orders, [1, 1]);
    }

    #[tokio::test]
    async fn open_completion_checkpoint_refusal_drops_upload_after_store_access() {
        use crate::host::native_context_reply_tests::{engine, ledger, store};
        use latent_core::BudgetProfile;
        use wasmtime::AsContextMut;

        for fail_checkpoint in [true, false] {
            let engine = engine();
            let budget = ledger(BudgetProfile::Phase1);
            let mut store = store(&engine, &budget, true);
            let mut resources = table();
            let reservation = resources.reserve_guarded(Kind::Upload).unwrap();
            let rep = reservation.rep();
            store.data_mut().capabilities.streams = resources;
            if fail_checkpoint {
                // The accounting watermark has not advanced to this value;
                // the real leading checkpoint therefore refuses it.
                store.set_fuel(u64::MAX).unwrap();
            }
            let observed = Arc::new(AtomicUsize::new(0));
            let witness = observed.clone();
            store
                .run_concurrent(async |access| {
                    let upload = ReentrantOpenUpload {
                        access: access.with_getter(|state: &mut crate::host::HostState| state),
                        observed: witness.clone(),
                    };
                    let pending = Reserved {
                        value: Ok(Box::new(upload) as Box<dyn HttpUpload>),
                        reservation,
                    };
                    let result = super::super::upload::complete_open(
                        access,
                        Ok(pending),
                        std::time::Instant::now(),
                    );
                    if fail_checkpoint {
                        assert!(result.is_err());
                        assert_eq!(witness.load(Ordering::SeqCst), 1);
                        access.with(|mut access| {
                            assert!(access
                                .as_context_mut()
                                .data_mut()
                                .capabilities
                                .streams
                                .entry(rep, Kind::Upload)
                                .is_err());
                        });
                    } else {
                        let resource = result.unwrap().0.unwrap();
                        assert_eq!(resource.rep(), rep);
                        assert_eq!(witness.load(Ordering::SeqCst), 0);
                        let value = access.with(|mut access| {
                            access
                                .as_context_mut()
                                .data_mut()
                                .capabilities
                                .streams
                                .take(rep, Kind::Upload, true)
                                .unwrap()
                        });
                        drop(value);
                        assert_eq!(witness.load(Ordering::SeqCst), 1);
                    }
                })
                .await
                .unwrap();
            assert_eq!(observed.load(Ordering::SeqCst), 1);
        }
    }

    #[tokio::test]
    async fn write_completion_checkpoint_refusal_drops_upload_after_store_access() {
        use crate::host::native_context_reply_tests::{engine, ledger, store};
        use latent_core::BudgetProfile;
        use wasmtime::AsContextMut;

        for fail_checkpoint in [true, false] {
            let engine = engine();
            let budget = ledger(BudgetProfile::Phase1);
            let mut store = store(&engine, &budget, true);
            let mut resources = table();
            let rep = resources.reserve(Kind::Upload).unwrap();
            store.data_mut().capabilities.streams = resources;
            if fail_checkpoint {
                store.set_fuel(u64::MAX).unwrap();
            }
            let observed = Arc::new(AtomicUsize::new(0));
            let witness = observed.clone();
            store
                .run_concurrent(async |access| {
                    let upload = ReentrantOpenUpload {
                        access: access.with_getter(|state: &mut crate::host::HostState| state),
                        observed: witness.clone(),
                    };
                    // Model the real write path: the published upload is taken
                    // without consuming its still-busy original table entry.
                    let upload = access.with(|mut access| {
                        let mut store = access.as_context_mut();
                        let table = &mut store.data_mut().capabilities.streams;
                        table
                            .put(rep, Kind::Upload, Value::Upload(Box::new(upload)))
                            .unwrap();
                        match table.take(rep, Kind::Upload, false).unwrap() {
                            Value::Upload(upload) => upload,
                            _ => panic!("expected upload"),
                        }
                    });
                    let result = super::super::upload::complete_write(
                        access,
                        rep,
                        Ok((upload, Ok(()))),
                        std::time::Instant::now(),
                    );
                    if fail_checkpoint {
                        assert!(result.is_err());
                        assert_eq!(witness.load(Ordering::SeqCst), 1);
                        access.with(|mut access| {
                            let mut store = access.as_context_mut();
                            let entry = store
                                .data_mut()
                                .capabilities
                                .streams
                                .entry(rep, Kind::Upload)
                                .unwrap();
                            assert!(entry.value.is_none());
                        });
                    } else {
                        assert!(result.unwrap().0.is_ok());
                        assert_eq!(witness.load(Ordering::SeqCst), 0);
                        let value = access.with(|mut access| {
                            access
                                .as_context_mut()
                                .data_mut()
                                .capabilities
                                .streams
                                .take(rep, Kind::Upload, true)
                                .unwrap()
                        });
                        drop(value);
                        assert_eq!(witness.load(Ordering::SeqCst), 1);
                    }
                })
                .await
                .unwrap();
            assert_eq!(observed.load(Ordering::SeqCst), 1);
        }
    }

    #[tokio::test]
    async fn write_completion_stale_row_drops_upload_after_store_access() {
        use crate::host::native_context_reply_tests::{engine, ledger, store};
        use latent_core::BudgetProfile;
        use wasmtime::AsContextMut;

        let engine = engine();
        let budget = ledger(BudgetProfile::Phase1);
        let mut store = store(&engine, &budget, true);
        let mut resources = table();
        let rep = resources.reserve(Kind::Upload).unwrap();
        store.data_mut().capabilities.streams = resources;
        let observed = Arc::new(AtomicUsize::new(0));
        let witness = observed.clone();
        store
            .run_concurrent(async |access| {
                let upload = ReentrantOpenUpload {
                    access: access.with_getter(|state: &mut crate::host::HostState| state),
                    observed: witness.clone(),
                };
                let upload = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    let table = &mut store.data_mut().capabilities.streams;
                    table
                        .put(rep, Kind::Upload, Value::Upload(Box::new(upload)))
                        .unwrap();
                    let upload = match table.take(rep, Kind::Upload, false).unwrap() {
                        Value::Upload(upload) => upload,
                        _ => panic!("expected upload"),
                    };
                    // Model a busy row retired before write completion.
                    // Guest-level abort/write reachability is separate.
                    table.remove(rep, Kind::Upload).unwrap();
                    upload
                });
                let result = super::super::upload::complete_write(
                    access,
                    rep,
                    Ok((upload, Ok(()))),
                    std::time::Instant::now(),
                );
                assert!(matches!(
                    result.unwrap().0,
                    Err(super::super::wit::HttpError::InvalidState)
                ));
                assert_eq!(witness.load(Ordering::SeqCst), 1);
                access.with(|mut access| {
                    assert!(access
                        .as_context_mut()
                        .data_mut()
                        .capabilities
                        .streams
                        .entry(rep, Kind::Upload)
                        .is_err());
                });
            })
            .await
            .unwrap();
        assert_eq!(observed.load(Ordering::SeqCst), 1);
    }

    struct PanicAfterUploadTake {
        armed: Arc<std::sync::atomic::AtomicBool>,
        now: std::time::Instant,
    }
    impl latent_core::ActivationClock for PanicAfterUploadTake {
        fn sample(&self) -> latent_core::ClockSample {
            latent_core::ClockSample::new(9000, self.now)
        }
        fn monotonic_now(&self) -> std::time::Instant {
            if self.armed.swap(false, Ordering::SeqCst) {
                panic!("injected post-take clock panic");
            }
            self.now
        }
    }

    #[tokio::test]
    async fn upload_take_clock_panic_drops_original_after_store_access() {
        use crate::host::native_context_reply_tests::{engine, ledger, store};
        use latent_core::BudgetProfile;
        use std::future::Future;
        use wasmtime::component::{InlineConcurrentHost, Resource};
        use wasmtime::AsContextMut;

        let mut drop_orders = Vec::new();
        for finish in [false, true] {
            let engine = engine();
            let budget = ledger(BudgetProfile::Phase1);
            let mut store = store(&engine, &budget, true);
            let armed = Arc::new(std::sync::atomic::AtomicBool::new(false));
            store.data_mut().clock = Arc::new(PanicAfterUploadTake {
                armed: Arc::clone(&armed),
                now: std::time::Instant::now(),
            });
            let mut resources = table();
            let rep = resources.reserve(Kind::Upload).unwrap();
            store.data_mut().capabilities.streams = resources;
            let observed = Arc::new(AtomicUsize::new(0));
            let witness = Arc::clone(&observed);
            store
                .run_concurrent(async |access| {
                    let upload = ReentrantOpenUpload {
                        access: access.with_getter(|state: &mut crate::host::HostState| state),
                        observed: Arc::clone(&witness),
                    };
                    access.with(|mut access| {
                        access
                            .as_context_mut()
                            .data_mut()
                            .capabilities
                            .streams
                            .put(rep, Kind::Upload, Value::Upload(Box::new(upload)))
                            .unwrap();
                    });
                    armed.store(true, Ordering::SeqCst);
                    let waker = std::task::Waker::noop();
                    let mut context = std::task::Context::from_waker(waker);
                    let panicked = if finish {
                        let host = super::super::upload::Finish;
                        let target = Resource::<super::super::wit::Upload>::new_own(rep);
                        let mut future = Box::pin(host.invoke(access, (target,)));
                        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                            future.as_mut().poll(&mut context)
                        }));
                        drop(future);
                        result.is_err()
                    } else {
                        let host = super::super::upload::Write;
                        let target = Resource::<super::super::wit::Upload>::new_borrow(rep);
                        let mut future = Box::pin(host.invoke(access, (target, Vec::new())));
                        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                            future.as_mut().poll(&mut context)
                        }));
                        drop(future);
                        result.is_err()
                    };
                    assert!(panicked, "the post-take clock must have panicked");
                    assert!(!armed.load(Ordering::SeqCst));
                    access.with(|mut access| {
                        let mut store = access.as_context_mut();
                        let row = store
                            .data_mut()
                            .capabilities
                            .streams
                            .entry(rep, Kind::Upload);
                        if finish {
                            assert!(row.is_err());
                        } else {
                            assert!(row.unwrap().value.is_none());
                        }
                    });
                })
                .await
                .unwrap();
            drop_orders.push(observed.load(Ordering::SeqCst));
        }
        assert_eq!(drop_orders, [1, 1]);
    }

    fn table() -> Table {
        Table {
            entries: (0..CAPACITY)
                .map(|_| Entry {
                    state: Shared::new(AtomicU64::new(0), None).unwrap(),
                    kind: Kind::Upload,
                    value: None,
                })
                .collect(),
            memory: None,
            native: None,
        }
    }
    #[test]
    fn foreign_wrong_kind_stale_and_busy_handles_fail_closed() {
        let mut first = table();
        let mut second = table();
        let drops = Arc::new(AtomicUsize::new(0));
        let rep = first.reserve(Kind::Upload).unwrap();
        first
            .put(
                rep,
                Kind::Upload,
                Value::Upload(Box::new(Upload(drops.clone()))),
            )
            .unwrap();
        assert!(second.take(rep, Kind::Upload, false).is_err());
        assert!(first.take(rep, Kind::Body, false).is_err());
        let value = first.take(rep, Kind::Upload, false).unwrap();
        assert!(first.take(rep, Kind::Upload, false).is_err());
        first.remove(rep, Kind::Upload).unwrap();
        assert_eq!(drops.load(Ordering::Acquire), 0);
        let replacement = first.reserve(Kind::Upload).unwrap();
        assert_ne!(replacement, rep);
        assert!(first.put(rep, Kind::Upload, value).is_err());
        assert_eq!(drops.load(Ordering::Acquire), 1);
        assert!(first.take(rep, Kind::Upload, true).is_err());
    }
    #[test]
    fn finite_table_drops_actual_resources_even_with_busy_entries() {
        let mut table = table();
        let drops = Arc::new(AtomicUsize::new(0));
        for _ in 0..CAPACITY {
            let rep = table.reserve(Kind::Upload).unwrap();
            table
                .put(
                    rep,
                    Kind::Upload,
                    Value::Upload(Box::new(Upload(drops.clone()))),
                )
                .unwrap();
        }
        assert!(table.reserve(Kind::Chunk).is_err());
        assert_eq!(table.entries.capacity(), CAPACITY);
        let rep = (table.entries[0].state.load(Ordering::Acquire) >> 2) as u32;
        let active = table.take(rep, Kind::Upload, false).unwrap();
        drop(table);
        assert_eq!(drops.load(Ordering::Acquire), CAPACITY - 1);
        drop(active);
        assert_eq!(drops.load(Ordering::Acquire), CAPACITY);
    }

    #[test]
    fn late_guard_cannot_erase_a_published_borrowed_or_reused_slot() {
        let mut table = table();
        let reservation = table.reserve_guarded(Kind::Upload).unwrap();
        let rep = reservation.rep();
        let drops = Arc::new(AtomicUsize::new(0));
        table
            .put(
                rep,
                Kind::Upload,
                Value::Upload(Box::new(Upload(drops.clone()))),
            )
            .unwrap();
        let borrowed = table.take(rep, Kind::Upload, false).unwrap();
        drop(reservation);
        assert!(table.entry(rep, Kind::Upload).is_ok());
        assert_eq!(drops.load(Ordering::Acquire), 0);
        table.put(rep, Kind::Upload, borrowed).unwrap();
        table.remove(rep, Kind::Upload).unwrap();
        assert_eq!(drops.load(Ordering::Acquire), 1);

        let stale = table.reserve_guarded(Kind::Chunk).unwrap();
        table.remove(stale.rep(), Kind::Chunk).unwrap();
        let replacement = table.reserve_guarded(Kind::Chunk).unwrap();
        drop(stale);
        assert!(table.entry(replacement.rep(), Kind::Chunk).is_ok());
        drop(replacement);
        assert!(table
            .entries
            .iter()
            .all(|entry| entry.state.load(Ordering::Acquire) == 0));
    }

    struct DropWitness {
        live: Arc<AtomicUsize>,
        slot: Shared<AtomicU64>,
        rep: u32,
    }
    impl Drop for DropWitness {
        fn drop(&mut self) {
            // The transport is an earlier field of PendingSocket and has
            // physically dropped; its unpublished reservation is still held.
            assert_eq!(
                self.slot.load(Ordering::Acquire),
                (u64::from(self.rep) << 2) | 1
            );
            self.live.fetch_sub(1, Ordering::AcqRel);
        }
    }
    struct PendingSocket {
        stream: tokio::net::TcpStream,
        _witness: DropWitness,
    }
    async fn pending_transport(mut owned: Reserved<PendingSocket>) {
        use tokio::io::AsyncReadExt;
        let mut byte = [0];
        let _ = owned.value.stream.read(&mut byte).await;
    }

    async fn cancel_real_transport(kind: Kind) {
        use std::{future::Future, task::Context, time::Duration};
        use tokio::{
            io::AsyncReadExt,
            net::{TcpListener, TcpStream},
        };
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let mut table = table();
        let live = Arc::new(AtomicUsize::new(0));
        // More than the fixed capacity demonstrates real reuse after every
        // cancellation, without increasing the table or abandoning a socket.
        for _ in 0..CAPACITY + 1 {
            let client = TcpStream::connect(listener.local_addr().unwrap())
                .await
                .unwrap();
            let (mut peer, _) = listener.accept().await.unwrap();
            let reservation = table.reserve_guarded(kind).unwrap();
            let slot = reservation.state.clone();
            let rep = reservation.rep();
            live.fetch_add(1, Ordering::AcqRel);
            let mut pending = Box::pin(pending_transport(Reserved {
                value: PendingSocket {
                    stream: client,
                    _witness: DropWitness {
                        live: Arc::clone(&live),
                        slot,
                        rep,
                    },
                },
                reservation,
            }));
            let mut context = Context::from_waker(std::task::Waker::noop());
            assert!(pending.as_mut().poll(&mut context).is_pending());
            assert!(table.entry(rep, kind).is_ok());
            assert_eq!(live.load(Ordering::Acquire), 1);
            drop(pending);
            assert_eq!(live.load(Ordering::Acquire), 0);
            assert!(table.entry(rep, kind).is_err());
            let mut byte = [0];
            assert_eq!(
                tokio::time::timeout(Duration::from_secs(2), peer.read(&mut byte))
                    .await
                    .unwrap()
                    .unwrap(),
                0
            );
        }
        assert_eq!(table.entries.capacity(), CAPACITY);
        assert!(table
            .entries
            .iter()
            .all(|entry| entry.state.load(Ordering::Acquire) == 0));
    }

    #[tokio::test]
    async fn cancelled_opening_upload_reaps_actual_transport_then_reuses_reserved_slot() {
        cancel_real_transport(Kind::Upload).await;
    }

    #[tokio::test]
    async fn cancelled_pending_read_reaps_actual_transport_then_reuses_unreturned_chunk_slot() {
        cancel_real_transport(Kind::Chunk).await;
    }

    #[tokio::test]
    async fn native_streaming_http_pending_reservation_outlives_table_without_cross_budget_credit()
    {
        use std::{future::Future, task::Context};
        use tokio::{
            io::AsyncReadExt,
            net::{TcpListener, TcpStream},
        };
        let budget = crate::host::native_table_tests::budget(1024 * 1024);
        let table_bytes = (std::alloc::Layout::array::<Entry>(CAPACITY).unwrap().size()
            + shared::ALLOCATION_BOOKKEEPING) as u64;
        let native = budget.reserve_host_memory(table_bytes).unwrap();
        let mut table = Table {
            entries: Vec::with_capacity(CAPACITY),
            memory: None,
            native: Some(native),
        };
        table.native.as_mut().unwrap().confirm();
        let state_bytes = Shared::<AtomicU64>::allocation_bytes().unwrap();
        for _ in 0..CAPACITY {
            let native = budget.reserve_host_memory(state_bytes).unwrap();
            table.entries.push(Entry {
                state: Shared::new(AtomicU64::new(0), Some(native)).unwrap(),
                kind: Kind::Upload,
                value: None,
            });
        }
        // This control pays actual table/state backing directly. The real sealed
        // session's separate shared broker owner is exercised by integration.
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let client = TcpStream::connect(listener.local_addr().unwrap())
            .await
            .unwrap();
        let (mut peer, _) = listener.accept().await.unwrap();
        let reservation = table.reserve_guarded(Kind::Upload).unwrap();
        let slot = reservation.state.clone();
        let rep = reservation.rep();
        let live = Arc::new(AtomicUsize::new(1));
        let mut pending = Box::pin(pending_transport(Reserved {
            value: PendingSocket {
                stream: client,
                _witness: DropWitness {
                    live: live.clone(),
                    slot,
                    rep,
                },
            },
            reservation,
        }));
        let mut context = Context::from_waker(std::task::Waker::noop());
        assert!(pending.as_mut().poll(&mut context).is_pending());
        assert_eq!(
            budget.host_memory_bytes(),
            table_bytes + CAPACITY as u64 * state_bytes
        );
        drop(table);
        assert_eq!(budget.host_memory_bytes(), state_bytes);
        assert_eq!(budget.outstanding_reservations(), 1);
        assert_eq!(live.load(Ordering::Acquire), 1);
        let other_budget = crate::host::native_table_tests::budget(1024 * 1024);
        let native = other_budget.reserve_host_memory(state_bytes).unwrap();
        let other = Shared::new(AtomicU64::new(62), Some(native)).unwrap();
        drop(pending);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
        assert_eq!(live.load(Ordering::Acquire), 0);
        assert_eq!(other_budget.host_memory_bytes(), state_bytes);
        assert_eq!(other.load(Ordering::Acquire), 62);
        let mut byte = [0];
        assert_eq!(
            tokio::time::timeout(std::time::Duration::from_secs(2), peer.read(&mut byte))
                .await
                .unwrap()
                .unwrap(),
            0
        );
        drop(other);
        assert_eq!(other_budget.host_memory_bytes(), 0);
    }
}
