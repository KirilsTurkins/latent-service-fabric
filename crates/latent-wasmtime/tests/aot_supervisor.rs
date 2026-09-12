//! An explicitly approved test executable that deliberately violates its output
//! contract. It tests the parent supervisor, not the production child sandbox.

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "admission/component.rs"]
mod component;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "aot_supervisor/driver.rs"]
mod driver;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "aot_supervisor/inherited.rs"]
mod inherited;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "isolated_aot/support.rs"]
#[allow(
    dead_code,
    reason = "shared real-catalog helpers serve two separate test executables"
)]
mod support;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "aot_supervisor/worker.rs"]
mod worker;

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn main() {
    if std::env::args().nth(1).as_deref() == Some("--worker-v1") {
        std::process::exit(worker::run());
    }
    driver::run();
}

#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
fn main() {
    eprintln!("isolated AOT supervisor fixtures require Linux x86_64");
}
