
// A remembered numeric index is not a lifetime identity. The source port
// supplies the same index for a new thread only after the old owner is gone.
// The fake cancellation stops a genuinely waiting test before it can hang.
#[test]
fn reused_index_after_leaked_mutex_guard_waits_without_fabricating_ownership() {
    let mutex: &'static mutex::Mutex = Box::leak(Box::new(mutex::Mutex::new()));
    runtime::index(41); mutex.lock();
    let seen = std::rc::Rc::new(cell::Cell::new(false));
    let entered = seen.clone();
    let admitted = runtime::wait_admissions();
    assert!(!mutex.try_lock(), "recursive try_lock must not acquire");
    assert_eq!(runtime::wait_admissions(), admitted, "try_lock must not wait");
    runtime::on_wait(move || { entered.set(true); panic!("synthetic root cancellation"); });
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        runtime::index(41); mutex.lock();
    }));
    assert!(result.is_err(), "locked mutex must not return");
    assert!(seen.get(), "reused index must reach the real Wait path");
    assert_eq!(runtime::wait_admissions(), admitted + 1);
    assert_eq!(runtime::live(), 0, "source-port cancellation releases its fake Wait");
    assert!(!mutex.try_lock(), "stale ownership never became acquisition");
}

#[test]
fn reused_index_after_leaked_writer_guard_keeps_rwlock_gate_closed() {
    let lock: &'static rwlock::RwLock = Box::leak(Box::new(rwlock::RwLock::new()));
    runtime::index(42); lock.write();
    let seen = std::rc::Rc::new(cell::Cell::new(false));
    let entered = seen.clone();
    runtime::on_wait(move || { entered.set(true); panic!("synthetic root cancellation"); });
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        runtime::index(42); lock.read();
    }));
    assert!(result.is_err(), "locked rwlock must not grant a reader");
    assert!(seen.get(), "reused index must reach the real gate Wait path");
    assert_eq!(runtime::live(), 0);
    assert!(!lock.try_read());
    assert!(!lock.try_write());
}

#[test]
fn reference_safe_forgotten_guards_keep_locks_held_after_thread_exit() {
    use std::sync::{Arc, Mutex, RwLock, TryLockError};
    let mutex = Arc::new(Mutex::new(()));
    let thread_mutex = Arc::clone(&mutex);
    std::thread::spawn(move || std::mem::forget(thread_mutex.lock().unwrap())).join().unwrap();
    assert!(matches!(mutex.try_lock(), Err(TryLockError::WouldBlock)));
    let lock = Arc::new(RwLock::new(()));
    let thread_lock = Arc::clone(&lock);
    std::thread::spawn(move || std::mem::forget(thread_lock.write().unwrap())).join().unwrap();
    assert!(matches!(lock.try_read(), Err(TryLockError::WouldBlock)));
    assert!(matches!(lock.try_write(), Err(TryLockError::WouldBlock)));
}
