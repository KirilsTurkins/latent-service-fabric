use super::*;
use latent_audit::{
    AuditFilter, AuditHandle, AuditLimits, AuditQueryRequest, AuditQueryTicket, AuditScope,
    DirectoryPhase2AuditJournal,
};
use std::{
    future::poll_fn,
    time::{Duration, Instant},
};
use tempfile::TempDir;

struct OneFrame(Option<Bytes>);
fn query_when_idle(handle: &AuditHandle, query: AuditQueryRequest) -> AuditQueryTicket {
    // This isolated fixture has one worker. Observe its actual idle boundary,
    // rather than racing thread startup with a fixed number of scheduler yields.
    let deadline = Instant::now() + Duration::from_secs(5);
    assert!(handle.wait_until_idle_for_test(deadline).unwrap());
    handle.query(query, deadline).unwrap()
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
    let page = query_when_idle(&handle, query()).wait().await.unwrap();
    let lease = page.response_lease();
    drop(page);
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
    drop(query_when_idle(&handle, query()).wait().await.unwrap());
    handle.close();
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}
