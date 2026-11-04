//! Reconstruct the fixed historical corpus only for the explicit diagnostic host.
#[cfg(feature = "rust-thread-diagnostic-legacy")]
#[path = "build-support/legacy_delta.rs"]
mod legacy_delta;

fn main() {
    #[cfg(feature = "rust-thread-diagnostic-legacy")]
    {
        let root =
            std::path::PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").expect("manifest dir"));
        let output = std::path::PathBuf::from(std::env::var_os("OUT_DIR").expect("output dir"));
        println!("cargo:rerun-if-changed=src/rust_catalogue.rs");
        println!("cargo:rerun-if-changed=src/rust_catalogue");
        legacy_delta::prepare(&root, &output)
            .expect("authenticated legacy catalogue reconstruction");
    }
}
