use super::*;
use latent_audit::{
    AuditFilter, AuditLimits, AuditQueryRequest, AuditScope, DirectoryPhase2AuditJournal,
};
use std::{
    future::poll_fn,
    time::{Duration, Instant},
};
use tempfile::TempDir;

struct OneFrame(Option<Bytes>);
fn accepted<T>(mut enqueue: impl FnMut() -> Result<T, latent_core::PlatformError>) -> T {
    for _ in 0..128 {
        match enqueue() {
            Ok(value) => return value,
            Err(error) if error.message == "audit-busy" => std::thread::yield_now(),
            Err(error) => panic!("audit fixture enqueue failed: {}", error.message),
        }
    }
    panic!("audit fixture enqueue exceeded its finite attempts");
}
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

#[tokio::test]
async fn page_lease_follows_unpolled_body_and_transport_retained_bytes() {
    let directory = TempDir::new().unwrap();
    let limits = AuditLimits {
        maximum_query_owners: 1,
        ..AuditLimits::default()
    };
    let (handle, mut worker) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), limits).unwrap();
    let query = || AuditQueryRequest {
        scope: AuditScope::Node,
        filter: AuditFilter::default(),
        cursor: None,
        limit: 1,
        maximum_bytes: 32768,
    };
    let page = accepted(|| handle.query(query(), Instant::now() + Duration::from_secs(5)))
        .wait()
        .await
        .unwrap();
    let (_, _, _, lease) = page.into_parts();
    let mut response = http::Response::new(Body::new(OneFrame(Some(Bytes::from_static(
        b"bounded-response",
    )))));
    response.extensions_mut().insert(lease);
    let mut body = retain(response).into_body();
    assert_eq!(handle.snapshot().query_owners, 1);
    assert!(handle
        .query(query(), Instant::now() + Duration::from_secs(5))
        .is_err());
    let frame = poll_fn(|cx| Pin::new(&mut body).poll_frame(cx))
        .await
        .unwrap()
        .unwrap();
    let bytes = frame.into_data().unwrap();
    drop(body);
    assert_eq!(handle.snapshot().query_owners, 1);
    assert_eq!(bytes.as_ref(), b"bounded-response");
    drop(bytes);
    assert_eq!(handle.snapshot().query_owners, 0);
    assert_eq!(handle.snapshot().query_bytes, 0);
    drop(
        accepted(|| handle.query(query(), Instant::now() + Duration::from_secs(5)))
            .wait()
            .await
            .unwrap(),
    );
    handle.close();
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}
