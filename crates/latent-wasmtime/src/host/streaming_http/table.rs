//! Fixed Store-local resources; no number can create or extend authority.
use latent_capabilities::broker::{
    http::HttpError,
    io::IoOutputChunk,
    streaming_http::{HttpBody, HttpUpload, StreamingHttpError as Error},
    CapabilitySession, SessionResourceTableReservation,
};
use std::sync::atomic::{AtomicU32, Ordering};
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
    rep: u32,
    kind: Kind,
    value: Option<Value>,
}
#[derive(Default)]
pub(crate) struct Table {
    entries: Vec<Entry>,
    memory: Option<SessionResourceTableReservation>,
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
            rep: 0,
            kind: Kind::Upload,
            value: None,
        });
        self.entries = entries;
        self.memory = Some(memory);
        Ok(())
    }
    pub(super) fn reserve(&mut self, kind: Kind) -> Result<u32, Error> {
        let slot = self
            .entries
            .iter_mut()
            .find(|e| e.rep == 0)
            .ok_or(HttpError::BudgetExhausted)?;
        let rep = NEXT_REP
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| n.checked_add(1))
            .map_err(|_| HttpError::BudgetExhausted)?;
        slot.rep = rep;
        slot.kind = kind;
        Ok(rep)
    }
    fn entry(&mut self, rep: u32, kind: Kind) -> Result<&mut Entry, Error> {
        self.entries
            .iter_mut()
            .find(|e| e.rep == rep && rep != 0 && e.kind == kind)
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
        Ok(())
    }
    pub(super) fn take(&mut self, rep: u32, kind: Kind, consume: bool) -> Result<Value, Error> {
        let entry = self.entry(rep, kind)?;
        let value = entry.value.take().ok_or(Error::InvalidState)?;
        if consume {
            entry.rep = 0;
        }
        Ok(value)
    }
    pub(super) fn remove(&mut self, rep: u32, kind: Kind) -> Result<(), Error> {
        let entry = self.entry(rep, kind)?;
        entry.value = None;
        entry.rep = 0;
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
    use std::sync::{atomic::AtomicUsize, Arc};
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
                    rep: 0,
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
        let rep = table.entries[0].rep;
        let active = table.take(rep, Kind::Upload, false).unwrap();
        drop(table);
        assert_eq!(drops.load(Ordering::Acquire), CAPACITY - 1);
        drop(active);
        assert_eq!(drops.load(Ordering::Acquire), CAPACITY);
    }
}
