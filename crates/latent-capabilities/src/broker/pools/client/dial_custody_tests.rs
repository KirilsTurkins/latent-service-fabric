use super::super::tests::fixture::{single, start, Setup};
use super::*;
use crate::broker::session::CapabilitySessionObserver;
use std::{
    io::Read,
    net::{TcpListener, TcpStream},
    sync::mpsc,
    time::Duration,
};

// A real TCP owner followed by a test-only gate. The gate observes the exact
// reservation after the socket has closed but before the whole value retires.
struct SocketWithTail {
    _socket: TcpStream,
    _tail: Tail,
}
struct Tail {
    client: Arc<ClientCore>,
    observer: CapabilitySessionObserver,
    reached: mpsc::Sender<(usize, bool)>,
    resume: mpsc::Receiver<()>,
    panic_after_release: bool,
}
impl Drop for Tail {
    fn drop(&mut self) {
        let _ = self.reached.send((
            self.client.connections.load(Ordering::Acquire),
            !self.observer.is_quiescent(),
        ));
        let _ = self.resume.recv_timeout(Duration::from_secs(5));
        assert!(
            !self.panic_after_release,
            "controlled socket destructor panic"
        );
    }
}
fn completed(_: &mut SocketWithTail) -> bool {
    true // Pool-order control only; no protected kernel retirement claim.
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn failed_dial_original_quota_survives_real_socket_retirement() {
    let setup = Setup::new(single());
    let client = setup
        .pools
        .client::<SocketWithTail>(&setup.provider, 1)
        .unwrap();
    let (session, _control) = setup.session("dial-original-retirement");
    let observer = session.observer();
    let call = start(&setup.pools, &client, &session).await;
    let reservation = client.reserve_connection(&call).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let socket = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (mut peer, _) = listener.accept().unwrap();
    peer.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    let (reached_tx, reached) = mpsc::channel();
    let (resume, wait) = mpsc::channel();
    reservation.quarantine_with_stream_retirement(
        SocketWithTail {
            _socket: socket,
            _tail: Tail {
                client: Arc::clone(&client.core),
                observer: observer.clone(),
                reached: reached_tx,
                resume: wait,
                panic_after_release: false,
            },
        },
        Some(completed),
    );
    drop(call);
    drop(session);
    assert!(!observer.is_quiescent());
    let original_metadata = setup.pools.snapshot().unwrap().metadata_bytes;
    let runner = Arc::clone(&client);
    let worker = std::thread::spawn(move || runner.progress_original_stream_quarantine());
    let observed = reached.recv_timeout(Duration::from_secs(5)).unwrap();
    let metadata_during_drop = setup.pools.snapshot().unwrap().metadata_bytes;
    let mut byte = [0];
    assert_eq!(peer.read(&mut byte).unwrap(), 0);
    resume.send(()).unwrap();
    worker.join().unwrap();
    assert_eq!(
        observed,
        (1, true),
        "original dial quota and lease must outlive the socket owner"
    );
    assert_eq!(metadata_during_drop, original_metadata);
    // The pool maintenance owner may hold its snapshot lock after the
    // original socket has retired. Retry only that transient observation.
    let snapshot = tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            match setup.pools.snapshot() {
                Ok(snapshot) => break snapshot,
                Err(error)
                    if error.code == latent_core::PlatformErrorCode::ResourceExhausted
                        && error.message == "capability-busy" =>
                {
                    tokio::task::yield_now().await;
                }
                Err(error) => panic!("pool snapshot failed after dial retirement: {error:?}"),
            }
        }
    })
    .await
    .expect("bounded pool snapshot after dial retirement");
    assert!(snapshot.metadata_bytes < original_metadata);
    assert_eq!(client.core.connections.load(Ordering::Acquire), 0);
    assert_eq!(client.core.epoch.quarantined.load(Ordering::Acquire), 0);
    assert!(observer.is_quiescent());
    drop(client);
    super::super::tests::fixture::clean(&setup.pools).await;
}

#[tokio::test]
async fn failed_dial_socket_panic_keeps_original_remaining_quota_in_paid_slot() {
    use std::panic::{catch_unwind, AssertUnwindSafe};
    let setup = Setup::new(single());
    let client = setup
        .pools
        .client::<SocketWithTail>(&setup.provider, 1)
        .unwrap();
    let (session, _control) = setup.session("dial-socket-panic");
    let observer = session.observer();
    let call = start(&setup.pools, &client, &session).await;
    let reservation = client.reserve_connection(&call).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let socket = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (_peer, _) = listener.accept().unwrap();
    let (reached_tx, reached) = mpsc::channel();
    let (resume, wait) = mpsc::channel();
    reservation.quarantine_with_stream_retirement(
        SocketWithTail {
            _socket: socket,
            _tail: Tail {
                client: client.core.clone(),
                observer: observer.clone(),
                reached: reached_tx,
                resume: wait,
                panic_after_release: true,
            },
        },
        Some(completed),
    );
    drop(call);
    drop(session);
    resume.send(()).unwrap();
    assert!(catch_unwind(AssertUnwindSafe(
        || client.progress_original_stream_quarantine()
    ))
    .is_err());
    assert_eq!(
        reached.recv_timeout(Duration::from_secs(2)).unwrap(),
        (1, true)
    );
    assert_eq!(client.core.connections.load(Ordering::Acquire), 1);
    assert_eq!(client.core.epoch.quarantined.load(Ordering::Acquire), 1);
    assert!(!observer.is_quiescent());
    let entry = client.idle.lock().unwrap().pop_front().unwrap();
    let Retained::FailedStreamRetirement { _reservation } = &entry else {
        panic!("same original failed dial remainder");
    };
    assert!(_reservation.lifetime.is_some());
    assert!(_reservation.activation.is_some());
    // Test-only cleanup; the consumed Socket is not reconstructed or claimed retired.
    client.core.epoch.quarantined.fetch_sub(1, Ordering::AcqRel);
    drop(entry);
    assert!(observer.is_quiescent());
    drop(client);
    super::super::tests::fixture::clean(&setup.pools).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn failed_dial_last_lease_waker_panic_keeps_remaining_original_quota() {
    use std::{
        future::Future,
        panic::{catch_unwind, AssertUnwindSafe},
        task::{Context, Poll, Wake, Waker},
    };
    struct RequestWake {
        client: Arc<ProviderClient<SocketWithTail>>,
        seen: Mutex<Option<(usize, usize, usize)>>,
    }
    impl Wake for RequestWake {
        fn wake(self: Arc<Self>) {
            *self.seen.lock().unwrap() = Some((
                self.client.core.connections.load(Ordering::Acquire),
                self.client.core.epoch.quarantined.load(Ordering::Acquire),
                self.client
                    .core
                    .epoch
                    .usage
                    .requests
                    .load(Ordering::Acquire),
            ));
            panic!("controlled last request wake panic");
        }
    }
    let setup = Setup::new(single());
    let client = setup
        .pools
        .client::<SocketWithTail>(&setup.provider, 1)
        .unwrap();
    let (session, _control) = setup.session("dial-last-lease-panic");
    let observer = session.observer();
    let call = start(&setup.pools, &client, &session).await;
    let reservation = client.reserve_connection(&call).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let socket = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (_peer, _) = listener.accept().unwrap();
    let (reached_tx, reached) = mpsc::channel();
    let (resume, wait) = mpsc::channel();
    reservation.quarantine_with_stream_retirement(
        SocketWithTail {
            _socket: socket,
            _tail: Tail {
                client: client.core.clone(),
                observer: observer.clone(),
                reached: reached_tx,
                resume: wait,
                panic_after_release: false,
            },
        },
        Some(completed),
    );
    drop(call);
    drop(session);
    let runner = client.clone();
    let worker = std::thread::spawn(move || {
        catch_unwind(AssertUnwindSafe(|| {
            runner.progress_original_stream_quarantine()
        }))
    });
    assert_eq!(
        reached.recv_timeout(Duration::from_secs(5)).unwrap(),
        (1, true)
    );
    let wake = Arc::new(RequestWake {
        client: client.clone(),
        seen: Mutex::new(None),
    });
    let waker = Waker::from(wake.clone());
    let mut notified = Box::pin(setup.pools.inner.changed.notified());
    notified.as_mut().enable();
    assert!(matches!(
        notified.as_mut().poll(&mut Context::from_waker(&waker)),
        Poll::Pending
    ));
    resume.send(()).unwrap();
    assert!(worker.join().unwrap().is_err());
    assert_eq!(*wake.seen.lock().unwrap(), Some((1, 1, 0)));
    assert_eq!(client.core.connections.load(Ordering::Acquire), 1);
    assert_eq!(client.core.epoch.quarantined.load(Ordering::Acquire), 1);
    let entry = client.idle.lock().unwrap().pop_front().unwrap();
    let Retained::FailedStreamRetirement { _reservation } = &entry else {
        panic!("same original failed dial remainder");
    };
    assert!(_reservation.lifetime.is_some());
    assert!(
        _reservation.activation.is_none(),
        "consumed IoLease cannot be reconstructed"
    );
    drop(notified);
    client.core.epoch.quarantined.fetch_sub(1, Ordering::AcqRel);
    drop(entry); // Test-only cleanup of remaining original owners.
    assert!(observer.is_quiescent());
    drop(client);
    super::super::tests::fixture::clean(&setup.pools).await;
}

#[tokio::test]
async fn failed_dial_notifies_after_refund_and_count_settlement_even_if_waker_panics() {
    use std::{
        future::Future,
        panic::{catch_unwind, AssertUnwindSafe},
        task::{Context, Poll, Wake, Waker},
    };
    struct WakeAfter {
        client: Arc<ProviderClient<SocketWithTail>>,
        seen: Mutex<Option<(usize, usize, bool)>>,
    }
    impl Wake for WakeAfter {
        fn wake(self: Arc<Self>) {
            *self.seen.lock().unwrap() = Some((
                self.client.core.connections.load(Ordering::Acquire),
                self.client.core.epoch.quarantined.load(Ordering::Acquire),
                self.client.idle.try_lock().is_ok(),
            ));
            // A reentrant maintenance pass sees a settled, unlocked table.
            self.client.progress_original_stream_quarantine();
            panic!("controlled post-quota wake panic");
        }
    }
    let setup = Setup::new(single());
    let client = setup
        .pools
        .client::<SocketWithTail>(&setup.provider, 1)
        .unwrap();
    let (session, _control) = setup.session("dial-post-refund-wake");
    let call = start(&setup.pools, &client, &session).await;
    let reservation = client.reserve_connection(&call).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let socket = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (_peer, _) = listener.accept().unwrap();
    let (reached_tx, reached) = mpsc::channel();
    let (resume, wait) = mpsc::channel();
    reservation.quarantine_with_stream_retirement(
        SocketWithTail {
            _socket: socket,
            _tail: Tail {
                client: client.core.clone(),
                observer: session.observer(),
                reached: reached_tx,
                resume: wait,
                panic_after_release: false,
            },
        },
        Some(completed),
    );
    resume.send(()).unwrap();
    let wake = Arc::new(WakeAfter {
        client: client.clone(),
        seen: Mutex::new(None),
    });
    let waker = Waker::from(wake.clone());
    let mut notified = Box::pin(setup.pools.inner.changed.notified());
    notified.as_mut().enable();
    assert!(matches!(
        notified.as_mut().poll(&mut Context::from_waker(&waker)),
        Poll::Pending
    ));
    // Keep the call alive so this wake belongs to the final quota settlement.
    assert!(catch_unwind(AssertUnwindSafe(
        || client.progress_original_stream_quarantine()
    ))
    .is_err());
    assert_eq!(
        reached.recv_timeout(Duration::from_secs(2)).unwrap(),
        (1, true)
    );
    assert_eq!(*wake.seen.lock().unwrap(), Some((0, 0, true)));
    assert!(client.idle.lock().unwrap().is_empty());
    drop(notified);
    drop(call);
    drop(session);
    drop(client);
    super::super::tests::fixture::clean(&setup.pools).await;
}

#[tokio::test]
async fn failed_dial_pending_and_callback_panic_keep_the_original_entry() {
    use std::panic::{catch_unwind, AssertUnwindSafe};
    fn pending(_: &mut SocketWithTail) -> bool {
        false
    }
    fn failed_step(_: &mut SocketWithTail) -> bool {
        panic!("controlled retirement callback panic")
    }
    let setup = Setup::new(single());
    let client = setup
        .pools
        .client::<SocketWithTail>(&setup.provider, 1)
        .unwrap();
    let (session, _control) = setup.session("dial-callback-retention");
    let observer = session.observer();
    let call = start(&setup.pools, &client, &session).await;
    let reservation = client.reserve_connection(&call).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let socket = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (_peer, _) = listener.accept().unwrap();
    let (reached_tx, reached) = mpsc::channel();
    let (resume, wait) = mpsc::channel();
    reservation.quarantine_with_stream_retirement(
        SocketWithTail {
            _socket: socket,
            _tail: Tail {
                client: client.core.clone(),
                observer: observer.clone(),
                reached: reached_tx,
                resume: wait,
                panic_after_release: false,
            },
        },
        Some(pending),
    );
    drop(call);
    drop(session);
    client.progress_original_stream_quarantine();
    assert_eq!(client.core.connections.load(Ordering::Acquire), 1);
    assert_eq!(client.core.epoch.quarantined.load(Ordering::Acquire), 1);
    assert!(!observer.is_quiescent());
    {
        let mut entries = client.idle.lock().unwrap();
        let Retained::Dial {
            stream_retirement, ..
        } = entries.front_mut().unwrap()
        else {
            panic!("original dial entry")
        };
        *stream_retirement = Some(failed_step);
    }
    assert!(catch_unwind(AssertUnwindSafe(
        || client.progress_original_stream_quarantine()
    ))
    .is_err());
    assert_eq!(client.idle.lock().unwrap().len(), 1);
    assert_eq!(client.core.connections.load(Ordering::Acquire), 1);
    assert_eq!(client.core.epoch.quarantined.load(Ordering::Acquire), 1);
    assert!(!observer.is_quiescent());
    {
        let mut entries = client.idle.lock().unwrap();
        let Retained::Dial {
            stream_retirement, ..
        } = entries.front_mut().unwrap()
        else {
            panic!("original dial entry")
        };
        *stream_retirement = Some(completed);
    }
    resume.send(()).unwrap();
    client.progress_original_stream_quarantine();
    assert_eq!(
        reached.recv_timeout(Duration::from_secs(2)).unwrap(),
        (1, true)
    );
    assert_eq!(client.core.connections.load(Ordering::Acquire), 0);
    assert_eq!(client.core.epoch.quarantined.load(Ordering::Acquire), 0);
    assert!(observer.is_quiescent());
    drop(client);
    super::super::tests::fixture::clean(&setup.pools).await;
}

#[tokio::test]
async fn failed_dial_normal_retirement_is_safe_while_caller_unwinds() {
    use std::panic::{catch_unwind, AssertUnwindSafe};
    struct DuringUnwind(Arc<ProviderClient<SocketWithTail>>);
    impl Drop for DuringUnwind {
        fn drop(&mut self) {
            self.0.progress_original_stream_quarantine();
        }
    }
    let setup = Setup::new(single());
    let client = setup
        .pools
        .client::<SocketWithTail>(&setup.provider, 1)
        .unwrap();
    let (session, _control) = setup.session("dial-caller-unwind");
    let observer = session.observer();
    let call = start(&setup.pools, &client, &session).await;
    let reservation = client.reserve_connection(&call).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let socket = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (_peer, _) = listener.accept().unwrap();
    let (reached_tx, reached) = mpsc::channel();
    let (resume, wait) = mpsc::channel();
    reservation.quarantine_with_stream_retirement(
        SocketWithTail {
            _socket: socket,
            _tail: Tail {
                client: client.core.clone(),
                observer: observer.clone(),
                reached: reached_tx,
                resume: wait,
                panic_after_release: false,
            },
        },
        Some(completed),
    );
    drop(call);
    drop(session);
    resume.send(()).unwrap();
    assert!(catch_unwind(AssertUnwindSafe(|| {
        let _during = DuringUnwind(client.clone());
        panic!("controlled caller unwind");
    }))
    .is_err());
    assert_eq!(
        reached.recv_timeout(Duration::from_secs(2)).unwrap(),
        (1, true)
    );
    assert_eq!(client.core.connections.load(Ordering::Acquire), 0);
    assert_eq!(client.core.epoch.quarantined.load(Ordering::Acquire), 0);
    assert!(observer.is_quiescent());
    drop(client);
    super::super::tests::fixture::clean(&setup.pools).await;
}
