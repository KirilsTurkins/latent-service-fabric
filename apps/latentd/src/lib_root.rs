//! Standalone node composition.

#![forbid(unsafe_code)]

// The shared signed-package fixture also exports policy-owned test material.
#[cfg(all(test, target_os = "linux", target_arch = "x86_64"))]
use latent_policy::supply_chain;

mod command;
pub use command::main_entry;

pub mod config;
pub mod standalone;
