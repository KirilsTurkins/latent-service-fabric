//! Real Linux descriptors and the original node pool; no custom kernel claim.
use super::*;
use crate::tests::{config, fixture::Fixture};
use std::{
    os::fd::AsRawFd,
    path::PathBuf,
    sync::atomic::{AtomicBool, Ordering},
    time::Duration,
};

fn descriptor(file: &File) -> PathBuf {
    PathBuf::from(format!("/proc/self/fd/{}", file.as_raw_fd()))
}

fn is_snapshot_busy(failure: &latent_core::PlatformError) -> bool {
    failure.code == latent_core::PlatformErrorCode::ResourceExhausted
        && failure.message == "capability-busy"
}

async fn stable_snapshot(
    pools: &ProviderPools,
) -> latent_capabilities::broker::pools::ProviderPoolSnapshot {
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            match pools.snapshot() {
                Ok(snapshot) => return snapshot,
                Err(failure) if is_snapshot_busy(&failure) => {
                    tokio::time::sleep(Duration::from_millis(1)).await;
                }
                Err(failure) => panic!("unexpected pool inspection error: {failure:?}"),
            }
        }
    })
    .await
    .expect("original bookkeeping must release within this test deadline")
}

fn blocking_snapshot(
    pools: &ProviderPools,
) -> latent_capabilities::broker::pools::ProviderPoolSnapshot {
    let expires = Instant::now() + Duration::from_secs(1);
    loop {
        match pools.snapshot() {
            Ok(snapshot) => return snapshot,
            Err(failure) if is_snapshot_busy(&failure) && Instant::now() < expires => {
                std::thread::sleep(Duration::from_millis(1));
            }
            Err(failure) => panic!("original blocking-job inspection failed: {failure:?}"),
        }
    }
}

async fn quarantined(pools: &ProviderPools) {
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if stable_snapshot(pools).await.failed_cleanup == 1 {
                break;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .expect("actual blocking owner returned to bounded quarantine");
}

#[test]
fn fixed_wire_rejects_wrong_expiry_error_and_unknown_phase() {
    let good = frame(READY, 123);
    assert_eq!(status(&good, 123).unwrap(), READY);
    assert!(status(&good, 124).is_err());
    let mut bad = good;
    bad[12] = 1;
    assert!(status(&bad, 123).is_err());
    assert!(status(&frame(4, 123), 123).is_err());
    assert!(status(&frame(0, 123), 123).is_err());
    bad = good;
    bad[4] = 1;
    assert!(status(&bad, 123).is_err());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn exhausted_node_allowance_refuses_before_any_open() {
    let fixture = Fixture::new(config());
    let entered = Arc::new(AtomicBool::new(false));
    let mut holds = Vec::new();
    while let Ok(charge) = fixture.pools.reserve_protocol_metadata(1024 * 1024) {
        holds.push(charge);
    }
    let before = stable_snapshot(&fixture.pools).await;
    let flag = Arc::clone(&entered);
    assert!(start_with(
        Arc::clone(&fixture.pools),
        &fixture.provider.inner.installed,
        Instant::now() + Duration::from_secs(5),
        move || {
            flag.store(true, Ordering::Release);
            File::open("/dev/null").map_err(|_| error(StreamErrorCode::IoFailed))
        },
        |_, _| Ok(())
    )
    .await
    .is_err());
    assert!(!entered.load(Ordering::Acquire));
    assert_eq!(stable_snapshot(&fixture.pools).await, before);
    drop(holds);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn possible_failed_open_retains_original_node_charge() {
    let fixture = Fixture::new(config());
    let before = stable_snapshot(&fixture.pools).await;
    let inspect = Arc::clone(&fixture.pools);
    assert!(start_with(
        Arc::clone(&fixture.pools),
        &fixture.provider.inner.installed,
        Instant::now() + Duration::from_secs(5),
        move || {
            let admitted = blocking_snapshot(&inspect);
            assert!(admitted.metadata_bytes >= before.metadata_bytes + 1024 * 1024);
            assert_eq!(admitted.connections, before.connections + 1);
            Err(error(StreamErrorCode::Unsupported))
        },
        |_, _| panic!("failed open cannot initialize")
    )
    .await
    .is_err());
    quarantined(&fixture.pools).await;
    let retained = stable_snapshot(&fixture.pools).await;
    assert_eq!(retained.connections, before.connections + 1);
    assert!(retained.metadata_bytes >= before.metadata_bytes + 1024 * 1024);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn postopen_failure_closes_real_fd_without_refunding_backing() {
    let fixture = Fixture::new(config());
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("postopen-owner");
    let original = path.clone();
    let (send, receive) = tokio::sync::oneshot::channel();
    let before = stable_snapshot(&fixture.pools).await;
    assert!(start_with(
        Arc::clone(&fixture.pools),
        &fixture.provider.inner.installed,
        Instant::now() + Duration::from_secs(5),
        move || { File::create(path).map_err(|_| error(StreamErrorCode::IoFailed)) },
        move |file, _| {
            let link = descriptor(file);
            assert_eq!(std::fs::read_link(&link).unwrap(), original);
            send.send(link).unwrap();
            Err(error(StreamErrorCode::Unsupported))
        }
    )
    .await
    .is_err());
    let link = receive.await.unwrap();
    quarantined(&fixture.pools).await;
    assert_ne!(
        std::fs::read_link(link).ok(),
        Some(directory.path().join("postopen-owner"))
    );
    let retained = stable_snapshot(&fixture.pools).await;
    assert_eq!(retained.connections, 1);
    assert!(retained.metadata_bytes >= before.metadata_bytes + 1024 * 1024);
}

// Keep maintenance on this task's runtime thread so it cannot contend for the
// admission mutex during synchronous Drop. The real close still runs on the
// original blocking-worker table; refusal/retained-FD behavior is tested below.
#[tokio::test]
async fn ready_owner_drop_closes_on_original_worker_and_retains_capacity() {
    let fixture = Fixture::new(config());
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("ready-owner");
    let original = path.clone();
    let (send, receive) = tokio::sync::oneshot::channel();
    let before = stable_snapshot(&fixture.pools).await;
    let owner = start_with(
        Arc::clone(&fixture.pools),
        &fixture.provider.inner.installed,
        Instant::now() + Duration::from_secs(5),
        move || File::create(path).map_err(|_| error(StreamErrorCode::IoFailed)),
        move |file, _| {
            send.send(descriptor(file)).unwrap();
            Ok(())
        },
    )
    .await
    .unwrap();
    let link = receive.await.unwrap();
    assert_eq!(std::fs::read_link(&link).unwrap(), original);
    assert_eq!(stable_snapshot(&fixture.pools).await.failed_cleanup, 0);
    drop(owner);
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let snapshot = stable_snapshot(&fixture.pools).await;
            if snapshot.failed_cleanup == 1 && snapshot.cleanup_jobs == 0 {
                break;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .expect("original close worker must finish while retaining its connection");
    assert_ne!(std::fs::read_link(link).ok(), Some(original));
    let retained = stable_snapshot(&fixture.pools).await;
    assert_eq!(retained.connections, 1);
    assert!(retained.metadata_bytes >= before.metadata_bytes + 1024 * 1024);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn abandoned_waiter_cannot_drop_running_job_or_late_returned_owner() {
    let fixture = Fixture::new(config());
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("abandoned-owner");
    let original = path.clone();
    let (entered, observed) = tokio::sync::oneshot::channel();
    let (release, blocked) = std::sync::mpsc::channel();
    let provider = fixture.provider.clone();
    let pools = Arc::clone(&fixture.pools);
    let startup = tokio::spawn(async move {
        start_with(
            pools,
            &provider.inner.installed,
            Instant::now() + Duration::from_secs(20),
            move || File::create(path).map_err(|_| error(StreamErrorCode::IoFailed)),
            move |file, _| {
                entered.send(descriptor(file)).unwrap();
                blocked.recv_timeout(Duration::from_secs(5)).unwrap();
                Ok(())
            },
        )
        .await
    });
    let link = observed.await.unwrap();
    startup.abort();
    match startup.await {
        Err(error) => assert!(error.is_cancelled()),
        Ok(_) => panic!("the logical result waiter was cancelled"),
    }
    assert_eq!(std::fs::read_link(&link).unwrap(), original);
    assert_eq!(stable_snapshot(&fixture.pools).await.connections, 1);
    release.send(()).unwrap();
    quarantined(&fixture.pools).await;
    assert_ne!(std::fs::read_link(link).ok(), Some(original));
    assert_eq!(stable_snapshot(&fixture.pools).await.connections, 1);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unavailable_cleanup_slot_keeps_fd_and_backing_without_inline_close() {
    let fixture = Fixture::new(config());
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("cleanup-refusal-owner");
    let original = path.clone();
    let (send, receive) = tokio::sync::oneshot::channel();
    let deadline = Instant::now() + Duration::from_secs(10);
    let owner = start_with(
        Arc::clone(&fixture.pools),
        &fixture.provider.inner.installed,
        deadline,
        move || File::create(path).map_err(|_| error(StreamErrorCode::IoFailed)),
        move |file, _| {
            send.send(descriptor(file)).unwrap();
            Ok(())
        },
    )
    .await
    .unwrap();
    let link = receive.await.unwrap();
    let client = fixture
        .pools
        .client::<Resource>(&fixture.provider.inner.installed, u16::MAX)
        .unwrap();
    let mut cleanup_holds = Vec::new();
    while let Ok(hold) = fixture.pools.maintenance(&client, deadline, 1) {
        cleanup_holds.push(hold);
    }
    drop(owner);
    quarantined(&fixture.pools).await;
    assert_eq!(std::fs::read_link(link).unwrap(), original);
    assert_eq!(stable_snapshot(&fixture.pools).await.connections, 1);
    drop(cleanup_holds);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cleanup_panic_keeps_original_connection_after_lost_unit_result() {
    let fixture = Fixture::new(config());
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("cleanup-panic-owner");
    let original = path.clone();
    let (send, receive) = tokio::sync::oneshot::channel();
    let mut owner = start_with(
        Arc::clone(&fixture.pools),
        &fixture.provider.inner.installed,
        Instant::now() + Duration::from_secs(10),
        move || File::create(path).map_err(|_| error(StreamErrorCode::IoFailed)),
        move |file, _| {
            send.send(descriptor(file)).unwrap();
            Ok(())
        },
    )
    .await
    .unwrap();
    let link = receive.await.unwrap();
    let connection = owner.connection.take().unwrap();
    let job = match fixture.pools.cleanup_blocking_quarantined(connection, |_| {
        panic!("physical close interrupted before descriptor take")
    }) {
        Ok(job) => job,
        Err(_) => panic!("admitted exact cleanup"),
    };
    assert!(job.wait().await.is_err());
    quarantined(&fixture.pools).await;
    assert_eq!(std::fs::read_link(link).unwrap(), original);
    assert_eq!(stable_snapshot(&fixture.pools).await.connections, 1);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn original_deadline_does_not_refund_a_blocked_native_constructor() {
    let fixture = Fixture::new(config());
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("deadline-owner");
    let original = path.clone();
    let (entered, observed) = tokio::sync::oneshot::channel();
    let (release, blocked) = std::sync::mpsc::channel();
    let provider = fixture.provider.clone();
    let pools = Arc::clone(&fixture.pools);
    let startup = tokio::spawn(async move {
        start_with(
            pools,
            &provider.inner.installed,
            Instant::now() + Duration::from_secs(1),
            move || File::create(path).map_err(|_| error(StreamErrorCode::IoFailed)),
            move |file, _| {
                entered.send(descriptor(file)).unwrap();
                blocked.recv_timeout(Duration::from_secs(5)).unwrap();
                Ok(())
            },
        )
        .await
    });
    let link = observed.await.unwrap();
    match startup.await.unwrap() {
        Err(failure) => assert_eq!(failure.code, StreamErrorCode::Timeout),
        Ok(_) => panic!("the physical constructor remains blocked"),
    }
    assert_eq!(std::fs::read_link(&link).unwrap(), original);
    assert_eq!(stable_snapshot(&fixture.pools).await.connections, 1);
    release.send(()).unwrap();
    quarantined(&fixture.pools).await;
    assert_ne!(std::fs::read_link(link).ok(), Some(original));
    assert_eq!(stable_snapshot(&fixture.pools).await.connections, 1);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn constructor_panic_retains_prepaid_backing_and_closes_real_fd() {
    let fixture = Fixture::new(config());
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("constructor-panic-owner");
    let original = path.clone();
    let (send, receive) = tokio::sync::oneshot::channel();
    assert!(start_with(
        Arc::clone(&fixture.pools),
        &fixture.provider.inner.installed,
        Instant::now() + Duration::from_secs(5),
        move || File::create(path).map_err(|_| error(StreamErrorCode::IoFailed)),
        move |file, _| {
            send.send(descriptor(file)).unwrap();
            panic!("constructor unwound after actual open");
        }
    )
    .await
    .is_err());
    let link = receive.await.unwrap();
    quarantined(&fixture.pools).await;
    assert_ne!(std::fs::read_link(link).ok(), Some(original));
    assert_eq!(stable_snapshot(&fixture.pools).await.connections, 1);
}
