//! Small real-catalog/compiler checks; native output is never loaded or invoked.
#![cfg(all(target_os = "linux", target_arch = "x86_64"))]

#[path = "admission/component.rs"]
mod component;
#[path = "isolated_aot/ownership.rs"]
mod ownership;
#[path = "isolated_aot/source.rs"]
mod source;
#[path = "isolated_aot/support.rs"]
mod support;
