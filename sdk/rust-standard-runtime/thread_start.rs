// SPDX-License-Identifier: MIT OR Apache-2.0
//! One-shot handoff of the original Box to pinned std ThreadInit/rust_start.
//! The existing Runtime allocation already contains every bounded Child slot;
//! moving this value into that slot needs no second System allocation/Native
//! owner. Box addresses and the original linear-memory charge remain intact.
//! Canonical child identity/initial handshake MUST already have completed.
use super::Token;
use crate::thread::ThreadInit;

pub(crate) struct Bootstrap {
    init: Option<Box<ThreadInit>>,
}
impl Bootstrap {
    /// Parent-side move into its existing Preparing/Child record. On any
    /// prestart refusal, ordinary Drop still consumes the original Box once.
    pub(crate) fn prepare(init: Box<ThreadInit>, task: Token) -> Self {
        assert!(task.valid(), "bootstrap requires its accepted child Task");
        Self { init: Some(init) }
    }
}

/// Consumes the exact Child record's sole original ThreadInit handoff.
/// The caller takes this value out of the registry before calling us, so no
/// Child/Runtime borrow spans original init(), allocation or user code.
/// This call does NOT mark TLS or frames exited, settle a Task/Result, free
/// the child context/stack, or prove physical canonical retirement.
pub(crate) fn run(mut bootstrap: Bootstrap) {
    let init = bootstrap
        .init
        .take()
        .expect("one original ThreadInit handoff");
    let rust_start = init.init();
    // The unchanged std initializer installs its current-thread handle before
    // destroying its original Box. The now-empty in-record handoff owns no
    // allocation or separate Native lease to free/settle before user work.
    drop(bootstrap);
    rust_start();
    // Caller next performs real TLS cleanup and returns through the compiler-
    // authenticated final epilogue. The Packet result alone cannot join/reap.
}
