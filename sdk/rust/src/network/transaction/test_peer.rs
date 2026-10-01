//! Serialization/transport peer only; this is not a node transaction executor.
use latent_rpc::{invocation::v1 as i, transaction::v1 as t};
use std::sync::{atomic::{AtomicUsize, Ordering}, Arc};
use tonic::{Request, Response, Status};

pub(super) struct Service {
    pub calls: Arc<AtomicUsize>,
    pub fail_audit: bool,
}

#[tonic::async_trait]
impl t::transaction_service_server::TransactionService for Service {
    async fn invoke_command(&self, request: Request<t::InvokeCommandRequest>) -> Result<Response<t::InvokeCommandResponse>, Status> {
        self.calls.fetch_add(1, Ordering::AcqRel);
        assert_eq!(request.get_ref().command.as_ref().unwrap().client_key, "original-client-key");
        assert_eq!(request.get_ref().expected_versions.len(), 1);
        Err(Status::aborted("transport fixture abort"))
    }
    async fn query(&self, _: Request<t::QueryRequest>) -> Result<Response<t::QueryResponse>, Status> { Err(Status::unimplemented("transport fixture")) }
    async fn lookup_commit(&self, _: Request<t::LookupCommitRequest>) -> Result<Response<t::LookupCommitResponse>, Status> { Err(Status::unimplemented("transport fixture")) }
    async fn get_effect(&self, _: Request<t::GetEffectRequest>) -> Result<Response<t::GetEffectResponse>, Status> { Err(Status::unimplemented("transport fixture")) }
    async fn list_effect_history(&self, _: Request<t::ListEffectHistoryRequest>) -> Result<Response<t::ListEffectHistoryResponse>, Status> { Err(Status::unimplemented("transport fixture")) }
    async fn cancel_command(&self, _: Request<t::CancelCommandRequest>) -> Result<Response<t::CancelCommandResponse>, Status> { Err(Status::unimplemented("transport fixture")) }

    async fn lookup_command(&self, request: Request<t::LookupCommandRequest>) -> Result<Response<t::LookupCommandResponse>, Status> {
        self.calls.fetch_add(1, Ordering::AcqRel);
        assert_eq!(request.metadata().get("authorization").unwrap(), "Bearer LSF-PUBLIC-SDK-TRANSPORT-FIXTURE-ONLY");
        if !self.fail_audit { return Err(Status::aborted("transport fixture abort")); }
        let key = request.into_inner().command.unwrap();
        let digest = format!("sha256:{}", "a".repeat(64));
        let source = t::SourceIdentity {
            publication_id: format!("publication:{digest}"), revision_id: "original-revision".into(),
            release_digest: digest.clone(), component_digest: digest.clone(), contract_digest: digest.clone(),
            state_schema: digest, route_generation: u64::MAX, input_format: "raw-v1".into(), result_format: "raw-v1".into(),
        };
        let mut response = Response::new(t::LookupCommandResponse { command: Some(t::CommandInspection {
            key: Some(t::CommandKey { namespace: key.namespace, recovery_scope: "caller-scope".into(),
                operation: key.operation, entity: key.entity, client_key: key.client_key }),
            command_id: "original-command".into(), attempt_id: "original-attempt".into(), fingerprint_sha256: vec![7;32],
            outcome: t::CommandOutcome::Rejected as i32, metadata_durable: true, application_state_committed: false,
            source: Some(source), retained_result: Some(t::command_inspection::RetainedResult::BusinessRejection(i::DeclaredError {
                code: "original-rejection".into(), message: "business decision".into(), payload: vec![1],
                media_type: "application/octet-stream".into(), metadata: std::collections::HashMap::default(),
            })), ..Default::default()
        }) });
        response.metadata_mut().insert("latent-audit-status", "durable".parse().unwrap());
        // Missing durable attempt is a deliberately malformed later audit field.
        Ok(response)
    }
}
