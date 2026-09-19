use latent_core::TenantId;
use latent_rpc::{control::v1 as control, invocation::v1 as invocation};
use latent_sdk::network::{ClientConfig, ClientLimits, RpcClient};
use prost::Message;
use std::{net::SocketAddr, time::Duration};
use tokio::{net::TcpListener, sync::oneshot, task::JoinHandle};
use tonic::{codegen::tokio_stream::wrappers::TcpListenerStream, Request, Response, Status};

const CREDENTIAL: &str = "LSF-PUBLIC-PROFILE-PEER-FIXTURE-ONLY";

#[derive(Clone)]
struct Service;

pub struct ScriptedPeer {
    address: SocketAddr,
    shutdown: Option<oneshot::Sender<()>>,
    task: Option<JoinHandle<()>>,
}

impl ScriptedPeer {
    pub async fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let (shutdown, stopped) = oneshot::channel();
        let task = tokio::spawn(async move {
            tonic::transport::Server::builder()
                .concurrency_limit_per_connection(4)
                .max_concurrent_streams(4)
                .add_service(control::policy_service_server::PolicyServiceServer::new(
                    Service,
                ))
                .add_service(
                    invocation::invocation_service_server::InvocationServiceServer::new(Service),
                )
                .serve_with_incoming_shutdown(TcpListenerStream::new(listener), async {
                    let _ = stopped.await;
                })
                .await
                .unwrap();
        });
        Self {
            address,
            shutdown: Some(shutdown),
            task: Some(task),
        }
    }

    pub fn client(&self) -> RpcClient {
        RpcClient::new(ClientConfig {
            endpoint: self.address,
            tenant: TenantId("tests".into()),
            credential: CREDENTIAL.to_owned().into(),
            limits: ClientLimits::default(),
        })
        .unwrap()
    }

    pub async fn stop(mut self) {
        self.shutdown.take().unwrap().send(()).unwrap();
        tokio::time::timeout(Duration::from_secs(2), self.task.take().unwrap())
            .await
            .unwrap()
            .unwrap();
    }
}

impl Drop for ScriptedPeer {
    fn drop(&mut self) {
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        if let Some(task) = &self.task {
            task.abort();
        }
    }
}

fn authenticated<Value>(request: &Request<Value>) -> Result<(), Status> {
    if request
        .metadata()
        .get("authorization")
        .and_then(|value| value.to_str().ok())
        != Some(format!("Bearer {CREDENTIAL}").as_str())
    {
        return Err(Status::unauthenticated("fixture only"));
    }
    Ok(())
}

#[tonic::async_trait]
impl control::policy_service_server::PolicyService for Service {
    async fn apply_policy(
        &self,
        request: Request<control::ApplyPolicyRequest>,
    ) -> Result<Response<control::ApplyPolicyResponse>, Status> {
        authenticated(&request)?;
        let request = request.into_inner();
        let mut policy = request.policy.unwrap();
        policy.generation = u64::MAX;
        policy.content_digest = format!("sha256:{}", "2".repeat(64));
        let receipt = control::CapabilityPolicyOperation {
            operation_id: request.operation_id.clone(),
            tenant: "tests".into(),
            id: policy.id.clone(),
            record_kind: policy.record_kind,
            generation: policy.generation,
            content_digest: policy.content_digest.clone(),
            revoked: false,
        };
        let mut response = Response::new(control::ApplyPolicyResponse {
            policy: Some(policy),
            receipt: Some(receipt),
        });
        match request.operation_id.as_str() {
            "future-audit" | "uncertain-audit" | "bad-audit" => {
                let status = if request.operation_id == "future-audit" {
                    "future-durable-v2"
                } else {
                    "outcome-unknown"
                };
                response
                    .metadata_mut()
                    .insert("latent-audit-status", status.parse().unwrap());
                let sequence = if request.operation_id == "bad-audit" {
                    "01".into()
                } else {
                    u64::MAX.to_string()
                };
                response
                    .metadata_mut()
                    .insert("latent-audit-attempt", sequence.parse().unwrap());
            }
            _ => {}
        }
        Ok(response)
    }

    async fn get_policy(
        &self,
        request: Request<control::GetPolicyRequest>,
    ) -> Result<Response<control::GetPolicyResponse>, Status> {
        authenticated(&request)?;
        let failure = control::PlatformError {
            code: "permission-denied".into(),
            message: "bounded fixture denial".into(),
            retryable: false,
            detail_items: vec![control::ErrorDetail {
                kind: "provider-outcome".into(),
                fields: [("outcome".into(), "unknown".into())].into(),
            }],
        };
        Err(Status::with_details(
            tonic::Code::PermissionDenied,
            "must not become the client diagnostic",
            failure.encode_to_vec().into(),
        ))
    }

    async fn list_policies(
        &self,
        _request: Request<control::ListPoliciesRequest>,
    ) -> Result<Response<control::ListPoliciesResponse>, Status> {
        Ok(Response::new(control::ListPoliciesResponse {
            policies: Vec::new(),
            catalog_generation: u64::MAX,
            page: Some(control::PageResponse {
                next_page_token: Some("x".repeat(118)),
            }),
        }))
    }

    async fn get_policy_operation(
        &self,
        _request: Request<control::GetPolicyOperationRequest>,
    ) -> Result<Response<control::GetPolicyOperationResponse>, Status> {
        Err(Status::not_found("not retained"))
    }

    async fn evaluate_policy(
        &self,
        _request: Request<control::EvaluatePolicyRequest>,
    ) -> Result<Response<control::EvaluatePolicyResponse>, Status> {
        Err(Status::unimplemented("fixture"))
    }

    async fn delete_policy(
        &self,
        _request: Request<control::DeletePolicyRequest>,
    ) -> Result<Response<control::Empty>, Status> {
        Err(Status::unimplemented("fixture"))
    }
}

#[tonic::async_trait]
impl invocation::invocation_service_server::InvocationService for Service {
    async fn invoke(
        &self,
        request: Request<invocation::InvokeRequest>,
    ) -> Result<Response<invocation::InvokeResponse>, Status> {
        authenticated(&request)?;
        let request = request.into_inner();
        let unknown = request.payload == b"unknown-platform";
        Ok(Response::new(invocation::InvokeResponse {
            activation_id: request
                .activation_id
                .unwrap_or_else(|| "assigned-profile".into()),
            revision_id: "revision".into(),
            release_digest: format!("sha256:{}", "1".repeat(64)),
            route_generation: u64::MAX,
            publication_id: Some(format!("publication:sha256:{}", "1".repeat(64))),
            consumption: Some(invocation::BudgetConsumption {
                cpu_fuel: u64::MAX,
                ..Default::default()
            }),
            result: Some(if unknown {
                invocation::invoke_response::Result::PlatformFailure(invocation::PlatformError {
                    code: "future-platform-code".into(),
                    ..Default::default()
                })
            } else {
                invocation::invoke_response::Result::Success(invocation::Success {
                    payload: request.payload,
                    metadata: request.metadata,
                    committed_state_version: Some(String::new()),
                    ..Default::default()
                })
            }),
        }))
    }

    async fn cancel(
        &self,
        request: Request<invocation::CancelRequest>,
    ) -> Result<Response<invocation::CancelResponse>, Status> {
        authenticated(&request)?;
        Ok(Response::new(invocation::CancelResponse {
            disposition: i32::MIN,
            terminal_state: Some("future-state".into()),
        }))
    }

    async fn get_activation(
        &self,
        request: Request<invocation::GetActivationRequest>,
    ) -> Result<Response<invocation::ActivationStatus>, Status> {
        authenticated(&request)?;
        let identity = request.into_inner().activation_id;
        Ok(Response::new(invocation::ActivationStatus {
            phase: if identity == "unknown-phase" {
                "future-phase".into()
            } else {
                "committed".into()
            },
            activation_id: identity,
            terminal_state: Some("completed".into()),
            last_updated_unix_millis: u64::MAX,
            terminal_at_unix_millis: Some(0),
            final_consumption: Some(invocation::BudgetConsumption {
                cpu_fuel: u64::MAX,
                ..Default::default()
            }),
            terminal_outcome: Some(invocation::activation_status::TerminalOutcome::Succeeded(
                invocation::ActivationSuccessSummary {
                    committed_state_version: Some(String::new()),
                    ..Default::default()
                },
            )),
            ..Default::default()
        }))
    }
}
