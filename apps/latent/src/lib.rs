//! Bounded, single-operation standalone operator client.
mod args;
mod audit_maintenance;
mod client;
mod command;
mod completions;
mod config;
mod error;
mod input;
mod invocation;
mod management;
mod operation;
mod output;
mod package;

pub use command::main_entry;
