use super::*;
use latent_core::PlatformError;
use std::sync::mpsc;

// Both the successful and injected-failure tests use this same observer.
// The hook deterministically exercises completion after an absent observation.
fn wait_for_publication(
    repo: &DirectoryArtifactRepository,
    query: &ArtifactQuery,
    writer: thread::JoinHandle<Result<ArtifactDescriptor, PlatformError>>,
    deadline: Instant,
    mut after_absent: impl FnMut(&thread::JoinHandle<Result<ArtifactDescriptor, PlatformError>>),
) -> Result<CapsuleArtifact, String> {
    loop {
        let observed =
            block_on(repo.resolve(query)).map_err(|error| format!("resolve: {error:?}"))?;
        if let Some(descriptor) = observed {
            let complete = block_on(repo.fetch(&descriptor.release_digest))
                .map_err(|error| format!("visible release was incomplete: {error:?}"))?;
            if complete.descriptor != descriptor {
                return Err("visible descriptor disagrees with complete fetch".to_owned());
            }
        } else {
            after_absent(&writer);
        }
        if writer.is_finished() {
            let descriptor = writer
                .join()
                .map_err(|_| "publication writer panicked".to_owned())?
                .map_err(|error| format!("publication writer failed: {error:?}"))?;
            // The earlier None preceded the join. Only this fresh observation
            // can establish visibility after a successful publication.
            let visible = block_on(repo.resolve(query))
                .map_err(|error| format!("resolve after join: {error:?}"))?;
            if visible.as_ref() != Some(&descriptor) {
                return Err("successful writer did not leave a visible release".to_owned());
            }
            return block_on(repo.fetch(&descriptor.release_digest))
                .map_err(|error| format!("fetch after join: {error:?}"));
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
    )
    .expect("complete publication");
    assert_eq!(actual, expected);
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
    let actual = wait_for_publication(&repo, &query, writer, deadline, |writer| {
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
    })
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
    )
    .expect_err("writer panic");
    assert_eq!(failure, "publication writer panicked");
}
