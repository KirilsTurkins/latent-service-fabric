//! Generated Rust bindings for authoritative Component Model worlds.
//!
//! Bindings are generated into Cargo `OUT_DIR` from checked-in WIT. This crate
//! contains no engine, store, executor, listener, process, thread, or service
//! allocation; it is the shared code-generation boundary for host and guest code.

#![forbid(unsafe_code)]

#[cfg(not(target_arch = "wasm32"))]
pub mod host {
    /// Host bindings for the aggregate `latent:platform/capsule` runtime world.
    pub mod runtime {
        include!(concat!(env!("OUT_DIR"), "/runtime_host.rs"));
    }

    /// Host bindings for the maintained echo integration fixture.
    pub mod echo {
        include!(concat!(env!("OUT_DIR"), "/echo_host.rs"));
    }
}

#[cfg(target_arch = "wasm32")]
pub mod guest {
    /// Guest bindings for the aggregate `latent:platform/capsule` runtime world.
    pub mod runtime {
        include!(concat!(env!("OUT_DIR"), "/runtime_guest.rs"));
    }
}
