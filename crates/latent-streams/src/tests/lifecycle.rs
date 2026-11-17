use super::{config, fixture::Fixture};
use crate::{StreamErrorCode, StreamLifecycle};
use latent_capabilities::broker::network::{OutboundStreamInvoker, StreamConnectRequest};
use std::{
    future::Future,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    task::{Context, Poll, Wake, Waker},
    time::{Duration, Instant},
};
use tokio::{io::AsyncReadExt, net::TcpListener};

#[derive(Clone, Copy, PartialEq, Eq)]
enum DrainLockCase {
    ReleasedBeforeDeadline,
    HeldPastDeadline,
    ConnectionRegistry,
}

async fn drain_with_contended_snapshot(case: DrainLockCase) {
    use std::sync::{mpsc, Mutex};

    struct HoldAfterWake {
        thread: std::thread::ThreadId,
        armed: AtomicBool,
        request: mpsc::Sender<()>,
        acquired: Mutex<mpsc::Receiver<()>>,
    }
    impl Wake for HoldAfterWake {
        fn wake(self: Arc<Self>) {
            self.wake_by_ref();
        }
        fn wake_by_ref(self: &Arc<Self>) {
            if std::thread::current().id() == self.thread
                && self.armed.swap(false, Ordering::AcqRel)
            {
                self.request.send(()).unwrap();
                self.acquired
                    .lock()
                    .unwrap()
                    .recv_timeout(Duration::from_secs(2))
                    .unwrap();
            }
        }
    }

    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let endpoint = configuration.destinations[0].endpoint.clone();
    let fixture = Fixture::new(configuration);
    let lifecycle = Arc::new(
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap(),
    );
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let handle = lifecycle
        .start(
            &session,
            StreamConnectRequest {
                endpoint,
                timeout_millis: None,
            },
        )
        .unwrap()
        .await
        .unwrap();
    let (peer, _) = listener.accept().await.unwrap();
    let (requested, request) = mpsc::channel();
    let (acquired, wait_acquired) = mpsc::channel();
    let (release, wait_release) = mpsc::channel();
    let holding_lifecycle = lifecycle.clone();
    let holding_registry = fixture.provider.inner.connections.clone();
    let holding = std::thread::spawn(move || {
        if request.recv_timeout(Duration::from_secs(2)).is_ok() {
            let hold = || {
                let _ = acquired.send(());
                let _ = wait_release.recv_timeout(Duration::from_secs(2));
            };
            if case == DrainLockCase::ConnectionRegistry {
                let _state = holding_registry.lock_for_test();
                hold();
            } else {
                holding_lifecycle.with_state_lock_for_test(hold);
            }
        }
    });
    let observer = Arc::new(HoldAfterWake {
        thread: std::thread::current().id(),
        armed: AtomicBool::new(false),
        request: requested,
        acquired: Mutex::new(wait_acquired),
    });
    let wake = Waker::from(observer.clone());
    let mut read = Box::pin(handle.read(1, None).unwrap());
    assert!(matches!(
        read.as_mut().poll(&mut Context::from_waker(&wake)),
        Poll::Pending
    ));
    observer.armed.store(true, Ordering::Release);
    let wait = if case == DrainLockCase::HeldPastDeadline {
        150
    } else {
        500
    };
    let mut drain = Box::pin(lifecycle.drain(Instant::now() + Duration::from_millis(wait)));
    let first = drain.as_mut().poll(&mut Context::from_waker(&wake));
    let pending = matches!(first, Poll::Pending);
    let initial_error = match first {
        Poll::Ready(Err(error)) => Some(error.code),
        _ => None,
    };
    let deadline_error = if pending && case == DrainLockCase::HeldPastDeadline {
        tokio::time::sleep(Duration::from_millis(200)).await;
        match drain.as_mut().poll(&mut Context::from_waker(&wake)) {
            Poll::Ready(Err(error)) => Some(error.code),
            _ => None,
        }
    } else {
        None
    };
    let paid_during_contention = control.budget.host_memory_bytes() > baseline;
    let _ = release.send(());
    holding.join().unwrap();
    drop((read, handle, peer));
    let finished = if pending && case == DrainLockCase::ReleasedBeforeDeadline {
        Some(drain.await)
    } else {
        drop(drain);
        None
    };
    drop((lifecycle, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
    assert!(
        paid_during_contention,
        "original connection owner must remain paid during status contention"
    );
    match case {
        DrainLockCase::ReleasedBeforeDeadline => {
            assert!(
                pending,
                "drain must retry the busy lifecycle snapshot, got {initial_error:?}"
            );
            assert_eq!(finished.unwrap().unwrap().usage.owners, 0);
        }
        DrainLockCase::HeldPastDeadline => {
            assert!(pending, "drain must wait until the original deadline");
            assert_eq!(deadline_error, Some(StreamErrorCode::Exhausted));
        }
        DrainLockCase::ConnectionRegistry => {
            assert!(!pending, "non-lifecycle exhaustion must not be retried");
            assert_eq!(initial_error, Some(StreamErrorCode::Exhausted));
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn drain_waits_for_lifecycle_snapshot_lock_without_releasing_original_owner() {
    drain_with_contended_snapshot(DrainLockCase::ReleasedBeforeDeadline).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn drain_retains_original_deadline_when_lifecycle_snapshot_stays_busy() {
    drain_with_contended_snapshot(DrainLockCase::HeldPastDeadline).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn drain_does_not_retry_connection_registry_exhaustion() {
    drain_with_contended_snapshot(DrainLockCase::ConnectionRegistry).await;
}

#[tokio::test]
async fn actual_stream_socket_and_connection_layouts_are_prepaid() {
    let fixture = Fixture::new(config());
    let before = fixture.pools.snapshot().unwrap().metadata_bytes;
    let slots = fixture
        .pools
        .limits()
        .unwrap()
        .maximum_connections_per_client;
    let client = fixture
        .pools
        .client::<crate::connection::Socket>(&fixture.provider.inner.installed, 0)
        .unwrap();
    let after = fixture.pools.snapshot().unwrap().metadata_bytes;
    let actual_slot = latent_capabilities::broker::pools::stream_retained_layout_bytes::<
        crate::connection::Socket,
    >();
    assert_eq!(after - before, 4096 + slots * actual_slot);
    let (owner_bytes, chunk_bytes) = crate::connection::prepaid_layout_bytes();
    assert!(owner_bytes <= 16 * 1024);
    assert!(chunk_bytes <= 512);
    drop(client);
    fixture.clean().await;
}

#[tokio::test]
async fn failed_dial_socket_drops_before_original_connection_reservation() {
    // Keep the port bound without listening, so the refusal cannot race a
    // different test reusing a just-closed ephemeral listener.
    let unlistening = tokio::net::TcpSocket::new_v4().unwrap();
    unlistening.bind("127.0.0.1:0".parse().unwrap()).unwrap();
    let port = unlistening.local_addr().unwrap().port();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = port;
    let fixture = Fixture::new(configuration.clone());
    let (session, control) = fixture.session(5000);
    let session = Arc::new(session);
    let observer = session.observer();
    let pools = Arc::clone(&fixture.pools);
    let (sent, received) = std::sync::mpsc::sync_channel(1);
    crate::connection::observe_socket_drop(
        &session,
        Box::new(move || {
            sent.send((pools.snapshot().unwrap().connections, observer.live_calls()))
                .unwrap();
        }),
    );
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let result = fixture.provider.start(&session, request).unwrap().await;
    crate::connection::clear_socket_drop_observer();
    assert!(result.is_err());
    let (connections, live_calls) = received.recv_timeout(Duration::from_secs(2)).unwrap();
    assert_eq!(connections, 1);
    assert!(live_calls > 0);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 0);
    drop((result, session, unlistening));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

struct ReentrantWake {
    lifecycle: Arc<StreamLifecycle>,
    stopped_without_lock: AtomicBool,
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn write_input_retirement_keeps_the_original_window_until_its_tail() {
    use tokio::io::AsyncWriteExt;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration);
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request)
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    peer.write_all(b"abc").await.unwrap();
    let mut held = Vec::new();
    for _ in 0..3 {
        held.push(stream.read(1, None).unwrap().await.unwrap().unwrap());
    }
    let connection = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (reached, resume) = connection.pause_next_write_retirement();
    drop(connection);
    let before_write = control.budget.host_memory_bytes();
    let write = stream.write(b"x".to_vec(), None).unwrap();
    let admitted = control.budget.host_memory_bytes();
    let dropping = std::thread::spawn(move || drop(write));
    reached.recv_timeout(Duration::from_secs(2)).unwrap();
    let during = control.budget.host_memory_bytes();
    let refusal = match stream.read(1, None) {
        Ok(future) => {
            drop(future);
            None
        }
        Err(failure) => Some(failure.code),
    };
    resume.send(()).unwrap();
    dropping.join().unwrap();
    drop(held);
    drop(stream);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
    eprintln!(
        "write admission delta={} during_tail={during}",
        admitted - before_write
    );
    assert_eq!(refusal, Some(StreamErrorCode::Exhausted));
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retired_write_input_keeps_the_original_connection_charge() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration);
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request)
        .unwrap()
        .await
        .unwrap();
    let (_peer, _) = listener.accept().await.unwrap();
    let connection = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (reached, resume) = connection.pause_next_write_retirement();
    let write = stream.write(b"x".to_vec(), None).unwrap();
    drop(connection);
    drop(stream);
    drop(session);
    let pools = fixture.pools.clone();
    let dropping = std::thread::spawn(move || drop(write));
    reached.recv_timeout(Duration::from_secs(2)).unwrap();
    let activation_during = control.budget.host_memory_bytes();
    let metadata_during = pools.snapshot().unwrap().metadata_bytes;
    resume.send(()).unwrap();
    dropping.join().unwrap();
    let metadata_after = pools.snapshot().unwrap().metadata_bytes;
    fixture.clean().await;
    drop(fixture);
    drop(pools);
    control.assert_native_settled();
    assert!(activation_during >= 16 * 1024);
    assert!(metadata_during >= metadata_after + 16 * 1024);
}
impl Wake for ReentrantWake {
    fn wake(self: Arc<Self>) {
        self.wake_by_ref();
    }
    fn wake_by_ref(self: &Arc<Self>) {
        if self.lifecycle.status().is_ok_and(|status| status.stopped) {
            self.stopped_without_lock.store(true, Ordering::Release);
        }
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn status_releases_lifecycle_lock_before_dropping_last_observed_owner() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration);
    let lifecycle = Arc::new(
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap(),
    );
    let (session, control) = fixture.session(5000);
    let handle = lifecycle.start(&session, request).unwrap().await.unwrap();
    let (_peer, _) = listener.accept().await.unwrap();
    lifecycle.retire();
    let registry = fixture.provider.inner.connections.clone();
    let connection = registry.snapshot(0).unwrap().unwrap();
    let probe = Arc::new(ReentrantWake {
        lifecycle: lifecycle.clone(),
        stopped_without_lock: AtomicBool::new(false),
    });
    connection.wake_in_drop_tail(Waker::from(probe.clone()));
    drop(connection);
    let (reached, resume) = registry.pause_next_observed_owner();
    let observer = lifecycle.clone();
    let status = std::thread::spawn(move || observer.status());
    reached.recv_timeout(Duration::from_secs(2)).unwrap();
    drop(handle);
    resume.send(()).unwrap();
    assert!(status.join().unwrap().is_ok());
    assert!(probe.stopped_without_lock.load(Ordering::Acquire));
    drop(probe);
    drop(registry);
    drop(lifecycle);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn chunk_header_tails_keep_original_four_slot_admission() {
    use tokio::io::AsyncWriteExt;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration);
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request)
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    peer.write_all(b"abcd").await.unwrap();
    let connection = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let mut held = Vec::new();
    for _ in 0..4 {
        let (reached, resume) = connection.pause_next_chunk_drop();
        let mut chunk = stream.read(1, None).unwrap().await.unwrap().unwrap();
        let copy = chunk.copy_bytes().unwrap();
        drop(chunk);
        let thread = std::thread::spawn(move || drop(copy));
        reached.recv_timeout(Duration::from_secs(2)).unwrap();
        held.push((resume, thread));
    }
    // Each thread pauses in the original chunk owner destructor while its
    // original window remains owned by the output-slot billing value.
    let refusal = match stream.read(1, None) {
        Ok(future) => {
            drop(future);
            None
        }
        Err(failure) => Some(failure.code),
    };
    for (resume, thread) in held {
        resume.send(()).unwrap();
        thread.join().unwrap();
    }
    drop(connection);
    drop(stream);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
    assert_eq!(
        refusal,
        Some(StreamErrorCode::Exhausted),
        "four retiring original owners must keep the four chunk slots"
    );
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn last_output_copy_keeps_original_connection_charge_during_retirement() {
    use tokio::io::AsyncWriteExt;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration);
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request)
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    peer.write_all(b"x").await.unwrap();
    let connection = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (reached, resume) = connection.pause_next_chunk_drop();
    let mut chunk = stream.read(1, None).unwrap().await.unwrap().unwrap();
    let copy = chunk.copy_bytes().unwrap();
    drop(chunk);
    drop(connection);
    drop(stream);
    drop(session);
    let pools = fixture.pools.clone();
    let thread = std::thread::spawn(move || drop(copy));
    reached.recv_timeout(Duration::from_secs(2)).unwrap();
    let activation_during_tail = control.budget.host_memory_bytes();
    let metadata_during_tail = pools.snapshot().unwrap().metadata_bytes;
    resume.send(()).unwrap();
    thread.join().unwrap();
    let metadata_after = pools.snapshot().unwrap().metadata_bytes;
    eprintln!("chunk tail: activation={activation_during_tail} provider_metadata_during={metadata_during_tail} provider_metadata_after={metadata_after}");
    fixture.clean().await;
    drop(fixture);
    drop(pools);
    control.assert_native_settled();
    assert!(
        activation_during_tail >= 16 * 1024,
        "the original activation charge must cover the retiring connection"
    );
    assert!(
        metadata_during_tail >= metadata_after + 16 * 1024,
        "the original provider charge must cover the retiring connection"
    );
}

#[cfg(unix)]
#[tokio::test]
async fn same_session_foreign_scope_cannot_supply_stream_chunk_custody() {
    use tokio::io::AsyncWriteExt;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration);
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request)
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let connection = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let foreign = Arc::new(session.reserve_stream().unwrap());
    let window = foreign.reserve_bound_chunk(1).unwrap();
    let before = control.budget.host_memory_bytes();
    let error = connection.try_foreign_chunk_window(window).err().unwrap();
    assert_eq!(error.code, latent_core::PlatformErrorCode::PermissionDenied);
    assert_eq!(control.budget.host_memory_bytes(), before);
    drop(foreign);
    peer.write_all(b"x").await.unwrap();
    let mut chunk = stream.read(1, None).unwrap().await.unwrap().unwrap();
    assert!(chunk.retain_owner(Arc::new(())).is_err());
    let copy = chunk.copy_bytes().unwrap();
    drop(chunk);
    assert_eq!(copy.as_ref(), b"x");
    drop(copy);
    drop(connection);
    drop(stream);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn output_copy_connection_panic_retains_only_original_bounded_row() {
    use tokio::io::AsyncWriteExt;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration.clone());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let stream = lifecycle.start(&session, request).unwrap().await.unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    peer.write_all(b"x").await.unwrap();
    let mut chunk = stream.read(1, None).unwrap().await.unwrap().unwrap();
    let copy = chunk.copy_bytes().unwrap();
    drop(chunk);
    let registry = fixture.provider.inner.connections.clone();
    let connection = registry.snapshot(0).unwrap().unwrap();
    connection.panic_in_drop_tail();
    drop(connection);
    lifecycle.rotate(1, 2, configuration.clone()).unwrap();
    drop(stream);
    assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(copy))).is_err());
    assert_eq!(lifecycle.status().unwrap().usage.owners, 1);
    assert!(control.budget.host_memory_bytes() >= baseline + 16 * 1024);
    lifecycle.rotate(2, 3, configuration).unwrap();
    assert_eq!(lifecycle.status().unwrap().retired_generations, 2);
    let pools = fixture.pools.clone();
    drop(fixture);
    drop(lifecycle);
    drop(registry);
    drop(session);
    let snapshot = pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    assert!(snapshot.is_clean(), "{snapshot:?}");
    drop(pools);
    control.assert_native_settled();
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn concurrent_chunk_and_copy_retire_one_original_window() {
    use tokio::io::AsyncWriteExt;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration);
    let (session, control) = fixture.session(5000);
    let stream = fixture
        .provider
        .start(&session, request)
        .unwrap()
        .await
        .unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    peer.write_all(b"abcd").await.unwrap();
    let mut held = Vec::new();
    for _ in 0..3 {
        held.push(stream.read(1, None).unwrap().await.unwrap().unwrap());
    }
    let connection = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (reached, resume) = connection.pause_next_chunk_drop();
    let mut chunk = stream.read(1, None).unwrap().await.unwrap().unwrap();
    let copy = chunk.copy_bytes().unwrap();
    let barrier = Arc::new(std::sync::Barrier::new(3));
    let first_barrier = barrier.clone();
    let first = std::thread::spawn(move || {
        first_barrier.wait();
        drop(chunk);
    });
    let second_barrier = barrier.clone();
    let second = std::thread::spawn(move || {
        second_barrier.wait();
        drop(copy);
    });
    barrier.wait();
    reached.recv_timeout(Duration::from_secs(2)).unwrap();
    let refusal = match stream.read(1, None) {
        Ok(future) => {
            drop(future);
            None
        }
        Err(failure) => Some(failure.code),
    };
    resume.send(()).unwrap();
    first.join().unwrap();
    second.join().unwrap();
    drop(held);
    drop(connection);
    drop(stream);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
    assert_eq!(refusal, Some(StreamErrorCode::Exhausted));
}

#[tokio::test]
async fn rotation_fences_old_grants_and_drain_reports_actual_retained_owners() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut config = config();
    config.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = || StreamConnectRequest {
        endpoint: config.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(config.clone());
    let lifecycle = Arc::new(
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap(),
    );
    let weak = Arc::downgrade(&lifecycle);
    let runtime = fixture.runtime();
    runtime.install_outbound_streams(lifecycle.clone()).unwrap();
    assert!(runtime.install_outbound_streams(lifecycle.clone()).is_err());
    assert_eq!(observed(&fixture).configuration_epoch, 1);
    assert_eq!(observed(&fixture).owners, 0);
    let (session, control) = fixture.session(5000);
    let control_session_bytes = control.native_session_bytes();
    let stream = lifecycle.start(&session, request()).unwrap().await.unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    assert_eq!(
        stream.write(b"PING".to_vec(), None).unwrap().await.unwrap(),
        4
    );
    let mut sent = [0; 4];
    peer.read_exact(&mut sent).await.unwrap();
    assert_eq!(&sent, b"PING");
    assert_eq!(observed(&fixture).live_accepted_write_bytes, 4);
    let pending = stream.read(16 * 1024, None).unwrap();
    assert_eq!(lifecycle.status().unwrap().usage.connections, 1);
    let replacement = lifecycle.rotate(1, 2, config.clone()).unwrap();
    assert_eq!(replacement.configuration_epoch(), 2);
    assert_eq!(lifecycle.status().unwrap().retired_generations, 1);
    assert_eq!(lifecycle.status().unwrap().usage.owners, 1);
    let usage = observed(&fixture);
    assert_eq!(usage.configuration_epoch, 2);
    assert_eq!(usage.retired_generations, 1);
    assert_eq!(usage.connections, 1);
    assert_eq!(usage.pending_operations, 1);
    assert_eq!(fixture.pools.snapshot().unwrap().connections, 1);
    assert!(control.budget.host_memory_bytes() >= 96 * 1024);
    assert!(lifecycle.start(&session, request()).is_err());
    assert_eq!(
        control.budget.snapshot_at(Instant::now()).outbound_requests,
        1
    );
    assert_eq!(
        lifecycle.rotate(1, 3, config).err().unwrap().code,
        StreamErrorCode::Revoked
    );
    assert_eq!(pending.await.err().unwrap().code, StreamErrorCode::Revoked);
    let mut byte = [0];
    match tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
        .await
        .unwrap()
    {
        Ok(0) => {}
        Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => {}
        value => panic!("physical closure expected: {value:?}"),
    }
    let status = lifecycle
        .drain(Instant::now() + Duration::from_millis(20))
        .await
        .unwrap();
    assert!(status.stopped);
    assert_eq!(status.usage.owners, 1);
    assert_eq!(status.usage.connections, 0);
    assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 1);
    let usage = observed(&fixture);
    assert!(usage.stopped);
    assert_eq!(usage.owners, 1);
    assert_eq!(usage.connections, 0);
    assert_eq!(usage.pending_operations, 0);
    assert_eq!(usage.live_accepted_write_bytes, 4);
    assert!(control.budget.host_memory_bytes() > 0);
    drop(stream);
    assert_eq!(
        lifecycle
            .drain(Instant::now() + Duration::from_secs(1))
            .await
            .unwrap()
            .usage
            .owners,
        0
    );
    assert_eq!(control.budget.host_memory_bytes(), control_session_bytes);
    assert_eq!(observed(&fixture).live_accepted_write_bytes, 0);
    assert_eq!(observed(&fixture).owners, 0);
    drop(replacement);
    drop(runtime);
    drop(lifecycle);
    assert!(weak.upgrade().is_none());
    assert!(fixture
        .broker
        .inspect_node_usage()
        .unwrap()
        .streams
        .is_none());
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retirement_waits_for_registry_contention_and_stops_original_connection() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut config = config();
    config.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: config.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(config);
    let lifecycle = Arc::new(
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap(),
    );
    let (session, control) = fixture.session(5000);
    let stream = lifecycle.start(&session, request).unwrap().await.unwrap();
    let (mut peer, _) = listener.accept().await.unwrap();
    let probe = Arc::new(ReentrantWake {
        lifecycle: Arc::clone(&lifecycle),
        stopped_without_lock: AtomicBool::new(false),
    });
    let waker = Waker::from(Arc::clone(&probe));
    let mut pending = Box::pin(stream.read(1, None).unwrap());
    assert!(matches!(
        pending.as_mut().poll(&mut Context::from_waker(&waker)),
        Poll::Pending
    ));
    let registry = Arc::clone(&fixture.provider.inner.connections);
    let guard = registry.lock_for_test();
    let (started_tx, started_rx) = std::sync::mpsc::channel();
    let (done_tx, done_rx) = std::sync::mpsc::channel();
    let retirement = Arc::clone(&lifecycle);
    let thread = std::thread::spawn(move || {
        started_tx.send(()).unwrap();
        retirement.retire();
        done_tx.send(()).unwrap();
    });
    started_rx.recv_timeout(Duration::from_secs(2)).unwrap();
    let deadline = Instant::now() + Duration::from_secs(2);
    while !fixture.provider.inner.installed.is_retired() {
        assert!(
            Instant::now() < deadline,
            "retirement did not reach the provider"
        );
        std::thread::yield_now();
    }
    assert!(done_rx.recv_timeout(Duration::from_millis(50)).is_err());
    drop(guard);
    done_rx.recv_timeout(Duration::from_secs(2)).unwrap();
    thread.join().unwrap();
    assert!(probe.stopped_without_lock.load(Ordering::Acquire));
    drop(pending);
    let mut byte = [0];
    match tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
        .await
        .unwrap()
    {
        Ok(0) => {}
        Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => {}
        value => panic!("original connection must be stopped: {value:?}"),
    }
    drop(stream);
    drop(probe);
    drop(waker);
    drop(lifecycle);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retirement_refuses_connect_held_before_registry_publication() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut config = config();
    config.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: config.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(config);
    let lifecycle = Arc::new(
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap(),
    );
    let (session, control) = fixture.session(5000);
    let base_bytes = control.native_session_bytes();
    let (reached, resume) = fixture.provider.inner.connections.pause_next_registration();
    let connecting = tokio::spawn(lifecycle.start(&session, request).unwrap());
    let (mut peer, _) = listener.accept().await.unwrap();
    tokio::task::spawn_blocking(move || reached.recv_timeout(Duration::from_secs(3)))
        .await
        .unwrap()
        .unwrap();
    assert!(control.budget.host_memory_bytes() > base_bytes);
    let before = lifecycle.status().unwrap();
    assert_eq!(before.usage.owners, 1);
    assert_eq!(before.usage.pending_operations, 0);
    lifecycle.retire();
    let stopped = lifecycle.status().unwrap();
    assert_eq!(stopped.usage.owners, 1);
    resume.send(()).unwrap();
    match connecting.await.unwrap() {
        Err(error) => assert_eq!(error.code, StreamErrorCode::Revoked),
        Ok(_) => panic!("a connect must not publish after retirement"),
    }
    let mut byte = [0];
    match tokio::time::timeout(Duration::from_secs(1), peer.read(&mut byte))
        .await
        .unwrap()
    {
        Ok(0) => {}
        Err(error) if error.kind() == std::io::ErrorKind::ConnectionReset => {}
        value => panic!("unpublished connection must be stopped: {value:?}"),
    }
    assert_eq!(lifecycle.status().unwrap().usage.owners, 0);
    drop(lifecycle);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn unpolled_connect_retains_its_prepaid_opening_through_retirement() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut config = config();
    config.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: config.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(config);
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (session, control) = fixture.session(5000);
    let original = control.native_session_bytes();
    let invocation = lifecycle.start(&session, request).unwrap();
    let status = lifecycle.status().unwrap();
    assert_eq!(status.usage.owners, 1);
    assert_eq!(status.usage.pending_operations, 0);
    assert_eq!(status.usage.connections, 0);
    lifecycle.retire();
    assert_eq!(lifecycle.status().unwrap().usage.owners, 1);
    drop(invocation);
    assert_eq!(lifecycle.status().unwrap().usage.owners, 0);
    assert_eq!(control.budget.host_memory_bytes(), original);
    drop(lifecycle);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn rotation_keeps_generation_until_original_future_allocation_retires() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration.clone());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (session, control) = fixture.session(5000);
    let base = control.native_session_bytes();
    let invocation = lifecycle.start(&session, request).unwrap();
    assert!(control.budget.host_memory_bytes() > base);
    lifecycle.rotate(1, 2, configuration.clone()).unwrap();
    assert_eq!(lifecycle.status().unwrap().retired_generations, 1);
    assert_eq!(lifecycle.status().unwrap().usage.owners, 1);

    // Stop during original future destruction, before its Box and host-memory
    // reservation retire. The original row must still hold its generation.
    let (reached, resume) = fixture.provider.inner.connections.pause_next_release();
    let (empty, resume_empty) = fixture
        .provider
        .inner
        .connections
        .pause_when_opening_empty();
    let dropping = std::thread::spawn(move || drop(invocation));
    reached.recv_timeout(Duration::from_secs(2)).unwrap();
    assert!(control.budget.host_memory_bytes() > base);
    assert_eq!(lifecycle.status().unwrap().usage.owners, 1);
    lifecycle.rotate(2, 3, configuration).unwrap();
    let generations_after_rotation = lifecycle.status().unwrap().retired_generations;
    resume.send(()).unwrap();
    empty.recv_timeout(Duration::from_secs(2)).unwrap();
    // The final row can clear only after the original Box and its reservation.
    let after_refund = control.budget.host_memory_bytes();
    resume_empty.send(()).unwrap();
    dropping.join().unwrap();
    drop(lifecycle);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();

    assert_eq!(after_refund, base);
    assert_eq!(
        generations_after_rotation, 2,
        "the original generation was pruned while its future allocation remained charged"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn rotation_keeps_connection_arc_billing_until_destructor_returns() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration.clone());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let handle = lifecycle.start(&session, request).unwrap().await.unwrap();
    let (_peer, _) = listener.accept().await.unwrap();
    let connection = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let (reached, resume) = connection.pause_drop_tail();
    drop(connection);
    lifecycle.rotate(1, 2, configuration.clone()).unwrap();
    let pools = fixture.pools.clone();
    drop(fixture);
    let dropping = std::thread::spawn(move || drop(handle));
    reached.recv_timeout(Duration::from_secs(2)).unwrap();
    let paid_before_rotation = control.budget.host_memory_bytes();
    lifecycle.rotate(2, 3, configuration.clone()).unwrap();
    let paid_after_rotation = control.budget.host_memory_bytes();
    let metadata_during_tail = pools.snapshot().unwrap().metadata_bytes;
    let retired_generations = lifecycle.status().unwrap().retired_generations;
    resume.send(()).unwrap();
    dropping.join().unwrap();
    lifecycle.rotate(3, 4, configuration).unwrap();
    let metadata_after_retirement = pools.snapshot().unwrap().metadata_bytes;
    drop(lifecycle);
    drop(session);
    let snapshot = pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    assert!(snapshot.is_clean(), "{snapshot:?}");
    drop(pools);
    control.assert_native_settled();
    assert!(paid_before_rotation >= baseline + 16 * 1024);
    assert!(
        paid_after_rotation >= baseline + 16 * 1024,
        "the original Connection Arc activation charge was refunded before its destructor returned"
    );
    assert!(metadata_during_tail >= metadata_after_retirement + 16 * 1024);
    assert_eq!(retired_generations, 2);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn connection_destructor_panic_keeps_only_a_bounded_registry_row() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration.clone());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let handle = lifecycle.start(&session, request).unwrap().await.unwrap();
    let (_peer, _) = listener.accept().await.unwrap();
    let registry = fixture.provider.inner.connections.clone();
    let connection = registry.snapshot(0).unwrap().unwrap();
    connection.panic_in_drop_tail();
    drop(connection);
    lifecycle.rotate(1, 2, configuration.clone()).unwrap();

    let panic = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(handle)));
    assert!(panic.is_err());
    assert_eq!(lifecycle.status().unwrap().usage.owners, 1);
    assert!(control.budget.host_memory_bytes() >= baseline + 16 * 1024);
    lifecycle.rotate(2, 3, configuration).unwrap();
    assert_eq!(lifecycle.status().unwrap().retired_generations, 2);

    // The failed row is bounded by its actual registry lifetime; dropping the
    // registry destroys its weak header and releases the original reservation.
    let pools = fixture.pools.clone();
    drop(fixture);
    drop(lifecycle);
    drop(registry);
    drop(session);
    let snapshot = pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    assert!(snapshot.is_clean(), "{snapshot:?}");
    drop(pools);
    control.assert_native_settled();
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn concurrent_connection_drops_keep_original_charge_on_destructor_panic() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration.clone());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (session, control) = fixture.session(5000);
    let baseline = control.native_session_bytes();
    let handle = lifecycle.start(&session, request).unwrap().await.unwrap();
    let (_peer, _) = listener.accept().await.unwrap();
    let registry = fixture.provider.inner.connections.clone();
    let connection = registry.snapshot(0).unwrap().unwrap();
    connection.panic_in_drop_tail();
    let (last_reached, last_resume) = connection.pause_drop_tail();
    lifecycle.rotate(1, 2, configuration.clone()).unwrap();
    let (non_last_reached, non_last_resume) = registry.pause_next_non_last_drop();
    let non_last = std::thread::spawn(move || drop(connection));
    non_last_reached
        .recv_timeout(Duration::from_secs(2))
        .unwrap();
    let last = std::thread::spawn(move || {
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| drop(handle)))
    });
    last_reached.recv_timeout(Duration::from_secs(2)).unwrap();
    non_last_resume.send(()).unwrap();
    non_last.join().unwrap();

    assert!(control.budget.host_memory_bytes() >= baseline + 16 * 1024);
    assert_eq!(lifecycle.status().unwrap().usage.owners, 1);
    lifecycle.rotate(2, 3, configuration.clone()).unwrap();
    assert_eq!(lifecycle.status().unwrap().retired_generations, 2);
    last_resume.send(()).unwrap();
    assert!(last.join().unwrap().is_err());

    // The same failed row and its original charges stay within the existing
    // per-provider registry and metadata limits across later clean rotations.
    let pools = fixture.pools.clone();
    let maximum_metadata = pools.limits().unwrap().maximum_metadata_bytes;
    for epoch in 3..8 {
        lifecycle
            .rotate(epoch, epoch + 1, configuration.clone())
            .unwrap();
        assert_eq!(lifecycle.status().unwrap().retired_generations, 2);
        assert!(control.budget.host_memory_bytes() >= baseline + 16 * 1024);
        assert!(pools.snapshot().unwrap().metadata_bytes <= maximum_metadata);
    }
    drop(fixture);
    drop(lifecycle);
    drop(registry);
    drop(session);
    let snapshot = pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    assert!(snapshot.is_clean(), "{snapshot:?}");
    drop(pools);
    control.assert_native_settled();
}

#[tokio::test]
async fn clean_rotations_reuse_the_bounded_retired_generations() {
    let configuration = config();
    let fixture = Fixture::new(configuration.clone());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    for epoch in 1..=12 {
        lifecycle
            .rotate(epoch, epoch + 1, configuration.clone())
            .unwrap();
        assert_eq!(lifecycle.status().unwrap().retired_generations, 1);
    }
    drop(lifecycle);
    fixture.clean().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unpolled_and_parked_connect_drop_original_admission_before_opening_row() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = || StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration.clone());
    let mut limits = fixture.pools.limits().unwrap();
    limits.maximum_running_per_provider = 1;
    fixture.pools.lower_limits(limits).unwrap();
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (first_session, first_control) = fixture.session(5000);
    let first = lifecycle
        .start(&first_session, request())
        .unwrap()
        .await
        .unwrap();
    let (_peer, _) = listener.accept().await.unwrap();
    let (second_session, second_control) = fixture.session(5000);
    for poll in [false, true] {
        let mut waiting = Box::pin(lifecycle.start(&second_session, request()).unwrap());
        if poll {
            assert!(matches!(
                waiting
                    .as_mut()
                    .poll(&mut Context::from_waker(Waker::noop())),
                Poll::Pending
            ));
        }
        let before = fixture.pools.snapshot().unwrap();
        assert_eq!(before.running_requests, 1);
        assert_eq!(before.pending_requests, 1);
        assert_eq!(lifecycle.status().unwrap().usage.owners, 2);
        let (reached, resume) = fixture.provider.inner.connections.pause_next_release();
        let thread = std::thread::spawn(move || drop(waiting));
        reached.recv_timeout(Duration::from_secs(2)).unwrap();
        let deadline = Instant::now() + Duration::from_secs(2);
        let at_release = loop {
            match fixture.pools.snapshot() {
                Ok(snapshot) => break snapshot,
                Err(error)
                    if error.code == latent_core::PlatformErrorCode::ResourceExhausted
                        && error.message == "capability-busy"
                        && Instant::now() < deadline =>
                {
                    std::thread::yield_now();
                }
                Err(error) => panic!("pool snapshot failed at original release barrier: {error:?}"),
            }
        };
        assert_eq!(at_release.running_requests, 1);
        assert_eq!(
            at_release.pending_requests, 0,
            "the original admission must drop before its opening row"
        );
        assert_eq!(lifecycle.status().unwrap().usage.owners, 2);
        resume.send(()).unwrap();
        thread.join().unwrap();
        assert_eq!(lifecycle.status().unwrap().usage.owners, 1);
    }
    drop(first);
    drop(lifecycle);
    drop(first_session);
    drop(second_session);
    fixture.clean().await;
    drop(fixture);
    first_control.assert_native_settled();
    second_control.assert_native_settled();
}

#[tokio::test]
async fn caller_panic_releases_unpolled_and_parked_openings() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = || StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration.clone());
    let mut limits = fixture.pools.limits().unwrap();
    limits.maximum_running_per_provider = 1;
    fixture.pools.lower_limits(limits).unwrap();
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (first_session, first_control) = fixture.session(5000);
    let first = lifecycle
        .start(&first_session, request())
        .unwrap()
        .await
        .unwrap();
    let (_peer, _) = listener.accept().await.unwrap();
    let (second_session, second_control) = fixture.session(5000);
    for poll in [false, true] {
        // A sticky row on each caught panic would exhaust all 32 slots.
        for _ in 0..=crate::connection_registry::CAPACITY {
            let mut waiting = Box::pin(lifecycle.start(&second_session, request()).unwrap());
            if poll {
                assert!(matches!(
                    waiting
                        .as_mut()
                        .poll(&mut Context::from_waker(Waker::noop())),
                    Poll::Pending
                ));
            }
            assert_eq!(fixture.pools.snapshot().unwrap().pending_requests, 1);
            let caught = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                let _waiting = waiting;
                panic!("unrelated caller panic");
            }));
            assert!(caught.is_err());
            assert_eq!(fixture.pools.snapshot().unwrap().pending_requests, 0);
            assert_eq!(lifecycle.status().unwrap().usage.owners, 1);
        }
    }
    drop(first);
    drop(lifecycle);
    drop(first_session);
    drop(second_session);
    fixture.clean().await;
    drop(fixture);
    first_control.assert_native_settled();
    second_control.assert_native_settled();
}

#[tokio::test]
async fn refused_start_during_existing_unwind_releases_opening() {
    struct StartOnUnwind<'a> {
        lifecycle: &'a StreamLifecycle,
        session: &'a latent_capabilities::broker::CapabilitySession,
        request: Option<StreamConnectRequest>,
        refused: &'a AtomicBool,
    }
    impl Drop for StartOnUnwind<'_> {
        fn drop(&mut self) {
            if let Some(request) = self.request.take() {
                let refused = self
                    .lifecycle
                    .start(self.session, request)
                    .is_err_and(|error| error.code == StreamErrorCode::Exhausted);
                self.refused
                    .store(std::thread::panicking() && refused, Ordering::Release);
            }
        }
    }

    let configuration = config();
    let endpoint = configuration.destinations[0].endpoint.clone();
    let fixture = Fixture::new(configuration);
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (session, control) = fixture.session(5000);
    let remaining = control.budget.granted().memory_bytes - control.budget.host_memory_bytes();
    let padding = control.budget.reserve_host_memory(remaining).unwrap();
    let refused = AtomicBool::new(false);
    for _ in 0..=crate::connection_registry::CAPACITY {
        refused.store(false, Ordering::Release);
        let caught = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _starter = StartOnUnwind {
                lifecycle: &lifecycle,
                session: &session,
                request: Some(StreamConnectRequest {
                    endpoint: endpoint.clone(),
                    timeout_millis: None,
                }),
                refused: &refused,
            };
            panic!("unrelated caller panic");
        }));
        assert!(caught.is_err());
        assert!(refused.load(Ordering::Acquire));
        assert_eq!(lifecycle.status().unwrap().usage.owners, 0);
    }
    drop(padding);
    drop(lifecycle);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

#[tokio::test]
async fn rotation_keeps_the_original_unpolled_opening_generation() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let request = StreamConnectRequest {
        endpoint: configuration.destinations[0].endpoint.clone(),
        timeout_millis: None,
    };
    let fixture = Fixture::new(configuration.clone());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (session, control) = fixture.session(5000);
    let invocation = lifecycle.start(&session, request).unwrap();
    lifecycle.rotate(1, 2, configuration.clone()).unwrap();
    let status = lifecycle.status().unwrap();
    assert_eq!(status.retired_generations, 1);
    assert_eq!(status.usage.owners, 1);
    lifecycle.rotate(2, 3, configuration.clone()).unwrap();
    assert!(lifecycle.status().unwrap().retired_generations >= 1);
    assert_eq!(lifecycle.status().unwrap().usage.owners, 1);
    drop(invocation);
    assert_eq!(lifecycle.status().unwrap().usage.owners, 0);
    lifecycle.rotate(3, 4, configuration).unwrap();
    assert_eq!(lifecycle.status().unwrap().retired_generations, 1);
    drop(lifecycle);
    drop(session);
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
}

// Leave exactly the requested bytes in the original pool, with each test-only
// filler obeying the existing per-reservation limit.
fn reserve_except(
    fixture: &Fixture,
    available: usize,
) -> Vec<latent_capabilities::broker::pools::ProviderMetadata> {
    let maximum = fixture.pools.limits().unwrap().maximum_metadata_bytes;
    let current = fixture.pools.snapshot().unwrap().metadata_bytes;
    let mut remaining = maximum.checked_sub(current + available).unwrap();
    let mut reservations = Vec::new();
    while remaining != 0 {
        let bytes = remaining.min(1024 * 1024);
        reservations.push(fixture.pools.reserve_protocol_metadata(bytes).unwrap());
        remaining -= bytes;
    }
    assert_eq!(
        maximum - fixture.pools.snapshot().unwrap().metadata_bytes,
        available
    );
    reservations
}

#[tokio::test]
async fn refused_initial_install_never_publishes_an_unusable_epoch() {
    let configuration = config();
    let fixture = Fixture::new(configuration.clone());
    let before = fixture.pools.snapshot().unwrap();
    let original = fixture.provider.reference();
    // The original ordering could pay configuration (128 KiB), pool epoch
    // (4096 bytes), and new ProviderUse (1024 bytes), then fail the registry.
    let reservations = reserve_except(&fixture, 128 * 1024 + 4096 + 1024);
    let failure = match crate::StreamProvider::install_for_qualification(
        fixture.pools.clone(),
        "not-published",
        1,
        0,
        configuration.clone(),
    ) {
        Ok(_) => panic!("unexpected successful install"),
        Err(error) => error,
    };
    assert_eq!(failure.code, StreamErrorCode::Exhausted);
    let installed = fixture.pools.provider("not-published");
    let current = fixture.pools.provider("streams").unwrap().reference();
    let original_retired = fixture.provider.inner.installed.is_retired();
    drop(reservations);
    assert!(
        installed.is_err(),
        "refused install published an unusable epoch"
    );
    assert!(!original_retired);
    assert!(current.same_installation(&original));
    assert_eq!(
        fixture.pools.snapshot().unwrap().metadata_bytes,
        before.metadata_bytes
    );
    assert_eq!(
        fixture.pools.snapshot().unwrap().configurations,
        before.configurations
    );
    let retry = crate::StreamProvider::install_for_qualification(
        fixture.pools.clone(),
        "not-published",
        1,
        0,
        configuration,
    )
    .unwrap();
    assert_eq!(retry.reference().configuration_epoch(), 1);
    retry.retire();
    drop(retry);
    drop(installed);
    drop(current);
    drop(original);
    fixture.clean().await;
}

#[tokio::test]
async fn refused_rotation_preserves_original_epoch_connection_and_new_admissions() {
    tokio::time::timeout(Duration::from_secs(15), async {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let mut configuration = config();
        configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
        let request = || StreamConnectRequest {
            endpoint: configuration.destinations[0].endpoint.clone(),
            timeout_millis: None,
        };
        let fixture = Fixture::new(configuration.clone());
        let lifecycle = Arc::new(
            StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
                .unwrap(),
        );
        let original = fixture.provider.reference();
        let (session, control) = fixture.session(10_000);
        let stream = lifecycle.start(&session, request()).unwrap().await.unwrap();
        let (mut peer, _) = listener.accept().await.unwrap();
        assert_eq!(
            stream
                .write(b"before".to_vec(), None)
                .unwrap()
                .await
                .unwrap(),
            6
        );
        let mut bytes = [0; 6];
        peer.read_exact(&mut bytes).await.unwrap();
        assert_eq!(&bytes, b"before");
        let before = fixture.pools.snapshot().unwrap();
        // The original ordering paid configuration and the replacement epoch,
        // then failed the still-unfunded registry after retiring the old epoch.
        let reservations = reserve_except(&fixture, 128 * 1024 + 4096);
        let failure = match lifecycle.rotate(1, 2, configuration.clone()) {
            Ok(_) => panic!("unexpected successful rotation"),
            Err(error) => error,
        };
        assert_eq!(failure.code, StreamErrorCode::Exhausted);
        let pool_reference = fixture.pools.provider("streams").unwrap().reference();
        let old_retired = fixture.provider.inner.installed.is_retired();
        drop(reservations);
        assert!(!old_retired, "refused rotation retired the original epoch");
        assert!(
            pool_reference.same_installation(&original),
            "refused rotation published epoch {}",
            pool_reference.configuration_epoch()
        );
        assert_eq!(lifecycle.reference().unwrap().configuration_epoch(), 1);
        assert_eq!(
            fixture.pools.snapshot().unwrap().metadata_bytes,
            before.metadata_bytes
        );
        assert_eq!(
            stream
                .write(b"after".to_vec(), None)
                .unwrap()
                .await
                .unwrap(),
            5
        );
        let mut bytes = [0; 5];
        peer.read_exact(&mut bytes).await.unwrap();
        assert_eq!(&bytes, b"after");
        // A new connection must still be admitted by the same original grant.
        let fresh = lifecycle.start(&session, request()).unwrap().await.unwrap();
        let (_fresh_peer, _) = listener.accept().await.unwrap();
        fresh.close().await.unwrap();
        stream.close().await.unwrap();
        let replacement = lifecycle.rotate(1, 2, configuration.clone()).unwrap();
        assert_eq!(replacement.configuration_epoch(), 2);
        assert!(fixture.provider.inner.installed.is_retired());
        assert!(lifecycle.start(&session, request()).is_err());
        drop(replacement);
        drop(pool_reference);
        drop(original);
        drop(lifecycle);
        drop(session);
        fixture.clean().await;
        drop(fixture);
        control.assert_native_settled();
    })
    .await
    .expect("bounded real-peer rotation test");
}

fn observed(fixture: &Fixture) -> latent_capabilities::broker::network::StreamNodeUsage {
    fixture
        .broker
        .inspect_node_usage()
        .unwrap()
        .streams
        .unwrap()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn provider_retirement_continues_after_multiple_connection_waker_panics() {
    use std::panic::{catch_unwind, AssertUnwindSafe};
    struct PanicOnce {
        label: &'static str,
        retirement_thread: std::thread::ThreadId,
        armed: AtomicBool,
        woke: AtomicBool,
    }
    impl Wake for PanicOnce {
        fn wake(self: Arc<Self>) {
            self.wake_by_ref();
        }
        fn wake_by_ref(self: &Arc<Self>) {
            if std::thread::current().id() == self.retirement_thread
                && self.armed.swap(false, Ordering::AcqRel)
            {
                self.woke.store(true, Ordering::Release);
                std::panic::panic_any(self.label);
            }
        }
    }
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let endpoint = configuration.destinations[0].endpoint.clone();
    // Include a real configured resolver, but never dispatch DNS to it.
    let mut dns = configuration.destinations[0].clone();
    dns.endpoint.host = "unused.example".into();
    dns.resolution = crate::StreamResolution::Dns {
        server: "127.0.0.1:53".parse().unwrap(),
        maximum_ttl_seconds: 1,
    };
    configuration.destinations.push(dns);
    let fixture = Fixture::new(configuration);
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (session, control) = fixture.session(5000);
    let session_bytes = control.native_session_bytes();
    let request = || StreamConnectRequest {
        endpoint: endpoint.clone(),
        timeout_millis: None,
    };
    let first = lifecycle.start(&session, request()).unwrap().await.unwrap();
    let (peer1, _) = listener.accept().await.unwrap();
    let second = lifecycle.start(&session, request()).unwrap().await.unwrap();
    let (peer2, _) = listener.accept().await.unwrap();
    assert!(
        !fixture.provider.inner.resolvers[1]
            .as_ref()
            .unwrap()
            .usage()
            .closed
    );
    let waker1 = Arc::new(PanicOnce {
        label: "first original connection wake failed",
        retirement_thread: std::thread::current().id(),
        armed: AtomicBool::new(false),
        woke: AtomicBool::new(false),
    });
    let waker2 = Arc::new(PanicOnce {
        label: "second original connection wake failed",
        retirement_thread: std::thread::current().id(),
        armed: AtomicBool::new(false),
        woke: AtomicBool::new(false),
    });
    let wake1 = Waker::from(waker1.clone());
    let wake2 = Waker::from(waker2.clone());
    let mut pending1 = Box::pin(first.read(1, None).unwrap());
    let mut pending2 = Box::pin(second.read(1, None).unwrap());
    assert!(matches!(
        pending1.as_mut().poll(&mut Context::from_waker(&wake1)),
        Poll::Pending
    ));
    assert!(matches!(
        pending2.as_mut().poll(&mut Context::from_waker(&wake2)),
        Poll::Pending
    ));
    waker1.armed.store(true, Ordering::Release);
    waker2.armed.store(true, Ordering::Release);
    let outcome = catch_unwind(AssertUnwindSafe(|| lifecycle.retire()));
    let preserved_first_panic = outcome
        .as_ref()
        .err()
        .and_then(|payload| payload.downcast_ref::<&str>())
        .copied();
    let first_state = first.inspect().state;
    let second_state = second.inspect().state;
    let resolver_closed = fixture.provider.inner.resolvers[1]
        .as_ref()
        .unwrap()
        .usage()
        .closed;
    let first_woke = waker1.woke.load(Ordering::Acquire);
    let second_woke = waker2.woke.load(Ordering::Acquire);
    let retained = lifecycle.status().unwrap().usage;
    let original_budget_held = control.budget.host_memory_bytes() > session_bytes;
    // Cleanup before assertions also keeps a failing baseline from leaking sockets.
    drop((pending1, pending2));
    lifecycle.retire();
    drop((first, second, peer1, peer2, lifecycle, session));
    fixture.clean().await;
    drop(fixture);
    control.assert_native_settled();
    assert!(
        first_woke && second_woke,
        "both original read wakers must run"
    );
    assert_eq!(
        preserved_first_panic,
        Some("first original connection wake failed")
    );
    assert_ne!(
        first_state,
        latent_capabilities::broker::network::StreamState::Open
    );
    assert_ne!(
        second_state,
        latent_capabilities::broker::network::StreamState::Open
    );
    assert_eq!(retained.connections, 2);
    assert_eq!(retained.pending_operations, 2);
    assert!(original_budget_held);
    assert!(
        resolver_closed,
        "the configured resolver must close after both wake panics"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn lifecycle_retirement_visits_older_generation_after_current_wake_panics() {
    use latent_capabilities::broker::{
        network::{STREAM_CAPABILITY, STREAM_PROFILE},
        CapabilityBindingSpec,
    };
    use latent_policy::capability::{MutationRequest, RecordKind};
    use std::panic::{catch_unwind, AssertUnwindSafe};
    struct PanicOnRetirement {
        thread: std::thread::ThreadId,
        armed: AtomicBool,
        woke: AtomicBool,
    }
    impl Wake for PanicOnRetirement {
        fn wake(self: Arc<Self>) {
            self.wake_by_ref();
        }
        fn wake_by_ref(self: &Arc<Self>) {
            if std::thread::current().id() == self.thread
                && self.armed.swap(false, Ordering::AcqRel)
            {
                self.woke.store(true, Ordering::Release);
                panic!("current generation wake failed");
            }
        }
    }
    struct ObserveOld {
        thread: std::thread::ThreadId,
        armed: AtomicBool,
        woke: AtomicBool,
    }
    impl Wake for ObserveOld {
        fn wake(self: Arc<Self>) {
            self.wake_by_ref();
        }
        fn wake_by_ref(self: &Arc<Self>) {
            if std::thread::current().id() == self.thread && self.armed.load(Ordering::Acquire) {
                self.woke.store(true, Ordering::Release);
            }
        }
    }
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let mut configuration = config();
    configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
    let endpoint = configuration.destinations[0].endpoint.clone();
    let fixture = Fixture::new(configuration.clone());
    let lifecycle =
        StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
            .unwrap();
    let (old_session, old_control) = fixture.session(5000);
    let old_baseline = old_control.native_session_bytes();
    let request = || StreamConnectRequest {
        endpoint: endpoint.clone(),
        timeout_millis: None,
    };
    let old_stream = lifecycle
        .start(&old_session, request())
        .unwrap()
        .await
        .unwrap();
    let (old_peer, _) = listener.accept().await.unwrap();
    let old_pending = old_stream.read(1, None).unwrap(); // keep this original socket retained
    let old_connection = fixture
        .provider
        .inner
        .connections
        .snapshot(0)
        .unwrap()
        .unwrap();
    let reference = lifecycle.rotate(1, 2, configuration).unwrap();
    assert_eq!(reference.configuration_epoch(), 2);
    assert_eq!(lifecycle.status().unwrap().retired_generations, 1);

    // Grant the real replacement epoch independently; no old binding widens authority.
    let binding = serde_json::json!({"formatVersion":1,"tenant":"a","capability":STREAM_CAPABILITY,
        "providerProfile":STREAM_PROFILE,"configurationDigest":reference.configuration_digest(),
        "configurationEpoch":2,"restriction":{"operations":[]}});
    fixture
        .policies
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                id: "retirement-next-binding",
                kind: RecordKind::ProviderBinding,
                operation_id: "retirement-next-binding",
                expected_revision: 0,
                document: Some(&serde_json::to_vec(&binding).unwrap()),
            },
            Instant::now() + Duration::from_secs(2),
            |_| Ok(()),
        )
        .unwrap();
    let plan = fixture
        .broker
        .compile_invocation_plan(
            &fixture.revision,
            Some(&latent_core::DeploymentId("retirement-next".into())),
            &[CapabilityBindingSpec {
                definition_digest: Some(&latent_artifacts::package::artifact_blob_digest(
                    b"retirement-next-binding",
                )),
                provider: &reference,
                imported_operations: &super::fixture::OPERATIONS.map(str::to_owned),
                policy_ids: &["p".into()],
                provider_binding_id: "retirement-next-binding",
                deployment_restriction_json: br#"{"operations":[]}"#,
            }],
            &fixture.publication,
            &[],
            &[],
            &[],
            None,
            Instant::now() + Duration::from_secs(2),
        )
        .unwrap();
    let (mut new_request, new_control) = fixture.request("retirement-next", 5000);
    new_request.cell.id = latent_core::CellId("retirement-next-cell".into());
    let new_session = fixture
        .broker
        .open_session(plan, &new_request, &new_control, &fixture.publication)
        .unwrap();
    let new_baseline = new_control.native_session_bytes();
    let new_stream = lifecycle
        .start(&new_session, request())
        .unwrap()
        .await
        .unwrap();
    let (new_peer, _) = listener.accept().await.unwrap();
    let mut new_pending = Box::pin(new_stream.read(1, None).unwrap());
    let panic_wake = Arc::new(PanicOnRetirement {
        thread: std::thread::current().id(),
        armed: AtomicBool::new(false),
        woke: AtomicBool::new(false),
    });
    let wake = Waker::from(panic_wake.clone());
    assert!(matches!(
        new_pending.as_mut().poll(&mut Context::from_waker(&wake)),
        Poll::Pending
    ));

    // Observe a fresh notification from the old, already-retired connection.
    let old_wake = Arc::new(ObserveOld {
        thread: std::thread::current().id(),
        armed: AtomicBool::new(false),
        woke: AtomicBool::new(false),
    });
    let old_waker = Waker::from(old_wake.clone());
    let mut old_notice = Box::pin(old_connection.retirement_notification_for_test());
    old_notice.as_mut().enable();
    assert!(matches!(
        old_notice
            .as_mut()
            .poll(&mut Context::from_waker(&old_waker)),
        Poll::Pending
    ));
    old_wake.armed.store(true, Ordering::Release);
    panic_wake.armed.store(true, Ordering::Release);
    let outcome = catch_unwind(AssertUnwindSafe(|| lifecycle.retire()));
    let first = outcome
        .as_ref()
        .err()
        .and_then(|payload| payload.downcast_ref::<&str>())
        .copied();
    let visited_old = old_wake.woke.load(Ordering::Acquire);
    let woke_current = panic_wake.woke.load(Ordering::Acquire);
    let status = lifecycle.status().unwrap();
    let old_paid = old_control.budget.host_memory_bytes() > old_baseline;
    let new_paid = new_control.budget.host_memory_bytes() > new_baseline;

    // Remove waiters and settle the exact original owners before assertions.
    drop(old_notice);
    drop((old_pending, new_pending));
    lifecycle.retire();
    drop((
        old_connection,
        old_stream,
        new_stream,
        old_peer,
        new_peer,
        lifecycle,
        old_session,
        new_session,
    ));
    drop((
        old_waker,
        wake,
        old_wake,
        panic_wake,
        reference,
        new_request,
    ));
    fixture.clean().await;
    drop(fixture);
    old_control.assert_native_settled();
    new_control.assert_native_settled();
    assert!(woke_current && visited_old);
    assert_eq!(first, Some("current generation wake failed"));
    assert!(status.stopped);
    assert_eq!(status.retired_generations, 1);
    assert_eq!(status.usage.connections, 2);
    assert_eq!(status.usage.pending_operations, 2);
    assert!(old_paid && new_paid);
}

#[test]
fn secondary_panic_payload_destructor_can_interrupt_the_retirement_walk() {
    use std::panic::{catch_unwind, AssertUnwindSafe};
    struct BadPayload;
    impl Drop for BadPayload {
        fn drop(&mut self) {
            panic!("secondary panic payload destructor failed");
        }
    }
    let mut first = None;
    crate::provider::attempt_retirement(&mut first, || panic!("first callback panic"));
    let mut visited_next = false;
    let second = catch_unwind(AssertUnwindSafe(|| {
        crate::provider::attempt_retirement(&mut first, || std::panic::panic_any(BadPayload));
        visited_next = true;
    }));
    let second_message = second
        .as_ref()
        .err()
        .and_then(|payload| payload.downcast_ref::<&str>())
        .copied();
    let first_message = first
        .as_ref()
        .and_then(|payload| payload.downcast_ref::<&str>())
        .copied();
    assert_eq!(first_message, Some("first callback panic"));
    assert_eq!(
        second_message,
        Some("secondary panic payload destructor failed")
    );
    assert!(!visited_next);
}
