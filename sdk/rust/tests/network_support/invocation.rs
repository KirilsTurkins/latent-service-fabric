use super::{authenticate, proto, Service};
use std::sync::atomic::Ordering;
use tonic::{Request, Response, Status};

#[tonic::async_trait]
impl proto::invocation_service_server::InvocationService for Service {
    async fn invoke(
        &self,
        request: Request<proto::InvokeRequest>,
    ) -> Result<Response<proto::InvokeResponse>, Status> {
        authenticate(&request)?;
        let request = request.into_inner();
        if request.target.as_ref().map(|target| target.tenant.as_str()) != Some("tests") {
            return Err(Status::permission_denied("tenant mismatch"));
        }
        let identity = request
            .activation_id
            .clone()
            .unwrap_or_else(|| "assigned".into());
        if identity.is_empty() {
            return Err(Status::invalid_argument("empty identity"));
        }
        self.0.invocations.fetch_add(1, Ordering::AcqRel);
        self.0.activations.lock().unwrap().insert(
            identity.clone(),
            proto::ActivationStatus {
                activation_id: identity.clone(),
                phase: "running".into(),
                ..Default::default()
            },
        );
        if request.payload == b"hold" {
            std::future::pending::<()>().await;
        }
        let result = if request.payload == b"declared" {
            proto::invoke_response::Result::DeclaredError(proto::DeclaredError {
                code: "domain-failure".into(),
                payload: b"typed failure".to_vec(),
                ..Default::default()
            })
        } else if request.payload == b"platform" {
            proto::invoke_response::Result::PlatformFailure(proto::PlatformError {
                code: "permission-denied".into(),
                ..Default::default()
            })
        } else {
            proto::invoke_response::Result::Success(proto::Success {
                payload: if request.payload == b"oversize" {
                    vec![1; 4096]
                } else {
                    request.payload.clone()
                },
                media_type: "application/octet-stream".into(),
                ..Default::default()
            })
        };
        Ok(Response::new(proto::InvokeResponse {
            activation_id: if request.payload == b"wrong-id" {
                "different".into()
            } else {
                identity
            },
            revision_id: "revision".into(),
            release_digest: format!("sha256:{}", "1".repeat(64)),
            route_generation: u64::MAX,
            consumption: Some(proto::BudgetConsumption::default()),
            result: Some(result),
            publication_id: None,
        }))
    }

    async fn cancel(
        &self,
        request: Request<proto::CancelRequest>,
    ) -> Result<Response<proto::CancelResponse>, Status> {
        authenticate(&request)?;
        self.0.cancellations.fetch_add(1, Ordering::AcqRel);
        let request = request.into_inner();
        let mut activations = self.0.activations.lock().unwrap();
        let Some(status) = activations.get_mut(&request.activation_id) else {
            return Ok(Response::new(proto::CancelResponse {
                disposition: 3,
                terminal_state: None,
            }));
        };
        if let Some(state) = &status.terminal_state {
            return Ok(Response::new(proto::CancelResponse {
                disposition: 2,
                terminal_state: Some(state.clone()),
            }));
        }
        status.terminal_state = Some("cancelled".into());
        status.terminal_at_unix_millis = Some(1);
        status.final_consumption = Some(proto::BudgetConsumption::default());
        status.terminal_outcome = Some(proto::activation_status::TerminalOutcome::PlatformFailure(
            proto::PlatformError {
                code: "cancelled".into(),
                ..Default::default()
            },
        ));
        Ok(Response::new(proto::CancelResponse {
            disposition: 1,
            terminal_state: None,
        }))
    }

    async fn get_activation(
        &self,
        request: Request<proto::GetActivationRequest>,
    ) -> Result<Response<proto::ActivationStatus>, Status> {
        authenticate(&request)?;
        self.0
            .activations
            .lock()
            .unwrap()
            .get(&request.into_inner().activation_id)
            .cloned()
            .map(Response::new)
            .ok_or_else(|| Status::not_found("not retained"))
    }
}
