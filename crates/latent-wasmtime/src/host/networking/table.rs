//! Fixed Store-local generations. Only the installed provider creates values;
//! a guessed/stale/foreign representation cannot insert or recover authority.
use latent_capabilities::broker::{
    io::IoOutputChunk,
    network::{OutboundStream, StreamError, StreamErrorCode},
    CapabilitySession, SessionResourceTableReservation,
};
use latent_core::budget::HostMemoryReservation;
use std::sync::atomic::{AtomicU32, Ordering};
const CAPACITY: usize = 8;
static NEXT_REP: AtomicU32 = AtomicU32::new(1);
#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Kind {
    Connection,
    Chunk,
}
pub(super) enum Value {
    Connection(Box<dyn OutboundStream>),
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
    native: Option<HostMemoryReservation>,
}
fn invalid() -> StreamError {
    StreamError::new(StreamErrorCode::InvalidState)
}
impl Table {
    pub(super) fn initialize(&mut self, session: &CapabilitySession) -> Result<(), StreamError> {
        if !self.entries.is_empty() {
            return Ok(());
        }
        let bytes = CAPACITY * std::mem::size_of::<Entry>() + 4096;
        let memory = session.reserve_resource_table(bytes)?;
        let mut native = session.reserve_host_memory(bytes as u64)?;
        let mut entries = Vec::with_capacity(CAPACITY);
        if entries.capacity() != CAPACITY {
            return Err(StreamError::new(StreamErrorCode::Exhausted));
        }
        entries.resize_with(CAPACITY, || Entry {
            rep: 0,
            kind: Kind::Connection,
            value: None,
        });
        native.confirm();
        self.entries = entries;
        self.memory = Some(memory);
        self.native = Some(native);
        Ok(())
    }
    pub(super) fn reserve(&mut self, kind: Kind) -> Result<u32, StreamError> {
        let entry = self
            .entries
            .iter_mut()
            .find(|e| e.rep == 0)
            .ok_or_else(|| StreamError::new(StreamErrorCode::Exhausted))?;
        let rep = NEXT_REP
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                value.checked_add(1)
            })
            .map_err(|_| StreamError::new(StreamErrorCode::Exhausted))?;
        entry.rep = rep;
        entry.kind = kind;
        Ok(rep)
    }
    fn entry(&mut self, rep: u32, kind: Kind) -> Result<&mut Entry, StreamError> {
        self.entries
            .iter_mut()
            .find(|e| rep != 0 && e.rep == rep && e.kind == kind)
            .ok_or_else(invalid)
    }
    pub(super) fn put(&mut self, rep: u32, kind: Kind, value: Value) -> Result<(), StreamError> {
        if !matches!(
            (&value, kind),
            (Value::Connection(_), Kind::Connection) | (Value::Chunk { .. }, Kind::Chunk)
        ) {
            return Err(invalid());
        }
        let entry = self.entry(rep, kind)?;
        if entry.value.is_some() {
            return Err(invalid());
        }
        entry.value = Some(value);
        Ok(())
    }
    pub(super) fn connection(&self, rep: u32) -> Result<&dyn OutboundStream, StreamError> {
        let entry = self
            .entries
            .iter()
            .find(|entry| rep != 0 && entry.rep == rep && entry.kind == Kind::Connection)
            .ok_or_else(invalid)?;
        match &entry.value {
            Some(Value::Connection(connection)) => Ok(connection.as_ref()),
            _ => Err(invalid()),
        }
    }
    pub(super) fn take_connection(
        &mut self,
        rep: u32,
    ) -> Result<Box<dyn OutboundStream>, StreamError> {
        let entry = self.entry(rep, Kind::Connection)?;
        let Some(Value::Connection(value)) = entry.value.take() else {
            return Err(invalid());
        };
        entry.rep = 0;
        Ok(value)
    }
    pub(super) fn remove(&mut self, rep: u32, kind: Kind) -> Result<(), StreamError> {
        let entry = self.entry(rep, kind)?;
        entry.value = None;
        entry.rep = 0;
        Ok(())
    }
    pub(super) fn chunk_bytes(&mut self, rep: u32) -> Result<Vec<u8>, StreamError> {
        let Some(Value::Chunk { value, delivered }) = &mut self.entry(rep, Kind::Chunk)?.value
        else {
            return Err(invalid());
        };
        if *delivered {
            return Err(invalid());
        }
        let bytes = value.copy_bytes()?;
        *delivered = true;
        Ok(bytes)
    }
}
