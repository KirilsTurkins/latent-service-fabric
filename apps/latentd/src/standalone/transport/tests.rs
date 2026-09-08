mod deadline;
mod gates;
mod network;
mod ownership;

use std::future::Future;
use std::sync::Arc;
use std::time::Duration;

use latent_core::{InvocationPrincipal, Metadata, PrincipalKind, SystemActivationClock, TenantId};
use tonic::body::Body;
use tonic::codegen::http::Request;
use tower::Layer;

use super::*;

const TOKEN: &str = "standalone-test-credential-00000001";

fn configuration() -> TransportConfig {
    TransportConfig {
        bind: "127.0.0.1:0".parse().unwrap(),
        maximum_connections: 1,
        maximum_rpcs: 3,
        reserved_cancel_status_rpcs: 1,
        maximum_control_jobs: 1,
        maximum_header_bytes: 4096,
        maximum_streams_per_connection: 4,
        request_timeout: Duration::from_secs(2),
        shutdown_timeout: Duration::from_millis(200),
        credentials: vec![TransportCredential {
            token: TOKEN.to_owned(),
            principal: InvocationPrincipal {
                subject: "operator".to_owned(),
                kind: PrincipalKind::Administrator,
                tenant: Some(TenantId("acme".to_owned())),
                service: None,
                claims: Metadata::from([("latent.node.operator".to_owned(), "true".to_owned())]),
            },
        }],
    }
}

fn run<F: Future<Output = ()>>(test: impl FnOnce(Handle) -> F) {
    let control = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(1)
        .thread_name("standalone-control-test")
        .enable_all()
        .build()
        .unwrap();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(async {
        tokio::time::timeout(Duration::from_secs(5), test(control.handle().clone()))
            .await
            .unwrap();
    });
}

fn request(path: &str) -> Request<Body> {
    Request::builder()
        .uri(path)
        .header("authorization", format!("Bearer {TOKEN}"))
        .body(Body::empty())
        .unwrap()
}

fn layer(shared: &Arc<state::Shared>, control_runtime: Handle) -> dispatch::DispatchLayer {
    dispatch::DispatchLayer {
        shared: Arc::clone(shared),
        clock: Arc::new(SystemActivationClock),
        control_runtime,
    }
}

fn ready_shared() -> Arc<state::Shared> {
    let shared = state::Shared::new(configuration());
    TransportHandle {
        shared: Arc::clone(&shared),
    }
    .start_accepting()
    .unwrap();
    shared
}
