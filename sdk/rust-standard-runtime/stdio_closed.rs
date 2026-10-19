// SPDX-License-Identifier: MIT OR Apache-2.0
// Explicit unsupported stdio for the maintained wasm32-unknown-unknown PAL.
use crate::io::{self, IoSlice, IoSliceMut};

pub struct Stdin;
pub struct Stdout;
pub struct Stderr;

impl Stdin { pub const fn new() -> Self { Self } }
impl Stdout { pub const fn new() -> Self { Self } }
impl Stderr { pub const fn new() -> Self { Self } }

fn unsupported<T>() -> io::Result<T> {
    Err(io::Error::from(io::ErrorKind::Unsupported))
}
impl io::Read for Stdin {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        if bytes.is_empty() { Ok(0) } else { unsupported() }
    }
    fn read_vectored(&mut self, buffers: &mut [IoSliceMut<'_>]) -> io::Result<usize> {
        if buffers.iter().all(|b| b.is_empty()) { Ok(0) } else { unsupported() }
    }
}
macro_rules! output {
    ($name:ident) => {
        impl io::Write for $name {
            fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
                if bytes.is_empty() { Ok(0) } else { unsupported() }
            }
            fn write_vectored(&mut self, buffers: &[IoSlice<'_>]) -> io::Result<usize> {
                if buffers.iter().all(|b| b.is_empty()) { Ok(0) } else { unsupported() }
            }
            fn flush(&mut self) -> io::Result<()> { unsupported() }
        }
    };
}
output!(Stdout);
output!(Stderr);

pub const STDIN_BUF_SIZE: usize = 0;
// The outer std wrapper must not turn our explicit error into a fake write/EOF.
pub fn is_ebadf(_error: &io::Error) -> bool { false }
// A failed print must not retry through an implicit panic logger.
pub fn panic_output() -> Option<Stdout> { None }
