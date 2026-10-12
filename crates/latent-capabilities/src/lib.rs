//! Sealed activation authority, bounded providers and invocation-scoped ownership.

#![forbid(unsafe_code)]

/// Sealed capability sessions and their bounded provider implementations.
pub mod broker;
/// Current-policy namespace authority; descriptive IDs never construct a grant.
pub mod namespace;
