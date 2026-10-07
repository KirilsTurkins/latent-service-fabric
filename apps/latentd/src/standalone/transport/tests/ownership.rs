use std::convert::Infallible;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Condvar, Mutex};
use std::task::{Context, Poll};

use http_body::{Body as HttpBody, Frame};
use tonic::codegen::{http::Response, Bytes};
use tower::{Service, ServiceExt};

use super::*;

struct DropProbe {
    shared: Arc<state::Shared>,
    checked: Arc<AtomicBool>,
}
impl Future for DropProbe {
    type Output = Result<Response<Body>, Infallible>;
    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Self::Output> {
        Poll::Pending
    }
}
impl Drop for DropProbe {
    fn drop(&mut self) {
        assert_eq!(self.shared.snapshot().active_rpcs, 1);
        self.checked.store(true, Ordering::Release);
    }
}

#[test]
fn request_owner_drops_inner_future_before_releasing_rpc_guard() {
    run(|control| async move {
        let shared = ready_shared();
        let checked = Arc::new(AtomicBool::new(false));
        let service = tower::service_fn({
            let shared = Arc::clone(&shared);
            let checked = Arc::clone(&checked);
            move |_| DropProbe {
                shared: Arc::clone(&shared),
                checked: Arc::clone(&checked),
            }
        });
        let mut service = layer(&shared, control).layer(service);
        let mut future = service.call(request("/latent.invocation.v1.InvocationService/Invoke"));
        std::future::poll_fn(|cx| {
            assert!(future.as_mut().poll(cx).is_pending());
            Poll::Ready(())
        })
        .await;
        drop(future);
        assert!(checked.load(Ordering::Acquire));
        assert_eq!(shared.snapshot().active_rpcs, 0);
    });
}

struct PendingBody {
    dropped: Arc<AtomicBool>,
    shared: Arc<state::Shared>,
}
impl HttpBody for PendingBody {
    type Data = Bytes;
    type Error = tonic::Status;
    fn poll_frame(
        self: Pin<&mut Self>,
        _: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, tonic::Status>>> {
        Poll::Pending
    }
}
impl Drop for PendingBody {
    fn drop(&mut self) {
        assert_eq!(self.shared.snapshot().active_rpcs, 1);
        self.dropped.store(true, Ordering::Release);
    }
}

#[test]
fn retained_output_body_holds_dispatch_capacity_until_dropped() {
    run(|control| async move {
        let shared = ready_shared();
        let dropped = Arc::new(AtomicBool::new(false));
        let service = tower::service_fn({
            let dropped = Arc::clone(&dropped);
            let shared = Arc::clone(&shared);
            move |_| {
                std::future::ready(Ok::<_, Infallible>(Response::new(Body::new(PendingBody {
                    dropped: Arc::clone(&dropped),
                    shared: Arc::clone(&shared),
                }))))
            }
        });
        let response = layer(&shared, control)
            .layer(service)
            .oneshot(request("/latent.invocation.v1.InvocationService/Invoke"))
            .await
            .unwrap();
        assert_eq!(shared.snapshot().active_rpcs, 1);
        assert!(!dropped.load(Ordering::Acquire));
        drop(response);
        assert!(dropped.load(Ordering::Acquire));
        assert_eq!(shared.snapshot().active_rpcs, 0);
    });
}

#[test]
fn cancelling_created_body_emits_unavailable_trailers_after_ordered_cleanup() {
    run(|control| async move {
        let shared = ready_shared();
        let dropped = Arc::new(AtomicBool::new(false));
        let service = tower::service_fn({
            let shared = Arc::clone(&shared);
            let dropped = Arc::clone(&dropped);
            move |_| {
                std::future::ready(Ok::<_, Infallible>(Response::new(Body::new(PendingBody {
                    dropped: Arc::clone(&dropped),
                    shared: Arc::clone(&shared),
                }))))
            }
        });
        let response = layer(&shared, control)
            .layer(service)
            .oneshot(request("/latent.invocation.v1.InvocationService/Invoke"))
            .await
            .unwrap();
        let mut body = Box::pin(response.into_body());
        std::future::poll_fn(|cx| {
            assert!(body.as_mut().poll_frame(cx).is_pending());
            Poll::Ready(())
        })
        .await;
        assert_eq!(shared.snapshot().active_rpcs, 1);
        assert!(!dropped.load(Ordering::Acquire));
        TransportHandle {
            shared: Arc::clone(&shared),
        }
        .cancel_active();
        let frame = std::future::poll_fn(|cx| body.as_mut().poll_frame(cx))
            .await
            .unwrap()
            .expect("shutdown sends a protocol status, not a body error");
        let trailers = frame.into_trailers().expect("gRPC status trailers");
        assert_eq!(trailers["grpc-status"], "14");
        assert!(trailers.len() <= 3);
        assert!(trailers["grpc-message"].as_bytes().len() <= 128);
        assert!(dropped.load(Ordering::Acquire));
        assert_eq!(shared.snapshot().active_rpcs, 0);
        assert!(body.is_end_stream());
        for _ in 0..2 {
            assert!(std::future::poll_fn(|cx| body.as_mut().poll_frame(cx))
                .await
                .is_none());
        }
    });
}

#[derive(Default)]
struct Latch {
    released: Mutex<bool>,
    wake: Condvar,
}
impl Latch {
    fn release(&self) {
        *self.released.lock().unwrap() = true;
        self.wake.notify_all();
    }
    fn wait(&self) {
        let released = self.released.lock().unwrap();
        let (released, _) = self
            .wake
            .wait_timeout_while(released, Duration::from_secs(2), |value| !*value)
            .unwrap();
        assert!(*released, "supervised control test latch expired");
    }
}
struct ReleaseOnDrop(Arc<Latch>);
impl Drop for ReleaseOnDrop {
    fn drop(&mut self) {
        self.0.release();
    }
}

#[test]
fn entire_control_future_stays_owned_after_waiter_abort_during_a_poll() {
    run(|control| async move {
        let shared = ready_shared();
        let latch = Arc::new(Latch::default());
        let release = ReleaseOnDrop(Arc::clone(&latch));
        let (started, ready) = tokio::sync::oneshot::channel();
        let started = Arc::new(Mutex::new(Some(started)));
        let service = tower::service_fn(move |_| {
            let started = Arc::clone(&started);
            let latch = Arc::clone(&latch);
            async move {
                assert_eq!(
                    std::thread::current().name(),
                    Some("standalone-control-test")
                );
                started.lock().unwrap().take().unwrap().send(()).unwrap();
                latch.wait();
                Ok::<_, Infallible>(Response::new(Body::empty()))
            }
        });
        let mut service = layer(&shared, control).layer(service);
        let waiter = service.call(request("/latent.control.v1.ReleaseService/PublishRelease"));
        ready.await.unwrap();
        drop(waiter);
        assert_eq!(shared.snapshot().active_control_jobs, 1);
        assert_eq!(shared.snapshot().active_rpcs, 1);
        drop(release);
        shared.idle().await;
        assert_eq!(shared.snapshot().active_control_jobs, 0);
        assert_eq!(shared.snapshot().active_rpcs, 0);
    });
}

struct RecoveryHeldBody;
impl HttpBody for RecoveryHeldBody {
    type Data = Bytes;
    type Error = tonic::Status;
    fn poll_frame(
        self: Pin<&mut Self>,
        _: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, tonic::Status>>> {
        Poll::Pending
    }
}

#[test]
fn phase4_recovery_uses_existing_reserved_rpc_slot_while_ordinary_responses_remain_owned() {
    run(|control| async move {
        use std::sync::atomic::AtomicUsize;
        let shared = ready_shared();
        let calls = Arc::new(AtomicUsize::new(0));
        let service = tower::service_fn({
            let calls = Arc::clone(&calls);
            move |request: Request<Body>| {
                let context = request
                    .extensions()
                    .get::<latent_wire::invocation::AuthenticatedInvocationContext>()
                    .expect("the original private listener authenticated the request");
                assert_eq!(context.principal().subject, "operator");
                calls.fetch_add(1, Ordering::Relaxed);
                std::future::ready(Ok::<_, Infallible>(Response::new(Body::new(
                    RecoveryHeldBody,
                ))))
            }
        });
        let service = layer(&shared, control).layer(service);
        let first = service
            .clone()
            .oneshot(request(
                "/latent.transaction.v1.TransactionService/InvokeCommand",
            ))
            .await
            .unwrap();
        let second = service
            .clone()
            .oneshot(request("/latent.transaction.v1.TransactionService/Query"))
            .await
            .unwrap();
        assert_eq!(shared.snapshot().active_rpcs, 2);
        assert_eq!(calls.load(Ordering::Relaxed), 2);
        for path in [
            "/latent.transaction.v1.TransactionService/InvokeCommand",
            "/latent.transaction.v1.TransactionService/Query",
            "/latent.control.v1.StateService/InspectNamespaceExtra",
            "/latent.control.v1.DispatcherService/Unknown",
        ] {
            let rejected = service.clone().oneshot(request(path)).await.unwrap();
            assert_eq!(rejected.headers()["grpc-status"], "8");
            drop(rejected);
            assert_eq!(calls.load(Ordering::Relaxed), 2);
        }
        for path in [
            "/latent.control.v1.StateService/MutateNamespace",
            "/latent.control.v1.StateService/InspectNamespace",
            "/latent.control.v1.StateService/SelectEntity",
            "/latent.control.v1.StateService/MutateState",
            "/latent.control.v1.StateService/PlanEffectMutation",
            "/latent.control.v1.StateService/GetStateOperationReceipt",
            "/latent.control.v1.DispatcherService/InspectDispatcher",
            "/latent.control.v1.DispatcherService/ControlDispatcher",
            "/latent.control.v1.DispatcherService/GetDispatcherOperation",
            "/latent.transaction.v1.TransactionService/LookupCommand",
            "/latent.transaction.v1.TransactionService/LookupCommit",
            "/latent.transaction.v1.TransactionService/GetEffect",
            "/latent.transaction.v1.TransactionService/ListEffectHistory",
            "/latent.transaction.v1.TransactionService/CancelCommand",
        ] {
            let before = calls.load(Ordering::Relaxed);
            let response = service.clone().oneshot(request(path)).await.unwrap();
            assert_eq!(calls.load(Ordering::Relaxed), before + 1);
            assert_eq!(shared.snapshot().active_rpcs, 3);
            let excess = service.clone().oneshot(request(path)).await.unwrap();
            assert_eq!(excess.headers()["grpc-status"], "8");
            assert_eq!(calls.load(Ordering::Relaxed), before + 1);
            drop(excess);
            assert_eq!(shared.snapshot().active_rpcs, 3);
            drop(response);
            assert_eq!(shared.snapshot().active_rpcs, 2);
        }
        // Recovery admission never bypasses private listener authentication.
        let unauthenticated = Request::builder()
            .uri("/latent.control.v1.DispatcherService/InspectDispatcher")
            .body(Body::empty())
            .unwrap();
        let before = calls.load(Ordering::Relaxed);
        let rejected = service.clone().oneshot(unauthenticated).await.unwrap();
        assert_eq!(rejected.headers()["grpc-status"], "16");
        assert_eq!(calls.load(Ordering::Relaxed), before);
        drop(rejected);
        assert_eq!(shared.snapshot().active_rpcs, 2);
        drop((first, second));
        assert_eq!(shared.snapshot().active_rpcs, 0);
        assert_eq!(shared.snapshot().active_control_jobs, 0);
    });
}
