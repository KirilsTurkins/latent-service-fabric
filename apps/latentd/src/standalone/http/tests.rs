//! Bounded protocol tests and real public-component node regressions.
mod config;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod fixture;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod lifecycle;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod network;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod real;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod real_delivery;
