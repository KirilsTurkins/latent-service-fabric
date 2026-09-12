//! Real isolated compiler, authenticated persistent bytes, and catalog readiness.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]

#[path = "isolated_aot/support.rs"]
#[allow(dead_code)]
mod compiler;
#[path = "admission/component.rs"]
mod component;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod runtime;

#[path = "native_aot_cache/audit.rs"]
mod audit;
#[path = "native_aot_cache/ownership.rs"]
mod ownership;
#[path = "native_aot_cache/reopen.rs"]
mod reopen;
#[path = "native_aot_cache/support.rs"]
mod support;
#[path = "native_aot_cache/tamper.rs"]
mod tamper;
