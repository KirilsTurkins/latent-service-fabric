use super::*;
use latent_artifacts::{DirectoryArtifactRepository, DirectoryArtifactRepositoryConfig};
use latent_control_store::{
    deployment_operations::DeploymentOperationLimits, DirectoryDeploymentRepository,
    DirectoryDeploymentRepositoryConfig,
};
use latent_core::{DeploymentId, PlatformErrorCode, TenantId};
use std::{future::poll_fn, sync::Arc};
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
async fn deployment_response_owner_survives_unpolled_body_and_retained_frame() {
    let directory = TempDir::new().unwrap();
    let artifacts = Arc::new(
        DirectoryArtifactRepository::open(
            directory.path().join("releases"),
            DirectoryArtifactRepositoryConfig::default(),
        )
        .unwrap(),
    );
    let store = DirectoryDeploymentRepository::open_with_operation_limits(
        directory.path().join("deployments"),
        artifacts,
        DirectoryDeploymentRepositoryConfig::default(),
        DeploymentOperationLimits {
            maximum_read_owners: 1,
            ..DeploymentOperationLimits::default()
        },
    )
    .await
    .unwrap();
    let tenant = TenantId("acme".into());
    let id = DeploymentId("absent".into());
    let value = store.get_operation_snapshot(&tenant, &id).await.unwrap();
    let (_, lease) = value.into_parts();
    let mut response = http::Response::new(Body::new(OneFrame(Some(Bytes::from_static(
        b"bounded-response",
    )))));
    response.extensions_mut().insert(lease);
    let mut body = retain(response).into_body();
    assert_eq!(
        store
            .get_operation_snapshot(&tenant, &id)
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    let bytes = poll_fn(|cx| Pin::new(&mut body).poll_frame(cx))
        .await
        .unwrap()
        .unwrap()
        .into_data()
        .unwrap();
    drop(body);
    assert_eq!(bytes.as_ref(), b"bounded-response");
    assert_eq!(
        store
            .get_operation_snapshot(&tenant, &id)
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    drop(bytes);
    drop(store.get_operation_snapshot(&tenant, &id).await.unwrap());
}
