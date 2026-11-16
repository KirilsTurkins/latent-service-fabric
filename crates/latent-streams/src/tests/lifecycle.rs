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

struct ReentrantWake {
    lifecycle: Arc<StreamLifecycle>,
    stopped_without_lock: AtomicBool,
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
        let at_release = fixture.pools.snapshot().unwrap();
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
