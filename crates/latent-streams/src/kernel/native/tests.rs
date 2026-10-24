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

#[test]
fn close_status_preserves_original_expiry_and_never_accepts_ready_as_retirement() {
    let expiry = ReadyExpiry(123);
    assert_eq!(
        close_status(&frame(CLOSED, 123), expiry).unwrap(),
        StreamKernelCloseObservation::RequestAccepted
    );
    for phase in [0, 1, READY, 3, 5, u32::MAX] {
        assert!(close_status(&frame(phase, 123), expiry).is_err());
    }
    assert!(close_status(&frame(CLOSED, 124), expiry).is_err());
    for offset in [0, 4, 12] {
        let mut wrong = frame(CLOSED, 123);
        wrong[offset] ^= 1;
        assert!(close_status(&wrong, expiry).is_err());
    }
}

#[test]
fn real_file_close_transfer_keeps_exact_frame_and_refuses_short_or_error_reply() {
    use std::io::{Read, Seek, SeekFrom};
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("fixed-close-wire");
    for (reply, expected) in [
        (
            frame(CLOSED, 123).to_vec(),
            StreamKernelCloseObservation::RequestAccepted,
        ),
        (
            frame(READY, 123).to_vec(),
            StreamKernelCloseObservation::Uncertain,
        ),
        (
            frame(CLOSED, 124).to_vec(),
            StreamKernelCloseObservation::Uncertain,
        ),
        (
            frame(CLOSED, 123)[..12].to_vec(),
            StreamKernelCloseObservation::Uncertain,
        ),
    ] {
        let mut content = vec![0; FRAME_BYTES];
        content.extend_from_slice(&reply);
        std::fs::write(&path, content).unwrap();
        let mut file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .unwrap();
        assert_eq!(close_request(&mut file, ReadyExpiry(123)), expected);
        assert_eq!(
            file.stream_position().unwrap(),
            (FRAME_BYTES + reply.len()) as u64
        );
        file.seek(SeekFrom::Start(0)).unwrap();
        let mut request = [0; FRAME_BYTES];
        file.read_exact(&mut request).unwrap();
        assert_eq!(request, frame(CLOSE, 123));
    }
    let mut readonly = File::open(&path).unwrap();
    assert_eq!(
        close_request(&mut readonly, ReadyExpiry(123)),
        StreamKernelCloseObservation::Uncertain
    );
    assert_eq!(readonly.stream_position().unwrap(), 0);
}

#[tokio::test]
async fn fixed_file_close_receipt_stays_paid_until_drop_without_refunding_backing() {
    let fixture = Fixture::new(config());
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("fixed-close-owner");
    let mut content = vec![0; FRAME_BYTES];
    content.extend_from_slice(&frame(CLOSED, 123));
    std::fs::write(&path, content).unwrap();
    let original = path.clone();
    let (send, receive) = tokio::sync::oneshot::channel();
    // Private real-file seam only; this control does not claim kernel READY.
    let owner = start_initialized_with(
        Arc::clone(&fixture.pools),
        &fixture.provider.inner.installed,
        Instant::now() + Duration::from_secs(5),
        move || {
            std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .open(path)
                .map_err(|_| error(StreamErrorCode::IoFailed))
        },
        move |file, _| {
            send.send(descriptor(file)).unwrap();
            Ok(Some(ReadyExpiry(123)))
        },
    )
    .await
    .unwrap();
    let link = receive.await.unwrap();
    let ready = stable_snapshot(&fixture.pools).await;
    let receipt = owner.close().unwrap().wait().await.unwrap();
    assert_eq!(
        receipt.observation(),
        StreamKernelCloseObservation::RequestAccepted
    );
    assert_ne!(std::fs::read_link(link).ok(), Some(original.clone()));
    let held = stable_snapshot(&fixture.pools).await;
    assert_eq!(held.connections, 1);
    assert_eq!(held.failed_cleanup, 1);
    assert_eq!(held.cleanup_jobs, ready.cleanup_jobs + 1);
    assert!(held.metadata_bytes >= 1024 * 1024);
    assert_eq!(
        &std::fs::read(original).unwrap()[..FRAME_BYTES],
        &frame(CLOSE, 123)
    );
    drop(receipt);
    // Receipt consumption can beat the original sender/worker tail. Its shared
    // billing must remain until that tail returns; lock access is not completion.
    let retained = tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let retained = stable_snapshot(&fixture.pools).await;
            assert_eq!(retained.connections, 1);
            assert_eq!(retained.failed_cleanup, 1);
            assert!(retained.metadata_bytes >= 1024 * 1024);
            if retained.cleanup_jobs == ready.cleanup_jobs {
                break retained;
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .expect("original sender/worker tail must return while backing stays held");
    assert_eq!(retained.cleanup_jobs, ready.cleanup_jobs);
    assert!(retained.metadata_bytes < held.metadata_bytes);
    assert_eq!(retained.connections, 1);
    assert_eq!(retained.failed_cleanup, 1);
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
    let ready = stable_snapshot(&fixture.pools).await;
    assert_eq!(ready.failed_cleanup, 0);
    assert_eq!(ready.cleanup_jobs, before.cleanup_jobs + 1);
    drop(owner);
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let snapshot = stable_snapshot(&fixture.pools).await;
            // The quarantined connection retains its original maintenance
            // permit; only the additional physical close job must retire.
            if snapshot.failed_cleanup == 1 && snapshot.cleanup_jobs == ready.cleanup_jobs {
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
