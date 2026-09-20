//! An explicitly approved test executable that deliberately violates its output
//! contract. It tests the parent supervisor, not the production child sandbox.

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "aot_supervisor/availability.rs"]
mod availability;
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
#[path = "aot_supervisor/probe.rs"]
mod probe;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[path = "generic_backend/support.rs"]
#[allow(dead_code, reason = "reuse maintained bounded invocation inputs")]
mod runtime;
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
    let arguments: Vec<_> = std::env::args().skip(1).collect();
    if arguments == ["--list"] {
        for name in driver::CASE_NAMES {
            println!("{name}: test");
        }
        println!("{} tests, 0 benchmarks", driver::CASE_NAMES.len());
        return;
    }
    for argument in arguments {
        assert!(
            matches!(argument.as_str(), "--nocapture" | "--test-threads=1"),
            "unsupported supervisor selection: {argument}"
        );
    }
    driver::run();
}

#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
fn main() {
    eprintln!("NOT RUN: isolated AOT supervisor fixtures require Linux x86_64");
    if std::env::var_os("LSF_AOT_REQUIRE_LINUX").is_some() {
        std::process::exit(1);
    }
}
