//! Standalone node composition.

#![forbid(unsafe_code)]

mod command;
pub use command::main_entry;

pub mod config;
pub mod standalone;
