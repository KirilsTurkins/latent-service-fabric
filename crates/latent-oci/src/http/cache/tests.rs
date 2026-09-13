#![cfg(unix)]

use super::*;
use crate::{RegistryConfig, RegistryCredentials, RegistryLimits};
use latent_artifacts::{package::artifact_blob_digest, RawArtifactCacheLimits};
use std::{sync::mpsc, time::Duration};
use tokio::{
    sync::oneshot,
    time::{timeout, Instant},
};

#[tokio::test]
async fn completed_disk_result_is_rejected_when_consumer_polls_after_deadline() {
    use std::{
        future::{poll_fn, Future},
        task::Poll,
    };

    let root = tempfile::tempdir().unwrap();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    let registry = registry(cache);
    let mut operation = registry.transport.begin(0).unwrap();
    let deadline = Instant::now() + Duration::from_secs(1);
    operation.deadline = deadline;
    let mut buffer = BlobBuffer::new(registry.transport.lease_bytes(6).unwrap());
    buffer.bytes = b"worker".to_vec();
    let (release, held) = mpsc::channel();
    let work = owned_job(Arc::new(operation), buffer, move |_| {
        held.recv_timeout(Duration::from_secs(3)).unwrap();
        Ok(())
    });
    tokio::pin!(work);
    // Spawn the disk job and register its waiter, then deliberately stop polling
    // this future until after the absolute operation deadline.
    poll_fn(|context| {
        assert!(work.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
    release.send(()).unwrap();
    timeout(Duration::from_secs(2), async {
        while registry.usage().in_flight != 0 {
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(registry.usage().retained_bytes, 6);
    tokio::time::sleep_until(deadline + Duration::from_millis(1)).await;
    assert_eq!(
        work.await.unwrap_err().code,
        PlatformErrorCode::DeadlineExceeded
    );
    assert_eq!(registry.usage().retained_bytes, 0);
}

fn registry(cache: Arc<RawArtifactCache>) -> HttpOciRegistry {
    HttpOciRegistry::new_with_cache(
        RegistryConfig {
            origin: "http://127.0.0.1:1".to_owned(),
            repository: "test/cache".to_owned(),
            credentials: RegistryCredentials::Anonymous,
            addresses: Vec::new(),
            additional_root_certificates: Vec::new(),
            allow_insecure_loopback: true,
            limits: RegistryLimits {
                max_in_flight: 1,
                max_retained_bytes: 6,
                ..RegistryLimits::default()
            },
        },
        cache,
    )
    .unwrap()
}

#[tokio::test]
async fn canceled_blocking_write_retains_transfer_bytes_and_cache_owner_until_stop() {
    let root = tempfile::tempdir().unwrap();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    let registry = registry(cache.clone());
    let operation = Arc::new(registry.transport.begin(0).unwrap());
    let mut graph = registry.transport.lease_bytes(6).unwrap();
    let mut buffer = BlobBuffer::new(graph.split(6).unwrap());
    buffer.bytes = b"worker".to_vec();
    let write = cache
        .reserve_write(RawArtifactKey::Blob(artifact_blob_digest(b"worker")), 6)
        .unwrap();
    let (entered, running) = oneshot::channel();
    let (release, held) = mpsc::channel();
    let task = tokio::spawn(owned_job(operation, buffer, move |buffer| {
        entered.send(()).unwrap();
        held.recv_timeout(Duration::from_secs(3)).unwrap();
        drop(write.publish(&buffer.bytes)?);
        Ok(())
    }));
    timeout(Duration::from_secs(2), running)
        .await
        .unwrap()
        .unwrap();
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    drop(graph); // The detached worker owns the split bytes, never a borrow.
    assert_eq!(registry.usage().retained_bytes, 6);
    assert_eq!(registry.usage().in_flight, 1);
    assert_eq!(cache.snapshot().unwrap().reserved_disk_bytes, 6);
    assert_eq!(cache.snapshot().unwrap().active_work, 1);
    assert!(registry.transport.begin(0).is_err());
    assert_eq!(
        registry
            .shutdown(Instant::now() + Duration::from_millis(10))
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::DeadlineExceeded
    );
    release.send(()).unwrap();
    timeout(Duration::from_secs(2), async {
        while registry.usage().in_flight != 0 || registry.usage().retained_bytes != 0 {
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(cache.snapshot().unwrap().active_work, 0);
    assert_eq!(cache.snapshot().unwrap().resident_disk_bytes, 6);
    registry
        .shutdown(Instant::now() + Duration::from_secs(1))
        .await
        .unwrap();
}

#[tokio::test]
async fn canceled_blocking_read_retains_file_pin_read_bytes_and_registry_permit() {
    let root = tempfile::tempdir().unwrap();
    let cache = RawArtifactCache::open(root.path(), RawArtifactCacheLimits::default()).unwrap();
    let pin = cache
        .reserve_write(RawArtifactKey::Blob(artifact_blob_digest(b"worker")), 6)
        .unwrap()
        .publish(b"worker")
        .unwrap();
    let read = pin.reserve_read(6).unwrap();
    let registry = registry(cache.clone());
    let operation = Arc::new(registry.transport.begin(0).unwrap());
    let mut buffer = BlobBuffer::new(registry.transport.lease_bytes(6).unwrap());
    buffer.bytes = vec![0; 6];
    let (entered, running) = oneshot::channel();
    let (release, held) = mpsc::channel();
    let task = tokio::spawn(owned_job(operation, buffer, move |buffer| {
        entered.send(()).unwrap();
        held.recv_timeout(Duration::from_secs(3)).unwrap();
        read.read_into(&mut buffer.bytes)
    }));
    timeout(Duration::from_secs(2), running)
        .await
        .unwrap()
        .unwrap();
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    let held = cache.snapshot().unwrap();
    assert_eq!(
        (
            held.pinned_disk_bytes,
            held.reserved_read_bytes,
            held.active_reads
        ),
        (6, 6, 1)
    );
    assert_eq!(registry.usage().retained_bytes, 6);
    assert_eq!(registry.usage().in_flight, 1);
    release.send(()).unwrap();
    timeout(Duration::from_secs(2), async {
        while registry.usage().in_flight != 0 || registry.usage().retained_bytes != 0 {
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap();
    let released = cache.snapshot().unwrap();
    assert_eq!(
        (
            released.pinned_disk_bytes,
            released.reserved_read_bytes,
            released.active_reads
        ),
        (0, 0, 0)
    );
}
