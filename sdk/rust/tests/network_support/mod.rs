mod invocation;
mod management;
mod socket;

use latent_core::{ActivationId, ContractId, FunctionId, ResourceBudget, ServiceId, TenantId};
use latent_rpc::{control::v1 as control, invocation::v1 as proto};
use latent_sdk::{
    network::{ClientConfig, ClientLimits, RpcClient},
    InvocationTarget, InvokeOptions, InvokeRequest,
};
use std::{
    collections::{BTreeMap, HashMap},
    net::SocketAddr,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tokio::{net::TcpListener, sync::oneshot, task::JoinHandle};
use tonic::{
    codegen::tokio_stream::{wrappers::TcpListenerStream, StreamExt},
    Request, Status,
};

pub const TOKEN: &str = "LSF-PUBLIC-SDK-TRANSPORT-FIXTURE-ONLY";

#[derive(Default)]
pub struct State {
    pub accepted: AtomicUsize,
    pub open: AtomicUsize,
    pub invocations: AtomicUsize,
    pub cancellations: AtomicUsize,
    pub mutations: AtomicUsize,
    pub activations: Mutex<HashMap<String, proto::ActivationStatus>>,
    pub policies: Mutex<HashMap<String, control::ApplyPolicyResponse>>,
}

#[derive(Clone)]
struct Service(Arc<State>);

pub struct Peer {
    pub address: SocketAddr,
    pub state: Arc<State>,
    shutdown: Option<oneshot::Sender<()>>,
    task: Option<JoinHandle<()>>,
}

impl Peer {
    pub async fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let state = Arc::new(State::default());
        let service = Service(Arc::clone(&state));
        let shared = Arc::clone(&state);
        let incoming = TcpListenerStream::new(listener).map(move |socket| {
            socket.map(|stream| {
                shared.accepted.fetch_add(1, Ordering::AcqRel);
                shared.open.fetch_add(1, Ordering::AcqRel);
                socket::Counted {
                    stream,
                    state: Arc::clone(&shared),
                }
            })
        });
        let (shutdown, stopped) = oneshot::channel();
        let task = tokio::spawn(async move {
            tonic::transport::Server::builder()
                .concurrency_limit_per_connection(8)
                .max_concurrent_streams(8)
                .add_service(
                    proto::invocation_service_server::InvocationServiceServer::new(service.clone()),
                )
                .add_service(control::policy_service_server::PolicyServiceServer::new(
                    service.clone(),
                ))
                .add_service(
                    control::capability_service_server::CapabilityServiceServer::new(service),
                )
                .serve_with_incoming_shutdown(incoming, async {
                    let _ = stopped.await;
                })
                .await
                .unwrap();
        });
        Self {
            address,
            state,
            shutdown: Some(shutdown),
            task: Some(task),
        }
    }

    pub fn config(&self) -> ClientConfig {
        ClientConfig {
            endpoint: self.address,
            tenant: TenantId("tests".into()),
            credential: TOKEN.to_owned().into(),
            limits: ClientLimits::default(),
        }
    }

    pub fn client(&self) -> RpcClient {
        RpcClient::new(self.config()).unwrap()
    }

    pub async fn stop(mut self) {
        self.shutdown.take().unwrap().send(()).unwrap();
        tokio::time::timeout(Duration::from_secs(2), self.task.take().unwrap())
            .await
            .unwrap()
            .unwrap();
    }
}

impl Drop for Peer {
    fn drop(&mut self) {
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        if let Some(task) = &self.task {
            task.abort();
        }
    }
}

fn authenticate<Value>(request: &Request<Value>) -> Result<(), Status> {
    if request
        .metadata()
        .get("authorization")
        .and_then(|value| value.to_str().ok())
        != Some(format!("Bearer {TOKEN}").as_str())
    {
        return Err(Status::unauthenticated("fixture denied"));
    }
    Ok(())
}

pub fn request(identity: &str, mode: &str) -> InvokeRequest {
    InvokeRequest {
        activation_id: Some(ActivationId(identity.into())),
        root_activation_id: None,
        parent_activation_id: None,
        target: InvocationTarget {
            tenant: TenantId("tests".into()),
            service: ServiceId("example".into()),
            contract: ContractId("example:api@1.0.0".into()),
            function: FunctionId("run".into()),
            route: None,
        },
        payload: mode.as_bytes().into(),
        media_type: "application/octet-stream".into(),
        options: InvokeOptions {
            deadline_unix_millis: None,
            priority: 0,
            idempotency_key: None,
            metadata: BTreeMap::new(),
            budget: ResourceBudget {
                cpu_fuel: 10000,
                memory_bytes: 65536,
                wall_time_limit_millis: Some(1000),
                child_calls: 0,
                outbound_requests: 1,
                state_read_bytes: 0,
                state_write_bytes: 0,
                blob_read_bytes: 32,
                blob_write_bytes: 32,
                log_bytes: 0,
                effect_count: 0,
            },
        },
    }
}

pub fn policy(operation: &str) -> control::ApplyPolicyRequest {
    control::ApplyPolicyRequest {
        operation_id: operation.into(),
        expected_generation: Some(0),
        policy: Some(control::Policy {
            id: "policy".into(),
            document: "{}".into(),
            record_kind: 1,
            ..Default::default()
        }),
    }
}

pub async fn wait_until(predicate: impl Fn() -> bool) {
    tokio::time::timeout(Duration::from_secs(2), async {
        while !predicate() {
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
    })
    .await
    .unwrap();
}
