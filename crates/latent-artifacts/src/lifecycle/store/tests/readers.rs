use super::*;
use std::{sync::mpsc, thread, time::Duration};

#[test]
fn healthy_final_starts_share_reads_and_exclude_generation_cutover() {
    // Only compact in-memory owners/rows are constructed. Neither final start
    // nor its eligibility recheck has a store or filesystem handle to consult.
    let id = identity(b"parallel-start");
    let record = publication(&id, "create").record.unwrap();
    let owner = Owner::new(None);
    let row = Row::new(&record);
    let token = ReleaseUseEligibility::new(
        LifecycleEligibility {
            owner: Arc::clone(&owner),
            row: Arc::clone(&row),
            generation: record.generation,
        },
        None,
    )
    .unwrap();
    let (held, acquired) = mpsc::channel();
    let (release, finish) = mpsc::channel();
    thread::scope(|scope| {
        let first_token = &token;
        let first = scope.spawn(move || {
            first_token
                .with_current(&mut |checker| {
                    checker.check()?;
                    held.send(()).unwrap();
                    finish.recv_timeout(Duration::from_secs(5)).unwrap();
                    checker.check()
                })
                .unwrap();
        });
        acquired.recv_timeout(Duration::from_secs(5)).unwrap();
        let mut second_started = false;
        token
            .with_current(&mut |checker| {
                checker.check()?;
                second_started = true;
                Ok(())
            })
            .unwrap();
        assert!(
            second_started,
            "healthy readers must not reject one another"
        );
        let failure = owner.write().unwrap_err();
        assert_eq!(failure.message, "release-lifecycle-busy");
        assert!(failure.retryable);
        assert_eq!(token.generation(), record.generation);
        release.send(()).unwrap();
        first.join().unwrap();
    });
    {
        let _cutover = owner.write().unwrap();
        row.adopt(&revocation(&record, "revoke").record.unwrap());
        let mut started = false;
        let failure = token
            .with_current(&mut |_| {
                started = true;
                Ok(())
            })
            .unwrap_err();
        assert_eq!(failure.message, "release-lifecycle-busy");
        assert!(!started);
    }
    let mut started = false;
    let failure = token
        .with_current(&mut |_| {
            started = true;
            Ok(())
        })
        .unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::PermissionDenied);
    assert!(
        !started,
        "old decisions cannot start after exclusive cutover"
    );
}
