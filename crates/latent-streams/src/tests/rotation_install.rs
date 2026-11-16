use super::{config, fixture::Fixture};
use crate::{StreamError, StreamErrorCode, StreamLifecycle, StreamProvider, StreamProviderConfig};
use latent_capabilities::broker::{
    network::{OutboundStreamInvoker, StreamConnectRequest},
    pools::{DeferredProviderInstall, ProviderPools},
};
use std::{
    future::Future,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    task::{Context, Poll, Wake, Waker},
};
use tokio::net::TcpListener;

struct InspectOnWake {
    lifecycle: Arc<StreamLifecycle>,
    active: AtomicBool,
    woke: AtomicBool,
    unlocked: AtomicBool,
    poisoned: AtomicBool,
    panic_once: AtomicBool,
    origin: std::thread::ThreadId,
}
impl Wake for InspectOnWake {
    fn wake(self: Arc<Self>) {
        self.wake_by_ref();
    }
    fn wake_by_ref(self: &Arc<Self>) {
        if !self.active.load(Ordering::Acquire) || std::thread::current().id() != self.origin {
            return;
        }
        self.woke.store(true, Ordering::Release);
        match self.lifecycle.status() {
            Ok(_) => self.unlocked.store(true, Ordering::Release),
            Err(error) if error.code == StreamErrorCode::Revoked => {
                self.poisoned.store(true, Ordering::Release)
            }
            Err(_) => {}
        }
        if self.panic_once.swap(false, Ordering::AcqRel) {
            panic!("controlled wake panic");
        }
    }
}

fn fail_after_publication(
    pools: Arc<ProviderPools>,
    id: &str,
    epoch: u64,
    expected: u64,
    config: StreamProviderConfig,
    completion: &mut DeferredProviderInstall<'_>,
) -> Result<StreamProvider, StreamError> {
    drop(StreamProvider::install_for_rotation(
        pools, id, epoch, expected, config, completion,
    )?);
    Err(StreamError::new(StreamErrorCode::Exhausted))
}

fn panic_after_publication(
    pools: Arc<ProviderPools>,
    id: &str,
    epoch: u64,
    expected: u64,
    config: StreamProviderConfig,
    completion: &mut DeferredProviderInstall<'_>,
) -> Result<StreamProvider, StreamError> {
    drop(StreamProvider::install_for_rotation(
        pools, id, epoch, expected, config, completion,
    )?);
    panic!("controlled post-publication unwind");
}

#[tokio::test]
async fn queued_connect_wakes_after_rotation_unlock_and_postpublication_failures() {
    for mode in ["pre-error", "success", "error", "panic", "wake-panic"] {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let mut configuration = config();
        configuration.destinations[0].endpoint.port = listener.local_addr().unwrap().port();
        let request = || StreamConnectRequest {
            endpoint: configuration.destinations[0].endpoint.clone(),
            timeout_millis: None,
        };
        let fixture = Fixture::new(configuration.clone());
        let mut limits = fixture.pools.limits().unwrap();
        limits.maximum_running_per_tenant = 1;
        limits.maximum_running_per_provider = 1;
        fixture.pools.lower_limits(limits).unwrap();
        let lifecycle = Arc::new(
            StreamLifecycle::from_installed_for_qualification("streams", fixture.provider.clone())
                .unwrap(),
        );
        let (session, control) = fixture.session(5000);
        let first = lifecycle.start(&session, request()).unwrap().await.unwrap();
        let (peer, _) = listener.accept().await.unwrap();
        assert_eq!(fixture.pools.snapshot().unwrap().running_requests, 1);
        let probe = Arc::new(InspectOnWake {
            lifecycle: Arc::clone(&lifecycle),
            active: AtomicBool::new(false),
            woke: AtomicBool::new(false),
            unlocked: AtomicBool::new(false),
            poisoned: AtomicBool::new(false),
            panic_once: AtomicBool::new(mode == "wake-panic"),
            origin: std::thread::current().id(),
        });
        let waker = Waker::from(Arc::clone(&probe));
        let mut pending = Box::pin(lifecycle.start(&session, request()).unwrap());
        assert!(matches!(
            pending.as_mut().poll(&mut Context::from_waker(&waker)),
            Poll::Pending
        ));
        assert_eq!(fixture.pools.snapshot().unwrap().pending_requests, 1);
        probe.active.store(true, Ordering::Release);
        match mode {
            "pre-error" => {
                let mut invalid = configuration;
                invalid.destinations.clear();
                let failure = match lifecycle.rotate(1, 2, invalid) {
                    Ok(_) => panic!("invalid prepublication configuration succeeded"),
                    Err(error) => error,
                };
                assert_eq!(failure.code, StreamErrorCode::InvalidInput);
            }
            "success" => {
                lifecycle.rotate(1, 2, configuration).unwrap();
            }
            "error" => {
                let failure = match lifecycle.rotate_with_installer(
                    1,
                    2,
                    configuration,
                    fail_after_publication,
                ) {
                    Ok(_) => panic!("post-publication error unexpectedly succeeded"),
                    Err(error) => error,
                };
                assert_eq!(failure.code, StreamErrorCode::Exhausted);
            }
            "panic" => {
                assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    let _ = lifecycle.rotate_with_installer(
                        1,
                        2,
                        configuration,
                        panic_after_publication,
                    );
                }))
                .is_err());
            }
            "wake-panic" => {
                assert!(std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    let _ = lifecycle.rotate(1, 2, configuration);
                }))
                .is_err());
            }
            _ => unreachable!(),
        }
        probe.active.store(false, Ordering::Release);
        if mode == "pre-error" {
            assert!(
                !probe.woke.load(Ordering::Acquire),
                "{mode}: unexpected publication wake"
            );
        } else {
            assert!(
                probe.woke.load(Ordering::Acquire),
                "{mode}: no synchronous wake"
            );
        }
        if mode == "panic" {
            assert!(
                probe.poisoned.load(Ordering::Acquire),
                "{mode}: lifecycle lock still held"
            );
        } else if mode != "pre-error" {
            assert!(
                probe.unlocked.load(Ordering::Acquire),
                "{mode}: lifecycle lock still held"
            );
        }
        let installed = fixture.pools.provider("streams").unwrap();
        assert_eq!(
            installed.is_retired(),
            mode == "error" || mode == "panic",
            "{mode}: replacement fence"
        );
        assert_eq!(
            fixture.provider.inner.installed.is_retired(),
            mode != "pre-error",
            "{mode}: old epoch fence"
        );
        assert_eq!(
            installed.reference().configuration_epoch(),
            if mode == "pre-error" { 1 } else { 2 }
        );
        if mode == "wake-panic" {
            assert_ne!(
                first.inspect().state,
                latent_capabilities::broker::network::StreamState::Open,
                "old provider must still be retired on a notification panic"
            );
        }
        drop(installed);
        drop(pending);
        drop(first);
        drop(peer);
        drop(waker);
        drop(probe);
        drop(lifecycle);
        drop(session);
        fixture.clean().await;
        drop(fixture);
        control.assert_native_settled();
    }
}
