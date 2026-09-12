use std::sync::{Arc, Mutex};
use std::time::Duration;

use hyper_util::rt::TokioIo;
use latent_core::{InvocationPrincipal, Metadata, PrincipalKind, TenantId};
use latent_wire::invocation::AuthenticatedInvocationContext;
use latent_wire::management::ManagementServiceAdapter;
use tokio::sync::oneshot;
use tokio::task::JoinHandle;
use tonic::codegen::tokio_stream::StreamExt;
use tonic::service::interceptor::InterceptedService;
use tonic::transport::{Channel, Endpoint};
use tonic::{Request, Status};
use tower::service_fn;

pub(super) struct Server {
    shutdown: Option<oneshot::Sender<()>>,
    task: JoinHandle<Result<(), tonic::transport::Error>>,
}

impl Server {
    pub async fn start(adapter: ManagementServiceAdapter) -> (Channel, Self) {
        let (client, server) = tokio::io::duplex(64 * 1024);
        let (shutdown, stopped) = oneshot::channel();
        let incoming = tonic::codegen::tokio_stream::iter([Ok::<_, std::io::Error>(server)])
            .chain(tonic::codegen::tokio_stream::pending());
        let task = tokio::spawn(
            tonic::transport::Server::builder()
                .add_service(InterceptedService::new(
                    adapter.clone().release_server(),
                    authenticate,
                ))
                .add_service(InterceptedService::new(
                    adapter.clone().deployment_server(),
                    authenticate,
                ))
                .add_service(InterceptedService::new(
                    adapter.clone().route_server(),
                    authenticate,
                ))
                .add_service(InterceptedService::new(
                    adapter.clone().audit_server(),
                    authenticate,
                ))
                .add_service(InterceptedService::new(
                    adapter.clone().rollout_server(),
                    authenticate,
                ))
                .add_service(InterceptedService::new(adapter.node_server(), authenticate))
                .serve_with_incoming_shutdown(incoming, async {
                    let _ = stopped.await;
                }),
        );
        let socket = Arc::new(Mutex::new(Some(client)));
        let connector = service_fn(move |_| {
            let socket = socket.lock().unwrap().take();
            async move {
                socket
                    .map(TokioIo::new)
                    .ok_or_else(|| std::io::Error::other("test transport is already connected"))
            }
        });
        let channel = tokio::time::timeout(
            Duration::from_secs(5),
            Endpoint::from_static("http://management.test")
                .timeout(Duration::from_secs(5))
                .connect_with_connector(connector),
        )
        .await
        .unwrap()
        .unwrap();
        (
            channel,
            Self {
                shutdown: Some(shutdown),
                task,
            },
        )
    }

    pub async fn shutdown(mut self) {
        let _ = self.shutdown.take().unwrap().send(());
        tokio::time::timeout(Duration::from_secs(5), &mut self.task)
            .await
            .unwrap()
            .unwrap()
            .unwrap();
    }
}

impl Drop for Server {
    fn drop(&mut self) {
        self.task.abort();
    }
}

/// The fixture authenticates only these fixed credentials. Arbitrary tenant or
/// claim metadata cannot manufacture a principal extension.
fn authenticate(mut request: Request<()>) -> Result<Request<()>, Status> {
    let identity = request
        .metadata()
        .get("authorization")
        .and_then(|value| value.to_str().ok());
    let (subject, tenant, kind, operator) = match identity {
        Some("alice") => ("alice", "acme", PrincipalKind::Administrator, false),
        Some("bob") => ("bob", "other", PrincipalKind::Administrator, false),
        Some("caller") => ("caller", "acme", PrincipalKind::User, false),
        Some("operator") => ("operator", "acme", PrincipalKind::Administrator, true),
        _ => return Err(Status::unauthenticated("test credential is required")),
    };
    let mut claims = Metadata::new();
    if operator {
        claims.insert("latent.node.operator".to_owned(), "true".to_owned());
    }
    request
        .extensions_mut()
        .insert(AuthenticatedInvocationContext::new(InvocationPrincipal {
            subject: subject.to_owned(),
            kind,
            tenant: Some(TenantId(tenant.to_owned())),
            service: None,
            claims,
        }));
    Ok(request)
}

pub(in super::super) fn request<T>(identity: &str, message: T) -> Request<T> {
    let mut request = Request::new(message);
    request
        .metadata_mut()
        .insert("authorization", identity.parse().unwrap());
    request.set_timeout(Duration::from_secs(5));
    request
}
