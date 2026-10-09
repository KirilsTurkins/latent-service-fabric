use super::*;

#[test]
fn shared_owner_refuses_overlap_and_durable_page_progress_resumes_after_restart() {
    let (dir, store, effects) = setup();
    let first = completed(&store, &effects, "first-page");
    let second = completed(&store, &effects, "second-page");
    let owner = ResultMaintenanceOwner::default();
    owner
        .anchor(&store, None, observation(1000, 0), maintenance)
        .unwrap();
    let (notice, ready) = std::sync::mpsc::sync_channel(1);
    let (release, paused) = std::sync::mpsc::sync_channel(1);
    let progress = std::thread::scope(|scope| {
        let worker_owner = &owner;
        let worker_store = &store;
        let worker = scope.spawn(move || {
            let mut first_authorization = true;
            worker_owner.step(worker_store, observation(1100, 100), |record| {
                if first_authorization {
                    first_authorization = false;
                    notice.send(()).unwrap();
                    paused
                        .recv_timeout(std::time::Duration::from_secs(5))
                        .unwrap();
                }
                maintenance(record)
            })
        });
        ready
            .recv_timeout(std::time::Duration::from_secs(5))
            .unwrap();
        assert_eq!(
            owner.step(&store, observation(1100, 100), |_| {
                panic!("overlapping step cannot reach policy or the native store")
            }),
            Err(AtomicError::InProgress)
        );
        release.send(()).unwrap();
        worker.join().unwrap().unwrap()
    });
    assert_eq!((progress.visited, progress.retired), (1, 1));
    assert!(progress.cursor.is_some());
    let marker_count = [&first, &second]
        .iter()
        .filter(|record| result_bytes(&store, record).starts_with(b"LCE\0"))
        .count();
    assert_eq!(marker_count, 1);
    drop(store);
    let store = open(&dir.path().join("state.redb"));
    let reopened_owner = ResultMaintenanceOwner::default();
    let progress = reopened_owner
        .step(&store, observation(1101, 101), maintenance)
        .unwrap();
    assert_eq!((progress.visited, progress.retired), (2, 2));
    assert!(progress.cursor.is_none());
    let again = reopened_owner
        .step(&store, observation(1102, 102), maintenance)
        .unwrap();
    assert_eq!(again.retired, 2);
    validate_view(&store.snapshot().unwrap(), foreign_codec).unwrap();
}
