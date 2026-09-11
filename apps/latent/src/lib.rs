//! Bounded, single-operation standalone operator client.
mod args;
mod client;
mod command;
mod config;
mod error;
mod input;
mod invocation;
mod management;
mod operation;
mod output;

pub use command::main_entry;
