use super::*;
use crate::store_io::StoreIoKind;
use std::cell::Cell;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

struct SendOnlyOwner {
    _not_sync: Cell<()>,
    dropped: Arc<AtomicUsize>,
    native_worker: Arc<AtomicBool>,
}

impl Drop for SendOnlyOwner {
    fn drop(&mut self) {
        self.native_worker.store(
            std::thread::current()
                .name()
                .is_some_and(|name| name.starts_with("latent-store-")),
            Ordering::SeqCst,
        );
        self.dropped.fetch_add(1, Ordering::SeqCst);
    }
}

#[test]
fn rejected_opening_keeps_send_only_owner_until_actual_worker_retirement() {
    let (_root, mut config) = fixture();
    config.io.queued_jobs = 1;
    let owner = start(config);
    let rendezvous = Rendezvous::new(3);
    let (notice, receiver) = mpsc::channel();
    let mut jobs = Vec::new();
    let mut tickets = Vec::new();
    for kind in [StoreIoKind::Read, StoreIoKind::Read, StoreIoKind::Write] {
        let worker = rendezvous.clone();
        let notice = notice.clone();
        jobs.push(
            owner
                .with_store(kind, 512, move |_engine| {
                    let (registration, mut retained) = worker.track(vec![0_u8; 512]).unwrap();
                    retained.commit(Stage::Entered).unwrap();
                    let mut pause = Box::pin(retained.pause());
                    PollProbe::default().pending(pause.as_mut());
                    notice
                        .send(worker.blocked(registration, Stage::Entered).unwrap())
                        .unwrap();
                    block_on(pause);
                    Ok(())
                })
                .unwrap(),
        );
        tickets.push(receiver.recv_timeout(WATCHDOG).unwrap());
    }
    let queued = owner.with_store(StoreIoKind::Write, 0, |_| Ok(())).unwrap();
    let dropped = Arc::new(AtomicUsize::new(0));
    let native_worker = Arc::new(AtomicBool::new(false));
    let result = owner.open_view_retaining(SendOnlyOwner {
        _not_sync: Cell::new(()),
        dropped: Arc::clone(&dropped),
        native_worker: Arc::clone(&native_worker),
    });
    let refused = matches!(
        result,
        Err(ProtectedStoreError::Io(StoreIoError::QueueFull))
    );
    let dropped_before_retirement = dropped.load(Ordering::SeqCst);
    let physically_owned = owner.snapshot().unwrap().physical_owners;
    // Release every real worker before asserting, including on the old source
    // whose rejected closure prematurely drops the original admitted owner.
    for ticket in tickets {
        rendezvous.release(ticket).unwrap();
    }
    for job in jobs {
        wait(job).unwrap().unwrap();
    }
    wait(queued).unwrap().unwrap();
    let shutdown = finish(&owner);
    assert!(shutdown.clean);
    assert!(shutdown.snapshot.physically_retired());
    assert!(refused);
    assert!(physically_owned > 0);
    assert_eq!(dropped_before_retirement, 0);
    assert_eq!(dropped.load(Ordering::SeqCst), 1);
    assert!(native_worker.load(Ordering::SeqCst));
}
