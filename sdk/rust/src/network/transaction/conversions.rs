// Generated from exact, fully qualified Protobuf transaction model owners.
use crate::transaction as model;
use latent_rpc::{control::v1 as c, phase4::ValidationError, transaction::v1 as t};

impl From<t::AbortFence> for model::AbortFence {
    fn from(value: t::AbortFence) -> Self {
        Self {
            command_id: value.command_id,
            attempt_id: value.attempt_id,
            transaction_id: value.transaction_id,
            owner_fence: value.owner_fence,
        }
    }
}

impl TryFrom<model::AbortFence> for t::AbortFence {
    type Error = ValidationError;
    fn try_from(value: model::AbortFence) -> Result<Self, Self::Error> {
        Ok(Self {
            command_id: value.command_id,
            attempt_id: value.attempt_id,
            transaction_id: value.transaction_id,
            owner_fence: value.owner_fence,
        })
    }
}

impl From<t::TransactionProfile> for model::TransactionProfile {
    fn from(value: t::TransactionProfile) -> Self {
        Self {
            profile: value.profile,
            host_abi_digest: value.host_abi_digest,
            preparation_profile_digest: value.preparation_profile_digest,
        }
    }
}

impl TryFrom<model::TransactionProfile> for t::TransactionProfile {
    type Error = ValidationError;
    fn try_from(value: model::TransactionProfile) -> Result<Self, Self::Error> {
        Ok(Self {
            profile: value.profile,
            host_abi_digest: value.host_abi_digest,
            preparation_profile_digest: value.preparation_profile_digest,
        })
    }
}

impl From<t::NamespaceSelector> for model::NamespaceSelector {
    fn from(value: t::NamespaceSelector) -> Self {
        Self {
            tenant: value.tenant,
            namespace: value.namespace,
            incarnation: value.incarnation,
        }
    }
}

impl TryFrom<model::NamespaceSelector> for t::NamespaceSelector {
    type Error = ValidationError;
    fn try_from(value: model::NamespaceSelector) -> Result<Self, Self::Error> {
        Ok(Self {
            tenant: value.tenant,
            namespace: value.namespace,
            incarnation: value.incarnation,
        })
    }
}

impl From<t::CommandSelector> for model::CommandSelector {
    fn from(value: t::CommandSelector) -> Self {
        Self {
            namespace: value.namespace.map(Into::into),
            operation: value.operation,
            entity: value.entity,
            client_key: value.client_key,
            shared_recovery_scope: value.shared_recovery_scope,
        }
    }
}

impl TryFrom<model::CommandSelector> for t::CommandSelector {
    type Error = ValidationError;
    fn try_from(value: model::CommandSelector) -> Result<Self, Self::Error> {
        Ok(Self {
            namespace: value.namespace.map(TryInto::try_into).transpose()?,
            operation: value.operation,
            entity: value.entity,
            client_key: value.client_key,
            shared_recovery_scope: value.shared_recovery_scope,
        })
    }
}

impl From<t::LookupCommandRequest> for model::LookupCommandRequest {
    fn from(value: t::LookupCommandRequest) -> Self {
        Self {
            profile: value.profile.map(Into::into),
            command: value.command.map(Into::into),
            attempt_id: value.attempt_id,
            authorization_publication: value.authorization_publication.map(Into::into),
        }
    }
}

impl TryFrom<model::LookupCommandRequest> for t::LookupCommandRequest {
    type Error = ValidationError;
    fn try_from(value: model::LookupCommandRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            profile: value.profile.map(TryInto::try_into).transpose()?,
            command: value.command.map(TryInto::try_into).transpose()?,
            attempt_id: value.attempt_id,
            authorization_publication: value.authorization_publication.map(Into::into),
        })
    }
}

impl From<t::CancelCommandRequest> for model::CancelCommandRequest {
    fn from(value: t::CancelCommandRequest) -> Self {
        Self {
            command: value.command.map(Into::into),
            reason: value.reason,
        }
    }
}

impl TryFrom<model::CancelCommandRequest> for t::CancelCommandRequest {
    type Error = ValidationError;
    fn try_from(value: model::CancelCommandRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            command: value.command.map(TryInto::try_into).transpose()?,
            reason: value.reason,
        })
    }
}

impl From<t::CommandKey> for model::CommandKey {
    fn from(value: t::CommandKey) -> Self {
        Self {
            namespace: value.namespace.map(Into::into),
            recovery_scope: value.recovery_scope,
            operation: value.operation,
            entity: value.entity,
            client_key: value.client_key,
        }
    }
}

impl TryFrom<model::CommandKey> for t::CommandKey {
    type Error = ValidationError;
    fn try_from(value: model::CommandKey) -> Result<Self, Self::Error> {
        Ok(Self {
            namespace: value.namespace.map(TryInto::try_into).transpose()?,
            recovery_scope: value.recovery_scope,
            operation: value.operation,
            entity: value.entity,
            client_key: value.client_key,
        })
    }
}

impl From<t::SourceIdentity> for model::SourceIdentity {
    fn from(value: t::SourceIdentity) -> Self {
        Self {
            publication_id: value.publication_id,
            revision_id: value.revision_id,
            release_digest: value.release_digest,
            route_generation: value.route_generation,
            contract_digest: value.contract_digest,
            state_schema: value.state_schema,
            input_format: value.input_format,
            result_format: value.result_format,
            component_digest: value.component_digest,
        }
    }
}

impl TryFrom<model::SourceIdentity> for t::SourceIdentity {
    type Error = ValidationError;
    fn try_from(value: model::SourceIdentity) -> Result<Self, Self::Error> {
        Ok(Self {
            publication_id: value.publication_id,
            revision_id: value.revision_id,
            release_digest: value.release_digest,
            route_generation: value.route_generation,
            contract_digest: value.contract_digest,
            state_schema: value.state_schema,
            input_format: value.input_format,
            result_format: value.result_format,
            component_digest: value.component_digest,
        })
    }
}

impl From<t::CommitReceipt> for model::CommitReceipt {
    fn from(value: t::CommitReceipt) -> Self {
        Self {
            command_id: value.command_id,
            attempt_id: value.attempt_id,
            transaction_id: value.transaction_id,
            committed_version: value.committed_version,
            committed_at_unix_millis: value.committed_at_unix_millis,
            effect_ids: value.effect_ids,
            receipt_id: value.receipt_id,
            source: value.source.map(Into::into),
        }
    }
}

impl TryFrom<model::CommitReceipt> for t::CommitReceipt {
    type Error = ValidationError;
    fn try_from(value: model::CommitReceipt) -> Result<Self, Self::Error> {
        Ok(Self {
            command_id: value.command_id,
            attempt_id: value.attempt_id,
            transaction_id: value.transaction_id,
            committed_version: value.committed_version,
            committed_at_unix_millis: value.committed_at_unix_millis,
            effect_ids: value.effect_ids,
            receipt_id: value.receipt_id,
            source: value.source.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<t::LinkedRetention> for model::LinkedRetention {
    fn from(value: t::LinkedRetention) -> Self {
        Self {
            record_format: value.record_format,
            record_version: value.record_version,
            payload_expires_at_unix_millis: value.payload_expires_at_unix_millis,
            identity_expires_at_unix_millis: value.identity_expires_at_unix_millis,
            remaining_recovery_millis: value.remaining_recovery_millis,
            required_record_ids: value.required_record_ids,
            payload_available: value.payload_available,
        }
    }
}

impl TryFrom<model::LinkedRetention> for t::LinkedRetention {
    type Error = ValidationError;
    fn try_from(value: model::LinkedRetention) -> Result<Self, Self::Error> {
        Ok(Self {
            record_format: value.record_format,
            record_version: value.record_version,
            payload_expires_at_unix_millis: value.payload_expires_at_unix_millis,
            identity_expires_at_unix_millis: value.identity_expires_at_unix_millis,
            remaining_recovery_millis: value.remaining_recovery_millis,
            required_record_ids: value.required_record_ids,
            payload_available: value.payload_available,
        })
    }
}

impl From<t::CommandInspection> for model::CommandInspection {
    fn from(value: t::CommandInspection) -> Self {
        let (success, business_rejection, technical_failure) = match value.retained_result {
            None => (None, None, None),
            Some(t::command_inspection::RetainedResult::Success(member)) => {
                (Some(member.into()), None, None)
            }
            Some(t::command_inspection::RetainedResult::BusinessRejection(member)) => {
                (None, Some(member.into()), None)
            }
            Some(t::command_inspection::RetainedResult::TechnicalFailure(member)) => {
                (None, None, Some(member.into()))
            }
        };
        Self {
            key: value.key.map(Into::into),
            command_id: value.command_id,
            attempt_id: value.attempt_id,
            fingerprint_sha256: value.fingerprint_sha256,
            outcome: model::CommandOutcome(value.outcome),
            metadata_durable: value.metadata_durable,
            application_state_committed: value.application_state_committed,
            source: value.source.map(Into::into),
            success,
            business_rejection,
            technical_failure,
            commit: value.commit.map(Into::into),
            proven_abort: value.proven_abort.map(Into::into),
            retention: value.retention.map(Into::into),
            cleanup_failure: value.cleanup_failure.map(Into::into),
        }
    }
}

impl TryFrom<model::CommandInspection> for t::CommandInspection {
    type Error = ValidationError;
    fn try_from(value: model::CommandInspection) -> Result<Self, Self::Error> {
        let retained_result = match (
            value.success,
            value.business_rejection,
            value.technical_failure,
        ) {
            (None, None, None) => None,
            (Some(member), None, None) => Some(t::command_inspection::RetainedResult::Success(
                member.into(),
            )),
            (None, Some(member), None) => Some(
                t::command_inspection::RetainedResult::BusinessRejection(member.into()),
            ),
            (None, None, Some(member)) => Some(
                t::command_inspection::RetainedResult::TechnicalFailure(member.into()),
            ),
            _ => return Err(ValidationError::Shape),
        };
        Ok(Self {
            key: value.key.map(TryInto::try_into).transpose()?,
            command_id: value.command_id,
            attempt_id: value.attempt_id,
            fingerprint_sha256: value.fingerprint_sha256,
            outcome: value.outcome.0,
            metadata_durable: value.metadata_durable,
            application_state_committed: value.application_state_committed,
            source: value.source.map(TryInto::try_into).transpose()?,
            commit: value.commit.map(TryInto::try_into).transpose()?,
            proven_abort: value.proven_abort.map(TryInto::try_into).transpose()?,
            retention: value.retention.map(TryInto::try_into).transpose()?,
            cleanup_failure: value.cleanup_failure.map(Into::into),
            retained_result,
        })
    }
}

impl From<t::CancelCommandResponse> for model::CancelCommandResponse {
    fn from(value: t::CancelCommandResponse) -> Self {
        Self {
            disposition: model::CommandCancelDisposition(value.disposition),
            command: value.command.map(Into::into),
        }
    }
}

impl TryFrom<model::CancelCommandResponse> for t::CancelCommandResponse {
    type Error = ValidationError;
    fn try_from(value: model::CancelCommandResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            disposition: value.disposition.0,
            command: value.command.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<t::EffectReceipt> for model::EffectReceipt {
    fn from(value: t::EffectReceipt) -> Self {
        Self {
            effect_id: value.effect_id,
            command_id: value.command_id,
            command_attempt_id: value.command_attempt_id,
            dispatch_attempt: value.dispatch_attempt,
            disposition: model::EffectDisposition(value.disposition),
            provider_receipt: value.provider_receipt,
            failure_code: value.failure_code,
            occurred_at_unix_millis: value.occurred_at_unix_millis,
            retention: value.retention.map(Into::into),
            management_operation_receipt_id: value.management_operation_receipt_id,
            provider_profile: value.provider_profile,
        }
    }
}

impl TryFrom<model::EffectReceipt> for t::EffectReceipt {
    type Error = ValidationError;
    fn try_from(value: model::EffectReceipt) -> Result<Self, Self::Error> {
        Ok(Self {
            effect_id: value.effect_id,
            command_id: value.command_id,
            command_attempt_id: value.command_attempt_id,
            dispatch_attempt: value.dispatch_attempt,
            disposition: value.disposition.0,
            provider_receipt: value.provider_receipt,
            failure_code: value.failure_code,
            occurred_at_unix_millis: value.occurred_at_unix_millis,
            retention: value.retention.map(TryInto::try_into).transpose()?,
            management_operation_receipt_id: value.management_operation_receipt_id,
            provider_profile: value.provider_profile,
        })
    }
}

impl From<c::EntityInspection> for model::EntityInspection {
    fn from(value: c::EntityInspection) -> Self {
        Self {
            entity: value.entity,
            version: value.version,
        }
    }
}

impl TryFrom<model::EntityInspection> for c::EntityInspection {
    type Error = ValidationError;
    fn try_from(value: model::EntityInspection) -> Result<Self, Self::Error> {
        Ok(Self {
            entity: value.entity,
            version: value.version,
        })
    }
}

impl From<t::ExpectedVersion> for model::ExpectedVersion {
    fn from(value: t::ExpectedVersion) -> Self {
        let (absent, version) = match value.expectation {
            None => (None, None),
            Some(t::expected_version::Expectation::Absent(member)) => (Some(member), None),
            Some(t::expected_version::Expectation::Version(member)) => (None, Some(member)),
        };
        Self {
            key: value.key,
            absent,
            version,
        }
    }
}

impl TryFrom<model::ExpectedVersion> for t::ExpectedVersion {
    type Error = ValidationError;
    fn try_from(value: model::ExpectedVersion) -> Result<Self, Self::Error> {
        let expectation = match (value.absent, value.version) {
            (None, None) => None,
            (Some(member), None) => Some(t::expected_version::Expectation::Absent(member)),
            (None, Some(member)) => Some(t::expected_version::Expectation::Version(member)),
            _ => return Err(ValidationError::Shape),
        };
        Ok(Self {
            key: value.key,
            expectation,
        })
    }
}

impl From<t::GetEffectRequest> for model::GetEffectRequest {
    fn from(value: t::GetEffectRequest) -> Self {
        Self {
            profile: value.profile.map(Into::into),
            command: value.command.map(Into::into),
            effect_id: value.effect_id,
            authorization_publication: value.authorization_publication.map(Into::into),
        }
    }
}

impl TryFrom<model::GetEffectRequest> for t::GetEffectRequest {
    type Error = ValidationError;
    fn try_from(value: model::GetEffectRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            profile: value.profile.map(TryInto::try_into).transpose()?,
            command: value.command.map(TryInto::try_into).transpose()?,
            effect_id: value.effect_id,
            authorization_publication: value.authorization_publication.map(Into::into),
        })
    }
}

impl From<t::GetEffectResponse> for model::GetEffectResponse {
    fn from(value: t::GetEffectResponse) -> Self {
        Self {
            effect: value.effect.map(Into::into),
        }
    }
}

impl TryFrom<model::GetEffectResponse> for t::GetEffectResponse {
    type Error = ValidationError;
    fn try_from(value: model::GetEffectResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            effect: value.effect.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<c::InspectNamespaceRequest> for model::InspectNamespaceRequest {
    fn from(value: c::InspectNamespaceRequest) -> Self {
        Self {
            profile: value.profile.map(Into::into),
            namespace: value.namespace.map(Into::into),
            authorization_publication: value.authorization_publication.map(Into::into),
        }
    }
}

impl TryFrom<model::InspectNamespaceRequest> for c::InspectNamespaceRequest {
    type Error = ValidationError;
    fn try_from(value: model::InspectNamespaceRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            profile: value.profile.map(TryInto::try_into).transpose()?,
            namespace: value.namespace.map(TryInto::try_into).transpose()?,
            authorization_publication: value.authorization_publication.map(Into::into),
        })
    }
}

impl From<c::GetStateOperationReceiptRequest> for model::GetStateOperationReceiptRequest {
    fn from(value: c::GetStateOperationReceiptRequest) -> Self {
        Self {
            namespace: value.namespace.map(Into::into),
            operation_id: value.operation_id,
        }
    }
}

impl TryFrom<model::GetStateOperationReceiptRequest> for c::GetStateOperationReceiptRequest {
    type Error = ValidationError;
    fn try_from(value: model::GetStateOperationReceiptRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            namespace: value.namespace.map(TryInto::try_into).transpose()?,
            operation_id: value.operation_id,
        })
    }
}

impl From<c::StateOperationReceipt> for model::StateOperationReceipt {
    fn from(value: c::StateOperationReceipt) -> Self {
        Self {
            operation_id: value.operation_id,
            receipt_id: value.receipt_id,
            mutation: model::StateMutationKind(value.mutation),
            namespace: value.namespace.map(Into::into),
            authenticated_operator: value.authenticated_operator,
            before_version: value.before_version,
            after_version: value.after_version,
            completed_at_unix_millis: value.completed_at_unix_millis,
            record_id: value.record_id,
            policy_digest: value.policy_digest,
            disposition: model::StateOperationDisposition(value.disposition),
        }
    }
}

impl TryFrom<model::StateOperationReceipt> for c::StateOperationReceipt {
    type Error = ValidationError;
    fn try_from(value: model::StateOperationReceipt) -> Result<Self, Self::Error> {
        Ok(Self {
            operation_id: value.operation_id,
            receipt_id: value.receipt_id,
            mutation: value.mutation.0,
            namespace: value.namespace.map(TryInto::try_into).transpose()?,
            authenticated_operator: value.authenticated_operator,
            before_version: value.before_version,
            after_version: value.after_version,
            completed_at_unix_millis: value.completed_at_unix_millis,
            record_id: value.record_id,
            policy_digest: value.policy_digest,
            disposition: value.disposition.0,
        })
    }
}

impl From<c::NamespaceOperationReceipt> for model::NamespaceOperationReceipt {
    fn from(value: c::NamespaceOperationReceipt) -> Self {
        Self {
            operation_id: value.operation_id,
            receipt_id: value.receipt_id,
            mutation: model::NamespaceMutationKind(value.mutation),
            namespace: value.namespace.map(Into::into),
            authenticated_operator: value.authenticated_operator,
            before_generation: value.before_generation,
            after_generation: value.after_generation,
            status: model::NamespaceStatus(value.status),
            state_schema: value.state_schema,
            disposition: model::StateOperationDisposition(value.disposition),
        }
    }
}

impl TryFrom<model::NamespaceOperationReceipt> for c::NamespaceOperationReceipt {
    type Error = ValidationError;
    fn try_from(value: model::NamespaceOperationReceipt) -> Result<Self, Self::Error> {
        Ok(Self {
            operation_id: value.operation_id,
            receipt_id: value.receipt_id,
            mutation: value.mutation.0,
            namespace: value.namespace.map(TryInto::try_into).transpose()?,
            authenticated_operator: value.authenticated_operator,
            before_generation: value.before_generation,
            after_generation: value.after_generation,
            status: value.status.0,
            state_schema: value.state_schema,
            disposition: value.disposition.0,
        })
    }
}

impl From<c::GetStateOperationReceiptResponse> for model::GetStateOperationReceiptResponse {
    fn from(value: c::GetStateOperationReceiptResponse) -> Self {
        Self {
            receipt: value.receipt.map(Into::into),
            namespace_receipt: value.namespace_receipt.map(Into::into),
        }
    }
}

impl TryFrom<model::GetStateOperationReceiptResponse> for c::GetStateOperationReceiptResponse {
    type Error = ValidationError;
    fn try_from(value: model::GetStateOperationReceiptResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            receipt: value.receipt.map(TryInto::try_into).transpose()?,
            namespace_receipt: value.namespace_receipt.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<t::ViewIdentity> for model::ViewIdentity {
    fn from(value: t::ViewIdentity) -> Self {
        Self {
            namespace: value.namespace.map(Into::into),
            version: value.version,
            state_schema: value.state_schema,
        }
    }
}

impl TryFrom<model::ViewIdentity> for t::ViewIdentity {
    type Error = ValidationError;
    fn try_from(value: model::ViewIdentity) -> Result<Self, Self::Error> {
        Ok(Self {
            namespace: value.namespace.map(TryInto::try_into).transpose()?,
            version: value.version,
            state_schema: value.state_schema,
        })
    }
}

impl From<c::NamespaceQuota> for model::NamespaceQuota {
    fn from(value: c::NamespaceQuota) -> Self {
        Self {
            state_keys: value.state_keys,
            state_bytes: value.state_bytes,
            result_rows: value.result_rows,
            result_bytes: value.result_bytes,
            effect_rows: value.effect_rows,
            effect_bytes: value.effect_bytes,
            payload_bytes: value.payload_bytes,
            recovery_bytes: value.recovery_bytes,
        }
    }
}

impl TryFrom<model::NamespaceQuota> for c::NamespaceQuota {
    type Error = ValidationError;
    fn try_from(value: model::NamespaceQuota) -> Result<Self, Self::Error> {
        Ok(Self {
            state_keys: value.state_keys,
            state_bytes: value.state_bytes,
            result_rows: value.result_rows,
            result_bytes: value.result_bytes,
            effect_rows: value.effect_rows,
            effect_bytes: value.effect_bytes,
            payload_bytes: value.payload_bytes,
            recovery_bytes: value.recovery_bytes,
        })
    }
}

impl From<c::NamespaceInspection> for model::NamespaceInspection {
    fn from(value: c::NamespaceInspection) -> Self {
        Self {
            view: value.view.map(Into::into),
            encoded_state_bytes: value.encoded_state_bytes,
            command_count: value.command_count,
            pending_effect_count: value.pending_effect_count,
            retained_formats: value.retained_formats.into_iter().map(Into::into).collect(),
            engine_profile: value.engine_profile,
            engine_profile_digest: value.engine_profile_digest,
            status: model::NamespaceStatus(value.status),
            quota: value.quota.map(Into::into),
            generation: value.generation,
        }
    }
}

impl TryFrom<model::NamespaceInspection> for c::NamespaceInspection {
    type Error = ValidationError;
    fn try_from(value: model::NamespaceInspection) -> Result<Self, Self::Error> {
        Ok(Self {
            view: value.view.map(TryInto::try_into).transpose()?,
            encoded_state_bytes: value.encoded_state_bytes,
            command_count: value.command_count,
            pending_effect_count: value.pending_effect_count,
            retained_formats: value
                .retained_formats
                .into_iter()
                .map(TryInto::try_into)
                .collect::<Result<_, _>>()?,
            engine_profile: value.engine_profile,
            engine_profile_digest: value.engine_profile_digest,
            status: value.status.0,
            quota: value.quota.map(TryInto::try_into).transpose()?,
            generation: value.generation,
        })
    }
}

impl From<c::InspectNamespaceResponse> for model::InspectNamespaceResponse {
    fn from(value: c::InspectNamespaceResponse) -> Self {
        Self {
            namespace: value.namespace.map(Into::into),
        }
    }
}

impl TryFrom<model::InspectNamespaceResponse> for c::InspectNamespaceResponse {
    type Error = ValidationError;
    fn try_from(value: model::InspectNamespaceResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            namespace: value.namespace.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<t::RetryAttempt> for model::RetryAttempt {
    fn from(value: t::RetryAttempt) -> Self {
        Self {
            request_id: value.request_id,
            expected_abort: value.expected_abort.map(Into::into),
        }
    }
}

impl TryFrom<model::RetryAttempt> for t::RetryAttempt {
    type Error = ValidationError;
    fn try_from(value: model::RetryAttempt) -> Result<Self, Self::Error> {
        Ok(Self {
            request_id: value.request_id,
            expected_abort: value.expected_abort.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<t::InvokeCommandRequest> for model::InvokeCommandRequest {
    fn from(value: t::InvokeCommandRequest) -> Self {
        Self {
            profile: value.profile.map(Into::into),
            invocation: value.invocation.map(Into::into),
            command: value.command.map(Into::into),
            input_format: value.input_format,
            expected_versions: value
                .expected_versions
                .into_iter()
                .map(Into::into)
                .collect(),
            retry_attempt: value.retry_attempt.map(Into::into),
        }
    }
}

impl TryFrom<model::InvokeCommandRequest> for t::InvokeCommandRequest {
    type Error = ValidationError;
    fn try_from(value: model::InvokeCommandRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            profile: value.profile.map(TryInto::try_into).transpose()?,
            invocation: value.invocation.map(Into::into),
            command: value.command.map(TryInto::try_into).transpose()?,
            input_format: value.input_format,
            expected_versions: value
                .expected_versions
                .into_iter()
                .map(TryInto::try_into)
                .collect::<Result<_, _>>()?,
            retry_attempt: value.retry_attempt.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<t::InvokeCommandResponse> for model::InvokeCommandResponse {
    fn from(value: t::InvokeCommandResponse) -> Self {
        Self {
            invocation: value.invocation.map(Into::into),
            command: value.command.map(Into::into),
            replayed: value.replayed,
        }
    }
}

impl TryFrom<model::InvokeCommandResponse> for t::InvokeCommandResponse {
    type Error = ValidationError;
    fn try_from(value: model::InvokeCommandResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            invocation: value
                .invocation
                .map(TryInto::try_into)
                .transpose()
                .map_err(|_| ValidationError::Shape)?,
            command: value.command.map(TryInto::try_into).transpose()?,
            replayed: value.replayed,
        })
    }
}

impl From<t::PageRequest> for model::PageRequest {
    fn from(value: t::PageRequest) -> Self {
        Self {
            limit: value.limit,
            cursor: value.cursor,
        }
    }
}

impl TryFrom<model::PageRequest> for t::PageRequest {
    type Error = ValidationError;
    fn try_from(value: model::PageRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            limit: value.limit,
            cursor: value.cursor,
        })
    }
}

impl From<t::ListEffectHistoryRequest> for model::ListEffectHistoryRequest {
    fn from(value: t::ListEffectHistoryRequest) -> Self {
        Self {
            effect: value.effect.map(Into::into),
            page: value.page.map(Into::into),
        }
    }
}

impl TryFrom<model::ListEffectHistoryRequest> for t::ListEffectHistoryRequest {
    type Error = ValidationError;
    fn try_from(value: model::ListEffectHistoryRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            effect: value.effect.map(TryInto::try_into).transpose()?,
            page: value.page.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<t::PageResponse> for model::PageResponse {
    fn from(value: t::PageResponse) -> Self {
        Self {
            next_cursor: value.next_cursor,
            returned_count: value.returned_count,
            encoded_bytes: value.encoded_bytes,
        }
    }
}

impl TryFrom<model::PageResponse> for t::PageResponse {
    type Error = ValidationError;
    fn try_from(value: model::PageResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            next_cursor: value.next_cursor,
            returned_count: value.returned_count,
            encoded_bytes: value.encoded_bytes,
        })
    }
}

impl From<t::ListEffectHistoryResponse> for model::ListEffectHistoryResponse {
    fn from(value: t::ListEffectHistoryResponse) -> Self {
        Self {
            receipts: value.receipts.into_iter().map(Into::into).collect(),
            page: value.page.map(Into::into),
        }
    }
}

impl TryFrom<model::ListEffectHistoryResponse> for t::ListEffectHistoryResponse {
    type Error = ValidationError;
    fn try_from(value: model::ListEffectHistoryResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            receipts: value
                .receipts
                .into_iter()
                .map(TryInto::try_into)
                .collect::<Result<_, _>>()?,
            page: value.page.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<t::LookupCommandResponse> for model::LookupCommandResponse {
    fn from(value: t::LookupCommandResponse) -> Self {
        Self {
            command: value.command.map(Into::into),
        }
    }
}

impl TryFrom<model::LookupCommandResponse> for t::LookupCommandResponse {
    type Error = ValidationError;
    fn try_from(value: model::LookupCommandResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            command: value.command.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<t::LookupCommitRequest> for model::LookupCommitRequest {
    fn from(value: t::LookupCommitRequest) -> Self {
        Self {
            profile: value.profile.map(Into::into),
            command: value.command.map(Into::into),
            receipt_id: value.receipt_id,
            authorization_publication: value.authorization_publication.map(Into::into),
        }
    }
}

impl TryFrom<model::LookupCommitRequest> for t::LookupCommitRequest {
    type Error = ValidationError;
    fn try_from(value: model::LookupCommitRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            profile: value.profile.map(TryInto::try_into).transpose()?,
            command: value.command.map(TryInto::try_into).transpose()?,
            receipt_id: value.receipt_id,
            authorization_publication: value.authorization_publication.map(Into::into),
        })
    }
}

impl From<t::LookupCommitResponse> for model::LookupCommitResponse {
    fn from(value: t::LookupCommitResponse) -> Self {
        Self {
            command: value.command.map(Into::into),
        }
    }
}

impl TryFrom<model::LookupCommitResponse> for t::LookupCommitResponse {
    type Error = ValidationError;
    fn try_from(value: model::LookupCommitResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            command: value.command.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<c::NamespaceConfiguration> for model::NamespaceConfiguration {
    fn from(value: c::NamespaceConfiguration) -> Self {
        Self {
            state_schema: value.state_schema,
            quota: value.quota.map(Into::into),
        }
    }
}

impl TryFrom<model::NamespaceConfiguration> for c::NamespaceConfiguration {
    type Error = ValidationError;
    fn try_from(value: model::NamespaceConfiguration) -> Result<Self, Self::Error> {
        Ok(Self {
            state_schema: value.state_schema,
            quota: value.quota.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<c::MutateNamespaceRequest> for model::MutateNamespaceRequest {
    fn from(value: c::MutateNamespaceRequest) -> Self {
        Self {
            namespace: value.namespace.map(Into::into),
            operation_id: value.operation_id,
            mutation: model::NamespaceMutationKind(value.mutation),
            expected_generation: value.expected_generation,
            configuration: value.configuration.map(Into::into),
        }
    }
}

impl TryFrom<model::MutateNamespaceRequest> for c::MutateNamespaceRequest {
    type Error = ValidationError;
    fn try_from(value: model::MutateNamespaceRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            namespace: value.namespace.map(TryInto::try_into).transpose()?,
            operation_id: value.operation_id,
            mutation: value.mutation.0,
            expected_generation: value.expected_generation,
            configuration: value.configuration.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<c::MutateNamespaceResponse> for model::MutateNamespaceResponse {
    fn from(value: c::MutateNamespaceResponse) -> Self {
        Self {
            receipt: value.receipt.map(Into::into),
            replayed: value.replayed,
            audit_ack: value.audit_ack.map(Into::into),
        }
    }
}

impl TryFrom<model::MutateNamespaceResponse> for c::MutateNamespaceResponse {
    type Error = ValidationError;
    fn try_from(value: model::MutateNamespaceResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            receipt: value.receipt.map(TryInto::try_into).transpose()?,
            replayed: value.replayed,
            audit_ack: value.audit_ack.map(Into::into),
        })
    }
}

impl From<c::MutateStateRequest> for model::MutateStateRequest {
    fn from(value: c::MutateStateRequest) -> Self {
        Self {
            namespace: value.namespace.map(Into::into),
            operation_id: value.operation_id,
            mutation: model::StateMutationKind(value.mutation),
            record_id: value.record_id,
            expected_version: value.expected_version,
            expected_policy_digest: value.expected_policy_digest,
            reason: value.reason,
        }
    }
}

impl TryFrom<model::MutateStateRequest> for c::MutateStateRequest {
    type Error = ValidationError;
    fn try_from(value: model::MutateStateRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            namespace: value.namespace.map(TryInto::try_into).transpose()?,
            operation_id: value.operation_id,
            mutation: value.mutation.0,
            record_id: value.record_id,
            expected_version: value.expected_version,
            expected_policy_digest: value.expected_policy_digest,
            reason: value.reason,
        })
    }
}

impl From<c::MutateStateResponse> for model::MutateStateResponse {
    fn from(value: c::MutateStateResponse) -> Self {
        Self {
            receipt: value.receipt.map(Into::into),
            audit_ack: value.audit_ack.map(Into::into),
        }
    }
}

impl TryFrom<model::MutateStateResponse> for c::MutateStateResponse {
    type Error = ValidationError;
    fn try_from(value: model::MutateStateResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            receipt: value.receipt.map(TryInto::try_into).transpose()?,
            audit_ack: value.audit_ack.map(Into::into),
        })
    }
}

impl From<t::QueryRequest> for model::QueryRequest {
    fn from(value: t::QueryRequest) -> Self {
        Self {
            profile: value.profile.map(Into::into),
            invocation: value.invocation.map(Into::into),
            namespace: value.namespace.map(Into::into),
            entity: value.entity,
            minimum_view_version: value.minimum_view_version,
        }
    }
}

impl TryFrom<model::QueryRequest> for t::QueryRequest {
    type Error = ValidationError;
    fn try_from(value: model::QueryRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            profile: value.profile.map(TryInto::try_into).transpose()?,
            invocation: value.invocation.map(Into::into),
            namespace: value.namespace.map(TryInto::try_into).transpose()?,
            entity: value.entity,
            minimum_view_version: value.minimum_view_version,
        })
    }
}

impl From<t::QueryResponse> for model::QueryResponse {
    fn from(value: t::QueryResponse) -> Self {
        Self {
            invocation: value.invocation.map(Into::into),
            view: value.view.map(Into::into),
            source: value.source.map(Into::into),
            observed_at_unix_millis: value.observed_at_unix_millis,
        }
    }
}

impl TryFrom<model::QueryResponse> for t::QueryResponse {
    type Error = ValidationError;
    fn try_from(value: model::QueryResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            invocation: value
                .invocation
                .map(TryInto::try_into)
                .transpose()
                .map_err(|_| ValidationError::Shape)?,
            view: value.view.map(TryInto::try_into).transpose()?,
            source: value.source.map(TryInto::try_into).transpose()?,
            observed_at_unix_millis: value.observed_at_unix_millis,
        })
    }
}

impl From<c::SelectEntityRequest> for model::SelectEntityRequest {
    fn from(value: c::SelectEntityRequest) -> Self {
        Self {
            namespace: value.namespace.map(Into::into),
            prefix: value.prefix,
            page: value.page.map(Into::into),
        }
    }
}

impl TryFrom<model::SelectEntityRequest> for c::SelectEntityRequest {
    type Error = ValidationError;
    fn try_from(value: model::SelectEntityRequest) -> Result<Self, Self::Error> {
        Ok(Self {
            namespace: value.namespace.map(TryInto::try_into).transpose()?,
            prefix: value.prefix,
            page: value.page.map(TryInto::try_into).transpose()?,
        })
    }
}

impl From<c::SelectEntityResponse> for model::SelectEntityResponse {
    fn from(value: c::SelectEntityResponse) -> Self {
        Self {
            entities: value.entities.into_iter().map(Into::into).collect(),
            page: value.page.map(Into::into),
        }
    }
}

impl TryFrom<model::SelectEntityResponse> for c::SelectEntityResponse {
    type Error = ValidationError;
    fn try_from(value: model::SelectEntityResponse) -> Result<Self, Self::Error> {
        Ok(Self {
            entities: value
                .entities
                .into_iter()
                .map(TryInto::try_into)
                .collect::<Result<_, _>>()?,
            page: value.page.map(TryInto::try_into).transpose()?,
        })
    }
}
