// SPDX-License-Identifier: MIT OR Apache-2.0
//! One-shot handoff to the pinned, unchanged std ThreadInit/rust_start body.
//! Canonical child identity/initial handshake MUST already have completed.
//! This allocation's Native owner is retained until ThreadInit installed the
//! current-thread handle, so no guest Global deallocation or broker settlement
//! is introduced before that original std ordering boundary.
use super::owner::{AllocationError, SystemOwned};
use super::Token;
use crate::ptr::{self, NonNull};
use crate::thread::ThreadInit;

pub(crate) struct Bootstrap {
    init: Option<Box<ThreadInit>>,
}
impl Bootstrap {
    /// Parent-side preparation. Fallible Native admission precedes System
    /// allocation; refusal drops the original Box/closure on that parent.
    pub(crate) fn prepare(
        init: Box<ThreadInit>,
        task: Token,
    ) -> Result<SystemOwned<Self>, AllocationError> {
        assert!(task.valid(), "bootstrap requires its accepted child Task");
        SystemOwned::try_new(Self { init: Some(init) }, Some(task))
    }
}

/// # Safety
/// `pointer` is this child's unique live SystemOwned<Bootstrap> raw transfer.
/// The canonical context/identity handshake and registry start transition have
/// completed on the child's own installed stack/TLS, after the creator's
/// initial return. No join/detach path may recover or free this same pointer.
/// This call does NOT mark TLS or frames exited, settle a Task/Result, free the
/// child context/stack, or prove physical canonical retirement.
pub(crate) unsafe fn run(pointer: NonNull<Bootstrap>) {
    // End the ONLY mutable field access before init(): init may use TLS and
    // the allocator, and the original rust_start later invokes arbitrary user
    // work. No Bootstrap or registry Rust borrow spans either call.
    let init = unsafe {
        let slot = ptr::addr_of_mut!((*pointer.as_ptr()).init);
        (*slot).take().expect("one original ThreadInit handoff")
    };
    let rust_start = init.init();
    // The unchanged std initializer has installed its current-thread handle
    // before destroying its original Box. Infrastructure free/Native settle
    // is now safe, and completes before the original closure is invoked.
    drop(unsafe { SystemOwned::from_raw(pointer) });
    rust_start();
    // Caller next performs real TLS cleanup and returns through the compiler-
    // authenticated final epilogue. The Packet result alone cannot join/reap.
}
