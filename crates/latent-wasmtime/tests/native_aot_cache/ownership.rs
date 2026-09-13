use super::support::{publish, revoke, Fixture, KEY};
use super::{component, runtime};
use latent_executor::ExecutionBackend;

#[tokio::test(flavor = "current_thread")]
async fn evicted_ready_handle_keeps_its_image_and_revocation_never_recovers_from_native_cache() {
    let fixture = Fixture::new();
    let repository = fixture.catalog();
    let first_release = publish(&repository, false).await;
    let second_release = publish(&repository, true).await;
    let session = fixture.session(repository.clone(), KEY);
    let first = session
        .prepare(repository.clone(), &first_release)
        .await
        .unwrap();
    let first_bytes = session.snapshot().images.bytes;
    assert!(first_bytes > 0);
    let second = session
        .prepare(repository.clone(), &second_release)
        .await
        .unwrap();
    let both = session.snapshot();
    assert_eq!(session.backend.cache_snapshot().maximum_entries, 1);
    assert_eq!(session.backend.cache_snapshot().entries, 1);
    assert_eq!(session.backend.cache_snapshot().evictions, 1);
    assert_eq!(both.images.images, 2);
    assert!(both.images.bytes > first_bytes);
    assert_eq!(both.images.loading_images, 0);
    drop(second);
    assert_eq!(session.snapshot().images.images, 2);
    // The first runtime is absent from the resident cache, but readiness still
    // owns its complete mapping and can materialize and invoke it safely.
    session.answer(first).await;
    assert_eq!(session.snapshot().images.images, 1);
    assert_eq!(
        session.snapshot().images.bytes,
        both.images.bytes - first_bytes
    );

    let queued = session
        .prepare(repository.clone(), &second_release)
        .await
        .unwrap();
    let active = session
        .backend
        .materialize_ready(
            session
                .prepare(repository.clone(), &second_release)
                .await
                .unwrap(),
        )
        .unwrap();
    let cancellation = runtime::Cancellation::new("native-cache-revoked-before-poll");
    let request = runtime::request(
        active.prepared.descriptor().clone(),
        &cancellation.id,
        component::CONTRACT,
        "answer",
        b"[]",
        runtime::budget(),
    );
    let invocation =
        session
            .backend
            .invoke_prepared_contained(request, active.prepared, &cancellation);
    let before = session.snapshot();
    revoke(&repository, &second_release).await;
    assert!(invocation.await.outcome.is_err());
    assert!(session.backend.materialize_ready(queued).is_err());
    assert!(session
        .prepare(repository.clone(), &second_release)
        .await
        .is_err());
    assert_eq!(
        session.snapshot().images.loader_attempts,
        before.images.loader_attempts
    );
    assert_eq!(
        session.snapshot().isolated_compilations,
        before.isolated_compilations
    );
    session.idle();
    drop(session);
    drop(repository);

    let repository = fixture.catalog();
    let reopened = fixture.session(repository.clone(), KEY);
    assert!(reopened
        .prepare(repository.clone(), &second_release)
        .await
        .is_err());
    let snapshot = reopened.snapshot();
    assert_eq!(snapshot.images.loader_attempts, 0);
    assert_eq!(snapshot.images.images, 0);
    assert_eq!(snapshot.isolated_compilations, 0);
    assert_eq!(snapshot.cache_hits, 0);
    reopened.idle();
}
