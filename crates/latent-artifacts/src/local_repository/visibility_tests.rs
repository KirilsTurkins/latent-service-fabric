use super::*;
use latent_core::PlatformError;
use std::sync::mpsc;

fn retryable_contention(failure: &PlatformError) -> bool {
    failure.code == PlatformErrorCode::Unavailable
        && failure.retryable
        && failure.message == "release-lifecycle-busy"
}

enum Observation {
    Absent,
    Busy,
    Complete(Box<CapsuleArtifact>),
}

fn observe_publication(
    repo: &DirectoryArtifactRepository,
    query: &ArtifactQuery,
    after_resolve: &mut impl FnMut(),
) -> Result<Observation, String> {
    let descriptor = match block_on(repo.resolve(query)) {
        Ok(Some(descriptor)) => descriptor,
        Ok(None) => return Ok(Observation::Absent),
        Err(failure) if retryable_contention(&failure) => return Ok(Observation::Busy),
        Err(failure) => return Err(format!("resolve: {failure:?}")),
    };
    after_resolve();
    let complete = match block_on(repo.fetch(&descriptor.release_digest)) {
        Ok(complete) => complete,
        Err(failure) if retryable_contention(&failure) => return Ok(Observation::Busy),
        Err(failure) => return Err(format!("visible release was incomplete: {failure:?}")),
    };
    if complete.descriptor != descriptor {
        return Err("visible descriptor disagrees with complete fetch".to_owned());
    }
    Ok(Observation::Complete(Box::new(complete)))
}

// Successful, contended and injected-failure tests use this same observer.
// Hooks force races without sleeps. Only explicit lifecycle contention retries.
fn wait_for_publication(
    repo: &DirectoryArtifactRepository,
    query: &ArtifactQuery,
    writer: thread::JoinHandle<Result<ArtifactDescriptor, PlatformError>>,
    deadline: Instant,
    mut after_absent: impl FnMut(&thread::JoinHandle<Result<ArtifactDescriptor, PlatformError>>),
    mut after_resolve: impl FnMut(),
    mut after_busy: impl FnMut(),
) -> Result<CapsuleArtifact, String> {
    let mut writer = Some(writer);
    let mut published = None;
    loop {
        if writer.as_ref().is_some_and(thread::JoinHandle::is_finished) {
            published = Some(
                writer
                    .take()
                    .expect("finished writer still owned")
                    .join()
                    .map_err(|_| "publication writer panicked".to_owned())?
                    .map_err(|error| format!("publication writer failed: {error:?}"))?,
            );
        }
        match observe_publication(repo, query, &mut after_resolve)? {
            Observation::Absent => {
                if published.is_some() {
                    return Err("successful writer did not leave a visible release".to_owned());
                }
                after_absent(writer.as_ref().expect("unfinished writer still owned"));
            }
            Observation::Busy => after_busy(),
            Observation::Complete(complete) => {
                if let Some(descriptor) = &published {
                    if &complete.descriptor != descriptor {
                        return Err("successful writer left a different visible release".to_owned());
                    }
                    return Ok(*complete);
                }
            }
        }
        if Instant::now() >= deadline {
            return Err(format!(
                "publication visibility deadline exceeded for {query:?}"
            ));
        }
        thread::yield_now();
    }
}

#[test]
fn readers_never_observe_partial_publication_and_wait_is_bounded() {
    let temp = TempRoot::new();
    let repo = Arc::new(repository(temp.path()));
    let expected = artifact("atomic", &vec![0x5a; 2 * 1024 * 1024]);
    let query = ArtifactQuery {
        reference: None,
        release_digest: Some(expected.descriptor.release_digest.clone()),
        media_type: None,
    };
    let writer_repo = Arc::clone(&repo);
    let writer_artifact = expected.clone();
    let writer = thread::spawn(move || block_on(writer_repo.publish(writer_artifact)));
    let actual = wait_for_publication(
        &repo,
        &query,
        writer,
        Instant::now() + Duration::from_secs(10),
        |_| {},
        || {},
        || {},
    )
    .expect("complete publication");
    assert_eq!(actual, expected);
}

#[test]
fn visible_complete_publication_retries_fence_contention_at_resolve_and_fetch() {
    for during_fetch in [false, true] {
        let temp = TempRoot::new();
        let repo = Arc::new(repository(temp.path()));
        let expected = artifact("held-fence", b"complete-component");
        let descriptor = block_on(repo.publish(expected.clone())).unwrap();
        let query = ArtifactQuery {
            reference: None,
            release_digest: Some(descriptor.release_digest.clone()),
            media_type: None,
        };
        let writer_repo = Arc::clone(&repo);
        let (start, wait) = mpsc::channel();
        let (held, acquired) = mpsc::channel();
        let (release, finish) = mpsc::channel();
        let writer = thread::spawn(move || {
            wait.recv_timeout(Duration::from_secs(5)).unwrap();
            writer_repo.life_store().with_exclusive(&mut |_| {
                held.send(()).unwrap();
                finish.recv_timeout(Duration::from_secs(5)).unwrap();
                Ok(())
            })?;
            Ok(descriptor)
        });
        if !during_fetch {
            start.send(()).unwrap();
            acquired.recv_timeout(Duration::from_secs(5)).unwrap();
        }
        let mut requested = !during_fetch;
        let mut released = false;
        let actual = wait_for_publication(
            &repo,
            &query,
            writer,
            Instant::now() + Duration::from_secs(5),
            |_| panic!("published immutable bytes cannot disappear"),
            || {
                if !requested {
                    start.send(()).unwrap();
                    acquired.recv_timeout(Duration::from_secs(5)).unwrap();
                    requested = true;
                }
            },
            || {
                if !released {
                    release.send(()).unwrap();
                    released = true;
                }
            },
        )
        .unwrap();
        assert!(
            released,
            "the real read must have observed fence contention"
        );
        assert_eq!(actual, expected);
    }
}

#[test]
fn healthy_final_start_does_not_block_complete_catalog_reads() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let expected = artifact("shared-fence", b"complete-component");
    let descriptor = block_on(repo.publish(expected.clone())).unwrap();
    let query = ArtifactQuery {
        reference: None,
        release_digest: Some(descriptor.release_digest.clone()),
        media_type: None,
    };
    let token = repo
        .execution_eligibility(&descriptor.release_digest)
        .unwrap()
        .unwrap();
    let (held, acquired) = mpsc::channel();
    let (release, finish) = mpsc::channel();
    thread::scope(|scope| {
        let first = scope.spawn(move || {
            token
                .with_current(&mut |checker| {
                    checker.check()?;
                    held.send(()).unwrap();
                    finish.recv_timeout(Duration::from_secs(5)).unwrap();
                    checker.check()
                })
                .unwrap();
        });
        acquired.recv_timeout(Duration::from_secs(5)).unwrap();
        assert_eq!(
            block_on(repo.resolve(&query)).unwrap(),
            Some(descriptor.clone())
        );
        assert_eq!(
            block_on(repo.fetch(&descriptor.release_digest)).unwrap(),
            expected
        );
        let second = repo
            .execution_eligibility(&descriptor.release_digest)
            .unwrap()
            .unwrap();
        second.with_current(&mut |checker| checker.check()).unwrap();
        release.send(()).unwrap();
        first.join().unwrap();
    });
}

#[test]
fn publication_observer_never_retries_noncontention_errors() {
    for (code, message, retryable) in [
        (
            PlatformErrorCode::Unavailable,
            "release-lifecycle-unavailable",
            false,
        ),
        (
            PlatformErrorCode::Unavailable,
            "release-lifecycle-busy",
            false,
        ),
        (
            PlatformErrorCode::CorruptArtifact,
            "release-lifecycle-busy",
            true,
        ),
        (
            PlatformErrorCode::Unavailable,
            "admission-authority-busy",
            true,
        ),
    ] {
        assert!(!retryable_contention(&PlatformError {
            code,
            message: message.to_owned(),
            retryable,
            details: Vec::new(),
        }));
    }
}

#[test]
fn completion_between_absent_resolve_and_writer_check_is_not_a_failure() {
    let temp = TempRoot::new();
    let repo = Arc::new(repository(temp.path()));
    let expected = artifact("scheduled", b"scheduled-component");
    let query = ArtifactQuery {
        reference: None,
        release_digest: Some(expected.descriptor.release_digest.clone()),
        media_type: None,
    };
    let (start, wait) = mpsc::channel();
    let writer_repo = Arc::clone(&repo);
    let writer_artifact = expected.clone();
    let writer = thread::spawn(move || {
        wait.recv_timeout(Duration::from_secs(5))
            .expect("reader first observed absence");
        block_on(writer_repo.publish(writer_artifact))
    });
    let deadline = Instant::now() + Duration::from_secs(10);
    let mut scheduled = false;
    let actual = wait_for_publication(
        &repo,
        &query,
        writer,
        deadline,
        |writer| {
            assert!(
                !scheduled,
                "the forced absent observation happens exactly once"
            );
            scheduled = true;
            start.send(()).expect("unblock publisher after None");
            while !writer.is_finished() {
                assert!(
                    Instant::now() < deadline,
                    "coordinated writer did not finish"
                );
                thread::yield_now();
            }
        },
        || {},
        || {},
    )
    .expect("a successful intervening publication must remain visible");
    assert!(scheduled);
    assert_eq!(actual, expected);
}

#[test]
fn publication_visibility_wait_reports_writer_failure_promptly() {
    let temp = TempRoot::new();
    let repo = Arc::new(repository(temp.path()));
    repo.inject_parent_sync_failure_once();
    let expected = artifact("atomic-failure", b"atomic-failure-component");
    let query = ArtifactQuery {
        reference: None,
        release_digest: Some(expected.descriptor.release_digest.clone()),
        media_type: None,
    };
    let writer_repo = Arc::clone(&repo);
    let writer = thread::spawn(move || block_on(writer_repo.publish(expected)));
    let failure = wait_for_publication(
        &repo,
        &query,
        writer,
        Instant::now() + Duration::from_secs(5),
        |_| {},
        || {},
        || {},
    )
    .expect_err("injected writer failure");
    assert!(failure.contains("Internal"), "{failure}");
    assert!(!failure.contains("deadline"), "{failure}");
}

#[test]
fn publication_visibility_wait_reports_writer_panic_promptly() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let query = ArtifactQuery {
        reference: None,
        release_digest: Some(release_digest(b"panic")),
        media_type: None,
    };
    let writer = thread::spawn(|| panic!("injected writer panic"));
    let failure = wait_for_publication(
        &repo,
        &query,
        writer,
        Instant::now() + Duration::from_secs(5),
        |_| {},
        || {},
        || {},
    )
    .expect_err("writer panic");
    assert_eq!(failure, "publication writer panicked");
}
