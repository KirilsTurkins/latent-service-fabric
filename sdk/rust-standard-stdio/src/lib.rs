//! Fixed intra-core bridge; no host interface, application callback or authority.
//!
//! This crate and std are compiled by the same exact pinned Rust compiler. Only
//! the exported symbol needs an unsafe attribute; the body uses generated typed
//! bindings and contains no pointer, variant-layout or allocator assumptions.
#![cfg(target_arch = "wasm32")]
#![deny(unsafe_code)]

use core::sync::atomic::{AtomicBool, Ordering};
use latent_component_bindings::blob_guest::latent::log::log;

static BUSY: AtomicBool = AtomicBool::new(false);

struct Call;
impl Drop for Call {
    fn drop(&mut self) {
        BUSY.store(false, Ordering::Release);
    }
}

// SAFETY: the owned sysroot is this symbol's sole maintained consumer. Its
// exact Rust-ABI declaration and this implementation are recipe-bound together;
// no external canonical caller or application-selected function is accepted.
#[allow(unsafe_code)]
#[unsafe(no_mangle)]
pub extern "Rust" fn __lsf_std_log_write_v1(level: u8, message: &str) -> u8 {
    let level = match level {
        2 => log::Level::Info,
        4 => log::Level::Error,
        _ => return 1,
    };
    if message.len() > 256 {
        return 1;
    }
    if BUSY
        .compare_exchange(false, true, Ordering::Acquire, Ordering::Relaxed)
        .is_err()
    {
        return 4;
    }
    let _call = Call;
    match log::write(level, message, &[]) {
        Ok(true) => 0,
        Err(log::LogError::InvalidField(_)) => 1,
        Err(log::LogError::BudgetExhausted) => 2,
        Err(log::LogError::Unavailable) => 3,
        Ok(false) => 5,
    }
}
