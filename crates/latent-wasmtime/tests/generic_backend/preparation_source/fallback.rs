use std::sync::atomic::{AtomicUsize, Ordering};
use std::task::{Context, Waker};

use latent_artifacts::ArtifactRepository;
use latent_core::PlatformErrorCode;
use latent_executor::ExecutionBackend;
use latent_wasmtime::WasmtimeComponentEngineFactory;

use super::super::support::{artifact_bytes, config, VALUES};
use super::support::{no_reservations, Directory, Repository};

#[test]
fn abandoned_untrusted_fetch_releases_capacity_and_full_gate_never_fetches() {
    let mut bounded = config();
    bounded.maximum_active_instances = 1;
    let factory = WasmtimeComponentEngineFactory::new(bounded).unwrap();
    let backend = factory.create_backend_instance();
    let value = artifact_bytes(b"pending fixture".to_vec(), &[VALUES]);
    let key = factory.preparation_key(value.descriptor.release_digest);
    let repository = Repository {
        source: None,
        fallback: None,
        fetches: AtomicUsize::new(0),
    };
    let mut pending = backend.prepare_from_repository(&repository, &key);
    let mut context = Context::from_waker(Waker::noop());
    assert!(pending.as_mut().poll(&mut context).is_pending());
    assert_eq!(backend.active_instance_reservations(), 1);
    assert_eq!(repository.fetches.load(Ordering::Relaxed), 1);
    let mut blocked = backend.prepare_from_repository(&repository, &key);
    let std::task::Poll::Ready(Err(error)) = blocked.as_mut().poll(&mut context) else {
        panic!("a full gate must reject before another fetch");
    };
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    assert!(error.retryable);
    assert_eq!(repository.fetches.load(Ordering::Relaxed), 1);
    drop(blocked);
    drop(pending);
    no_reservations(&backend);
}

#[tokio::test(flavor = "current_thread")]
async fn untrusted_bytes_descriptor_length_and_requested_digest_are_all_bound() {
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    let value = artifact_bytes(b"digest-only fixture".to_vec(), &[VALUES]);
    let key = factory.preparation_key(value.descriptor.release_digest.clone());
    for fault in 0..4 {
        let mut changed = value.clone();
        match fault {
            0 => changed.component_bytes[0] ^= 1,
            1 => changed.descriptor.size_bytes += 1,
            2 => changed.descriptor.release_digest.0.push('0'),
            _ => changed.manifest.component_digest.0.push('0'),
        }
        let repository = Repository {
            source: None,
            fallback: Some(changed),
            fetches: AtomicUsize::new(0),
        };
        let error = backend
            .prepare_from_repository(&repository, &key)
            .await
            .unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);
        assert_eq!(repository.fetches.load(Ordering::Relaxed), 1);
        no_reservations(&backend);
        assert_eq!(backend.cache_snapshot().misses, 0);
    }
}

#[tokio::test(flavor = "current_thread")]
async fn declared_digest_case_is_accepted_but_requested_key_stays_canonical() {
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    // A valid empty component reaches surface validation only after digest checks.
    let mut value = artifact_bytes(b"\0asm\x0d\0\x01\0".to_vec(), &[VALUES]);
    let key = factory.preparation_key(value.descriptor.release_digest.clone());
    value.descriptor.release_digest.0.make_ascii_uppercase();
    value.manifest.component_digest.0.make_ascii_uppercase();
    assert_eq!(
        backend.prepare(&value, &key).await.unwrap_err().code,
        PlatformErrorCode::IncompatibleContract
    );
    assert_eq!(backend.cache_snapshot().misses, 1);
    let mut noncanonical = key;
    noncanonical.release.0.make_ascii_uppercase();
    assert_eq!(
        backend
            .prepare(&value, &noncanonical)
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::CorruptArtifact
    );
    assert_eq!(backend.cache_snapshot().misses, 1);
    assert_eq!(backend.preparation_activity_snapshot().component_hashes, 2);
    no_reservations(&backend);
}

#[tokio::test(flavor = "current_thread")]
async fn authenticated_size_and_metadata_bounds_reject_before_fetch_or_reservation() {
    let directory = Directory::new();
    let repository = directory.open();
    let value = artifact_bytes(b"bounded source fixture".to_vec(), &[VALUES]);
    let release = repository
        .publish(value.clone())
        .await
        .unwrap()
        .release_digest;
    let verified = repository.verification_snapshot();
    for limit in 0..2 {
        let mut bounded = config();
        if limit == 0 {
            bounded.maximum_component_bytes = value.component_bytes.len() - 1;
        } else {
            bounded.maximum_artifact_metadata_bytes = 1;
        }
        let factory = WasmtimeComponentEngineFactory::new(bounded).unwrap();
        let backend = factory.create_backend_instance();
        let key = factory.preparation_key(release.clone());
        assert_eq!(
            backend
                .prepare_from_repository(&repository, &key)
                .await
                .unwrap_err()
                .code,
            PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(repository.verification_snapshot(), verified);
        assert_eq!(backend.cache_snapshot().misses, 0);
        assert_eq!(
            backend.preparation_activity_snapshot().repository_fetches,
            0
        );
        no_reservations(&backend);
    }
}
