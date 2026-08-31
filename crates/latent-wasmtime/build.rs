fn main() {
    let target = std::env::var("TARGET").expect("TARGET must be set by Cargo");
    println!("cargo:rustc-env=LATENT_WASMTIME_HOST_TARGET={target}");
}
