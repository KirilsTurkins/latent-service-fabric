use super::*;
use crate::output::Category;
use latent_rpc::invocation::v1::GetActivationRequest;
use std::{
    pin::Pin,
    sync::{atomic::AtomicUsize, Arc},
    task::{Context, Poll, Waker},
};

fn session(allowance: Duration) -> Session {
    let mut authorization = MetadataValue::from_static("Bearer private-test-credential");
    authorization.set_sensitive(true);
    Session {
        channel: Endpoint::from_static("http://127.0.0.1:1").connect_lazy(),
        tenant: "tests".to_owned(),
        authorization,
        deadline: Instant::now() + allowance,
        dispatched: AtomicBool::new(false),
        maximum_request: 4096,
        maximum_response: 4096,
    }
}

fn request() -> GetActivationRequest {
    GetActivationRequest {
        activation_id: "known".to_owned(),
    }
}

fn timeout<T>(request: &Request<T>) -> Duration {
    let value = request
        .metadata()
        .get("grpc-timeout")
        .unwrap()
        .to_str()
        .unwrap();
    let (digits, unit) = value.split_at(value.len() - 1);
    let value = digits.parse::<u64>().unwrap();
    match unit {
        "n" => Duration::from_nanos(value),
        "u" => Duration::from_micros(value),
        "m" => Duration::from_millis(value),
        "S" => Duration::from_secs(value),
        _ => panic!("test allowance is at most five seconds"),
    }
}

#[derive(Default)]
struct Counts {
    polls: AtomicUsize,
    drops: AtomicUsize,
}
struct PendingCall(Arc<Counts>);
impl Future for PendingCall {
    type Output = Result<Response<()>, Status>;

    fn poll(self: Pin<&mut Self>, _: &mut Context<'_>) -> Poll<Self::Output> {
        self.0.polls.fetch_add(1, Ordering::SeqCst);
        Poll::Pending
    }
}
impl Drop for PendingCall {
    fn drop(&mut self) {
        self.0.drops.fetch_add(1, Ordering::SeqCst);
    }
}

#[tokio::test(start_paused = true)]
async fn requests_use_remaining_time_and_one_sensitive_authorization_header() {
    let session = session(Duration::from_secs(5));
    let first = session.request(request()).unwrap();
    assert_eq!(timeout(&first), Duration::from_secs(5));
    assert_eq!(first.metadata().get_all("authorization").iter().count(), 1);
    assert!(first
        .metadata()
        .get("authorization")
        .unwrap()
        .is_sensitive());
    assert_eq!(
        first
            .metadata()
            .get("authorization")
            .unwrap()
            .to_str()
            .unwrap(),
        "Bearer private-test-credential"
    );
    assert!(!session.dispatched());

    tokio::time::advance(Duration::from_secs(4)).await;
    let second = session.request(request()).unwrap();
    assert_eq!(timeout(&second), Duration::from_secs(1));
    tokio::time::advance(Duration::from_secs(1)).await;
    let failure = session.request(request()).unwrap_err();
    assert_eq!(failure.error["code"], "rpc-timeout");
    assert!(failure.outcome_known);
    assert!(!session.dispatched());
}

#[tokio::test(start_paused = true)]
async fn pending_call_uses_original_deadline_and_drops_its_only_rpc_owner() {
    let session = session(Duration::from_secs(5));
    // Time already spent before dispatch is part of the same allowance.
    tokio::time::advance(Duration::from_secs(3)).await;
    let counts = Arc::new(Counts::default());
    let mut call = Box::pin(session.call(PendingCall(Arc::clone(&counts))));
    let mut context = Context::from_waker(Waker::noop());
    assert!(call.as_mut().poll(&mut context).is_pending());
    assert!(session.dispatched());
    tokio::time::advance(Duration::from_secs(1)).await;
    assert!(call.as_mut().poll(&mut context).is_pending());
    tokio::time::advance(Duration::from_secs(1)).await;
    let failure = call.await.unwrap_err();
    assert_eq!(failure.category, Category::TransportError);
    assert_eq!(failure.error["code"], "rpc-timeout");
    assert!(!failure.outcome_known);
    assert!(counts.polls.load(Ordering::SeqCst) > 0);
    assert_eq!(counts.drops.load(Ordering::SeqCst), 1);
}

#[tokio::test(start_paused = true)]
async fn expired_or_oversized_preflight_never_polls_or_marks_dispatch() {
    let mut session = session(Duration::ZERO);
    let counts = Arc::new(Counts::default());
    let failure = session
        .call(PendingCall(Arc::clone(&counts)))
        .await
        .unwrap_err();
    assert!(failure.outcome_known);
    assert!(!session.dispatched());
    assert_eq!(counts.polls.load(Ordering::SeqCst), 0);
    assert_eq!(counts.drops.load(Ordering::SeqCst), 1);

    session.deadline = Instant::now() + Duration::from_secs(1);
    session.maximum_request = 1;
    let failure = session.request(request()).unwrap_err();
    assert_eq!(failure.error["code"], "request-limit");
    assert!(failure.outcome_known);
    assert!(!session.dispatched());
}

#[tokio::test(start_paused = true)]
async fn dropping_pending_call_drops_rpc_without_sending_hidden_cancellation() {
    let session = session(Duration::from_secs(5));
    let counts = Arc::new(Counts::default());
    let mut call = Box::pin(session.call(PendingCall(Arc::clone(&counts))));
    let mut context = Context::from_waker(Waker::noop());
    assert!(call.as_mut().poll(&mut context).is_pending());
    drop(call);
    assert!(session.dispatched());
    assert_eq!(counts.polls.load(Ordering::SeqCst), 1);
    assert_eq!(counts.drops.load(Ordering::SeqCst), 1);
    let failure = Failure::interrupted(session.dispatched());
    assert_eq!(failure.category, Category::Interrupted);
    assert!(!failure.outcome_known);
    assert!(!failure.error.to_string().contains("accepted"));
}

#[tokio::test(start_paused = true)]
async fn retryable_server_failure_is_returned_after_one_poll_without_retry() {
    let session = session(Duration::from_secs(5));
    let polls = AtomicUsize::new(0);
    let error = latent_rpc::control::v1::PlatformError {
        code: "unavailable".to_owned(),
        retryable: true,
        message: "private peer diagnostic".to_owned(),
        detail_items: Vec::new(),
    };
    let future = std::future::poll_fn(|_| {
        polls.fetch_add(1, Ordering::SeqCst);
        Poll::Ready(Err::<Response<()>, _>(Status::with_details(
            tonic::Code::Unavailable,
            "private peer diagnostic",
            error.encode_to_vec().into(),
        )))
    });
    let failure = session.call(future).await.unwrap_err();
    assert_eq!(polls.load(Ordering::SeqCst), 1);
    assert!(session.dispatched());
    assert_eq!(failure.category, Category::PlatformError);
    assert_eq!(failure.error["retryable"], true);
    assert!(!failure.outcome_known);
    assert!(!failure.error.to_string().contains("private"));
}
