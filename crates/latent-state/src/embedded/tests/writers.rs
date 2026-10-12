use super::*;

#[test]
fn bounded_concurrent_writers_serialize_conflicts_and_preserve_independent_rows() {
    use std::sync::Barrier;
    let dir = tempfile::tempdir().unwrap();
    let store = Arc::new(
        EmbeddedStore::open_file(file(&dir.path().join("store.redb")), StoreLimits::default())
            .unwrap(),
    );
    let barrier = Arc::new(Barrier::new(3));
    let started = Instant::now();
    let threads = ["first", "second"].map(|value| {
        let store = Arc::clone(&store);
        let barrier = Arc::clone(&barrier);
        std::thread::spawn(move || {
            barrier.wait();
            let mut batch = bundle(value);
            batch.expectations.push(ExpectedRow {
                key: key(Family::State, "command-1"),
                value: None,
            });
            let outcome = store.apply(batch);
            store
                .apply(AtomicBatch {
                    expectations: vec![],
                    mutations: vec![RowMutation {
                        key: key(Family::State, value),
                        value: Some(value.as_bytes().to_vec()),
                    }],
                })
                .unwrap();
            outcome
        })
    });
    barrier.wait();
    let outcomes = threads.map(|thread| thread.join().unwrap());
    assert_eq!(outcomes.iter().filter(|v| v.is_ok()).count(), 1);
    assert_eq!(
        outcomes
            .iter()
            .filter(|v| **v == Err(StoreError::Conflict))
            .count(),
        1
    );
    let view = store.snapshot().unwrap();
    let winner = view.get(&key(Family::State, "command-1")).unwrap().unwrap();
    for family in [Family::Command, Family::Outbox] {
        assert_eq!(
            view.get(&key(family, "command-1")),
            Ok(Some(winner.clone()))
        );
    }
    for value in ["first", "second"] {
        assert_eq!(
            view.get(&key(Family::State, value)),
            Ok(Some(value.as_bytes().to_vec()))
        );
    }
    println!(
        "LSF_STORE_WRITERS {}",
        serde_json::json!({"workers":2,"winningCommits":1,"conflicts":1,"independentCommits":2,"elapsedMicros":started.elapsed().as_micros()})
    );
}
