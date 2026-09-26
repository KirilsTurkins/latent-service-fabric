//! Store-local lookup data: exact kind, nonreused generation and actual owners.
use latent_capabilities::broker::{
    blob::{BlobChunk, BlobError as Error, BlobReader, BlobWriter},
    CapabilitySession, SessionResourceTableReservation,
};
use std::sync::atomic::{AtomicU32, Ordering};
const CAPACITY: usize = 64;
static NEXT: AtomicU32 = AtomicU32::new(1);
#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Kind {
    Writer,
    Reader,
    Chunk,
}
#[expect(
    clippy::large_enum_variant,
    reason = "the fixed table prepays every complete entry, retaining chunk owners without another heap allocation"
)]
pub(super) enum Value {
    Writer(Box<dyn BlobWriter>),
    Reader(Box<dyn BlobReader>),
    Chunk { value: BlobChunk, delivered: bool },
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
            return Err(Error::BudgetExhausted);
        }
        entries.resize_with(CAPACITY, || Entry {
            rep: 0,
            kind: Kind::Writer,
            value: None,
        });
        self.entries = entries;
        self.memory = Some(memory);
        Ok(())
    }
    pub(super) fn reserve(&mut self, kind: Kind) -> Result<u32, Error> {
        let entry = self
            .entries
            .iter_mut()
            .find(|e| e.rep == 0)
            .ok_or(Error::BudgetExhausted)?;
        let rep = NEXT
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| n.checked_add(1))
            .map_err(|_| Error::BudgetExhausted)?;
        entry.rep = rep;
        entry.kind = kind;
        Ok(rep)
    }
    fn entry(&mut self, rep: u64, kind: Kind) -> Result<&mut Entry, Error> {
        self.entries
            .iter_mut()
            .find(|e| rep != 0 && u64::from(e.rep) == rep && e.kind == kind)
            .ok_or(Error::InvalidState)
    }
    pub(super) fn put(&mut self, rep: u64, kind: Kind, value: Value) -> Result<(), Error> {
        if !matches!(
            (&value, kind),
            (Value::Writer(_), Kind::Writer)
                | (Value::Reader(_), Kind::Reader)
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
    pub(super) fn take(&mut self, rep: u64, kind: Kind, consume: bool) -> Result<Value, Error> {
        let entry = self.entry(rep, kind)?;
        let value = entry.value.take().ok_or(Error::InvalidState)?;
        if consume {
            entry.rep = 0;
        }
        Ok(value)
    }
    pub(super) fn remove(&mut self, rep: u64, kind: Kind) -> Result<(), Error> {
        let entry = self.entry(rep, kind)?;
        entry.value = None;
        entry.rep = 0;
        Ok(())
    }
    pub(super) fn close(&mut self, rep: u64) -> Result<bool, Error> {
        let entry = self
            .entries
            .iter_mut()
            .find(|e| rep != 0 && u64::from(e.rep) == rep && e.kind != Kind::Chunk)
            .ok_or(Error::InvalidState)?;
        entry.value = None;
        entry.rep = 0;
        Ok(true)
    }
    pub(super) fn bytes(&mut self, rep: u32) -> Result<Vec<u8>, Error> {
        let Some(Value::Chunk { value, delivered }) =
            &mut self.entry(u64::from(rep), Kind::Chunk)?.value
        else {
            return Err(Error::InvalidState);
        };
        if *delivered {
            return Err(Error::InvalidState);
        }
        *delivered = true;
        Ok(value.bytes().to_vec())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_capabilities::broker::blob::{BlobFuture, BlobSeal};
    use std::sync::{atomic::AtomicUsize, Arc};
    struct Writer(Arc<AtomicUsize>);
    impl Drop for Writer {
        fn drop(&mut self) {
            self.0.fetch_add(1, Ordering::AcqRel);
        }
    }
    impl BlobWriter for Writer {
        fn write(&mut self, _: u64, _: Vec<u8>) -> Result<BlobFuture<'_, u64>, Error> {
            Err(Error::InvalidState)
        }
        fn seal(self: Box<Self>) -> Result<BlobFuture<'static, BlobSeal>, Error> {
            Err(Error::InvalidState)
        }
    }
    fn table() -> Table {
        Table {
            entries: (0..CAPACITY)
                .map(|_| Entry {
                    rep: 0,
                    kind: Kind::Writer,
                    value: None,
                })
                .collect(),
            memory: None,
        }
    }
    #[test]
    fn forged_foreign_wrong_kind_busy_and_stale_numbers_never_create_authority() {
        let mut first = table();
        let mut foreign = table();
        let drops = Arc::new(AtomicUsize::new(0));
        let rep = u64::from(first.reserve(Kind::Writer).unwrap());
        first
            .put(
                rep,
                Kind::Writer,
                Value::Writer(Box::new(Writer(drops.clone()))),
            )
            .unwrap();
        for invalid in [0, u64::MAX, rep + (1 << 32)] {
            assert!(first.take(invalid, Kind::Writer, false).is_err());
        }
        assert!(foreign.take(rep, Kind::Writer, false).is_err());
        assert!(first.take(rep, Kind::Reader, false).is_err());
        let active = first.take(rep, Kind::Writer, false).unwrap();
        assert!(first.take(rep, Kind::Writer, false).is_err());
        first.close(rep).unwrap();
        let replacement = first.reserve(Kind::Writer).unwrap();
        assert_ne!(u64::from(replacement), rep);
        assert_eq!(drops.load(Ordering::Acquire), 0);
        assert!(first.put(rep, Kind::Writer, active).is_err());
        assert_eq!(drops.load(Ordering::Acquire), 1);
    }
    #[test]
    fn finite_capacity_and_store_drop_retain_busy_physical_owners() {
        let mut table = table();
        let drops = Arc::new(AtomicUsize::new(0));
        for _ in 0..CAPACITY {
            let rep = table.reserve(Kind::Writer).unwrap();
            table
                .put(
                    u64::from(rep),
                    Kind::Writer,
                    Value::Writer(Box::new(Writer(drops.clone()))),
                )
                .unwrap();
        }
        assert!(table.reserve(Kind::Chunk).is_err());
        let rep = u64::from(table.entries[0].rep);
        let active = table.take(rep, Kind::Writer, false).unwrap();
        drop(table);
        assert_eq!(drops.load(Ordering::Acquire), CAPACITY - 1);
        drop(active);
        assert_eq!(drops.load(Ordering::Acquire), CAPACITY);
    }
}
