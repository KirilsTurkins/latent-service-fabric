use super::*;
use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
use latent_audit::{AuditLimits, DirectoryPhase2AuditJournal};
use latent_control_store::{
    rollouts::RolloutId, DirectoryDeploymentRepository, DirectoryDeploymentRepositoryConfig,
};
use latent_core::TenantId;
use latent_rollout::{CoordinatorLimits, RolloutCoordinator};
use std::{
    future::poll_fn,
    sync::Arc,
    time::{Duration, Instant},
};
use tempfile::TempDir;

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
async fn rollout_response_owner_survives_unpolled_body_and_retained_frame() {
    let directory = TempDir::new().unwrap();
    let artifacts = Arc::new(
        DirectoryArtifactRepository::open(
            directory.path().join("releases"),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap(),
    );
    let store = Arc::new(
        DirectoryDeploymentRepository::open(
            directory.path().join("deployments"),
            artifacts,
            DirectoryDeploymentRepositoryConfig::default(),
        )
        .await
        .unwrap(),
    );
    let (audit, mut journal) =
        DirectoryPhase2AuditJournal::open(directory.path().join("audit"), AuditLimits::default())
            .unwrap();
    let (handle, mut worker) = RolloutCoordinator::start(
        store,
        audit.clone(),
        CoordinatorLimits {
            maximum_query_owners: 1,
            ..CoordinatorLimits::default()
        },
        &tokio::runtime::Handle::current(),
    )
    .unwrap();
    worker
        .wait_started(Instant::now() + Duration::from_secs(5))
        .await
        .unwrap();
    let get = || {
        handle.get(
            TenantId("acme".into()),
            RolloutId("absent".into()),
            Instant::now() + Duration::from_secs(5),
        )
    };
    let value = get().unwrap().wait().await.unwrap();
    let (_, lease) = value.into_parts();
    let mut response = http::Response::new(Body::new(OneFrame(Some(Bytes::from_static(
        b"bounded-response",
    )))));
    response.extensions_mut().insert(lease);
    let mut body = retain(response).into_body();
    assert_eq!(handle.snapshot().response_owners, 1);
    assert!(get().is_err());
    let frame = poll_fn(|cx| Pin::new(&mut body).poll_frame(cx))
        .await
        .unwrap()
        .unwrap();
    let bytes = frame.into_data().unwrap();
    drop(body);
    assert_eq!(handle.snapshot().response_owners, 1);
    assert_eq!(bytes.as_ref(), b"bounded-response");
    drop(bytes);
    assert_eq!(handle.snapshot().response_owners, 0);
    assert_eq!(handle.snapshot().response_bytes, 0);
    drop(get().unwrap().wait().await.unwrap());
    handle.close();
    assert!(worker
        .join_until(Instant::now() + Duration::from_secs(5))
        .await
        .unwrap());
    audit.close();
    assert!(journal
        .join_until(Instant::now() + Duration::from_secs(5))
        .unwrap());
}
