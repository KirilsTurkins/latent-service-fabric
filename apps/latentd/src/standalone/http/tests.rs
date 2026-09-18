//! Bounded protocol tests and real public-component node regressions.
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod angular;
mod config;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub(super) mod fixture;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod lifecycle;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod network;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod real;
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
mod real_delivery;
