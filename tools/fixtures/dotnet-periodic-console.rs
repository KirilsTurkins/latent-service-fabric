//! Diagnostic-only Console projection; no raw guest text crosses the LOG import.
//! The retained original TimerHandler and its FailFast behavior are unchanged.
use super::{exports::wasi::io, latent::log::log};
use std::cell::{Cell, RefCell};
const MAX_INPUT: usize = 8192;
const MAX_CHUNK: usize = 256;
const MAX_TAIL: usize = 128;
pub const CODES: &[&[u8]] = &[
    b"activation-timer-driver-completion",
    b"activation-timer-driver-epoch-limit",
    b"activation-timer-driver-task-identity",
    b"managed-timer-accepted-owner",
    b"managed-timer-callback-limit",
    b"managed-timer-change-owner",
    b"managed-timer-change-state",
    b"managed-timer-dispatch-owner",
    b"managed-timer-dispatch-state",
    b"managed-timer-missing-record",
    b"managed-timer-mutation-limit",
    b"managed-timer-record-limit",
    b"managed-timer-return-owner",
    b"managed-timer-return-state",
    b"managed-work-admission-refused",
    b"managed-work-captured-parent-retired",
    b"managed-work-closing-state",
    b"managed-work-context-owner",
    b"managed-work-double-settle",
    b"managed-work-duplicate-enqueue",
    b"managed-work-execution-parent",
    b"managed-work-finalization-continuations",
    b"managed-work-finalization-owners",
    b"managed-work-finalization-queue",
    b"managed-work-finalization-state",
    b"managed-work-finalization-timers",
    b"managed-work-independent-admission-closed",
    b"managed-work-installation",
    b"managed-work-missing-record",
    b"managed-work-parent-retired",
    b"managed-work-queue-record-limit",
    b"managed-work-record-limit",
    b"managed-work-required-continuation-limit",
    b"managed-work-transport-parent",
    b"managed-work-unproven-quiescence",
    b"managed-work-unregistered-dequeue",
    b"managed-work-untracked-startup-work",
 ];
struct Decoder { total: usize, tail: Vec<u8>, tail_starts_line: bool, emitted: bool }
impl Default for Decoder {
    fn default() -> Self { Self { total:0,tail:Vec::new(),tail_starts_line:true,emitted:false } }
}
impl Decoder {
    fn feed(&mut self, bytes: &[u8]) -> Result<Option<usize>, ()> {
        self.total=self.total.checked_add(bytes.len()).ok_or(())?;
        if self.total>MAX_INPUT { return Err(()); }
        if self.emitted { return Ok(None); }
        let mut joined=std::mem::take(&mut self.tail); joined.extend_from_slice(bytes);
        let found=(0..=CODES.len()).filter_map(|code| {
            let marker=format!("LSF-PERIODIC-CODE:{code:04}\n");
            joined.windows(marker.len()).enumerate().find_map(|(at, bytes)|
                (bytes==marker.as_bytes() && (if at==0 { self.tail_starts_line } else { joined[at-1]==b'\n' })).then_some((at,code)))
        }).min();
        if let Some((_,code))=found { self.emitted=true; return Ok(Some(code+1)); }
        let retain=joined.len().saturating_sub(MAX_TAIL);
        if retain>0 { self.tail_starts_line=joined[retain-1]==b'\n'; }
        self.tail.extend_from_slice(&joined[retain..]);
        Ok(None)
    }
}
pub struct Stream { permit: Cell<usize>, decoder: RefCell<Decoder>, failed: Cell<bool> }
pub fn stdout() -> Option<Stream> { None }
pub fn stderr() -> Option<Stream> {
    Some(Stream { permit: Cell::new(0),decoder: RefCell::new(Decoder::default()),failed: Cell::new(false) })
}
impl Stream {
    fn error(&self) -> io::streams::StreamError {
        self.failed.set(true);
        io::streams::StreamError::LastOperationFailed(io::error::Error::new(super::ClosedError {
            _slot: super::quota::Slot::new(),
        }))
    }
    pub fn check_write(&self) -> Result<u64,io::streams::StreamError> {
        if self.failed.get() { return Err(self.error()); }
        self.permit.set(MAX_CHUNK); Ok(MAX_CHUNK as u64)
    }
    pub fn write(&self, bytes: Vec<u8>) -> Result<(),io::streams::StreamError> {
        if self.failed.get() || bytes.len()>self.permit.replace(0) { return Err(self.error()); }
        let code=self.decoder.borrow_mut().feed(&bytes).map_err(|_|self.error())?;
        if let Some(code)=code {
            // One unique ASCII message length; exact original host encodedLogBytes
            // is the public diagnostic channel. Original exception text is dropped.
            let message="p".repeat(code);
            if !matches!(log::write(log::Level::Error,&message,&[]),Ok(true)) { return Err(self.error()); }
        }
        Ok(())
    }
    pub fn flush(&self) -> Result<(),io::streams::StreamError> {
        if self.failed.get() { Err(self.error()) } else { Ok(()) }
    }
}
