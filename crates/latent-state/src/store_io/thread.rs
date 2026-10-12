//! Keep native exit separate from completion of a Rust thread's main function.

use std::io;
use std::thread::{Builder, JoinHandle};

#[cfg(target_os = "linux")]
use std::sync::{
    atomic::{AtomicI32, Ordering},
    Arc,
};

pub(super) struct StoreThread {
    handle: JoinHandle<()>,
    #[cfg(target_os = "linux")]
    tid: Arc<AtomicI32>,
}

impl StoreThread {
    pub(super) fn spawn(builder: Builder, run: impl FnOnce() + Send + 'static) -> io::Result<Self> {
        #[cfg(target_os = "linux")]
        let tid = Arc::new(AtomicI32::new(0));
        #[cfg(target_os = "linux")]
        let worker_tid = Arc::clone(&tid);
        let handle = builder.spawn(move || {
            #[cfg(target_os = "linux")]
            worker_tid.store(
                rustix::thread::gettid().as_raw_nonzero().get(),
                Ordering::Release,
            );
            run();
        })?;
        Ok(Self {
            handle,
            #[cfg(target_os = "linux")]
            tid,
        })
    }

    pub(super) fn has_exited(&self) -> bool {
        if !self.handle.is_finished() {
            return false;
        }
        #[cfg(target_os = "linux")]
        {
            let Some(tid) = rustix::process::Pid::from_raw(self.tid.load(Ordering::Acquire)) else {
                return false;
            };
            // is_finished can precede arbitrary thread-local destructors. The
            // signal-zero probe sends no signal and proves native exit only
            // on ESRCH. A reused TID or any other error conservatively keeps
            // the owned handle pending under the caller's original deadline.
            matches!(
                rustix::process::test_kill_process(tid),
                Err(rustix::io::Errno::SRCH)
            )
        }
        #[cfg(not(target_os = "linux"))]
        {
            // Installed transactional node execution is qualified on Linux.
            // Other hosts retain the existing standard-library join behavior.
            true
        }
    }

    pub(super) fn join(self) -> std::thread::Result<()> {
        self.handle.join()
    }
}
