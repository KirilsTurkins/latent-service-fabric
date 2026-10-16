//! Rust source-profile facade over the shared, bounded component transforms.
//!
//! This remains a source experiment: the reexported proofs authenticate only
//! the current Rust context/layout profile. They do not enable engine thread
//! creation or qualify another language's standard runtime.
#![forbid(unsafe_code)]

pub use latent_component_threading::{
    AdmissionReceipt, CONTEXT_STACK_POINTER_OFFSET, ComponentRoutingReceipt, MAX_BYTES,
    MAX_FUNCTIONS, MAX_OPERATORS, Receipt, RootReceipt, ThreadEntryReceipt, transform,
    transform_owned_root_bootstrap, transform_owned_thread_admission, transform_owned_thread_entry,
    verify_component_routing,
};
