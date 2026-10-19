// SPDX-License-Identifier: MIT OR Apache-2.0
// Bounded textual standard output beneath unchanged Rust std::io/print code.
use crate::io::{self, IoSlice, IoSliceMut};

const MAX_BYTES: usize = 256;
const MAX_VECTORS: usize = 16;

// Intra-core Rust ABI, not a host interface. The fixed compiler-owned bridge
// uses the captured SDK's actual typed generated log bindings. Both sides are
// built by the exact same pinned compiler; no application callback is accepted.
unsafe extern "Rust" {
    fn __lsf_std_log_write_v1(level: u8, message: &str) -> u8;
}

pub struct Stdin;
pub struct Stdout;
pub struct Stderr;
impl Stdin { pub const fn new() -> Self { Self } }
impl Stdout { pub const fn new() -> Self { Self } }
impl Stderr { pub const fn new() -> Self { Self } }

impl io::Read for Stdin {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        if bytes.is_empty() { Ok(0) } else { Err(io::Error::from(io::ErrorKind::Unsupported)) }
    }
    fn read_vectored(&mut self, buffers: &mut [IoSliceMut<'_>]) -> io::Result<usize> {
        if buffers.iter().all(|b| b.is_empty()) { Ok(0) } else { Err(io::Error::from(io::ErrorKind::Unsupported)) }
    }
}
fn write(level: u8, bytes: &[u8]) -> io::Result<usize> {
    if bytes.is_empty() { return Ok(0); }
    if bytes.len() > MAX_BYTES { return Err(io::Error::from(io::ErrorKind::InvalidInput)); }
    let text = crate::str::from_utf8(bytes).map_err(|_| io::Error::from(io::ErrorKind::InvalidData))?;
    // The validated slice remains borrowed until the synchronous typed call
    // returns. The bridge owns/retire its generated variant payload normally.
    let status = unsafe { __lsf_std_log_write_v1(level, text) };
    match status {
        0 => Ok(bytes.len()),
        1 => Err(io::Error::from(io::ErrorKind::InvalidData)),
        2 => Err(io::Error::from(io::ErrorKind::QuotaExceeded)),
        3 => Err(io::Error::from(io::ErrorKind::NotConnected)),
        4 => Err(io::Error::from(io::ErrorKind::WouldBlock)),
        5 => Err(io::Error::from(io::ErrorKind::Other)),
        _ => panic!("unrecognized pinned standard log bridge result"),
    }
}
fn vectored(level: u8, buffers: &[IoSlice<'_>]) -> io::Result<usize> {
    if buffers.len() > MAX_VECTORS { return Err(io::Error::from(io::ErrorKind::InvalidInput)); }
    if buffers.iter().all(|b| b.is_empty()) { return Ok(0); }
    let mut joined = [0u8; MAX_BYTES];
    let mut length = 0usize;
    for buffer in buffers {
        if buffer.len() > MAX_BYTES - length { return Err(io::Error::from(io::ErrorKind::InvalidInput)); }
        joined[length..length + buffer.len()].copy_from_slice(buffer);
        length += buffer.len();
    }
    write(level, &joined[..length])
}
macro_rules! output {
    ($name:ident, $level:expr) => {
        impl io::Write for $name {
            fn write(&mut self, bytes: &[u8]) -> io::Result<usize> { write($level, bytes) }
            fn write_vectored(&mut self, buffers: &[IoSlice<'_>]) -> io::Result<usize> { vectored($level, buffers) }
            // No buffer/worker: successful writes already completed synchronously.
            // This acknowledges current sink acceptance, not remote durability.
            fn flush(&mut self) -> io::Result<()> { Ok(()) }
        }
    };
}
output!(Stdout, 2);
output!(Stderr, 4);

pub const STDIN_BUF_SIZE: usize = 0;
pub fn is_ebadf(_error: &io::Error) -> bool { false }
pub fn panic_output() -> Option<Stderr> { None }
