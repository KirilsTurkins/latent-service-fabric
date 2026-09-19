use crate::management as model;
use latent_rpc::{control::v1 as control, invocation::v1 as invocation};

impl From<control::ResourceBudget> for model::ResourceBudget {
    fn from(value: control::ResourceBudget) -> Self {
        Self {
            cpu_fuel: value.cpu_fuel,
            memory_bytes: value.memory_bytes,
            child_calls: value.child_calls,
            outbound_requests: value.outbound_requests,
            state_read_bytes: value.state_read_bytes,
            state_write_bytes: value.state_write_bytes,
            blob_read_bytes: value.blob_read_bytes,
            blob_write_bytes: value.blob_write_bytes,
            log_bytes: value.log_bytes,
            effect_count: value.effect_count,
            wall_time_limit_millis: value.wall_time_limit_millis,
        }
    }
}

impl From<model::ResourceBudget> for control::ResourceBudget {
    fn from(value: model::ResourceBudget) -> Self {
        Self {
            cpu_fuel: value.cpu_fuel,
            memory_bytes: value.memory_bytes,
            child_calls: value.child_calls,
            outbound_requests: value.outbound_requests,
            state_read_bytes: value.state_read_bytes,
            state_write_bytes: value.state_write_bytes,
            blob_read_bytes: value.blob_read_bytes,
            blob_write_bytes: value.blob_write_bytes,
            log_bytes: value.log_bytes,
            effect_count: value.effect_count,
            wall_time_limit_millis: value.wall_time_limit_millis,
        }
    }
}

impl From<control::ErrorDetail> for model::ErrorDetail {
    fn from(value: control::ErrorDetail) -> Self {
        Self {
            kind: value.kind,
            fields: value.fields.into_iter().collect(),
        }
    }
}

impl From<model::ErrorDetail> for control::ErrorDetail {
    fn from(value: model::ErrorDetail) -> Self {
        Self {
            kind: value.kind,
            fields: value.fields.into_iter().collect(),
        }
    }
}

impl From<control::PlatformError> for model::PlatformError {
    fn from(value: control::PlatformError) -> Self {
        Self {
            code: value.code,
            message: value.message,
            retryable: value.retryable,
            detail_items: value.detail_items.into_iter().map(Into::into).collect(),
        }
    }
}

impl From<model::PlatformError> for control::PlatformError {
    fn from(value: model::PlatformError) -> Self {
        Self {
            code: value.code,
            message: value.message,
            retryable: value.retryable,
            detail_items: value.detail_items.into_iter().map(Into::into).collect(),
        }
    }
}

impl From<control::ObjectMetadata> for model::ObjectMetadata {
    fn from(value: control::ObjectMetadata) -> Self {
        Self {
            name: value.name,
            tenant: value.tenant,
            namespace: value.namespace,
            labels: value.labels.into_iter().collect(),
            annotations: value.annotations.into_iter().collect(),
        }
    }
}

impl From<model::ObjectMetadata> for control::ObjectMetadata {
    fn from(value: model::ObjectMetadata) -> Self {
        Self {
            name: value.name,
            tenant: value.tenant,
            namespace: value.namespace,
            labels: value.labels.into_iter().collect(),
            annotations: value.annotations.into_iter().collect(),
        }
    }
}

impl From<control::PageRequest> for model::PageRequest {
    fn from(value: control::PageRequest) -> Self {
        Self {
            page_size: value.page_size,
            page_token: value.page_token,
        }
    }
}

impl From<model::PageRequest> for control::PageRequest {
    fn from(value: model::PageRequest) -> Self {
        Self {
            page_size: value.page_size,
            page_token: value.page_token,
        }
    }
}

impl From<control::PageResponse> for model::PageResponse {
    fn from(value: control::PageResponse) -> Self {
        Self {
            next_page_token: value.next_page_token,
        }
    }
}

impl From<model::PageResponse> for control::PageResponse {
    fn from(value: model::PageResponse) -> Self {
        Self {
            next_page_token: value.next_page_token,
        }
    }
}

impl From<control::AuditAck> for model::AuditAck {
    fn from(value: control::AuditAck) -> Self {
        Self {
            status: model::AuditAckStatus(value.status),
            attempt_sequence: value.attempt_sequence,
        }
    }
}

impl From<model::AuditAck> for control::AuditAck {
    fn from(value: model::AuditAck) -> Self {
        Self {
            status: value.status.0,
            attempt_sequence: value.attempt_sequence,
        }
    }
}

impl From<invocation::InvocationTarget> for model::InvocationTarget {
    fn from(value: invocation::InvocationTarget) -> Self {
        Self {
            tenant: value.tenant,
            service: value.service,
            contract: value.contract,
            function: value.function,
            route: value.route,
        }
    }
}

impl From<model::InvocationTarget> for invocation::InvocationTarget {
    fn from(value: model::InvocationTarget) -> Self {
        Self {
            tenant: value.tenant,
            service: value.service,
            contract: value.contract,
            function: value.function,
            route: value.route,
        }
    }
}

impl From<invocation::InvokeRequest> for model::InvokeRequest {
    fn from(value: invocation::InvokeRequest) -> Self {
        Self {
            activation_id: value.activation_id,
            parent_activation_id: value.parent_activation_id,
            root_activation_id: value.root_activation_id,
            target: value.target.map(Into::into),
            payload: value.payload,
            media_type: value.media_type,
            deadline_unix_millis: value.deadline_unix_millis,
            priority: value.priority,
            idempotency_key: value.idempotency_key,
            budget: value.budget.map(Into::into),
            metadata: value.metadata.into_iter().collect(),
        }
    }
}

impl From<model::InvokeRequest> for invocation::InvokeRequest {
    fn from(value: model::InvokeRequest) -> Self {
        Self {
            activation_id: value.activation_id,
            parent_activation_id: value.parent_activation_id,
            root_activation_id: value.root_activation_id,
            target: value.target.map(Into::into),
            payload: value.payload,
            media_type: value.media_type,
            deadline_unix_millis: value.deadline_unix_millis,
            priority: value.priority,
            idempotency_key: value.idempotency_key,
            budget: value.budget.map(Into::into),
            metadata: value.metadata.into_iter().collect(),
        }
    }
}

impl From<invocation::BudgetConsumption> for model::BudgetConsumption {
    fn from(value: invocation::BudgetConsumption) -> Self {
        Self {
            cpu_fuel: value.cpu_fuel,
            peak_memory_bytes: value.peak_memory_bytes,
            wall_time_micros: value.wall_time_micros,
            child_calls: value.child_calls,
            outbound_requests: value.outbound_requests,
            state_read_bytes: value.state_read_bytes,
            state_write_bytes: value.state_write_bytes,
            blob_read_bytes: value.blob_read_bytes,
            blob_write_bytes: value.blob_write_bytes,
            log_bytes: value.log_bytes,
            effect_count: value.effect_count,
        }
    }
}

impl From<model::BudgetConsumption> for invocation::BudgetConsumption {
    fn from(value: model::BudgetConsumption) -> Self {
        Self {
            cpu_fuel: value.cpu_fuel,
            peak_memory_bytes: value.peak_memory_bytes,
            wall_time_micros: value.wall_time_micros,
            child_calls: value.child_calls,
            outbound_requests: value.outbound_requests,
            state_read_bytes: value.state_read_bytes,
            state_write_bytes: value.state_write_bytes,
            blob_read_bytes: value.blob_read_bytes,
            blob_write_bytes: value.blob_write_bytes,
            log_bytes: value.log_bytes,
            effect_count: value.effect_count,
        }
    }
}

impl From<invocation::InvokeResponse> for model::InvokeResponse {
    fn from(value: invocation::InvokeResponse) -> Self {
        let (success, declared_error, platform_failure) = match value.result {
            None => (None, None, None),
            Some(invocation::invoke_response::Result::Success(member)) => {
                (Some(member.into()), None, None)
            }
            Some(invocation::invoke_response::Result::DeclaredError(member)) => {
                (None, Some(member.into()), None)
            }
            Some(invocation::invoke_response::Result::PlatformFailure(member)) => {
                (None, None, Some(member.into()))
            }
        };
        Self {
            activation_id: value.activation_id,
            revision_id: value.revision_id,
            release_digest: value.release_digest,
            route_generation: value.route_generation,
            consumption: value.consumption.map(Into::into),
            publication_id: value.publication_id,
            success,
            declared_error,
            platform_failure,
        }
    }
}

impl TryFrom<model::InvokeResponse> for invocation::InvokeResponse {
    type Error = super::RpcFailure;
    fn try_from(value: model::InvokeResponse) -> Result<Self, Self::Error> {
        let result = match (value.success, value.declared_error, value.platform_failure) {
            (None, None, None) => None,
            (Some(member), None, None) => {
                Some(invocation::invoke_response::Result::Success(member.into()))
            }
            (None, Some(member), None) => Some(invocation::invoke_response::Result::DeclaredError(
                member.into(),
            )),
            (None, None, Some(member)) => Some(
                invocation::invoke_response::Result::PlatformFailure(member.into()),
            ),
            _ => return Err(super::RpcFailure::local(super::FailureKind::InvalidRequest)),
        };
        Ok(Self {
            activation_id: value.activation_id,
            revision_id: value.revision_id,
            release_digest: value.release_digest,
            route_generation: value.route_generation,
            consumption: value.consumption.map(Into::into),
            publication_id: value.publication_id,
            result,
        })
    }
}

impl From<invocation::Success> for model::Success {
    fn from(value: invocation::Success) -> Self {
        Self {
            payload: value.payload,
            media_type: value.media_type,
            committed_state_version: value.committed_state_version,
            effect_ids: value.effect_ids,
            metadata: value.metadata.into_iter().collect(),
        }
    }
}

impl From<model::Success> for invocation::Success {
    fn from(value: model::Success) -> Self {
        Self {
            payload: value.payload,
            media_type: value.media_type,
            committed_state_version: value.committed_state_version,
            effect_ids: value.effect_ids,
            metadata: value.metadata.into_iter().collect(),
        }
    }
}

impl From<invocation::DeclaredError> for model::DeclaredError {
    fn from(value: invocation::DeclaredError) -> Self {
        Self {
            code: value.code,
            message: value.message,
            payload: value.payload,
            media_type: value.media_type,
            metadata: value.metadata.into_iter().collect(),
        }
    }
}

impl From<model::DeclaredError> for invocation::DeclaredError {
    fn from(value: model::DeclaredError) -> Self {
        Self {
            code: value.code,
            message: value.message,
            payload: value.payload,
            media_type: value.media_type,
            metadata: value.metadata.into_iter().collect(),
        }
    }
}

impl From<invocation::CancelRequest> for model::CancelRequest {
    fn from(value: invocation::CancelRequest) -> Self {
        Self {
            activation_id: value.activation_id,
            reason: value.reason,
        }
    }
}

impl From<model::CancelRequest> for invocation::CancelRequest {
    fn from(value: model::CancelRequest) -> Self {
        Self {
            activation_id: value.activation_id,
            reason: value.reason,
        }
    }
}

impl From<invocation::CancelResponse> for model::CancelResponse {
    fn from(value: invocation::CancelResponse) -> Self {
        Self {
            disposition: model::CancelDisposition(value.disposition),
            terminal_state: value.terminal_state,
        }
    }
}

impl From<model::CancelResponse> for invocation::CancelResponse {
    fn from(value: model::CancelResponse) -> Self {
        Self {
            disposition: value.disposition.0,
            terminal_state: value.terminal_state,
        }
    }
}

impl From<invocation::GetActivationRequest> for model::GetActivationRequest {
    fn from(value: invocation::GetActivationRequest) -> Self {
        Self {
            activation_id: value.activation_id,
        }
    }
}

impl From<model::GetActivationRequest> for invocation::GetActivationRequest {
    fn from(value: model::GetActivationRequest) -> Self {
        Self {
            activation_id: value.activation_id,
        }
    }
}

impl From<invocation::ActivationStatus> for model::ActivationStatus {
    fn from(value: invocation::ActivationStatus) -> Self {
        let (succeeded, declared_error, platform_failure) = match value.terminal_outcome {
            None => (None, None, None),
            Some(invocation::activation_status::TerminalOutcome::Succeeded(member)) => {
                (Some(member.into()), None, None)
            }
            Some(invocation::activation_status::TerminalOutcome::DeclaredError(member)) => {
                (None, Some(member.into()), None)
            }
            Some(invocation::activation_status::TerminalOutcome::PlatformFailure(member)) => {
                (None, None, Some(member.into()))
            }
        };
        Self {
            activation_id: value.activation_id,
            phase: value.phase,
            terminal_state: value.terminal_state,
            last_updated_unix_millis: value.last_updated_unix_millis,
            metadata: value.metadata.into_iter().collect(),
            final_consumption: value.final_consumption.map(Into::into),
            terminal_at_unix_millis: value.terminal_at_unix_millis,
            succeeded,
            declared_error,
            platform_failure,
        }
    }
}

impl TryFrom<model::ActivationStatus> for invocation::ActivationStatus {
    type Error = super::RpcFailure;
    fn try_from(value: model::ActivationStatus) -> Result<Self, Self::Error> {
        let terminal_outcome = match (
            value.succeeded,
            value.declared_error,
            value.platform_failure,
        ) {
            (None, None, None) => None,
            (Some(member), None, None) => Some(
                invocation::activation_status::TerminalOutcome::Succeeded(member.into()),
            ),
            (None, Some(member), None) => {
                Some(invocation::activation_status::TerminalOutcome::DeclaredError(member.into()))
            }
            (None, None, Some(member)) => {
                Some(invocation::activation_status::TerminalOutcome::PlatformFailure(member.into()))
            }
            _ => return Err(super::RpcFailure::local(super::FailureKind::InvalidRequest)),
        };
        Ok(Self {
            activation_id: value.activation_id,
            phase: value.phase,
            terminal_state: value.terminal_state,
            last_updated_unix_millis: value.last_updated_unix_millis,
            metadata: value.metadata.into_iter().collect(),
            final_consumption: value.final_consumption.map(Into::into),
            terminal_at_unix_millis: value.terminal_at_unix_millis,
            terminal_outcome,
        })
    }
}

impl From<invocation::ActivationSuccessSummary> for model::ActivationSuccessSummary {
    fn from(value: invocation::ActivationSuccessSummary) -> Self {
        Self {
            committed_state_version: value.committed_state_version,
            effect_ids: value.effect_ids,
            metadata: value.metadata.into_iter().collect(),
        }
    }
}

impl From<model::ActivationSuccessSummary> for invocation::ActivationSuccessSummary {
    fn from(value: model::ActivationSuccessSummary) -> Self {
        Self {
            committed_state_version: value.committed_state_version,
            effect_ids: value.effect_ids,
            metadata: value.metadata.into_iter().collect(),
        }
    }
}

impl From<control::Policy> for model::Policy {
    fn from(value: control::Policy) -> Self {
        Self {
            id: value.id,
            metadata: value.metadata.map(Into::into),
            document: value.document,
            generation: value.generation,
            language: value.language,
            record_kind: model::CapabilityPolicyRecordKind(value.record_kind),
            content_digest: value.content_digest,
            revoked: value.revoked,
        }
    }
}

impl From<model::Policy> for control::Policy {
    fn from(value: model::Policy) -> Self {
        Self {
            id: value.id,
            metadata: value.metadata.map(Into::into),
            document: value.document,
            generation: value.generation,
            language: value.language,
            record_kind: value.record_kind.0,
            content_digest: value.content_digest,
            revoked: value.revoked,
        }
    }
}

impl From<control::ApplyPolicyRequest> for model::ApplyPolicyRequest {
    fn from(value: control::ApplyPolicyRequest) -> Self {
        Self {
            policy: value.policy.map(Into::into),
            expected_generation: value.expected_generation,
            operation_id: value.operation_id,
        }
    }
}

impl From<model::ApplyPolicyRequest> for control::ApplyPolicyRequest {
    fn from(value: model::ApplyPolicyRequest) -> Self {
        Self {
            policy: value.policy.map(Into::into),
            expected_generation: value.expected_generation,
            operation_id: value.operation_id,
        }
    }
}

impl From<control::ApplyPolicyResponse> for model::ApplyPolicyResponse {
    fn from(value: control::ApplyPolicyResponse) -> Self {
        Self {
            policy: value.policy.map(Into::into),
            receipt: value.receipt.map(Into::into),
        }
    }
}

impl From<model::ApplyPolicyResponse> for control::ApplyPolicyResponse {
    fn from(value: model::ApplyPolicyResponse) -> Self {
        Self {
            policy: value.policy.map(Into::into),
            receipt: value.receipt.map(Into::into),
        }
    }
}

impl From<control::GetPolicyRequest> for model::GetPolicyRequest {
    fn from(value: control::GetPolicyRequest) -> Self {
        Self {
            id: value.id,
            record_kind: model::CapabilityPolicyRecordKind(value.record_kind),
        }
    }
}

impl From<model::GetPolicyRequest> for control::GetPolicyRequest {
    fn from(value: model::GetPolicyRequest) -> Self {
        Self {
            id: value.id,
            record_kind: value.record_kind.0,
        }
    }
}

impl From<control::GetPolicyResponse> for model::GetPolicyResponse {
    fn from(value: control::GetPolicyResponse) -> Self {
        Self {
            policy: value.policy.map(Into::into),
        }
    }
}

impl From<model::GetPolicyResponse> for control::GetPolicyResponse {
    fn from(value: model::GetPolicyResponse) -> Self {
        Self {
            policy: value.policy.map(Into::into),
        }
    }
}

impl From<control::CapabilityPolicyOperation> for model::CapabilityPolicyOperation {
    fn from(value: control::CapabilityPolicyOperation) -> Self {
        Self {
            operation_id: value.operation_id,
            tenant: value.tenant,
            id: value.id,
            record_kind: model::CapabilityPolicyRecordKind(value.record_kind),
            generation: value.generation,
            content_digest: value.content_digest,
            revoked: value.revoked,
        }
    }
}

impl From<model::CapabilityPolicyOperation> for control::CapabilityPolicyOperation {
    fn from(value: model::CapabilityPolicyOperation) -> Self {
        Self {
            operation_id: value.operation_id,
            tenant: value.tenant,
            id: value.id,
            record_kind: value.record_kind.0,
            generation: value.generation,
            content_digest: value.content_digest,
            revoked: value.revoked,
        }
    }
}

impl From<control::GetPolicyOperationRequest> for model::GetPolicyOperationRequest {
    fn from(value: control::GetPolicyOperationRequest) -> Self {
        Self {
            operation_id: value.operation_id,
        }
    }
}

impl From<model::GetPolicyOperationRequest> for control::GetPolicyOperationRequest {
    fn from(value: model::GetPolicyOperationRequest) -> Self {
        Self {
            operation_id: value.operation_id,
        }
    }
}

impl From<control::GetPolicyOperationResponse> for model::GetPolicyOperationResponse {
    fn from(value: control::GetPolicyOperationResponse) -> Self {
        Self {
            receipt: value.receipt.map(Into::into),
        }
    }
}

impl From<model::GetPolicyOperationResponse> for control::GetPolicyOperationResponse {
    fn from(value: model::GetPolicyOperationResponse) -> Self {
        Self {
            receipt: value.receipt.map(Into::into),
        }
    }
}

impl From<control::ListPoliciesRequest> for model::ListPoliciesRequest {
    fn from(value: control::ListPoliciesRequest) -> Self {
        Self {
            record_kind: model::CapabilityPolicyRecordKind(value.record_kind),
            page: value.page.map(Into::into),
        }
    }
}

impl From<model::ListPoliciesRequest> for control::ListPoliciesRequest {
    fn from(value: model::ListPoliciesRequest) -> Self {
        Self {
            record_kind: value.record_kind.0,
            page: value.page.map(Into::into),
        }
    }
}

impl From<control::ListPoliciesResponse> for model::ListPoliciesResponse {
    fn from(value: control::ListPoliciesResponse) -> Self {
        Self {
            policies: value.policies.into_iter().map(Into::into).collect(),
            catalog_generation: value.catalog_generation,
            page: value.page.map(Into::into),
        }
    }
}

impl From<model::ListPoliciesResponse> for control::ListPoliciesResponse {
    fn from(value: model::ListPoliciesResponse) -> Self {
        Self {
            policies: value.policies.into_iter().map(Into::into).collect(),
            catalog_generation: value.catalog_generation,
            page: value.page.map(Into::into),
        }
    }
}

impl From<control::CapabilityDescriptor> for model::CapabilityDescriptor {
    fn from(value: control::CapabilityDescriptor) -> Self {
        Self {
            id: value.id,
            contract: value.contract,
            provider: value.provider,
            operations: value.operations,
            attributes: value.attributes.into_iter().collect(),
            inspection: value.inspection.map(Into::into),
        }
    }
}

impl From<model::CapabilityDescriptor> for control::CapabilityDescriptor {
    fn from(value: model::CapabilityDescriptor) -> Self {
        Self {
            id: value.id,
            contract: value.contract,
            provider: value.provider,
            operations: value.operations,
            attributes: value.attributes.into_iter().collect(),
            inspection: value.inspection.map(Into::into),
        }
    }
}

impl From<control::ListCapabilitiesRequest> for model::ListCapabilitiesRequest {
    fn from(value: control::ListCapabilitiesRequest) -> Self {
        Self {
            contract_prefix: value.contract_prefix,
            provider: value.provider,
            page: value.page.map(Into::into),
            deployment_id: value.deployment_id,
            include_node_usage: value.include_node_usage,
        }
    }
}

impl From<model::ListCapabilitiesRequest> for control::ListCapabilitiesRequest {
    fn from(value: model::ListCapabilitiesRequest) -> Self {
        Self {
            contract_prefix: value.contract_prefix,
            provider: value.provider,
            page: value.page.map(Into::into),
            deployment_id: value.deployment_id,
            include_node_usage: value.include_node_usage,
        }
    }
}

impl From<control::ListCapabilitiesResponse> for model::ListCapabilitiesResponse {
    fn from(value: control::ListCapabilitiesResponse) -> Self {
        Self {
            capabilities: value.capabilities.into_iter().map(Into::into).collect(),
            page: value.page.map(Into::into),
            revision: value.revision.map(Into::into),
            tenant_usage: value.tenant_usage.map(Into::into),
            node_usage: value.node_usage.map(Into::into),
            state: value.state,
        }
    }
}

impl From<model::ListCapabilitiesResponse> for control::ListCapabilitiesResponse {
    fn from(value: model::ListCapabilitiesResponse) -> Self {
        Self {
            capabilities: value.capabilities.into_iter().map(Into::into).collect(),
            page: value.page.map(Into::into),
            revision: value.revision.map(Into::into),
            tenant_usage: value.tenant_usage.map(Into::into),
            node_usage: value.node_usage.map(Into::into),
            state: value.state,
        }
    }
}

impl From<control::CapabilityInspectionRevision> for model::CapabilityInspectionRevision {
    fn from(value: control::CapabilityInspectionRevision) -> Self {
        Self {
            deployment_id: value.deployment_id,
            revision_id: value.revision_id,
            component_digest: value.component_digest,
            publication_id: value.publication_id,
            route_generation: value.route_generation,
            catalog_transaction: value.catalog_transaction,
        }
    }
}

impl From<model::CapabilityInspectionRevision> for control::CapabilityInspectionRevision {
    fn from(value: model::CapabilityInspectionRevision) -> Self {
        Self {
            deployment_id: value.deployment_id,
            revision_id: value.revision_id,
            component_digest: value.component_digest,
            publication_id: value.publication_id,
            route_generation: value.route_generation,
            catalog_transaction: value.catalog_transaction,
        }
    }
}

impl From<control::CapabilityInspectionPolicy> for model::CapabilityInspectionPolicy {
    fn from(value: control::CapabilityInspectionPolicy) -> Self {
        Self {
            id: value.id,
            revision: value.revision,
            digest: value.digest,
        }
    }
}

impl From<model::CapabilityInspectionPolicy> for control::CapabilityInspectionPolicy {
    fn from(value: model::CapabilityInspectionPolicy) -> Self {
        Self {
            id: value.id,
            revision: value.revision,
            digest: value.digest,
        }
    }
}

impl From<control::CapabilityBindingInspection> for model::CapabilityBindingInspection {
    fn from(value: control::CapabilityBindingInspection) -> Self {
        Self {
            definition_digest: value.definition_digest,
            provider_binding: value.provider_binding.map(Into::into),
            policies: value.policies.into_iter().map(Into::into).collect(),
            provider_profile: value.provider_profile,
            provider_configuration_digest: value.provider_configuration_digest,
            provider_configuration_epoch: value.provider_configuration_epoch,
            state: value.state,
        }
    }
}

impl From<model::CapabilityBindingInspection> for control::CapabilityBindingInspection {
    fn from(value: model::CapabilityBindingInspection) -> Self {
        Self {
            definition_digest: value.definition_digest,
            provider_binding: value.provider_binding.map(Into::into),
            policies: value.policies.into_iter().map(Into::into).collect(),
            provider_profile: value.provider_profile,
            provider_configuration_digest: value.provider_configuration_digest,
            provider_configuration_epoch: value.provider_configuration_epoch,
            state: value.state,
        }
    }
}

impl From<control::CapabilityInspectionCeiling> for model::CapabilityInspectionCeiling {
    fn from(value: control::CapabilityInspectionCeiling) -> Self {
        Self {
            operations: value.operations,
            input_bytes: value.input_bytes,
            output_bytes: value.output_bytes,
            wall_time_millis: value.wall_time_millis,
        }
    }
}

impl From<model::CapabilityInspectionCeiling> for control::CapabilityInspectionCeiling {
    fn from(value: model::CapabilityInspectionCeiling) -> Self {
        Self {
            operations: value.operations,
            input_bytes: value.input_bytes,
            output_bytes: value.output_bytes,
            wall_time_millis: value.wall_time_millis,
        }
    }
}

impl From<control::CapabilityResourceUsage> for model::CapabilityResourceUsage {
    fn from(value: control::CapabilityResourceUsage) -> Self {
        Self {
            scope: value.scope,
            counters: value.counters.into_iter().collect(),
            unavailable: value.unavailable,
        }
    }
}

impl From<model::CapabilityResourceUsage> for control::CapabilityResourceUsage {
    fn from(value: model::CapabilityResourceUsage) -> Self {
        Self {
            scope: value.scope,
            counters: value.counters.into_iter().collect(),
            unavailable: value.unavailable,
        }
    }
}

impl From<control::PublicationRef> for model::PublicationRef {
    fn from(value: control::PublicationRef) -> Self {
        Self {
            id: value.id,
            tenant: value.tenant,
        }
    }
}

impl From<model::PublicationRef> for control::PublicationRef {
    fn from(value: model::PublicationRef) -> Self {
        Self {
            id: value.id,
            tenant: value.tenant,
        }
    }
}

impl From<invocation::ResourceBudget> for model::ResourceBudget {
    fn from(value: invocation::ResourceBudget) -> Self {
        Self {
            cpu_fuel: value.cpu_fuel,
            memory_bytes: value.memory_bytes,
            child_calls: value.child_calls,
            outbound_requests: value.outbound_requests,
            state_read_bytes: value.state_read_bytes,
            state_write_bytes: value.state_write_bytes,
            blob_read_bytes: value.blob_read_bytes,
            blob_write_bytes: value.blob_write_bytes,
            log_bytes: value.log_bytes,
            effect_count: value.effect_count,
            wall_time_limit_millis: value.wall_time_limit_millis,
        }
    }
}

impl From<model::ResourceBudget> for invocation::ResourceBudget {
    fn from(value: model::ResourceBudget) -> Self {
        Self {
            cpu_fuel: value.cpu_fuel,
            memory_bytes: value.memory_bytes,
            child_calls: value.child_calls,
            outbound_requests: value.outbound_requests,
            state_read_bytes: value.state_read_bytes,
            state_write_bytes: value.state_write_bytes,
            blob_read_bytes: value.blob_read_bytes,
            blob_write_bytes: value.blob_write_bytes,
            log_bytes: value.log_bytes,
            effect_count: value.effect_count,
            wall_time_limit_millis: value.wall_time_limit_millis,
        }
    }
}

impl From<invocation::ErrorDetail> for model::ErrorDetail {
    fn from(value: invocation::ErrorDetail) -> Self {
        Self {
            kind: value.kind,
            fields: value.fields.into_iter().collect(),
        }
    }
}

impl From<model::ErrorDetail> for invocation::ErrorDetail {
    fn from(value: model::ErrorDetail) -> Self {
        Self {
            kind: value.kind,
            fields: value.fields.into_iter().collect(),
        }
    }
}

impl From<invocation::PlatformError> for model::PlatformError {
    fn from(value: invocation::PlatformError) -> Self {
        Self {
            code: value.code,
            message: value.message,
            retryable: value.retryable,
            detail_items: value.detail_items.into_iter().map(Into::into).collect(),
        }
    }
}

impl From<model::PlatformError> for invocation::PlatformError {
    fn from(value: model::PlatformError) -> Self {
        Self {
            code: value.code,
            message: value.message,
            retryable: value.retryable,
            detail_items: value.detail_items.into_iter().map(Into::into).collect(),
        }
    }
}
