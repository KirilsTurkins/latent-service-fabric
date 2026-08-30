//! Crate-level lint boundary for the explicitly non-production Phase 0 spike.
//!
//! The implementation deliberately keeps the complete executable lifecycle in
//! one auditable module. These narrowly scoped exceptions apply only to this
//! finite spike surface and must not be carried into Phase 1 production APIs.

#![forbid(unsafe_code)]
#![allow(
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

/// Shared internal Phase 0 composition used by the executable and baseline.
#[doc(hidden)]
pub mod phase0_composition;

/// Native collector and build identity shared by Phase 0 evidence binaries.
#[doc(hidden)]
pub mod phase0_collector;

#[path = "lib.rs"]
mod spike;

pub use spike::{
    main_entry, EXIT_DOMAIN_ERROR, EXIT_GUEST_TRAP, EXIT_INTERNAL_SPIKE_FAILURE,
    EXIT_INVALID_COMPONENT_OR_CONFIGURATION, EXIT_SUCCESS, EXIT_TIMEOUT_OR_CANCELLED,
};
