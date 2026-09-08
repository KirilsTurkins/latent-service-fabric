//! Standalone node composition and the isolated legacy Phase 0 tools.
//!
//! Legacy lint exceptions apply only to the three Phase 0 module boundaries.

#![forbid(unsafe_code)]

/// Shared internal Phase 0 composition used by the executable and baseline.
#[doc(hidden)]
#[allow(
    clippy::assigning_clones,
    clippy::format_collect,
    clippy::large_enum_variant,
    clippy::manual_let_else,
    clippy::map_unwrap_or,
    clippy::needless_pass_by_value,
    clippy::single_match_else,
    clippy::too_many_arguments,
    clippy::too_many_lines
)]
pub mod phase0_composition;

/// Native collector and build identity shared by Phase 0 evidence binaries.
#[doc(hidden)]
#[allow(
    clippy::assigning_clones,
    clippy::format_collect,
    clippy::large_enum_variant,
    clippy::manual_let_else,
    clippy::map_unwrap_or,
    clippy::needless_pass_by_value,
    clippy::single_match_else,
    clippy::too_many_arguments,
    clippy::too_many_lines
)]
pub mod phase0_collector;

#[allow(
    clippy::assigning_clones,
    clippy::format_collect,
    clippy::large_enum_variant,
    clippy::manual_let_else,
    clippy::map_unwrap_or,
    clippy::needless_pass_by_value,
    clippy::single_match_else,
    clippy::too_many_arguments,
    clippy::too_many_lines
)]
#[path = "lib.rs"]
mod spike;

pub use spike::{
    EXIT_DOMAIN_ERROR, EXIT_GUEST_TRAP, EXIT_INTERNAL_SPIKE_FAILURE,
    EXIT_INVALID_COMPONENT_OR_CONFIGURATION, EXIT_SUCCESS, EXIT_TIMEOUT_OR_CANCELLED,
};

mod command;
pub use command::main_entry;

pub mod config;
pub mod standalone;
