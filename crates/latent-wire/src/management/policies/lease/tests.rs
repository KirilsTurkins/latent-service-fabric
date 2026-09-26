use super::*;
use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
use latent_policy::capability::{PolicyStore, PolicyStoreLimits, RecordKind};
use std::{
    future::poll_fn,
    time::{Duration, Instant},
};

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

#[tokio::test]
async fn policy_owner_survives_unpolled_body_and_retained_frame() {
    let directory = tempfile::TempDir::new().unwrap();
    let catalog = DirectoryArtifactRepository::open(
        directory.path().join("artifacts"),
        DirectoryArtifactRepositoryConfig::default(),
    )
    .unwrap();
    let store = PolicyStore::open(
        &directory.path().join("policies"),
        PolicyStoreLimits {
            maximum_read_owners: 1,
            ..PolicyStoreLimits::default()
        },
        catalog.lifecycle_authority(),
    )
    .unwrap();
    let get = || {
        store.get(
            "a",
            RecordKind::Policy,
            "absent",
            4096,
            Instant::now() + Duration::from_secs(5),
        )
    };
    let (_, lease) = get().unwrap().into_parts();
    let mut response = http::Response::new(Body::new(OneFrame(Some(Bytes::from_static(
        b"bounded-response",
    )))));
    response.extensions_mut().insert(lease);
    let mut body = retain(response).into_body();
    assert_eq!(store.retained_read_owners(), 1);
    assert!(get().is_err());
    let frame = poll_fn(|cx| Pin::new(&mut body).poll_frame(cx))
        .await
        .unwrap()
        .unwrap();
    let bytes = frame.into_data().unwrap();
    drop(body);
    assert_eq!(bytes.as_ref(), b"bounded-response");
    assert!(get().is_err());
    drop(bytes);
    assert_eq!(store.retained_read_owners(), 0);
    drop(get().unwrap());
}
