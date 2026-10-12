//! Fixed Store-local resources; no number can create or extend authority.
use latent_capabilities::broker::{
    CapabilitySession, SessionResourceTableReservation,
    http::HttpError,
    io::IoOutputChunk,
    streaming_http::{HttpBody, HttpUpload, StreamingHttpError as Error},
};
use std::sync::{
    Arc,
    atomic::{AtomicU32, AtomicU64, Ordering},
};
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
    state: Arc<AtomicU64>,
    kind: Kind,
    value: Option<Value>,
}
#[derive(Default)]
pub(crate) struct Table {
    entries: Vec<Entry>,
    memory: Option<Arc<SessionResourceTableReservation>>,
}

pub(super) struct Reservation {
    state: Arc<AtomicU64>,
    rep: u32,
    // Metadata that survives Store destruction remains charged until this
    // affine guard actually disappears; the fixed table's slack covers it.
    _memory: Option<Arc<SessionResourceTableReservation>>,
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
        let mut entries = Vec::with_capacity(CAPACITY);
        if entries.capacity() != CAPACITY {
            return Err(HttpError::BudgetExhausted.into());
        }
        entries.resize_with(CAPACITY, || Entry {
            state: Arc::new(AtomicU64::new(0)),
            kind: Kind::Upload,
            value: None,
        });
        self.entries = entries;
        self.memory = Some(Arc::new(memory));
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
        let state = Arc::clone(&entry.state);
        Ok(Reservation {
            state,
            rep,
            _memory: self.memory.as_ref().map(Arc::clone),
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
    pub(super) fn chunk_bytes(&mut self, rep: u32) -> Result<Vec<u8>, Error> {
        let Some(Value::Chunk { value, delivered }) = &mut self.entry(rep, Kind::Chunk)?.value
        else {
            return Err(Error::InvalidState);
        };
        if *delivered {
            return Err(Error::InvalidState);
        }
        *delivered = true;
        Ok(value.bytes().to_vec())
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
    use std::sync::atomic::AtomicUsize;
    struct Upload(Arc<AtomicUsize>);
    impl Drop for Upload {
        fn drop(&mut self) {
            self.0.fetch_add(1, Ordering::AcqRel);
        }
    }
    impl HttpUpload for Upload {
        fn write(&mut self, _: Vec<u8>) -> latent_core::BoxFuture<'_, Result<(), Error>> {
            Box::pin(async { Err(Error::InvalidState) })
        }
        fn finish(
            self: Box<Self>,
        ) -> latent_core::BoxFuture<'static, Result<Box<dyn HttpBody>, Error>> {
            Box::pin(async { Err(Error::InvalidState) })
        }
    }
    fn table() -> Table {
        Table {
            entries: (0..CAPACITY)
                .map(|_| Entry {
                    state: Arc::new(AtomicU64::new(0)),
                    kind: Kind::Upload,
                    value: None,
                })
                .collect(),
            memory: None,
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
        assert!(
            table
                .entries
                .iter()
                .all(|entry| entry.state.load(Ordering::Acquire) == 0)
        );
    }

    struct DropWitness {
        live: Arc<AtomicUsize>,
        slot: Arc<AtomicU64>,
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
            let slot = Arc::clone(&reservation.state);
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
        assert!(
            table
                .entries
                .iter()
                .all(|entry| entry.state.load(Ordering::Acquire) == 0)
        );
    }

    #[tokio::test]
    async fn cancelled_opening_upload_reaps_actual_transport_then_reuses_reserved_slot() {
        cancel_real_transport(Kind::Upload).await;
    }

    #[tokio::test]
    async fn cancelled_pending_read_reaps_actual_transport_then_reuses_unreturned_chunk_slot() {
        cancel_real_transport(Kind::Chunk).await;
    }
}
