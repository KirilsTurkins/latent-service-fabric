// SPDX-License-Identifier: MIT OR Apache-2.0
//! Selected pinned std PAL. Native handle ownership stays in the real registry.
use crate::ffi::CStr;
use crate::io;
use crate::num::NonZero;
use crate::thread::ThreadInit;
use crate::time::Duration;

pub(crate) mod runtime;
pub(crate) mod wait;

pub const DEFAULT_MIN_STACK_SIZE: usize = 64 * 1024;

pub struct Thread {
    handle: Option<runtime::Handle>,
}
// The handle is an activation-local, generation-checked registry identity. The
// selected Store serializes canonical threads; it never escapes into a host OS.
unsafe impl Send for Thread {}
unsafe impl Sync for Thread {}
impl Thread {
    // The ordinary upstream ThreadInit/rust_start/Packet closure is unchanged.
    // Admission and stack/context ownership precede actual canonical creation.
    pub unsafe fn new(stack: usize, init: Box<ThreadInit>) -> io::Result<Self> {
        unsafe { runtime::spawn(stack, init) }.map(|handle| Self {
            handle: Some(handle),
        })
    }
    pub fn join(mut self) {
        let handle = self.handle.take().expect("one logical thread join handle");
        // Does not return on a merely filled Packet. Real Rust/TLS frames and
        // the canonical child completion boundary must have returned first.
        runtime::join(handle);
    }
}
impl Drop for Thread {
    fn drop(&mut self) {
        if let Some(handle) = self.handle.take() {
            // Detaching a user handle does not stop accepted work, refund a
            // live owner or free its frame. The root drainer still owns it.
            runtime::detach(handle);
        }
    }
}

pub fn available_parallelism() -> io::Result<NonZero<usize>> {
    Ok(NonZero::new(1).unwrap())
}
pub fn current_os_id() -> Option<u64> {
    None
}
pub fn set_name(_name: &CStr) { /* std keeps the ordinary logical thread name. */
}
pub fn yield_now() {
    runtime::yield_eligible();
}
pub fn sleep(duration: Duration) {
    if duration.is_zero() {
        return;
    }
    let queue = wait::WaitQueue::new();
    // Only matching admitted timer readiness returns false. Cancellation,
    // deadline, provider errors and an unavailable runtime never become sleep.
    assert!(
        !queue.prepare(Some(duration)).wait(),
        "sleep had a non-timer wake"
    );
}

// The source body is preserved at its original table index by the authenticated
// post-link entry transform. Its generated stackless wrapper installs slot1
// before any Rust prologue and detaches only after the last Rust/TLS epilogue.
#[inline(never)]
#[unsafe(no_mangle)]
pub unsafe extern "C" fn __lsf_rust_owned_thread_entry(context: *mut u8) {
    unsafe {
        runtime::entered(context);
    }
}
