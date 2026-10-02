use super::*;
use latent_core::PlatformErrorCode;
use std::{
    future::poll_fn,
    sync::atomic::{AtomicBool, AtomicUsize, Ordering},
};
struct Owner {
    current: Arc<AtomicBool>,
    retired: Arc<AtomicUsize>,
}
impl Phase4ResponseOwner for Owner {
    fn reserved_bytes(&self) -> usize {
        4 * 1024 * 1024
    }
    fn with_current(&self, publish: &mut dyn FnMut()) -> Result<(), PlatformError> {
        if !self.current.load(Ordering::Acquire) {
            return Err(PlatformError {
                code: PlatformErrorCode::PermissionDenied,
                message: "fixture-revoked".into(),
                retryable: false,
                details: Vec::new(),
            });
        }
        publish();
        Ok(())
    }
}
impl Drop for Owner {
    fn drop(&mut self) {
        self.retired.fetch_add(1, Ordering::Release);
    }
}
struct OneFrame(Option<Bytes>);
impl HttpBody for OneFrame {
    type Data = Bytes;
    type Error = Status;
    fn poll_frame(
        mut self: Pin<&mut Self>,
        _: &mut Context<'_>,
    ) -> Poll<Option<Result<Frame<Bytes>, Status>>> {
        Poll::Ready(self.0.take().map(|bytes| Ok(Frame::data(bytes))))
    }
}
fn body(current: Arc<AtomicBool>, retired: Arc<AtomicUsize>) -> Body {
    let lease = ResponseLease::new(Arc::new(Owner { current, retired }));
    let mut response = http::Response::new(Body::new(OneFrame(Some(Bytes::from_static(
        b"retained-result",
    )))));
    response.extensions_mut().insert(lease);
    retain(response).into_body()
}
#[tokio::test]
async fn actual_frame_holds_response_owner_after_body_disconnect() {
    let current = Arc::new(AtomicBool::new(true));
    let retired = Arc::new(AtomicUsize::new(0));
    let mut body = body(current, retired.clone());
    let frame = poll_fn(|cx| Pin::new(&mut body).poll_frame(cx))
        .await
        .unwrap()
        .unwrap();
    let bytes = frame.into_data().unwrap();
    drop(body);
    assert_eq!(retired.load(Ordering::Acquire), 0);
    assert_eq!(bytes.as_ref(), b"retained-result");
    drop(bytes);
    assert_eq!(retired.load(Ordering::Acquire), 1);
}
#[tokio::test]
async fn revocation_before_deferred_encoding_denies_original_retained_body() {
    let current = Arc::new(AtomicBool::new(true));
    let retired = Arc::new(AtomicUsize::new(0));
    let mut body = body(current.clone(), retired.clone());
    current.store(false, Ordering::Release);
    let error = poll_fn(|cx| Pin::new(&mut body).poll_frame(cx))
        .await
        .unwrap()
        .unwrap_err();
    assert_eq!(error.code(), tonic::Code::PermissionDenied);
    assert_eq!(retired.load(Ordering::Acquire), 1);
}
#[test]
fn unpolled_response_body_drop_retires_exact_owner_once() {
    let retired = Arc::new(AtomicUsize::new(0));
    let body = body(Arc::new(AtomicBool::new(true)), retired.clone());
    assert_eq!(retired.load(Ordering::Acquire), 0);
    drop(body);
    assert_eq!(retired.load(Ordering::Acquire), 1);
}
