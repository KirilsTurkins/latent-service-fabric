use super::*;

#[test]
fn uncertain_publication_recovers_the_physical_inventory_without_refund() {
    for (operation, skip, published) in [("rename", 0, false), ("sync", 1, true), ("sync", 2, true)]
    {
        let root = temporary_root();
        let owner = store(root.path());
        let mut writer = owner
            .create(&scope(), "text/plain", Some(4), &|| Ok(()))
            .unwrap();
        writer.write(0, b"data", &|| Ok(())).unwrap();
        owner.inner.root.fail_after(operation, skip);
        assert_eq!(writer.seal(&|| Ok(())), Err(LocalBlobError::Uncertain));
        let usage = owner.snapshot().unwrap();
        assert!(usage.poisoned);
        assert_eq!(usage.reserved_stage_bytes, 4);
        assert_eq!(usage.resident_disk_bytes, 0);
        assert!(matches!(
            owner.create(&scope(), "text/plain", Some(0), &|| Ok(())),
            Err(LocalBlobError::Uncertain)
        ));
        drop(owner);
        let owner = store(root.path());
        let usage = owner.snapshot().unwrap();
        assert_eq!(usage.referenced_objects, usize::from(published));
        assert_eq!(usage.resident_disk_bytes, if published { 4 } else { 0 });
        assert_eq!(usage.stages, usize::from(!published));
        if published {
            let reference = put(&owner, b"data");
            let reader = owner.open_read(&scope(), &reference, &|| Ok(())).unwrap();
            assert_eq!(read(&reader, 0, 4).unwrap(), b"data");
        } else {
            assert_eq!(
                owner
                    .reclaim(4, &|| Ok(()))
                    .unwrap()
                    .released_payload_reservations,
                4
            );
        }
    }
}

#[test]
fn failed_unlink_or_sync_does_not_refund_and_reopens_as_unreferenced() {
    for (operation, skip) in [
        ("unlink", 0),
        ("unlink", 1),
        ("unlink", 3),
        ("unlink", 4),
        ("sync", 0),
        ("sync", 1),
    ] {
        let root = temporary_root();
        let owner = store(root.path());
        let reference = put(&owner, b"data");
        owner
            .release_reference(&scope(), &reference, &|| Ok(()))
            .unwrap();
        owner.inner.root.fail_after(operation, skip);
        assert_eq!(owner.reclaim(4, &|| Ok(())), Err(LocalBlobError::Uncertain));
        assert_eq!(owner.snapshot().unwrap().resident_disk_bytes, 4);
        drop(owner);
        let owner = store(root.path());
        assert_eq!(owner.snapshot().unwrap().referenced_objects, 0);
        assert!(matches!(
            owner.open_read(&scope(), &reference, &|| Ok(())),
            Err(LocalBlobError::NotFound)
        ));
        owner.reclaim(4, &|| Ok(())).unwrap();
        assert_eq!(owner.snapshot().unwrap().resident_disk_bytes, 0);
    }
}

#[test]
fn interrupted_stage_is_recovered_with_actual_bytes_and_never_resumed() {
    let root = temporary_root();
    let owner = store(root.path());
    let mut writer = owner
        .create(&scope(), "text/plain", None, &|| Ok(()))
        .unwrap();
    writer.write(0, b"short", &|| Ok(())).unwrap();
    drop(writer);
    assert_eq!(owner.snapshot().unwrap().reserved_stage_bytes, 16);
    drop(owner);
    let owner = store(root.path());
    assert_eq!(owner.snapshot().unwrap().reserved_stage_bytes, 5);
    assert_eq!(owner.snapshot().unwrap().handles, 0);
    assert_eq!(
        owner
            .reclaim(1, &|| Ok(()))
            .unwrap()
            .released_payload_reservations,
        5
    );
}

#[test]
fn cancellation_after_a_physical_write_poisoned_the_writer_but_keeps_stage_charge() {
    let root = temporary_root();
    let owner = store(root.path());
    let mut writer = owner
        .create(&scope(), "text/plain", Some(4), &|| Ok(()))
        .unwrap();
    let checks = AtomicUsize::new(0);
    assert_eq!(
        writer.write(0, b"data", &|| {
            if checks.fetch_add(1, Ordering::AcqRel) == 0 {
                Ok(())
            } else {
                Err(LocalBlobError::Closed)
            }
        }),
        Err(LocalBlobError::Closed)
    );
    assert_eq!(
        writer.write(0, b"data", &|| Ok(())),
        Err(LocalBlobError::Closed)
    );
    assert_eq!(writer.seal(&|| Ok(())), Err(LocalBlobError::Closed));
    assert_eq!(owner.snapshot().unwrap().reserved_stage_bytes, 4);
    assert_eq!(owner.reclaim(1, &|| Ok(())).unwrap().stages, 1);
}

#[test]
fn closing_owner_does_not_release_root_lock_until_actual_handles_retire() {
    let root = temporary_root();
    let owner = store(root.path());
    let mut writer = owner
        .create(&scope(), "text/plain", Some(0), &|| Ok(()))
        .unwrap();
    owner.close();
    assert_eq!(
        writer.write(0, b"", &|| Ok(())),
        Err(LocalBlobError::Closed)
    );
    drop(owner);
    assert!(matches!(
        LocalBlobStore::open(root.path(), "private", limits()),
        Err(LocalBlobError::Busy)
    ));
    drop(writer);
    let owner = store(root.path());
    assert_eq!(owner.reclaim(1, &|| Ok(())).unwrap().stages, 1);
}

#[test]
fn concurrent_duplicate_seals_reject_promptly_and_explicit_retry_converges() {
    let root = temporary_root();
    let owner = store(root.path());
    let mut first = owner
        .create(&scope(), "text/plain", Some(4), &|| Ok(()))
        .unwrap();
    first.write(0, b"data", &|| Ok(())).unwrap();
    let mut second = owner
        .create(&scope(), "text/plain", Some(4), &|| Ok(()))
        .unwrap();
    second.write(0, b"data", &|| Ok(())).unwrap();
    let entered = Arc::new(std::sync::Barrier::new(2));
    let release = Arc::new(std::sync::Barrier::new(2));
    let entered_worker = entered.clone();
    let release_worker = release.clone();
    let thread = std::thread::spawn(move || {
        let once = AtomicBool::new(false);
        first.seal(&|| {
            if !once.swap(true, Ordering::AcqRel) {
                entered_worker.wait();
                release_worker.wait();
            }
            Ok(())
        })
    });
    entered.wait();
    assert_eq!(second.seal(&|| Ok(())), Err(LocalBlobError::Busy));
    release.wait();
    let reference = thread.join().unwrap().unwrap();
    assert_eq!(put(&owner, b"data"), reference);
    assert_eq!(owner.snapshot().unwrap().objects, 1);
    assert_eq!(owner.reclaim(4, &|| Ok(())).unwrap().stages, 2);
}

#[test]
fn cancellation_and_shutdown_keep_running_file_work_until_the_worker_retires() {
    let root = temporary_root();
    let owner = store(root.path());
    let mut writer = owner
        .create(&scope(), "text/plain", Some(4), &|| Ok(()))
        .unwrap();
    let (entered, receive) = std::sync::mpsc::channel();
    let (release, blocked) = std::sync::mpsc::channel();
    let thread = std::thread::spawn(move || {
        let checks = AtomicUsize::new(0);
        writer.write(0, b"data", &|| {
            if checks.fetch_add(1, Ordering::AcqRel) == 1 {
                // Pause the actual file owner after its physical write, before
                // the cancellation checkpoint returns. No timing assumption.
                entered.send(()).unwrap();
                blocked
                    .recv_timeout(std::time::Duration::from_secs(5))
                    .unwrap();
                return Err(LocalBlobError::Cancelled);
            }
            Ok(())
        })
    });
    receive
        .recv_timeout(std::time::Duration::from_secs(5))
        .unwrap();
    assert_eq!(owner.snapshot().unwrap().active_work, 1);
    assert_eq!(owner.snapshot().unwrap().handles, 1);
    assert_eq!(owner.reclaim(1, &|| Ok(())).unwrap().stages, 0);
    owner.close();
    assert_eq!(owner.snapshot().unwrap().reserved_stage_bytes, 4);
    assert!(matches!(
        LocalBlobStore::open(root.path(), "private", limits()),
        Err(LocalBlobError::Busy)
    ));
    release.send(()).unwrap();
    assert_eq!(thread.join().unwrap(), Err(LocalBlobError::Cancelled));
    assert_eq!(owner.snapshot().unwrap().active_work, 0);
    assert_eq!(owner.snapshot().unwrap().handles, 0);
    drop(owner);
    let reopened = store(root.path());
    assert_eq!(reopened.snapshot().unwrap().reserved_stage_bytes, 4);
    assert_eq!(reopened.reclaim(1, &|| Ok(())).unwrap().stages, 1);
}
