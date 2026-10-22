// SPDX-License-Identifier: MIT OR Apache-2.0
//! Closed guest-local linkage from the selected captured ThreadPool to std.
//!
//! These definitions are internal Core functions, not host imports or a new
//! authority surface. The selected compiler must authenticate their callsites,
//! callback/table targets, the complete port body and original pool Arc origin.
//! No raw Runtime borrow survives an admission, wait or captured callback.
use super::current_index;
use super::executor_control::Drain;
use super::executor_root::{self as root, CapturedCallbacks};
use super::executor_worker::{self as worker, Callbacks as WorkerCallbacks};
use crate::io;
use crate::ptr::{self, NonNull};

#[repr(C)]
pub(crate) struct Reply {
    status: u32,
    kind: u32,
    key: u64,
    count: u32,
}
impl Reply {
    fn success() -> Self {
        Self {
            status: 0,
            kind: 0,
            key: 0,
            count: 0,
        }
    }
    fn key(key: u64) -> Self {
        Self {
            key,
            ..Self::success()
        }
    }
    fn error(error: io::Error) -> Self {
        let status = match error.kind() {
            io::ErrorKind::WouldBlock => 1,
            io::ErrorKind::Unsupported => 2,
            io::ErrorKind::PermissionDenied => 3,
            io::ErrorKind::Interrupted => 4,
            io::ErrorKind::TimedOut => 5,
            io::ErrorKind::InvalidInput => 6,
            io::ErrorKind::OutOfMemory => 7,
            io::ErrorKind::AlreadyExists => 8,
            _ => panic!("unmapped selected std pool error"),
        };
        Self {
            status,
            ..Self::success()
        }
    }
}
fn invalid() -> io::Error {
    io::Error::from(io::ErrorKind::InvalidInput)
}
unsafe fn write(out: *mut Reply, result: io::Result<Reply>) {
    assert!(!out.is_null(), "selected pool reply pointer absent");
    unsafe { out.write(result.unwrap_or_else(Reply::error)) };
}

#[no_mangle]
pub(crate) unsafe extern "C" fn __lsf_rust_pool_prepare(out: *mut Reply) {
    let result = root::prepare().map(Reply::key);
    unsafe { write(out, result) };
}

#[no_mangle]
pub(crate) unsafe extern "C" fn __lsf_rust_pool_commit(
    pool: u64,
    pointer: *mut (),
    progress: unsafe extern "C" fn(*mut ()) -> u32,
    release: unsafe extern "C" fn(*mut ()),
) {
    let pointer = NonNull::new(pointer).expect("captured pool Arc absent");
    unsafe { root::commit_prepared(pool, pointer, CapturedCallbacks { progress, release }) };
}

#[no_mangle]
pub(crate) unsafe extern "C" fn __lsf_rust_pool_abort_setup(pool: u64) {
    root::abort_prepared(pool);
}

fn request(operation: u32, pool: u64, a: u64, b: u64, pointer: *mut ()) -> io::Result<Reply> {
    // Check the entire finite local message before touching owner/lifecycle
    // state. Unknown operations/extra fields cannot alias a valid transition.
    let valid = match operation {
        0 => (1..=32).contains(&a) && b == 0 && pointer.is_null(),
        1 | 3 | 4 | 6..=10 => a != 0 && b == 0 && pointer.is_null(),
        2 => a != 0 && b == 0 && !pointer.is_null(),
        5 | 12..=14 => a == 0 && b == 0 && pointer.is_null(),
        11 => a != 0 && b != 0 && pointer.is_null(),
        _ => false,
    };
    if !valid {
        return Err(invalid());
    }
    let binding = root::control(pool)?;
    // Root's retained Arc and the caller's actual pool/worker reference keep
    // this separately prepaid backing live throughout any canonical handoff.
    let control = unsafe { binding.control.as_ref() };
    let mut result = Reply::success();
    match operation {
        0 => result.key = control.begin_generation(a as usize)?.unwrap_or(0),
        1 => result.key = control.reserve_worker(a, binding.parent)?,
        2 => {
            if pointer != binding.pointer.as_ptr() {
                return Err(invalid());
            }
            let canonical = current_index();
            control.check_worker_start(a, canonical)?;
            // Both validations precede transfer of the ONE caller-owned Arc.
            // register checks the actual Running child/context and duplicate
            // lease; its successful path is pure and cannot yield.
            unsafe {
                worker::register(
                    binding.handle,
                    binding.pointer,
                    WorkerCallbacks {
                        tls_drained: root::worker_tls_drained,
                        frames_exited: root::worker_frames_exited,
                        release: root::worker_release,
                    },
                )?;
            }
            control
                .worker_started(a, canonical)
                .expect("prevalidated worker Arc transfer");
        }
        3 => control.commit_generation(a)?,
        4 => {
            let (generation, messages) = control.abort_generation(a)?;
            result.key = generation;
            result.count = u32::try_from(messages).expect("bounded abort Close count");
        }
        5 => result.key = control.admit_future(binding.parent)?,
        6 => control.dequeued(a)?,
        7 => control.waiting(a)?,
        8 => control.requeue(a)?,
        9 => control.completed(a)?,
        10 => control.wake_dropped(a)?,
        11 => result.count = u32::from(control.claim_close(a, b)?),
        12 => match control.drain()? {
            Drain::Pending => {}
            Drain::Close {
                generation,
                messages,
            } => {
                result.kind = 1;
                result.key = generation;
                result.count = u32::try_from(messages).expect("bounded actual Close count");
            }
            Drain::Quiescent => result.kind = 2,
        },
        13 => control.retire()?,
        14 => root::changed(),
        _ => unreachable!(),
    }
    // Notification is explicit operation14 after the port releases its real
    // queue mutex. Pure UnparkMutex->Waiting publication never calls a host.
    Ok(result)
}

#[no_mangle]
pub(crate) unsafe extern "C" fn __lsf_rust_pool_request(
    operation: u32,
    pool: u64,
    a: u64,
    b: u64,
    pointer: *mut (),
    out: *mut Reply,
) {
    let result = request(operation, pool, a, b, pointer);
    unsafe { write(out, result) };
}
