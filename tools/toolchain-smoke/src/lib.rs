//! Compile-only probes for the dependencies selected by the Phase 0 baseline.
//!
//! This crate deliberately does not construct an engine, store, executor, listener,
//! thread, process, or service-owned runtime resource.

#[cfg(not(target_arch = "wasm32"))]
pub mod host {
    #[derive(Debug, Clone, PartialEq, Eq, clap::Parser, serde::Serialize, serde::Deserialize)]
    #[command(name = "latent-toolchain-smoke")]
    pub struct ProbeConfiguration {
        #[arg(long, default_value = "phase-0")]
        pub profile: String,
    }

    pub mod bindings {
        include!(concat!(env!("OUT_DIR"), "/host_bindings.rs"));
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
}

#[cfg(target_arch = "wasm32")]
pub mod guest_bindings {
    include!(concat!(env!("OUT_DIR"), "/guest_bindings.rs"));
}
