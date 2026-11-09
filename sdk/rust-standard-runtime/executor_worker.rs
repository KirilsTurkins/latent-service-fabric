// SPDX-License-Identifier: MIT OR Apache-2.0
//! The captured executor's worker reference follows real PAL TLS/frame exit.
//!
//! These callbacks only update the captured pool's nonsuspending lifecycle
//! state. They do not poll futures, run TLS destructors, or free a stack.
use super::executor_root;
use super::{children, current_index, existing, reg, tls};
use crate::io;
use crate::ptr::NonNull;

#[derive(Clone, Copy)]
pub(crate) struct Callbacks {
    pub(crate) tls_drained: unsafe fn(NonNull<()>, u64),
    pub(crate) frames_exited: unsafe fn(NonNull<()>, u64),
    pub(crate) release: unsafe fn(NonNull<()>),
}

pub(crate) struct Lease {
    pointer: NonNull<()>,
    callbacks: Callbacks,
    worker: u64,
}
impl Lease {
    pub(crate) fn tls_notification(&self) -> (NonNull<()>, u64, unsafe fn(NonNull<()>, u64)) {
        (self.pointer, self.worker, self.callbacks.tls_drained)
    }
    pub(crate) unsafe fn after_frames(self) {
        // The reaper already authenticated phase/SP/TLS/frame return and freed
        // the actual child linear context. It still owns that child's Task.
        unsafe {
            (self.callbacks.frames_exited)(self.pointer, self.worker);
            (self.callbacks.release)(self.pointer);
        }
        // release consumes exactly the transferred real Arc reference. Other
        // Arc references/backing and the original linear charge may remain.
    }
}

/// Install the one retained pool reference for this actual running worker.
/// On Err the caller still owns pointer; on Ok the Child owns it until reaping.
///
/// # Safety
/// pointer is an owned Arc::into_raw reference to the same pool registered by
/// executor, and all three callbacks come from the authenticated captured port.
/// The TLS/frame callbacks are nonsuspending, cannot run/drop user values, and
/// cannot submit work. The pool supplies its already validated, nonzero worker
/// key. That key remains unique through real frame retirement even if the
/// canonical index is recycled. The release callback consumes one reference
/// on the reaper's normal Rust frame. The selected compiler's complete graph must authenticate
/// these callsites/callback bodies; this private source API alone does not.
pub(crate) unsafe fn register(
    executor: executor_root::Handle,
    pointer: NonNull<()>,
    worker: u64,
    callbacks: Callbacks,
) -> io::Result<()> {
    if worker == 0 || existing().is_null() || !executor_root::owns(executor, pointer) {
        return Err(io::Error::from(io::ErrorKind::InvalidInput));
    }
    let canonical = current_index();
    let context = tls::installed_context().addr();
    let handle = reg(|registry| registry.running_child(canonical, context))
        .map_err(|_| io::Error::from(io::ErrorKind::InvalidInput))?;
    children(|table| {
        let child = table[handle.slot()]
            .as_mut()
            .expect("live executor worker backing");
        if child.executor.is_some() {
            return Err(io::Error::from(io::ErrorKind::AlreadyExists));
        }
        child.executor = Some(Lease {
            pointer,
            callbacks,
            worker,
        });
        Ok(())
    })
}
