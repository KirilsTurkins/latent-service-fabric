//! Generated bindings are the only unsafe-code allowance in this guest adapter.
#![allow(
    clippy::same_length_and_capacity,
    reason = "wit-bindgen consumes allocations transferred by the canonical ABI"
)]
#[cfg(not(feature = "backend-http"))]
wit_bindgen::generate!({
    path: ["../../wit/platform/context", "../../wit/platform/http-v2", "../../wit/platform/web", "wit"],
    world: "latent:angular-renderer-internal/adapter@0.1.0",
    generate_all,
});

#[cfg(feature = "backend-http")]
wit_bindgen::generate!({
    path: ["../../wit/platform/context", "../../wit/platform/http-v2", "../../wit/platform/web", "wit"],
    world: "latent:angular-renderer-internal/adapter-http@0.1.0",
    generate_all,
});

use super::Adapter;
export!(Adapter);
