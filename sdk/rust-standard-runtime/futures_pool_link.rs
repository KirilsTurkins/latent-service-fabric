// SPDX-License-Identifier: MIT OR Apache-2.0
//! Guest-local private linkage for the captured executor port, not a host WIT.
//! Matching selected std definitions exist; final private graph is unqualified.
use std::io;

pub(crate) const PENDING: u32 = 0;
pub(crate) const QUIESCENT: u32 = 1;
pub(crate) const RELEASABLE: u32 = 2;
#[repr(C)]
struct Reply {
    status: u32,
    kind: u32,
    key: u64,
    count: u32,
}
impl Reply {
    fn empty() -> Self {
        Self {
            status: u32::MAX,
            kind: u32::MAX,
            key: u64::MAX,
            count: u32::MAX,
        }
    }
    fn result(self) -> io::Result<Self> {
        if self.status == 0 {
            return Ok(self);
        }
        let kind = match self.status {
            1 => io::ErrorKind::WouldBlock,
            2 => io::ErrorKind::Unsupported,
            3 => io::ErrorKind::PermissionDenied,
            4 => io::ErrorKind::Interrupted,
            5 => io::ErrorKind::TimedOut,
            6 => io::ErrorKind::InvalidInput,
            7 => io::ErrorKind::OutOfMemory,
            8 => io::ErrorKind::AlreadyExists,
            _ => panic!("invalid selected std executor status"),
        };
        Err(io::Error::from(kind))
    }
}
#[derive(Clone, Copy)]
pub(crate) struct Pool(u64);
#[derive(Clone, Copy)]
pub(crate) struct Generation(u64);
#[derive(Clone, Copy)]
pub(crate) struct Worker(u64);
#[derive(Clone, Copy)]
pub(crate) struct FutureKey(u64);
pub(crate) struct Close {
    pub(crate) generation: Generation,
    pub(crate) messages: usize,
}
pub(crate) enum Drain {
    Pending,
    Close(Close),
    Quiescent,
}
pub(crate) struct PoolSetup(Option<Pool>);
impl PoolSetup {
    pub(crate) fn new() -> io::Result<Self> {
        let mut result = Reply::empty();
        unsafe {
            __lsf_rust_pool_prepare(&mut result);
        }
        let result = result.result()?;
        assert!(result.key != 0 && result.kind == 0 && result.count == 0);
        Ok(Self(Some(Pool(result.key))))
    }
    pub(crate) fn handle(&self) -> Pool {
        self.0.expect("selected pool setup consumed")
    }
    pub(crate) unsafe fn commit(
        mut self,
        pointer: *mut (),
        progress: unsafe extern "C" fn(*mut ()) -> u32,
        release: unsafe extern "C" fn(*mut ()),
    ) {
        let handle = self.0.take().expect("selected pool setup committed twice");
        assert!(!pointer.is_null());
        unsafe {
            __lsf_rust_pool_commit(handle.0, pointer, progress, release);
        }
    }
}
impl Drop for PoolSetup {
    fn drop(&mut self) {
        if let Some(pool) = self.0.take() {
            unsafe {
                __lsf_rust_pool_abort_setup(pool.0);
            }
        }
    }
}
impl Pool {
    fn request(self, operation: u32, a: u64, b: u64, pointer: *mut ()) -> io::Result<Reply> {
        let mut result = Reply::empty();
        unsafe {
            __lsf_rust_pool_request(operation, self.0, a, b, pointer, &mut result);
        }
        result.result()
    }
    fn exact(self, operation: u32, a: u64, b: u64) -> Reply {
        self.request(operation, a, b, std::ptr::null_mut())
            .expect("selected executor state/admission refused")
    }
    pub(crate) fn begin_generation(self, size: usize) -> io::Result<Option<Generation>> {
        let value = self.request(
            0,
            u64::try_from(size).map_err(|_| io::Error::from(io::ErrorKind::InvalidInput))?,
            0,
            std::ptr::null_mut(),
        )?;
        assert!(value.kind == 0 && value.count == 0);
        Ok((value.key != 0).then_some(Generation(value.key)))
    }
    pub(crate) fn reserve_worker(self, generation: Generation) -> io::Result<Worker> {
        let value = self.request(1, generation.0, 0, std::ptr::null_mut())?;
        assert!(value.key != 0);
        Ok(Worker(value.key))
    }
    pub(crate) unsafe fn worker_entered(self, worker: Worker, pointer: *mut ()) -> io::Result<()> {
        self.request(2, worker.0, 0, pointer).map(|_| ())
    }
    pub(crate) fn commit_generation(self, generation: Generation) {
        self.exact(3, generation.0, 0);
    }
    pub(crate) fn abort_generation(self, generation: Generation) -> Close {
        let value = self.exact(4, generation.0, 0);
        assert_eq!(value.key, generation.0);
        assert!(value.count <= 32);
        Close {
            generation,
            messages: value.count as usize,
        }
    }
    pub(crate) fn admit_future(self) -> io::Result<FutureKey> {
        let value = self.request(5, 0, 0, std::ptr::null_mut())?;
        assert!(value.key != 0);
        Ok(FutureKey(value.key))
    }
    pub(crate) fn dequeued(self, key: FutureKey) {
        self.exact(6, key.0, 0);
    }
    pub(crate) fn waiting(self, key: FutureKey) {
        self.exact(7, key.0, 0);
    }
    pub(crate) fn requeue(self, key: FutureKey) {
        self.exact(8, key.0, 0);
    }
    pub(crate) fn completed(self, key: FutureKey) {
        self.exact(9, key.0, 0);
    }
    pub(crate) fn wake_dropped(self, key: FutureKey) {
        self.exact(10, key.0, 0);
    }
    pub(crate) fn claim_close(self, worker: Worker, generation: Generation) -> bool {
        let value = self.exact(11, worker.0, generation.0);
        assert!(value.count <= 1);
        value.count == 1
    }
    pub(crate) fn drain(self) -> Drain {
        let value = self.exact(12, 0, 0);
        match value.kind {
            0 => Drain::Pending,
            1 => {
                assert!(value.key != 0 && value.count <= 32);
                Drain::Close(Close {
                    generation: Generation(value.key),
                    messages: value.count as usize,
                })
            }
            2 => Drain::Quiescent,
            _ => panic!("invalid selected executor drain state"),
        }
    }
    pub(crate) fn retire(self) {
        self.exact(13, 0, 0);
    }
    pub(crate) fn changed(self) {
        self.exact(14, 0, 0);
    }
}
unsafe extern "C" {
    fn __lsf_rust_pool_prepare(out: *mut Reply);
    fn __lsf_rust_pool_commit(
        pool: u64,
        pointer: *mut (),
        progress: unsafe extern "C" fn(*mut ()) -> u32,
        release: unsafe extern "C" fn(*mut ()),
    );
    fn __lsf_rust_pool_abort_setup(pool: u64);
    fn __lsf_rust_pool_request(
        operation: u32,
        pool: u64,
        a: u64,
        b: u64,
        pointer: *mut (),
        out: *mut Reply,
    );
}
