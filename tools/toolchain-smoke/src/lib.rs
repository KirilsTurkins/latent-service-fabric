//! Compile-only probes for the dependencies selected by the build foundation.
//!
//! This crate deliberately does not construct an engine, store, executor, listener,
//! thread, process, or service-owned runtime resource.

#[cfg(not(target_arch = "wasm32"))]
pub mod host {
    #[derive(Debug, Clone, PartialEq, Eq, clap::Parser, serde::Serialize, serde::Deserialize)]
    #[command(name = "latent-toolchain-smoke")]
    pub struct ProbeConfiguration {
        #[arg(long, default_value = "phase-1-foundation")]
        pub profile: String,
    }

    pub mod bindings {
        pub use latent_component_bindings::host::runtime::*;
    }

    pub fn digest(bytes: &[u8]) -> [u8; 32] {
        *blake3::hash(bytes).as_bytes()
    }

    pub fn encode_json(configuration: &ProbeConfiguration) -> serde_json::Result<Vec<u8>> {
        serde_json::to_vec(configuration)
    }

    pub fn encode_toml(configuration: &ProbeConfiguration) -> Result<String, toml::ser::Error> {
        toml::to_string(configuration)
    }

    pub fn temporary_directory() -> std::io::Result<tempfile::TempDir> {
        tempfile::tempdir()
    }

    pub async fn yield_once() {
        tokio::task::yield_now().await;
    }

    pub fn enable_component_model(config: &mut wasmtime::Config) {
        config.wasm_component_model(true);
        config.wasm_component_model_async(true);
    }

    pub fn tracing_dispatch() -> tracing::Dispatch {
        tracing::Dispatch::new(tracing_subscriber::registry())
    }
}

#[cfg(target_arch = "wasm32")]
pub mod guest_bindings {
    pub use latent_component_bindings::guest::runtime::*;
}
