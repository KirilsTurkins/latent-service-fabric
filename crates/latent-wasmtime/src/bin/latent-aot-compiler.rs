//! Standalone, one-job trusted compiler worker; this executable never loads AOT.
#![forbid(unsafe_code)]

fn main() {
    std::process::exit(latent_wasmtime::run_aot_compiler_worker());
}
