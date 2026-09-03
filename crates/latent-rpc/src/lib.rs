//! Build-generated Protobuf messages and Tonic client/server definitions.
//!
//! The checked-in `.proto` files under `api/proto` are authoritative. This crate
//! owns deterministic Rust generation into Cargo `OUT_DIR`; it deliberately
//! contains no service implementation, listener, process, thread, or runtime.

#![forbid(unsafe_code)]

/// Control-plane APIs from the `latent.control.v1` Protobuf package.
pub mod control {
    pub mod v1 {
        tonic::include_proto!("latent.control.v1");
    }
}

/// Generic invocation APIs from the `latent.invocation.v1` Protobuf package.
pub mod invocation {
    pub mod v1 {
        tonic::include_proto!("latent.invocation.v1");
    }
}

/// Descriptor set generated from the same exhaustive input manifest as the Rust types.
pub const FILE_DESCRIPTOR_SET: &[u8] = tonic::include_file_descriptor_set!("latent_descriptor");
