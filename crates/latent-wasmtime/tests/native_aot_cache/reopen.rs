use super::support::{artifact, publish, Fixture, KEY};

#[tokio::test(flavor = "current_thread")]
async fn real_miss_invokes_then_reopened_native_hit_verifies_source_without_compiling() {
    let fixture = Fixture::new();
    let repository = fixture.catalog();
    let release = publish(&repository, false).await;
    let session = fixture.session(repository.clone(), KEY);
    let before = repository.verification_snapshot();
    let ready = session.prepare(repository.clone(), &release).await.unwrap();
    let first = session.snapshot();
    assert_eq!(first.isolated_compilations, 1);
    assert_eq!(first.images.loader_attempts, 1);
    assert_eq!(first.cache_misses, 1);
    assert_eq!(first.cache_hits, 0);
    assert_eq!(first.receipts.entries, 1);
    assert_eq!(
        repository.verification_snapshot().full_fetch_attempts - before.full_fetch_attempts,
        1
    );
    session.answer(ready).await;
    session.idle();

    let before_warm = repository.verification_snapshot();
    let resident = session.prepare(repository.clone(), &release).await.unwrap();
    assert_eq!(repository.verification_snapshot(), before_warm);
    assert_eq!(session.snapshot().isolated_compilations, 1);
    assert_eq!(session.snapshot().images.loader_attempts, 1);
    drop(resident);
    // Every factory, cache and catalog owner is gone before opening the same
    // roots again. Persistent reuse cannot be an old in-memory prepared hit.
    drop(session);
    drop(repository);

    let repository = fixture.catalog();
    let reopened = fixture.session(repository.clone(), KEY);
    let before = repository.verification_snapshot();
    let active = reopened
        .prepare_borrowed(repository.as_ref(), &release)
        .await
        .unwrap();
    let after = repository.verification_snapshot();
    assert_eq!(after.full_fetch_attempts - before.full_fetch_attempts, 1);
    assert_eq!(
        after.component_verification_attempts - before.component_verification_attempts,
        1
    );
    assert_eq!(
        after.component_bytes_hashed - before.component_bytes_hashed,
        artifact(false).component_bytes.len() as u64
    );
    let snapshot = reopened.snapshot();
    assert_eq!(snapshot.isolated_compilations, 0);
    assert_eq!(snapshot.cache_hits, 1);
    assert_eq!(snapshot.cache_misses, 0);
    assert_eq!(snapshot.cache_rejections, 0);
    assert_eq!(snapshot.images.loader_attempts, 1);
    reopened.answer_active(active).await;
    reopened.idle();
}
