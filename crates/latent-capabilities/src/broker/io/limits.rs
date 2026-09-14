use super::{capacity, invalid, PlatformError};
use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::Duration,
};

#[derive(Debug, Clone, Copy)]
pub struct IoLimits {
    pub maximum_calls: usize,
    pub maximum_running_calls: usize,
    pub maximum_queued_calls: usize,
    pub maximum_staged_bytes: usize,
    pub maximum_result_bytes: usize,
    pub maximum_buffers: usize,
    pub maximum_streams: usize,
    pub maximum_metadata_bytes: usize,
    pub maximum_chunk_bytes: usize,
    pub maximum_stream_chunks: usize,
    pub maximum_stream_bytes: u64,
    pub maximum_queue_wait: Duration,
}
impl Default for IoLimits {
    fn default() -> Self {
        Self {
            maximum_calls: 256,
            maximum_running_calls: 64,
            maximum_queued_calls: 128,
            maximum_staged_bytes: 8 * 1024 * 1024,
            maximum_result_bytes: 8 * 1024 * 1024,
            maximum_buffers: 1024,
            maximum_streams: 128,
            maximum_metadata_bytes: 4 * 1024 * 1024,
            maximum_chunk_bytes: 64 * 1024,
            maximum_stream_chunks: 8,
            maximum_stream_bytes: 64 * 1024 * 1024,
            maximum_queue_wait: Duration::from_secs(5),
        }
    }
}
impl IoLimits {
    pub fn validate(self) -> Result<(), PlatformError> {
        for (value, maximum) in [
            (self.maximum_calls, 4096),
            (self.maximum_running_calls, 4096),
            (self.maximum_queued_calls, 4096),
            (self.maximum_staged_bytes, 256 * 1024 * 1024),
            (self.maximum_result_bytes, 256 * 1024 * 1024),
            (self.maximum_buffers, 65536),
            (self.maximum_streams, 4096),
            (self.maximum_metadata_bytes, 64 * 1024 * 1024),
            (self.maximum_chunk_bytes, 1024 * 1024),
            (self.maximum_stream_chunks, 128),
        ] {
            if value == 0 || value > maximum {
                return Err(invalid());
            }
        }
        if self.maximum_running_calls > self.maximum_calls
            || self.maximum_queued_calls > self.maximum_calls
            || self.maximum_chunk_bytes > self.maximum_staged_bytes.min(self.maximum_result_bytes)
            || self.maximum_stream_bytes == 0
            || self.maximum_stream_bytes > 1024 * 1024 * 1024
            || self.maximum_queue_wait.is_zero()
            || self.maximum_queue_wait > Duration::from_mins(1)
        {
            return Err(invalid());
        }
        Ok(())
    }
}
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct IoSnapshot {
    pub calls: usize,
    pub occupied_running_slots: usize,
    pub queued_calls: usize,
    pub staged_bytes: usize,
    pub result_bytes: usize,
    pub buffers: usize,
    pub streams: usize,
    pub metadata_bytes: usize,
}
#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Kind {
    Call,
    Queued,
    Staged,
    Result,
    Buffer,
    Stream,
    Metadata,
}
pub(super) struct Counters {
    values: [AtomicUsize; 7],
    maxima: [usize; 7],
}
impl Counters {
    pub fn new(l: IoLimits) -> Self {
        Self {
            values: std::array::from_fn(|_| AtomicUsize::new(0)),
            maxima: [
                l.maximum_calls,
                l.maximum_queued_calls,
                l.maximum_staged_bytes,
                l.maximum_result_bytes,
                l.maximum_buffers,
                l.maximum_streams,
                l.maximum_metadata_bytes,
            ],
        }
    }
    pub fn acquire(self: &Arc<Self>, kind: Kind, amount: usize) -> Result<Charge, PlatformError> {
        let index = kind as usize;
        let mut previous = self.values[index].load(Ordering::Acquire);
        for _ in 0..16 {
            let next = previous
                .checked_add(amount)
                .filter(|n| *n <= self.maxima[index])
                .ok_or_else(capacity)?;
            match self.values[index].compare_exchange_weak(
                previous,
                next,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => {
                    return Ok(Charge {
                        counters: Arc::clone(self),
                        kind,
                        amount,
                    })
                }
                Err(current) => previous = current,
            }
        }
        Err(super::super::busy())
    }
    pub fn snapshot(&self) -> IoSnapshot {
        let v = self.values.each_ref().map(|v| v.load(Ordering::Acquire));
        IoSnapshot {
            calls: v[0],
            occupied_running_slots: 0,
            queued_calls: v[1],
            staged_bytes: v[2],
            result_bytes: v[3],
            buffers: v[4],
            streams: v[5],
            metadata_bytes: v[6],
        }
    }
}
pub(super) struct Charge {
    counters: Arc<Counters>,
    pub kind: Kind,
    amount: usize,
}
impl Drop for Charge {
    fn drop(&mut self) {
        self.counters.values[self.kind as usize].fetch_sub(self.amount, Ordering::AcqRel);
    }
}
