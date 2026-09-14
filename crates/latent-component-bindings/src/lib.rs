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

    /// Versioned Phase 3 provider contracts. Generated types install no provider.
    pub mod phase3 {
        include!(concat!(env!("OUT_DIR"), "/phase3_host.rs"));
    }

    /// Owned HTTP resources under the separate V3 compatibility profile.
    pub mod streaming {
        include!(concat!(env!("OUT_DIR"), "/streaming_host.rs"));
    }

    /// Bounded immutable-blob resources and explicit storage outcomes.
    pub mod blob {
        include!(concat!(env!("OUT_DIR"), "/blob_host.rs"));
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

#[cfg(target_arch = "wasm32")]
pub mod phase3_guest {
    //! Guest bindings for the exact Phase 3 ABI. Provider availability is separate.
    include!(concat!(env!("OUT_DIR"), "/phase3_guest.rs"));
}

#[cfg(target_arch = "wasm32")]
pub mod streaming_guest {
    //! Explicitly owned HTTP streams; no provider or authority is installed here.
    include!(concat!(env!("OUT_DIR"), "/streaming_guest.rs"));
}

#[cfg(target_arch = "wasm32")]
pub mod blob_guest {
    //! Immutable blob handles and owned bounded range results.
    include!(concat!(env!("OUT_DIR"), "/blob_guest.rs"));
}
