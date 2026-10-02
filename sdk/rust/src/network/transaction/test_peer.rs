//! Serialization/transport peer only; this is not a node transaction executor.
use latent_rpc::{invocation::v1 as i, transaction::v1 as t};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use tonic::{Request, Response, Status};

pub(super) struct State {
    pub calls: Arc<AtomicUsize>,
}
pub(super) fn effect_plan(
    original: latent_rpc::control::v1::PlanEffectMutationRequest,
) -> latent_rpc::control::v1::EffectManagementPlan {
    latent_rpc::control::v1::EffectManagementPlan {
        original: Some(original),
        plan_digest: vec![2; 32],
        management_sequence: 1,
        owner_epoch: u64::MAX,
        claim_generation: 1,
        dispatch_attempt: 1,
        prepared_at_unix_millis: 1000,
        expires_at_unix_millis: 2000,
        before: 4,
        safety: 1,
        dedup_valid_until_unix_millis: None,
    }
}
fn effect_receipt(
    plan: latent_rpc::control::v1::EffectManagementPlan,
) -> latent_rpc::control::v1::StateOperationReceipt {
    let original = plan.original.as_ref().unwrap();
    let effect = original.effect.as_ref().unwrap();
    latent_rpc::control::v1::StateOperationReceipt {
        operation_id: original.operation_id.clone(),
        receipt_id: "effect-management-receipt".into(),
        mutation: original.mutation,
        namespace: effect.command.as_ref().unwrap().namespace.clone(),
        authenticated_operator: "operator".into(),
        before_version: original.expected_version.clone(),
        after_version: vec![3; 32],
        completed_at_unix_millis: 1500,
        record_id: Some(effect.effect_id.clone()),
        policy_digest: original.expected_policy_digest.clone(),
        disposition: 1,
        effect: Some(latent_rpc::control::v1::EffectManagementReceiptDetails {
            original_plan: Some(plan),
            before: 4,
            after: 9,
            fact: 1,
            provider_receipt: None,
            provider_observed_at_unix_millis: None,
        }),
    }
}
#[tonic::async_trait]
impl latent_rpc::control::v1::state_service_server::StateService for State {
    async fn inspect_namespace(
        &self,
        _: Request<latent_rpc::control::v1::InspectNamespaceRequest>,
    ) -> Result<Response<latent_rpc::control::v1::InspectNamespaceResponse>, Status> {
        Err(Status::unimplemented("transport peer"))
    }
    async fn select_entity(
        &self,
        _: Request<latent_rpc::control::v1::SelectEntityRequest>,
    ) -> Result<Response<latent_rpc::control::v1::SelectEntityResponse>, Status> {
        Err(Status::unimplemented("transport peer"))
    }
    async fn mutate_namespace(
        &self,
        _: Request<latent_rpc::control::v1::MutateNamespaceRequest>,
    ) -> Result<Response<latent_rpc::control::v1::MutateNamespaceResponse>, Status> {
        Err(Status::unimplemented("transport peer"))
    }
    async fn plan_effect_mutation(
        &self,
        request: Request<latent_rpc::control::v1::PlanEffectMutationRequest>,
    ) -> Result<Response<latent_rpc::control::v1::PlanEffectMutationResponse>, Status> {
        self.calls.fetch_add(1, Ordering::AcqRel);
        let original = request.into_inner();
        let reason = original.reason.clone();
        let mut plan = effect_plan(original);
        if reason == "bad-window" {
            plan.expires_at_unix_millis = 31001;
        }
        Ok(Response::new(
            latent_rpc::control::v1::PlanEffectMutationResponse {
                plan: Some(plan),
                replayed: false,
                audit_ack: (reason == "bad-audit").then_some(latent_rpc::control::v1::AuditAck {
                    status: 91,
                    attempt_sequence: None,
                }),
            },
        ))
    }
    async fn mutate_state(
        &self,
        request: Request<latent_rpc::control::v1::MutateStateRequest>,
    ) -> Result<Response<latent_rpc::control::v1::MutateStateResponse>, Status> {
        self.calls.fetch_add(1, Ordering::AcqRel);
        let original = request.into_inner();
        let mut receipt = effect_receipt(original.effect_plan.unwrap());
        if original.reason == "forged-fact" {
            let details = receipt.effect.as_mut().unwrap();
            details.fact = 2;
            details.provider_receipt = Some("forged-provider".into());
            details.provider_observed_at_unix_millis = Some(1400);
        }
        Ok(Response::new(
            latent_rpc::control::v1::MutateStateResponse {
                receipt: Some(receipt),
                audit_ack: None,
                replayed: false,
            },
        ))
    }
    async fn get_state_operation_receipt(
        &self,
        request: Request<latent_rpc::control::v1::GetStateOperationReceiptRequest>,
    ) -> Result<Response<latent_rpc::control::v1::GetStateOperationReceiptResponse>, Status> {
        self.calls.fetch_add(1, Ordering::AcqRel);
        let original = request.into_inner();
        let plan = original.original_effect_plan.unwrap();
        assert_ne!(
            original.namespace.unwrap().authorization_publication,
            plan.original
                .as_ref()
                .unwrap()
                .effect
                .as_ref()
                .unwrap()
                .authorization_publication
        );
        Ok(Response::new(
            latent_rpc::control::v1::GetStateOperationReceiptResponse {
                receipt: Some(effect_receipt(plan)),
                namespace_receipt: None,
                audit_ack: None,
            },
        ))
    }
}

pub(super) struct Service {
    pub calls: Arc<AtomicUsize>,
    pub fail_audit: bool,
}

#[tonic::async_trait]
impl t::transaction_service_server::TransactionService for Service {
    async fn invoke_command(
        &self,
        request: Request<t::InvokeCommandRequest>,
    ) -> Result<Response<t::InvokeCommandResponse>, Status> {
        self.calls.fetch_add(1, Ordering::AcqRel);
        assert_eq!(
            request.get_ref().command.as_ref().unwrap().client_key,
            "original-client-key"
        );
        assert_eq!(request.get_ref().expected_versions.len(), 1);
        Err(Status::aborted("transport fixture abort"))
    }
    async fn query(
        &self,
        _: Request<t::QueryRequest>,
    ) -> Result<Response<t::QueryResponse>, Status> {
        Err(Status::unimplemented("transport fixture"))
    }
    async fn lookup_commit(
        &self,
        _: Request<t::LookupCommitRequest>,
    ) -> Result<Response<t::LookupCommitResponse>, Status> {
        Err(Status::unimplemented("transport fixture"))
    }
    async fn get_effect(
        &self,
        _: Request<t::GetEffectRequest>,
    ) -> Result<Response<t::GetEffectResponse>, Status> {
        Err(Status::unimplemented("transport fixture"))
    }
    async fn list_effect_history(
        &self,
        _: Request<t::ListEffectHistoryRequest>,
    ) -> Result<Response<t::ListEffectHistoryResponse>, Status> {
        Err(Status::unimplemented("transport fixture"))
    }
    async fn cancel_command(
        &self,
        _: Request<t::CancelCommandRequest>,
    ) -> Result<Response<t::CancelCommandResponse>, Status> {
        Err(Status::unimplemented("transport fixture"))
    }

    async fn lookup_command(
        &self,
        request: Request<t::LookupCommandRequest>,
    ) -> Result<Response<t::LookupCommandResponse>, Status> {
        self.calls.fetch_add(1, Ordering::AcqRel);
        assert_eq!(
            request.metadata().get("authorization").unwrap(),
            "Bearer LSF-PUBLIC-SDK-TRANSPORT-FIXTURE-ONLY"
        );
        if !self.fail_audit {
            return Err(Status::aborted("transport fixture abort"));
        }
        let key = request.into_inner().command.unwrap();
        let digest = format!("sha256:{}", "a".repeat(64));
        let source = t::SourceIdentity {
            publication_id: format!("publication:{digest}"),
            revision_id: "original-revision".into(),
            release_digest: digest.clone(),
            component_digest: digest.clone(),
            contract_digest: digest.clone(),
            state_schema: digest,
            route_generation: u64::MAX,
            input_format: "raw-v1".into(),
            result_format: "raw-v1".into(),
        };
        let mut response = Response::new(t::LookupCommandResponse {
            command: Some(t::CommandInspection {
                key: Some(t::CommandKey {
                    namespace: key.namespace,
                    recovery_scope: "caller-scope".into(),
                    operation: key.operation,
                    entity: key.entity,
                    client_key: key.client_key,
                }),
                command_id: "original-command".into(),
                attempt_id: "original-attempt".into(),
                fingerprint_sha256: vec![7; 32],
                outcome: t::CommandOutcome::Rejected as i32,
                metadata_durable: true,
                application_state_committed: false,
                source: Some(source),
                retained_result: Some(t::command_inspection::RetainedResult::BusinessRejection(
                    i::DeclaredError {
                        code: "original-rejection".into(),
                        message: "business decision".into(),
                        payload: vec![1],
                        media_type: "application/octet-stream".into(),
                        metadata: std::collections::HashMap::default(),
                    },
                )),
                ..Default::default()
            }),
        });
        response
            .metadata_mut()
            .insert("latent-audit-status", "durable".parse().unwrap());
        // Missing durable attempt is a deliberately malformed later audit field.
        Ok(response)
    }
}

pub(super) struct Dispatcher {
    pub calls: Arc<AtomicUsize>,
}

#[tonic::async_trait]
impl latent_rpc::control::v1::dispatcher_service_server::DispatcherService for Dispatcher {
    async fn inspect_dispatcher(
        &self,
        request: Request<latent_rpc::control::v1::InspectDispatcherRequest>,
    ) -> Result<Response<latent_rpc::control::v1::InspectDispatcherResponse>, Status> {
        use latent_rpc::control::v1 as c;
        self.calls.fetch_add(1, Ordering::AcqRel);
        assert_eq!(request.get_ref().scope, c::DispatcherScope::Node as i32);
        Ok(Response::new(c::InspectDispatcherResponse {
            dispatcher: Some(c::DispatcherSnapshot {
                generation: Some(c::DispatcherGeneration {
                    owner_epoch: u64::MAX,
                    revision: u64::MAX,
                }),
                paused: true,
                failure: c::DispatcherFailure::None as i32,
                physical_owners: u64::MAX,
                ..Default::default()
            }),
            audit_ack: None,
        }))
    }

    async fn control_dispatcher(
        &self,
        request: Request<latent_rpc::control::v1::ControlDispatcherRequest>,
    ) -> Result<Response<latent_rpc::control::v1::ControlDispatcherResponse>, Status> {
        use latent_rpc::control::v1 as c;
        self.calls.fetch_add(1, Ordering::AcqRel);
        assert_eq!(
            request.metadata().get("authorization").unwrap(),
            "Bearer LSF-PUBLIC-SDK-TRANSPORT-FIXTURE-ONLY"
        );
        let original = request.into_inner();
        let mut receipt = dispatcher_receipt(&original);
        if original.action == c::DispatcherAction::Resume as i32 {
            receipt.clock_continuity_proven = false;
        }
        if original.operation_id == "not-committed" {
            receipt.disposition = c::StateOperationDisposition::Conflict as i32;
        }
        Ok(Response::new(c::ControlDispatcherResponse {
            receipt: Some(receipt),
            replayed: original.operation_id == "replayed",
            published: true,
            paused: true,
            audit_ack: (original.operation_id == "original-control").then_some(c::AuditAck {
                status: 91,
                attempt_sequence: None,
            }),
        }))
    }

    async fn get_dispatcher_operation(
        &self,
        request: Request<latent_rpc::control::v1::GetDispatcherOperationRequest>,
    ) -> Result<Response<latent_rpc::control::v1::GetDispatcherOperationResponse>, Status> {
        use latent_rpc::control::v1 as c;
        self.calls.fetch_add(1, Ordering::AcqRel);
        let original = request.into_inner().original.unwrap();
        assert_eq!(original.operation_id, "original-control");
        assert_eq!(
            original.expected_generation.as_ref().unwrap().revision,
            u64::MAX - 1
        );
        Ok(Response::new(c::GetDispatcherOperationResponse {
            receipt: Some(dispatcher_receipt(&original)),
            audit_ack: None,
        }))
    }
}

fn dispatcher_receipt(
    original: &latent_rpc::control::v1::ControlDispatcherRequest,
) -> latent_rpc::control::v1::DispatcherOperationReceipt {
    use latent_rpc::control::v1 as c;
    let before = original.expected_generation.as_ref().unwrap();
    c::DispatcherOperationReceipt {
        operation_id: original.operation_id.clone(),
        receipt_id: "dispatcher-receipt".into(),
        action: original.action,
        authenticated_operator: "operator".into(),
        actor_tenant: "operator-tenant".into(),
        before_generation: Some(*before),
        after_generation: Some(c::DispatcherGeneration {
            owner_epoch: before.owner_epoch,
            revision: before.revision + 1,
        }),
        observed_at_unix_millis: u64::MAX,
        clock_continuity_proven: true,
        restore_review_required: false,
        disposition: c::StateOperationDisposition::Committed as i32,
    }
}
