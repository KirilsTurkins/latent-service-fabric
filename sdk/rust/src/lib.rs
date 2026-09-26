//! Typed Rust SDK for LSF clients with an optional bounded RPC transport.

#![forbid(unsafe_code)]

pub mod management;

#[cfg(feature = "transport")]
pub mod network;
