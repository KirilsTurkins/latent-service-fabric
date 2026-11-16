use super::super::tests::fixture::{connect, single, start, Setup};
use super::*;
use std::{
    net::TcpStream,
    panic::{catch_unwind, AssertUnwindSafe},
};

#[test]
fn ordinary_retained_layout_is_unchanged_for_representative_payloads() {
    fn same<T: Send + 'static>() {
        assert_eq!(
            std::alloc::Layout::new::<Retained<T>>(),
            std::alloc::Layout::new::<PreviousRetained<T>>()
        );
    }
    same::<()>();
    same::<u8>();
    same::<u64>();
    same::<u128>();
    same::<TcpStream>();
    same::<[u8; 1024]>();
}

#[tokio::test]
async fn stream_custody_entry_points_refuse_non_stream_provider() {
    fn never(_: &mut TcpStream) -> Option<StreamRetirementGuard> {
        panic!("non-stream callback must not run");
    }
    let setup = Setup::new(single());
    let (session, _control) = setup.session("non-stream-custody-refusal");
    let called = std::sync::atomic::AtomicBool::new(false);
    let prepared = session.prepare_stream_io_future_with(
        &setup.provider.reference(),
        |_: ()| -> (std::future::Ready<()>, StreamRetirementGuard) {
            called.store(true, Ordering::SeqCst);
            panic!("non-stream future builder must not run");
        },
    );
    assert!(prepared.is_err());
    assert!(!called.load(Ordering::SeqCst));

    let call = setup.call(&session).await;
    let (connection, _peer) = connect(&setup.client, &call);
    connection.quarantine_stream_with_guard(never);
    setup.client.progress_original_stream_quarantine();
    let original = {
        let mut idle = setup.client.idle.lock().unwrap();
        let entry = idle.pop_front().unwrap();
        assert!(matches!(
            entry,
            Retained::Connection {
                stream_retirement: None,
                ..
            }
        ));
        entry
    };
    // Test-only cleanup of the fake owner; no native retirement is claimed.
    setup
        .client
        .core
        .epoch
        .quarantined
        .fetch_sub(1, Ordering::AcqRel);
    drop(original);
    drop(call);
    drop(session);
    super::super::tests::fixture::clean(&setup.pools).await;
}

#[tokio::test]
async fn guarded_quarantine_is_published_before_a_waker_panics() {
    use crate::broker::io::StreamRetirementObserver;
    use std::{
        future::Future,
        sync::atomic::AtomicUsize,
        task::{Context, Poll, Wake, Waker},
    };
    struct GuardedTcp {
        _socket: TcpStream,
        custody: Option<StreamRetirementGuard>,
    }
    struct Observer(Arc<AtomicUsize>);
    impl StreamRetirementObserver for Observer {
        fn release_stream_retirement(&self, _: u64) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    struct PanicWake;
    impl Wake for PanicWake {
        fn wake(self: Arc<Self>) {
            panic!("original pool wake failed");
        }
    }
    fn retired(value: &mut GuardedTcp) -> Option<StreamRetirementGuard> {
        value.custody.take()
    }
    let setup = Setup::new(single());
    let client = setup
        .pools
        .client::<GuardedTcp>(&setup.provider, 1)
        .unwrap();
    let (session, _control) = setup.session("guarded-publication-wake-panic");
    let observation = session.observer();
    let call = start(&setup.pools, &client, &session).await;
    let reservation = client.reserve_connection(&call).unwrap();
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (_peer, _) = listener.accept().unwrap();
    let released = Arc::new(AtomicUsize::new(0));
    let guard = StreamRetirementGuard::new(Arc::new(Observer(released.clone())), 17);
    let connection = reservation
        .connected(GuardedTcp {
            _socket: stream,
            custody: Some(guard),
        })
        .unwrap_or_else(|error| panic!("original connection refused: {error:?}"));
    drop(call);
    drop(session);
    let mut notified = Box::pin(setup.pools.inner.changed.notified());
    notified.as_mut().enable();
    let waker = Waker::from(Arc::new(PanicWake));
    assert!(matches!(
        notified.as_mut().poll(&mut Context::from_waker(&waker)),
        Poll::Pending
    ));
    assert!(catch_unwind(AssertUnwindSafe(
        || connection.quarantine_with_stream_guard(retired)
    ))
    .is_err());
    assert_eq!(
        setup.client.core.epoch.quarantined.load(Ordering::Acquire),
        1
    );
    assert_eq!(client.idle.lock().unwrap().len(), 1);
    assert!(!observation.is_quiescent());
    assert_eq!(released.load(Ordering::SeqCst), 0);
    drop(notified);
    client.progress_original_stream_quarantine();
    assert!(observation.is_quiescent());
    assert_eq!(released.load(Ordering::SeqCst), 1);
    drop(client);
    super::super::tests::fixture::clean(&setup.pools).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn last_original_lease_request_wake_panic_retains_the_remaining_quota() {
    use crate::broker::io::StreamRetirementObserver;
    use std::{
        future::Future,
        sync::{
            atomic::{AtomicBool, AtomicUsize},
            mpsc,
        },
        task::{Context, Poll, Wake, Waker},
    };
    struct GuardedTcp {
        _socket: TcpStream,
        custody: Option<StreamRetirementGuard>,
    }
    struct Observer(Arc<AtomicUsize>);
    impl StreamRetirementObserver for Observer {
        fn release_stream_retirement(&self, _: u64) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    struct Gate {
        reached: mpsc::Sender<()>,
        resume: Mutex<mpsc::Receiver<()>>,
    }
    impl Wake for Gate {
        fn wake(self: Arc<Self>) {
            let _ = self.reached.send(());
            let _ = self
                .resume
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(5));
        }
    }
    struct RequestWake {
        client: Arc<ProviderClient<GuardedTcp>>,
        reached: AtomicBool,
    }
    impl Wake for RequestWake {
        fn wake(self: Arc<Self>) {
            // Request::drop has settled its own counters, while the original
            // connection quota and dequeued quarantine remain outstanding.
            assert_eq!(
                self.client
                    .core
                    .epoch
                    .usage
                    .requests
                    .load(Ordering::Acquire),
                0
            );
            assert_eq!(self.client.core.connections.load(Ordering::Acquire), 1);
            assert_eq!(
                self.client.core.epoch.quarantined.load(Ordering::Acquire),
                1
            );
            self.reached.store(true, Ordering::Release);
            panic!("last request wake failed");
        }
    }
    fn retired(value: &mut GuardedTcp) -> Option<StreamRetirementGuard> {
        value.custody.take()
    }

    let setup = Setup::new(single());
    let client = setup
        .pools
        .client::<GuardedTcp>(&setup.provider, 1)
        .unwrap();
    let (session, _control) = setup.session("last-original-lease-request-wake");
    let observer = session.observer();
    let call = start(&setup.pools, &client, &session).await;
    let reservation = client.reserve_connection(&call).unwrap();
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (_peer, _) = listener.accept().unwrap();
    let released = Arc::new(AtomicUsize::new(0));
    let custody = StreamRetirementGuard::new(Arc::new(Observer(released.clone())), 17);
    let connection = reservation
        .connected(GuardedTcp {
            _socket: stream,
            custody: Some(custody),
        })
        .unwrap_or_else(|failure| panic!("original connection refused: {failure:?}"));
    connection.quarantine_with_stream_guard(retired);
    drop(call);
    drop(session);
    assert!(!observer.is_quiescent());
    assert_eq!(client.core.epoch.usage.requests.load(Ordering::Acquire), 1);

    let (reached_tx, reached) = mpsc::channel();
    let (resume, held) = mpsc::channel();
    let first = Waker::from(Arc::new(Gate {
        reached: reached_tx,
        resume: Mutex::new(held),
    }));
    let mut first_notified = Box::pin(setup.pools.inner.changed.notified());
    first_notified.as_mut().enable();
    assert!(matches!(
        first_notified
            .as_mut()
            .poll(&mut Context::from_waker(&first)),
        Poll::Pending
    ));
    let runner = client.clone();
    let thread = std::thread::spawn(move || {
        catch_unwind(AssertUnwindSafe(|| {
            runner.progress_original_stream_quarantine()
        }))
    });
    reached.recv_timeout(Duration::from_secs(2)).unwrap();
    let request_wake = Arc::new(RequestWake {
        client: client.clone(),
        reached: AtomicBool::new(false),
    });
    let second = Waker::from(request_wake.clone());
    let mut second_notified = Box::pin(setup.pools.inner.changed.notified());
    second_notified.as_mut().enable();
    assert!(matches!(
        second_notified
            .as_mut()
            .poll(&mut Context::from_waker(&second)),
        Poll::Pending
    ));
    resume.send(()).unwrap();
    assert!(thread.join().unwrap().is_err());
    assert!(request_wake.reached.load(Ordering::Acquire));

    assert_eq!(client.core.epoch.quarantined.load(Ordering::Acquire), 1);
    assert_eq!(client.core.connections.load(Ordering::Acquire), 1);
    assert_eq!(released.load(Ordering::SeqCst), 0);
    let retained = client
        .idle
        .lock()
        .unwrap()
        .pop_front()
        .expect("same paid failed row");
    let Retained::FailedStreamRetirement { _reservation } = &retained else {
        panic!("expected the original remaining connection reservation");
    };
    assert!(
        _reservation.activation.is_none(),
        "the consumed IoLease cannot be reconstructed"
    );
    assert!(_reservation.lifetime.is_some());
    assert!(observer.is_quiescent());

    // Test-only release of the fake retained remainder; no native retirement
    // or recovered lease is asserted by this fixture.
    drop(first_notified);
    drop(second_notified);
    client.core.epoch.quarantined.fetch_sub(1, Ordering::AcqRel);
    drop(retained);
    assert_eq!(client.core.connections.load(Ordering::Acquire), 0);
    drop(request_wake);
    drop(client);
    super::super::tests::fixture::clean(&setup.pools).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn post_quota_wake_panic_does_not_leave_a_phantom_quarantine() {
    use crate::broker::io::StreamRetirementObserver;
    use std::{
        future::Future,
        sync::{atomic::AtomicUsize, mpsc},
        task::{Context, Poll, Wake, Waker},
    };
    struct GuardedTcp {
        _socket: TcpStream,
        custody: Option<StreamRetirementGuard>,
    }
    struct Observer(Arc<AtomicUsize>);
    impl StreamRetirementObserver for Observer {
        fn release_stream_retirement(&self, _: u64) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    struct Gate {
        reached: mpsc::Sender<()>,
        resume: Mutex<mpsc::Receiver<()>>,
    }
    impl Wake for Gate {
        fn wake(self: Arc<Self>) {
            let _ = self.reached.send(());
            let _ = self
                .resume
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(5));
        }
    }
    struct PanicWake;
    impl Wake for PanicWake {
        fn wake(self: Arc<Self>) {
            panic!("post-quota waiter failed");
        }
    }
    fn retired(value: &mut GuardedTcp) -> Option<StreamRetirementGuard> {
        value.custody.take()
    }

    let setup = Setup::new(single());
    let client = setup
        .pools
        .client::<GuardedTcp>(&setup.provider, 1)
        .unwrap();
    let (session, _control) = setup.session("post-quota-wake-panic");
    let observer = session.observer();
    let call = start(&setup.pools, &client, &session).await;
    let reservation = client.reserve_connection(&call).unwrap();
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (_peer, _) = listener.accept().unwrap();
    let released = Arc::new(AtomicUsize::new(0));
    let guard = StreamRetirementGuard::new(Arc::new(Observer(released.clone())), 17);
    let connection = reservation
        .connected(GuardedTcp {
            _socket: stream,
            custody: Some(guard),
        })
        .unwrap_or_else(|error| panic!("original connection refused: {error:?}"));
    connection.quarantine_with_stream_guard(retired);

    let (reached_tx, reached) = mpsc::channel();
    let (resume, held) = mpsc::channel();
    let first = Waker::from(Arc::new(Gate {
        reached: reached_tx,
        resume: Mutex::new(held),
    }));
    let mut first_notified = Box::pin(setup.pools.inner.changed.notified());
    first_notified.as_mut().enable();
    assert!(matches!(
        first_notified
            .as_mut()
            .poll(&mut Context::from_waker(&first)),
        Poll::Pending
    ));
    let runner = client.clone();
    let thread = std::thread::spawn(move || {
        catch_unwind(AssertUnwindSafe(|| {
            runner.progress_original_stream_quarantine()
        }))
    });
    reached.recv_timeout(Duration::from_secs(2)).unwrap();
    assert_eq!(client.core.connections.load(Ordering::Acquire), 1);
    assert_eq!(client.core.epoch.quarantined.load(Ordering::Acquire), 1);
    assert_eq!(released.load(Ordering::SeqCst), 0);

    let second = Waker::from(Arc::new(PanicWake));
    let mut second_notified = Box::pin(setup.pools.inner.changed.notified());
    second_notified.as_mut().enable();
    assert!(matches!(
        second_notified
            .as_mut()
            .poll(&mut Context::from_waker(&second)),
        Poll::Pending
    ));
    resume.send(()).unwrap();
    assert!(thread.join().unwrap().is_err());
    assert_eq!(client.core.connections.load(Ordering::Acquire), 0);
    assert_eq!(client.core.epoch.quarantined.load(Ordering::Acquire), 0);
    assert!(client.idle.lock().unwrap().is_empty());
    assert_eq!(released.load(Ordering::SeqCst), 1);
    drop(first_notified);
    drop(second_notified);
    drop(call);
    drop(session);
    assert!(observer.is_quiescent());
    drop(client);
    super::super::tests::fixture::clean(&setup.pools).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn stream_guard_outlives_original_connected_pool_lease() {
    use crate::broker::io::StreamRetirementObserver;
    use std::{
        future::Future,
        sync::{atomic::AtomicUsize, mpsc},
        task::{Context, Poll, Wake, Waker},
    };

    struct GuardedTcp {
        _socket: TcpStream,
        custody: Option<StreamRetirementGuard>,
    }
    struct Observer(Arc<AtomicUsize>);
    impl StreamRetirementObserver for Observer {
        fn release_stream_retirement(&self, sequence: u64) {
            assert_eq!(sequence, 17);
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    struct Gate {
        reached: mpsc::Sender<()>,
        resume: Mutex<mpsc::Receiver<()>>,
    }
    impl Wake for Gate {
        fn wake(self: Arc<Self>) {
            self.wake_by_ref();
        }
        fn wake_by_ref(self: &Arc<Self>) {
            let _ = self.reached.send(());
            let _ = self
                .resume
                .lock()
                .unwrap()
                .recv_timeout(Duration::from_secs(5));
        }
    }
    fn retired(value: &mut GuardedTcp) -> Option<StreamRetirementGuard> {
        value.custody.take()
    }

    let setup = Setup::new(single());
    let client = setup
        .pools
        .client::<GuardedTcp>(&setup.provider, 1)
        .unwrap();
    let (session, _control) = setup.session("guarded-original-pool-lease");
    let observation = session.observer();
    let call = start(&setup.pools, &client, &session).await;
    let reservation = client.reserve_connection(&call).unwrap();
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (_peer, _) = listener.accept().unwrap();
    let released = Arc::new(AtomicUsize::new(0));
    let guard = StreamRetirementGuard::new(Arc::new(Observer(released.clone())), 17);
    let mut connection = reservation
        .connected(GuardedTcp {
            _socket: stream,
            custody: Some(guard),
        })
        .unwrap_or_else(|error| panic!("original connection refused: {error:?}"));
    connection.cleanup_failed();
    client.retain_quarantine(Retained::GuardedStreamConnection {
        owner: connection,
        stream_retirement: retired,
    });
    drop(call);
    drop(session);
    assert!(!observation.is_quiescent());

    // The guarded lifetime notifies after its physical Socket has dropped,
    // while the original PooledConnection IoLease has not yet dropped.
    let (reached_tx, reached) = mpsc::channel();
    let (resume, resume_rx) = mpsc::channel();
    let waker = Waker::from(Arc::new(Gate {
        reached: reached_tx,
        resume: Mutex::new(resume_rx),
    }));
    let mut notified = Box::pin(setup.pools.inner.changed.notified());
    notified.as_mut().enable();
    assert!(matches!(
        notified.as_mut().poll(&mut Context::from_waker(&waker)),
        Poll::Pending
    ));
    let runner = Arc::clone(&client);
    let thread = std::thread::spawn(move || runner.progress_original_stream_quarantine());
    reached.recv_timeout(Duration::from_secs(2)).unwrap();
    let still_live = !observation.is_quiescent();
    let before_release = released.load(Ordering::SeqCst);
    resume.send(()).unwrap();
    thread.join().unwrap();
    assert!(
        still_live,
        "the original IoLease must still be held at the barrier"
    );
    assert_eq!(before_release, 0);
    assert_eq!(released.load(Ordering::SeqCst), 1);
    assert!(observation.is_quiescent());
    drop(notified);
    drop(client);
    super::super::tests::fixture::clean(&setup.pools).await;
}

#[tokio::test]
async fn stream_guard_stays_outstanding_if_original_pool_drop_panics() {
    use crate::broker::io::StreamRetirementObserver;
    use std::{
        io::Read,
        sync::{atomic::AtomicUsize, mpsc},
    };
    struct Gate {
        reached: mpsc::Sender<()>,
        resume: mpsc::Receiver<()>,
    }
    impl Drop for Gate {
        fn drop(&mut self) {
            let _ = self.reached.send(());
            let _ = self.resume.recv_timeout(Duration::from_secs(5));
        }
    }
    struct GuardedTcp {
        _gate: Gate,
        _socket: TcpStream,
        custody: Option<StreamRetirementGuard>,
    }
    impl Drop for GuardedTcp {
        fn drop(&mut self) {
            panic!("original physical owner drop failed");
        }
    }
    struct Observer(Arc<AtomicUsize>);
    impl StreamRetirementObserver for Observer {
        fn release_stream_retirement(&self, _: u64) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    fn retired(value: &mut GuardedTcp) -> Option<StreamRetirementGuard> {
        value.custody.take()
    }
    for already_quarantined in [false, true] {
        let setup = Setup::new(single());
        let client = setup
            .pools
            .client::<GuardedTcp>(&setup.provider, 1)
            .unwrap();
        let (session, _control) = setup.session("guarded-pool-drop-panic");
        let observation = session.observer();
        let call = start(&setup.pools, &client, &session).await;
        let reservation = client.reserve_connection(&call).unwrap();
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (mut peer, _) = listener.accept().unwrap();
        peer.set_read_timeout(Some(Duration::from_millis(100)))
            .unwrap();
        let (reached_tx, reached) = mpsc::channel();
        let (resume, resume_rx) = mpsc::channel();
        let released = Arc::new(AtomicUsize::new(0));
        let owner = Arc::new(Observer(released.clone()));
        let weak = Arc::downgrade(&owner);
        let guard = StreamRetirementGuard::new(owner, 17);
        let mut connection = reservation
            .connected(GuardedTcp {
                _gate: Gate {
                    reached: reached_tx,
                    resume: resume_rx,
                },
                _socket: stream,
                custody: Some(guard),
            })
            .unwrap_or_else(|error| panic!("original connection refused: {error:?}"));
        let operation: Box<dyn FnOnce() -> bool + Send> = if already_quarantined {
            connection.cleanup_failed();
            client.retain_quarantine(Retained::GuardedStreamConnection {
                owner: connection,
                stream_retirement: retired,
            });
            let runner = Arc::clone(&client);
            Box::new(move || {
                catch_unwind(AssertUnwindSafe(|| {
                    runner.progress_original_stream_quarantine()
                }))
                .is_err()
            })
        } else {
            let custody = connection.resource().custody.take().unwrap();
            Box::new(move || {
                catch_unwind(AssertUnwindSafe(|| {
                    connection.retire_stream_with_guard_inner(custody, false)
                }))
                .is_err()
            })
        };
        drop(call);
        drop(session);
        let thread = std::thread::spawn(operation);
        reached.recv_timeout(Duration::from_secs(2)).unwrap();
        let original_lease_held = !observation.is_quiescent();
        let row_still_held = released.load(Ordering::SeqCst) == 0;
        // The actual TCP socket field has not yet dropped at this barrier.
        let socket_still_open = peer.read(&mut [0]).is_err();
        resume.send(()).unwrap();
        assert!(thread.join().unwrap());
        assert!(original_lease_held);
        assert!(row_still_held);
        assert!(socket_still_open);
        assert_eq!(released.load(Ordering::SeqCst), 0);
        assert!(
            weak.upgrade().is_none(),
            "the sticky row must not leak a marker Arc"
        );
        assert!(
            !observation.is_quiescent(),
            "the original IoLease must remain retained"
        );
        let failed = {
            let mut idle = client.idle.lock().unwrap();
            let failed = idle.pop_front().unwrap();
            assert!(matches!(failed, Retained::FailedStreamRetirement { .. }));
            failed
        };
        // Test-only cleanup of the retained original remainder. Production
        // leaves this unproved destructor failure permanently quarantined.
        client.core.epoch.quarantined.fetch_sub(1, Ordering::AcqRel);
        drop(failed);
        assert!(observation.is_quiescent());
        assert!(weak.upgrade().is_none());
        assert_eq!(released.load(Ordering::SeqCst), 0);
        drop(client);
        super::super::tests::fixture::clean(&setup.pools).await;
    }
}

#[tokio::test]
async fn stream_lifetime_wake_panic_retains_original_lease_and_quota() {
    use crate::broker::io::StreamRetirementObserver;
    use std::{
        future::Future,
        io::Read,
        sync::atomic::AtomicUsize,
        task::{Context, Poll, Wake, Waker},
    };
    struct GuardedTcp {
        _socket: TcpStream,
        custody: Option<StreamRetirementGuard>,
    }
    struct Observer(Arc<AtomicUsize>);
    impl StreamRetirementObserver for Observer {
        fn release_stream_retirement(&self, _: u64) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    struct PanicWake;
    impl Wake for PanicWake {
        fn wake(self: Arc<Self>) {
            panic!("lifetime notification failed");
        }
    }
    fn retired(value: &mut GuardedTcp) -> Option<StreamRetirementGuard> {
        value.custody.take()
    }
    for already_quarantined in [false, true] {
        let setup = Setup::new(single());
        let client = setup
            .pools
            .client::<GuardedTcp>(&setup.provider, 1)
            .unwrap();
        let (session, _control) = setup.session("guarded-lifetime-wake-panic");
        let observation = session.observer();
        let call = start(&setup.pools, &client, &session).await;
        let reservation = client.reserve_connection(&call).unwrap();
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (mut peer, _) = listener.accept().unwrap();
        peer.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
        let released = Arc::new(AtomicUsize::new(0));
        let marker = Arc::new(Observer(released.clone()));
        let weak = Arc::downgrade(&marker);
        let guard = StreamRetirementGuard::new(marker, 17);
        let mut connection = reservation
            .connected(GuardedTcp {
                _socket: stream,
                custody: Some(guard),
            })
            .unwrap_or_else(|error| panic!("original connection refused: {error:?}"));
        let operation: Box<dyn FnOnce() + Send> = if already_quarantined {
            connection.cleanup_failed();
            client.retain_quarantine(Retained::GuardedStreamConnection {
                owner: connection,
                stream_retirement: retired,
            });
            let runner = Arc::clone(&client);
            Box::new(move || runner.progress_original_stream_quarantine())
        } else {
            let custody = connection.resource().custody.take().unwrap();
            Box::new(move || connection.retire_stream_with_guard_inner(custody, false))
        };
        drop(call);
        drop(session);
        let mut notified = Box::pin(setup.pools.inner.changed.notified());
        notified.as_mut().enable();
        let waker = Waker::from(Arc::new(PanicWake));
        assert!(matches!(
            notified.as_mut().poll(&mut Context::from_waker(&waker)),
            Poll::Pending
        ));
        assert!(catch_unwind(AssertUnwindSafe(operation)).is_err());
        assert_eq!(
            peer.read(&mut [0]).unwrap(),
            0,
            "physical socket field dropped before wake"
        );
        assert!(
            !observation.is_quiescent(),
            "the original IoLease remains retained"
        );
        assert_eq!(client.core.connections.load(Ordering::Acquire), 1);
        assert_eq!(setup.pools.snapshot().unwrap().connections, 1);
        assert_eq!(client.core.epoch.quarantined.load(Ordering::Acquire), 1);
        assert_eq!(released.load(Ordering::SeqCst), 0);
        assert!(weak.upgrade().is_none());
        drop(notified);
        let failed = {
            let mut idle = client.idle.lock().unwrap();
            let failed = idle.pop_front().unwrap();
            assert!(matches!(failed, Retained::FailedStreamRetirement { .. }));
            failed
        };
        // Test-only disposal of the same retained remainder.
        client.core.epoch.quarantined.fetch_sub(1, Ordering::AcqRel);
        drop(failed);
        assert!(observation.is_quiescent());
        drop(client);
        super::super::tests::fixture::clean(&setup.pools).await;
    }
}
